"""Append-only Flow generation orchestration with provider-independent request ordering."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import shutil

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock
from .validation import AssetValidationError, validate_image, validate_video

MANIFEST_VERSION = "story-auto-generation-manifest/1.0.0"
FINAL = {"SUCCEEDED", "FAILED_PERMANENT", "AUTH_REQUIRED", "CREDIT_BLOCKED", "CANCELLED", "AMBIGUOUS"}

class FlowError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = ""):
        self.failure_class = failure_class; super().__init__(failure_class + (f": {detail}" if detail else ""))

def _now(): return datetime.now(timezone.utc).isoformat()
def _manifest(paths, project_id):
    path = paths.artifact_path("output/generation_manifest.json")
    if not path.exists(): return path, {"schema_version": MANIFEST_VERSION, "project_id": project_id, "requests": []}
    try:
        data = read_json(path)
        if data.get("schema_version") != MANIFEST_VERSION or data.get("project_id") != project_id or not isinstance(data.get("requests"), list): raise ValueError()
        return path, data
    except Exception as error: raise FlowError("GENERATION_MANIFEST_INVALID") from error

def _entry(manifest, request):
    found = next((x for x in manifest["requests"] if x["request_id"] == request["request_id"]), None)
    if found is None:
        found = {"request_id":request["request_id"], "request_identity_sha256":request["fingerprint"], "related_identity":request.get("shot_id") or request.get("entity_id"), "media_type":request["media_type"], "provider":"google_flow", "prompt_sha256":request["fingerprint"], "reference_asset_hashes":[], "attempts":[], "status":"PENDING", "created_at":_now()}; manifest["requests"].append(found)
    elif found.get("request_identity_sha256") != request["fingerprint"]: return None
    return found

def _valid_selected(paths, entry):
    selected = entry.get("selected_asset")
    if not isinstance(selected, dict) or not isinstance(selected.get("path"), str): return False
    path = paths.artifact_path(selected["path"])
    try:
        metadata = validate_image(path) if entry["media_type"] == "IMAGE" else validate_video(path)
        return metadata["sha256"] == selected.get("sha256")
    except Exception: return False

def _runnable(request, entries): return all(entries.get(dep, {}).get("status") == "SUCCEEDED" for dep in request.get("depends_on", []))

@dataclass
class FlowExecutor:
    """A live adapter supplies generate(); it must acquire to the given temp file."""
    capabilities: Any
    generate: Any

    def run(self, request, refs, temporary: Path):
        self.capabilities.require(request["media_type"], bool(refs))
        return self.generate(request, refs, temporary)

def execute_generation(runtime_root: Path | str, project_id: str, *, executor: FlowExecutor, execute: bool = False, request_ids: set[str] | None = None) -> dict:
    """Explicit spend gate. Never re-submit after an unresolved post-dispatch outcome."""
    if not execute: raise FlowError("EXECUTION_CONFIRMATION_REQUIRED", "pass explicit execute-generation permission")
    paths, config = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    review = read_json(paths.artifact_path("output/review_state.json"))
    if review.get("plan_approval", {}).get("status") != "APPROVED": raise FlowError("PLAN_APPROVAL_REQUIRED")
    requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
    selected = [r for r in requests if request_ids is None or r["request_id"] in request_ids]
    if len(selected) > 3: raise FlowError("GENERATION_GUARDRAIL_BLOCKED", "Goal 06 permits only the three-request vertical slice")
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id); entries = {e["request_id"]:e for e in manifest["requests"]}; submissions = 0
        for request in selected:
            entry = _entry(manifest, request)
            if entry is None: continue # identity changed: retain old provenance, a planner-generated id is required
            if entry.get("status") == "SUCCEEDED" and _valid_selected(paths, entry): continue
            if entry.get("status") in (FINAL - {"SUCCEEDED"}): continue
            if not _runnable(request, entries): continue
            attempt_number = len(entry["attempts"]) + 1
            if attempt_number > 2: entry["status"] = "FAILED_PERMANENT"; continue
            attempt = {"attempt":attempt_number, "status":"SUBMITTED", "started_at":_now(), "provider_mode":request["media_type"]}; entry["attempts"].append(attempt); entry["status"]="GENERATING"; atomic_write_json(path, manifest)
            temp = paths.artifact_path(f"assets/attempts/{request['request_id']}/attempt_{attempt_number:03d}/provider_result.{ 'png' if request['media_type'] == 'IMAGE' else 'mp4'}")
            refs = [entries[d].get("selected_asset", {}).get("path") for d in request.get("depends_on", [])]
            try:
                result = executor.run(request, refs, temp); source = Path(result or temp)
                if not source.is_file(): raise FlowError("ASSET_ACQUISITION_FAILED")
                temp.parent.mkdir(parents=True, exist_ok=True)
                if source.resolve() != temp.resolve(): shutil.copy2(source, temp)
                metadata = validate_image(temp) if request["media_type"] == "IMAGE" else validate_video(temp)
                final_rel = f"assets/{request['media_type'].lower()}/{request['request_id']}/attempt_{attempt_number:03d}{temp.suffix}"
                final_path = paths.artifact_path(final_rel); final_path.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(temp), final_path)
                attempt.update({"status":"SUCCEEDED", "completed_at":_now(), "asset_path":final_rel, "asset_sha256":metadata["sha256"], "metadata":metadata})
                entry.update({"status":"SUCCEEDED", "selected_asset":{"path":final_rel,"sha256":metadata["sha256"],"attempt":attempt_number,"metadata":metadata}, "updated_at":_now()}); submissions += 1
            except FlowError as error:
                # A post-dispatch timeout/unknown result is deliberately terminal and non-resubmittable.
                state = "AMBIGUOUS" if error.failure_class in {"FLOW_TIMEOUT", "FLOW_RESULT_AMBIGUOUS"} else ("AUTH_REQUIRED" if error.failure_class == "FLOW_AUTH_REQUIRED" else "FAILED_RETRYABLE")
                attempt.update({"status":state, "failure_class":error.failure_class, "completed_at":_now()}); entry.update({"status":state, "failure_class":error.failure_class, "updated_at":_now()})
            except AssetValidationError as error:
                attempt.update({"status":"FAILED_RETRYABLE", "failure_class":error.failure_class, "completed_at":_now()}); entry.update({"status":"FAILED_RETRYABLE", "failure_class":error.failure_class, "updated_at":_now()})
            atomic_write_json(path, manifest); entries[request["request_id"]] = entry
    return {"selected":len(selected), "new_submissions":submissions, "manifest":"output/generation_manifest.json"}

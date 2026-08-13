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
from story_auto.core.resources import ensure_free_space
from story_auto.core.visual import MediaQualityError, validate_production_qc
from .validation import AssetValidationError, validate_image, validate_video
from .session import FlowSessionError

MANIFEST_VERSION = "story-auto-generation-manifest/1.0.0"
FINAL = {"SUCCEEDED", "FAILED_PERMANENT", "AUTH_REQUIRED", "CREDIT_BLOCKED", "CANCELLED"}

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


def reconcile_local_assets(runtime_root: Path | str, project_id: str) -> set[str]:
    """Invalidate only provider selections whose exact local bytes no longer validate."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    invalidated: set[str] = set()
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        for entry in manifest["requests"]:
            if entry.get("status") != "SUCCEEDED" or _valid_selected(paths, entry):
                continue
            selected = entry.get("selected_asset") if isinstance(entry.get("selected_asset"), dict) else {}
            entry.setdefault("asset_invalidations", []).append({
                "detected_at": _now(), "path": selected.get("path"),
                "expected_sha256": selected.get("sha256"), "failure_class": "ASSET_INVALID",
            })
            entry.update({"status": "FAILED_RETRYABLE", "failure_class": "ASSET_INVALID", "updated_at": _now()})
            invalidated.add(entry["request_id"])
        if invalidated:
            atomic_write_json(path, manifest)
    return invalidated


def reject_selected_asset(runtime_root: Path | str, project_id: str, request_id: str, *, reason: str) -> None:
    """Record a visual-review rejection without deleting or rewriting its attempt."""
    if not isinstance(reason, str) or not reason.strip():
        raise FlowError("CREATIVE_REJECTION_INVALID")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        if not entry or entry.get("status") not in {"SUCCEEDED", "QC_PENDING"} or not isinstance(entry.get("selected_asset"), dict):
            raise FlowError("CREATIVE_REJECTION_INVALID")
        selected = entry["selected_asset"]
        entry.setdefault("creative_rejections", []).append({"rejected_at": _now(), "asset_path": selected.get("path"),
                                                              "asset_sha256": selected.get("sha256"), "reason": reason.strip()})
        entry.update({"status": "FAILED_RETRYABLE", "failure_class": "CREATIVE_REJECTED", "updated_at": _now()})
        atomic_write_json(path, manifest)


def review_production_asset(runtime_root: Path | str, project_id: str, request_id: str, report: dict) -> None:
    """Approve or reject selected bytes using the complete production QC rubric."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        if not entry or entry.get("status") not in {"SUCCEEDED", "QC_PENDING"} or not isinstance(entry.get("selected_asset"), dict):
            raise FlowError("MEDIA_QC_INVALID")
        try:
            accepted = validate_production_qc(report, provider=entry.get("provider"))
        except MediaQualityError as error:
            entry.setdefault("quality_reviews", []).append({"reviewed_at": _now(), "status": "REJECTED", "failure_class": error.failure_class, "report": report})
            entry.update({"status": "FAILED_RETRYABLE", "failure_class": error.failure_class, "updated_at": _now()})
            atomic_write_json(path, manifest)
            raise FlowError(error.failure_class) from error
        entry.setdefault("quality_reviews", []).append({"reviewed_at": _now(), "status": "APPROVED", "report": accepted})
        entry["selected_asset"]["production_qc"] = "APPROVED"
        entry.update({"status": "SUCCEEDED", "failure_class": None, "updated_at": _now()})
        atomic_write_json(path, manifest)


def queue_regeneration(runtime_root: Path | str, project_id: str, request_id: str, *, reason: str) -> None:
    """Make exactly one selected request runnable again without erasing history."""
    if not isinstance(reason, str) or not reason.strip(): raise FlowError("REGENERATION_REASON_REQUIRED")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        if not entry or entry.get("status") in {"GENERATING", "AMBIGUOUS"}: raise FlowError("REGENERATION_NOT_ALLOWED")
        entry.setdefault("operator_actions", []).append({"action":"REGENERATE","reason":reason.strip(),"at":_now()})
        entry.update({"status":"FAILED_RETRYABLE","failure_class":"OPERATOR_REGENERATION","updated_at":_now()})
        atomic_write_json(path, manifest)

def reopen_verified_pre_dispatch_failure(runtime_root: Path | str, project_id: str, request_id: str) -> None:
    """Only reopens an attempt with recorded proof no Generate click happened."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id); entry = next((e for e in manifest["requests"] if e.get("request_id") == request_id), None)
        if not entry or entry.get("status") != "FAILED_PERMANENT": raise FlowError("GENERATION_RECONCILIATION_INVALID")
        attempt = entry.get("attempts", [])[-1] if entry.get("attempts") else None
        safe_pre_dispatch = {"FLOW_UI_CHANGED", "FLOW_CAPABILITY_UNAVAILABLE"}
        if not isinstance(attempt, dict) or attempt.get("failure_class") not in safe_pre_dispatch or attempt.get("dispatch_confirmed") is not False: raise FlowError("GENERATION_RECONCILIATION_INVALID")
        entry["status"] = "FAILED_RETRYABLE"; entry["reconciled_at"] = _now(); entry["reconciliation"] = "verified_no_dispatch"; atomic_write_json(path, manifest)

def adopt_manual_recovery(runtime_root: Path | str, project_id: str, request_id: str, source: Path, *, settings: dict, attribution: str) -> dict:
    """Adopt one attributable human-recovered Flow output without a new submit."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest=_manifest(paths, project_id); entry=next((e for e in manifest["requests"] if e.get("request_id")==request_id),None)
        if not entry or entry.get("status") not in {"AMBIGUOUS", "NOT_DISPATCHED", "FAILED_RETRYABLE"} or not attribution: raise FlowError("MANUAL_RECOVERY_ATTRIBUTION_INSUFFICIENT")
        metadata=validate_image(source) if entry["media_type"]=="IMAGE" else validate_video(source)
        number=len(entry["attempts"])+1; rel=f"assets/{entry['media_type'].lower()}/{request_id}/manual_recovery_{number:03d}{source.suffix}"; target=paths.artifact_path(rel);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        try: request=next(item for item in read_json(paths.artifact_path("output/generation_requests.json"))["requests"] if item.get("request_id")==request_id)
        except Exception: request={}
        production=request.get("execution_tier")=="STANDARD_PRODUCTION"
        attempt={"attempt":number,"status":"SUCCEEDED","dispatch_origin":"human_manual_recovery","attribution_evidence":attribution,"provider_settings":settings,"asset_path":rel,"asset_sha256":metadata["sha256"],"metadata":metadata,"completed_at":_now()}
        entry["attempts"].append(attempt);entry.update({"status":"QC_PENDING" if production else "SUCCEEDED","selected_asset":{"path":rel,"sha256":metadata["sha256"],"attempt":number,"metadata":metadata,"production_qc":"PENDING" if production else "ENGINEERING_FIXTURE"},"failure_class":None,"updated_at":_now()});atomic_write_json(path,manifest);return entry["selected_asset"]

@dataclass
class FlowExecutor:
    """A live adapter supplies generate(); it must acquire to the given temp file."""
    capabilities: Any
    generate: Any

    def run(self, request, refs, temporary: Path):
        self.capabilities.require(request["media_type"], bool(refs))
        return self.generate(request, refs, temporary)

def execute_generation(runtime_root: Path | str, project_id: str, *, executor: FlowExecutor, execute: bool = False,
                       request_ids: set[str] | None = None, production_batch: bool = False,
                       max_requests: int | None = None) -> dict:
    """Run the bounded vertical slice while preserving every provider attempt."""
    if not execute: raise FlowError("EXECUTION_CONFIRMATION_REQUIRED", "pass explicit execute-generation permission")
    paths, config = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    review = read_json(paths.artifact_path("output/review_state.json"))
    if review.get("plan_approval", {}).get("status") != "APPROVED": raise FlowError("PLAN_APPROVAL_REQUIRED")
    requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
    selected = [r for r in requests if request_ids is None or r["request_id"] in request_ids]
    if max_requests is not None:
        if max_requests < 1: raise FlowError("GENERATION_GUARDRAIL_BLOCKED", "max_requests must be positive")
        selected = selected[:max_requests]
    if not production_batch and len(selected) > 4: raise FlowError("GENERATION_GUARDRAIL_BLOCKED", "bounded execution permits at most four selected requests")
    kinds = [(r.get("purpose"), r.get("media_type")) for r in selected]
    if (not production_batch and any(kinds.count(kind) > 1 for kind in kinds)) or any(kind not in {("REFERENCE", "IMAGE"), ("SHOT", "IMAGE"), ("SHOT", "VIDEO"), ("THUMBNAIL", "IMAGE")} for kind in kinds):
        raise FlowError("GENERATION_GUARDRAIL_BLOCKED", "bounded execution permits one reference image, shot image, shot video, and thumbnail")
    storage=config.settings.get("storage",{})
    if not isinstance(storage,dict): raise FlowError("STORAGE_SETTINGS_INVALID")
    ensure_free_space(paths.runtime.temp,minimum_free_bytes=int(storage.get("minimum_free_bytes",64*1024*1024)))
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id); entries = {e["request_id"]:e for e in manifest["requests"]}; submissions = 0
        control_path = paths.artifact_path("output/execution_control.json")
        paused = False
        for request in selected:
            try: paused = read_json(control_path).get("pause_requested") is True
            except Exception: paused = False
            if paused: break
            if request.get("media_type") == "IMAGE" and request.get("output_count", 1) != 1:
                raise FlowError("IMAGE_OUTPUT_COUNT_MISMATCH")
            entry = _entry(manifest, request)
            if entry is None: continue # identity changed: retain old provenance, a planner-generated id is required
            if entry.get("status") == "SUCCEEDED" and _valid_selected(paths, entry): continue
            if entry.get("status") == "QC_PENDING" and _valid_selected(paths, entry): continue
            if entry.get("status") == "AMBIGUOUS": continue # reconcile provider-visible state before any new dispatch
            if entry.get("status") in (FINAL - {"SUCCEEDED"}): continue
            if not _runnable(request, entries): continue
            entry["reference_asset_hashes"] = [entries[dep]["selected_asset"]["sha256"] for dep in request.get("depends_on", [])]
            attempt_number = len(entry["attempts"]) + 1
            # Ambiguous/retryable attempts are append-only.  A finite higher
            # ceiling prevents loops while accepted-goal policy permits recovery.
            # The default permits an evidence-led correction after an initial
            # bounded retry cycle; it is a stop-loss, never a cost ceiling.
            maximum = int(config.settings.get("flow", {}).get("max_attempts", 12))
            if attempt_number > maximum: entry["status"] = "FAILED_PERMANENT"; entry["failure_class"]="FLOW_RETRY_STOP_LOSS"; continue
            attempt = {"attempt":attempt_number, "status":"SUBMITTED", "started_at":_now(), "provider_mode":request["media_type"], "dispatch_confirmed":False}; entry["attempts"].append(attempt); entry["status"]="GENERATING"; atomic_write_json(path, manifest)
            temp = paths.artifact_path(f"assets/attempts/{request['request_id']}/attempt_{attempt_number:03d}/provider_result.{ 'png' if request['media_type'] == 'IMAGE' else 'mp4'}")
            # Provider adapters receive concrete local files, never manifest-
            # relative paths.  In particular CDP's file-input API silently
            # cannot attach a path relative to the process working directory.
            refs = [str(paths.artifact_path(entries[d]["selected_asset"]["path"])) for d in request.get("depends_on", [])]
            try:
                temp.parent.mkdir(parents=True, exist_ok=True)
                result = executor.run(request, refs, temp); attempt["dispatch_confirmed"] = bool(getattr(executor.generate, "dispatch_confirmed", True)); attempt["provider_settings"] = getattr(executor.generate, "last_settings", None); source = Path(result or temp)
                if not source.is_file(): raise FlowError("ASSET_ACQUISITION_FAILED")
                if source.resolve() != temp.resolve(): shutil.copy2(source, temp)
                metadata = validate_image(temp) if request["media_type"] == "IMAGE" else validate_video(temp)
                final_rel = f"assets/{request['media_type'].lower()}/{request['request_id']}/attempt_{attempt_number:03d}{temp.suffix}"
                final_path = paths.artifact_path(final_rel); final_path.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(temp), final_path)
                production = request.get("execution_tier") == "STANDARD_PRODUCTION"
                resulting_status = "QC_PENDING" if production else "SUCCEEDED"
                attempt.update({"status":"SUCCEEDED", "completed_at":_now(), "asset_path":final_rel, "asset_sha256":metadata["sha256"], "metadata":metadata})
                entry.update({"status":resulting_status, "selected_asset":{"path":final_rel,"sha256":metadata["sha256"],"attempt":attempt_number,"metadata":metadata,"production_qc":"PENDING" if production else "ENGINEERING_FIXTURE"}, "updated_at":_now()}); submissions += 1
            except (FlowError, FlowSessionError) as error:
                attempt["dispatch_confirmed"] = bool(getattr(executor.generate, "dispatch_confirmed", attempt.get("dispatch_confirmed", False)))
                attempt["provider_settings"] = getattr(executor.generate, "last_settings", None)
                state = "AMBIGUOUS" if error.failure_class in {"FLOW_TIMEOUT", "FLOW_RESULT_AMBIGUOUS"} else ("NOT_DISPATCHED" if error.failure_class == "FLOW_NOT_DISPATCHED" else ("AUTH_REQUIRED" if error.failure_class == "FLOW_AUTH_REQUIRED" else ("FAILED_PERMANENT" if error.failure_class in {"FLOW_PROJECT_MISMATCH", "FLOW_CAPABILITY_UNAVAILABLE", "FLOW_REFERENCE_VIDEO_CAPABILITY_BLOCKED"} else "FAILED_RETRYABLE")))
                attempt.update({"status":state, "failure_class":error.failure_class, "diagnostic":str(error), "completed_at":_now()}); entry.update({"status":state, "failure_class":error.failure_class, "updated_at":_now()})
            except AssetValidationError as error:
                attempt.update({"status":"FAILED_RETRYABLE", "failure_class":error.failure_class, "completed_at":_now()}); entry.update({"status":"FAILED_RETRYABLE", "failure_class":error.failure_class, "updated_at":_now()})
            atomic_write_json(path, manifest); entries[request["request_id"]] = entry
    return {"selected":len(selected), "new_submissions":submissions, "paused":paused, "manifest":"output/generation_manifest.json"}

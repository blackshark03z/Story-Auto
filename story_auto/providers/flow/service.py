"""Append-only Flow generation orchestration with provider-independent request ordering."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import shutil

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock
from story_auto.core.resources import ensure_free_space
from story_auto.core.visual import MediaQualityError, validate_production_qc
from .postprocess import (
    PROCESSOR_NAME,
    PROCESSOR_VERSION,
    FlowImagePostprocessError,
    process_flow_image,
    profile_evidence,
)
from .validation import AssetValidationError, validate_image, validate_video
from .session import FlowSessionError

MANIFEST_VERSION = "story-auto-generation-manifest/1.0.0"
FINAL = {"SUCCEEDED", "FAILED_PERMANENT", "AUTH_REQUIRED", "CREDIT_BLOCKED", "CANCELLED"}
LOCAL_IMAGE_FAILURES = {
    "FLOW_IMAGE_POSTPROCESS_FAILED",
    "FLOW_IMAGE_POSTPROCESS_SOURCE_INVALID",
    "FLOW_IMAGE_POSTPROCESS_UNSUPPORTED_GEOMETRY",
    "FLOW_IMAGE_POSTPROCESS_DIMENSIONS_CHANGED",
    "FLOW_IMAGE_POSTPROCESS_OUTPUT_CONFLICT",
    "FLOW_IMAGE_DERIVATIVE_INVALID",
}

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


def _successful_raw_image(paths, entry):
    """Return the newest valid raw provider image explicitly awaiting cleanup."""
    for attempt in reversed(entry.get("attempts", [])):
        if (attempt.get("status") != "SUCCEEDED"
                or attempt.get("production_image_postprocess_required") is not True
                or not isinstance(attempt.get("asset_path"), str)):
            continue
        try:
            metadata = validate_image(paths.artifact_path(attempt["asset_path"]))
        except AssetValidationError:
            continue
        if metadata["sha256"] == attempt.get("asset_sha256"):
            return attempt, metadata
    return None, None


def _clean_rel(entry: dict, attempt: dict) -> str:
    return f"assets/image/{entry['request_id']}/attempt_{attempt['attempt']:03d}_clean.png"


def _process_raw_image(paths, entry: dict, attempt: dict, *, output_rel: str | None = None) -> dict:
    """Append one local processing record and bind selected bytes on success."""
    source_rel = attempt["asset_path"]
    source_sha = attempt["asset_sha256"]
    output_rel = output_rel or _clean_rel(entry, attempt)
    processing_number = len(entry.setdefault("postprocess_attempts", [])) + 1
    source_metadata = attempt.get("metadata", {})
    profile = profile_evidence(int(source_metadata.get("width", 0)), int(source_metadata.get("height", 0)))
    record = {
        "processing_attempt": processing_number,
        "status": "PROCESSING",
        "source_provider_attempt": attempt["attempt"],
        "source_path": source_rel,
        "source_sha256": source_sha,
        "output_path": output_rel,
        "processor_name": PROCESSOR_NAME,
        "processor_version": PROCESSOR_VERSION,
        "flow_mark_profile_version": profile["profile_version"],
        "profile_sha256": profile["profile_sha256"],
        "started_at": _now(),
    }
    entry["postprocess_attempts"].append(record)
    try:
        result = process_flow_image(paths.artifact_path(source_rel), paths.artifact_path(output_rel))
    except FlowImagePostprocessError as error:
        record.update({"status": "FAILED", "failure_class": error.failure_class,
                       "diagnostic": str(error), "completed_at": _now()})
        entry.update({"status": "FAILED_RETRYABLE", "failure_class": error.failure_class,
                      "updated_at": _now()})
        raise
    if result["source_sha256"] != source_sha:
        record.update({"status": "FAILED", "failure_class": "FLOW_IMAGE_POSTPROCESS_SOURCE_INVALID",
                       "completed_at": _now()})
        entry.update({"status": "FAILED_RETRYABLE", "failure_class": "FLOW_IMAGE_POSTPROCESS_SOURCE_INVALID",
                      "updated_at": _now()})
        raise FlowImagePostprocessError("FLOW_IMAGE_POSTPROCESS_SOURCE_INVALID")
    record.update({
        "status": "SUCCEEDED",
        "output_sha256": result["output_sha256"],
        "processor_name": result["processor_name"],
        "processor_version": result["processor_version"],
        "flow_mark_profile_version": result["profile_version"],
        "profile_sha256": result["profile_sha256"],
        "mask_sha256": result["mask_sha256"],
        "completed_at": _now(),
    })
    selected = {
        "path": output_rel,
        "sha256": result["output_sha256"],
        "attempt": attempt["attempt"],
        "metadata": result["output_metadata"],
        "production_qc": "PENDING",
        "source_provider_attempt": attempt["attempt"],
        "source_path": source_rel,
        "source_sha256": source_sha,
        "postprocess_attempt": processing_number,
        "processor_name": result["processor_name"],
        "processor_version": result["processor_version"],
        "flow_mark_profile_version": result["profile_version"],
        "mask_sha256": result["mask_sha256"],
    }
    entry.update({"selected_asset": selected, "status": "QC_PENDING", "failure_class": None,
                  "updated_at": _now()})
    return selected


def _repair_local_image(paths, entry: dict, request: dict) -> bool:
    """Retry cleanup from preserved raw bytes; return whether provider dispatch must stop."""
    if request.get("media_type") != "IMAGE" or request.get("execution_tier") != "STANDARD_PRODUCTION":
        return False
    attempt, _ = _successful_raw_image(paths, entry)
    if attempt is None:
        return False
    selected = entry.get("selected_asset")
    lineage_matches = isinstance(selected, dict) and selected.get("source_provider_attempt") == attempt.get("attempt")
    local_failure = entry.get("failure_class") in LOCAL_IMAGE_FAILURES
    derivative_invalid = lineage_matches and not _valid_selected(paths, entry)
    if not local_failure and not derivative_invalid:
        return False
    try:
        _process_raw_image(paths, entry, attempt, output_rel=(selected or {}).get("path"))
    except FlowImagePostprocessError:
        pass
    return True


def _find_duplicate_selection(paths, manifest: dict, request: dict, metadata: dict, entry: dict):
    identity_field = "dhash256" if request["media_type"] == "IMAGE" else "sha256"
    for other in manifest["requests"]:
        if other is entry or other.get("media_type") != request["media_type"]:
            continue
        other_selected = other.get("selected_asset")
        if not isinstance(other_selected, dict):
            continue
        other_identity = other_selected.get("metadata", {}).get(identity_field)
        if not other_identity and request["media_type"] == "IMAGE":
            try:
                other_identity = validate_image(paths.artifact_path(other_selected["path"]))[identity_field]
            except Exception:
                other_identity = None
        same = other_identity == metadata.get(identity_field)
        if request["media_type"] == "IMAGE" and other_identity and metadata.get(identity_field):
            try:
                same = (int(other_identity, 16) ^ int(metadata[identity_field], 16)).bit_count() <= 4
            except ValueError:
                same = False
        if same:
            return other
    return None

def _runnable(request, entries): return all(entries.get(dep, {}).get("status") == "SUCCEEDED" for dep in request.get("depends_on", []))


def reconcile_local_assets(runtime_root: Path | str, project_id: str) -> set[str]:
    """Invalidate only provider selections whose exact local bytes no longer validate."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    invalidated: set[str] = set()
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        for entry in manifest["requests"]:
            if entry.get("status") not in {"SUCCEEDED", "QC_PENDING"} or _valid_selected(paths, entry):
                continue
            selected = entry.get("selected_asset") if isinstance(entry.get("selected_asset"), dict) else {}
            raw_attempt, _ = _successful_raw_image(paths, entry)
            failure_class = "FLOW_IMAGE_DERIVATIVE_INVALID" if raw_attempt is not None else "ASSET_INVALID"
            entry.setdefault("asset_invalidations", []).append({
                "detected_at": _now(), "path": selected.get("path"),
                "expected_sha256": selected.get("sha256"), "failure_class": failure_class,
            })
            entry.update({"status": "FAILED_RETRYABLE", "failure_class": failure_class, "updated_at": _now()})
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


def recover_interrupted_pre_dispatch_attempt(runtime_root: Path | str, project_id: str, request_id: str) -> None:
    """Reopen a process-interrupted attempt only when no dispatch setup began."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        attempt = entry.get("attempts", [])[-1] if isinstance(entry, dict) and entry.get("attempts") else None
        valid = (
            isinstance(entry, dict) and entry.get("status") == "GENERATING"
            and isinstance(attempt, dict) and attempt.get("status") == "SUBMITTED"
            and attempt.get("dispatch_confirmed") is False
            and attempt.get("provider_settings") is None
        )
        if not valid:
            raise FlowError("GENERATION_RECONCILIATION_INVALID")
        attempt.update({"status":"NOT_DISPATCHED", "failure_class":"FLOW_PROCESS_INTERRUPTED_PRE_DISPATCH",
                        "diagnostic":"process interrupted before provider setup or dispatch", "completed_at":_now()})
        entry.update({"status":"NOT_DISPATCHED", "failure_class":"FLOW_PROCESS_INTERRUPTED_PRE_DISPATCH",
                      "updated_at":_now()})
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
            accepted = validate_production_qc(
                report, provider=entry.get("provider"), media_type=entry.get("media_type")
            )
            # Story shots require an explicit structured comparison to their
            # narration intent. Technical/media quality alone is insufficient.
            try:
                requests = read_json(paths.artifact_path("output/generation_requests.json")).get("requests", [])
            except Exception:
                requests = []
            request = next((item for item in requests if item.get("request_id") == request_id), {})
            if request.get("purpose") == "SHOT":
                classification = report.get("alignment_classification") or report.get("visual_narration_alignment")
                if classification not in {"PASS_DIRECT", "PASS_SUPPORTIVE", "PASS_ATMOSPHERIC"}:
                    failure = "VISUAL_NARRATION_ALIGNMENT_QC_REQUIRED" if not classification else "VISUAL_NARRATION_ALIGNMENT_MISMATCH"
                    raise MediaQualityError(failure)
                if classification == "PASS_ATMOSPHERIC":
                    try:
                        shots = read_json(paths.artifact_path("output/shot_plan.json")).get("shots", [])
                    except Exception:
                        shots = []
                    shot = next((item for item in shots if item.get("shot_id") == request.get("shot_id")), {})
                    if not shot.get("atmospheric"):
                        raise MediaQualityError("VISUAL_NARRATION_ALIGNMENT_MISMATCH")
        except MediaQualityError as error:
            entry.setdefault("quality_reviews", []).append({"reviewed_at": _now(), "status": "REJECTED", "failure_class": error.failure_class, "report": report})
            entry.update({"status": "FAILED_RETRYABLE", "failure_class": error.failure_class, "updated_at": _now()})
            atomic_write_json(path, manifest)
            raise FlowError(error.failure_class) from error
        entry.setdefault("quality_reviews", []).append({"reviewed_at": _now(), "status": "APPROVED", "report": accepted})
        entry["selected_asset"]["production_qc"] = "APPROVED"
        if request.get("purpose") == "SHOT":
            # validate_production_qc intentionally returns only the technical
            # rubric. Keep the separately validated narrative verdict with the
            # exact selected bytes so the final render audit is self-contained.
            entry["selected_asset"]["alignment_classification"] = classification
            entry["selected_asset"]["alignment_observation"] = str(report.get("notes", "")).strip()
        temporal_ready = request.get("media_type") != "VIDEO" or entry["selected_asset"].get("temporal_qc") == "APPROVED"
        entry.update({"status": "SUCCEEDED" if temporal_ready else "QC_PENDING",
                      "failure_class": None if temporal_ready else "TEMPORAL_VIDEO_QC_REQUIRED", "updated_at": _now()})
        atomic_write_json(path, manifest)


def review_temporal_asset(runtime_root: Path | str, project_id: str, request_id: str, report: dict) -> None:
    """Apply deterministic temporal hard gates to exact selected video bytes."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        selected = entry.get("selected_asset") if isinstance(entry, dict) else None
        if not entry or entry.get("media_type") != "VIDEO" or entry.get("status") not in {"QC_PENDING", "SUCCEEDED"} or not isinstance(selected, dict):
            raise FlowError("TEMPORAL_VIDEO_QC_INVALID")
        state = report.get("state")
        if state not in {"PASS_TEMPORAL", "PASS_WITH_USABLE_WINDOW", "REJECT_ACTION_LOGIC", "REJECT_ANATOMY", "REJECT_LOOP", "REJECT_IDENTITY", "REJECT_BACKGROUND", "UNCERTAIN"}:
            raise FlowError("TEMPORAL_VIDEO_QC_INVALID")
        selected.setdefault("temporal_reviews", []).append({"reviewed_at": _now(), "report": report})
        if state not in {"PASS_TEMPORAL", "PASS_WITH_USABLE_WINDOW"} or not report.get("eligible"):
            failure = "TEMPORAL_VIDEO_QC_UNCERTAIN" if state == "UNCERTAIN" else state
            selected["temporal_qc"] = "REJECTED"
            entry.update({"status": "FAILED_RETRYABLE", "failure_class": failure, "updated_at": _now()})
            atomic_write_json(path, manifest)
            raise FlowError(failure)
        metadata = selected.get("metadata", {})
        duration = float(metadata.get("duration_seconds", 0))
        start, end = float(report.get("usable_start", 0)), float(report.get("usable_end", duration))
        if start < 0 or end <= start or end > duration + .05:
            raise FlowError("USABLE_TEMPORAL_WINDOW_INVALID")
        selected.update({"temporal_qc": "APPROVED", "usable_start": start, "usable_end": end,
                         "temporal_state": state})
        semantic_ready = selected.get("production_qc") == "APPROVED" and selected.get("alignment_classification") in {"PASS_DIRECT", "PASS_SUPPORTIVE", "PASS_ATMOSPHERIC"}
        entry.update({"status": "SUCCEEDED" if semantic_ready else "QC_PENDING",
                      "failure_class": None if semantic_ready else "VISUAL_NARRATION_ALIGNMENT_QC_REQUIRED", "updated_at": _now()})
        atomic_write_json(path, manifest)


def reopen_uncertain_temporal_qc(runtime_root: Path | str, project_id: str, request_id: str) -> None:
    """Retry reasoning on the same bytes; never queue a provider generation."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        selected = entry.get("selected_asset") if isinstance(entry, dict) else None
        if (not entry or entry.get("status") != "FAILED_RETRYABLE"
                or entry.get("failure_class") != "TEMPORAL_VIDEO_QC_UNCERTAIN"
                or not isinstance(selected, dict)):
            raise FlowError("TEMPORAL_QC_RETRY_INVALID")
        entry.setdefault("qc_retry_events", []).append({"at": _now(), "asset_sha256": selected.get("sha256"),
                                                         "reason": "retry uncertain Gemini routing/QC on identical bytes"})
        selected["temporal_qc"] = "PENDING"
        entry.update({"status": "QC_PENDING", "failure_class": "TEMPORAL_VIDEO_QC_REQUIRED", "updated_at": _now()})
        atomic_write_json(path, manifest)


def queue_regeneration(runtime_root: Path | str, project_id: str, request_id: str, *, reason: str) -> None:
    """Make exactly one selected request runnable again without erasing history."""
    if not isinstance(reason, str) or not reason.strip(): raise FlowError("REGENERATION_REASON_REQUIRED")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        if not entry or entry.get("status") in {"GENERATING", "AMBIGUOUS"}: raise FlowError("REGENERATION_NOT_ALLOWED")
        raw_attempt, _ = _successful_raw_image(paths, entry)
        retry_local = raw_attempt is not None and entry.get("failure_class") in LOCAL_IMAGE_FAILURES
        action = "RETRY_LOCAL_POSTPROCESS" if retry_local else "REGENERATE"
        entry.setdefault("operator_actions", []).append({"action":action,"reason":reason.strip(),"at":_now()})
        entry.update({"status":"FAILED_RETRYABLE",
                      "failure_class":entry.get("failure_class") if retry_local else "OPERATOR_REGENERATION",
                      "updated_at":_now()})
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

def reopen_verified_false_dispatch(runtime_root: Path | str, project_id: str, request_id: str,
                                   *, evidence: dict) -> None:
    """Reopen a legacy timeout only when exact post-attempt UI evidence proves no dispatch."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        entry = next((item for item in manifest["requests"] if item.get("request_id") == request_id), None)
        attempt = entry.get("attempts", [])[-1] if isinstance(entry, dict) and entry.get("attempts") else None
        settings = attempt.get("provider_settings", {}) if isinstance(attempt, dict) else {}
        try:
            request = next(item for item in read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
                           if item.get("request_id") == request_id)
        except Exception as error:
            raise FlowError("GENERATION_RECONCILIATION_INVALID") from error
        prompt_hash = hashlib.sha256(request["prompt"].encode("utf-8")).hexdigest()
        screenshot_hash = evidence.get("screenshot_sha256") if isinstance(evidence, dict) else None
        valid = (entry.get("status") == "AMBIGUOUS" and attempt.get("failure_class") == "FLOW_TIMEOUT"
                 and settings.get("dispatch_ack_method") == "composer_clear_or_output_transition"
                 and settings.get("last_added_candidate_count") == 0
                 and evidence.get("prompt_retained") is True and evidence.get("visible_media_count") == 0
                 and evidence.get("prompt_sha256") == prompt_hash and isinstance(screenshot_hash, str)
                 and len(screenshot_hash) == 64 and all(c in "0123456789abcdef" for c in screenshot_hash))
        if not valid: raise FlowError("GENERATION_RECONCILIATION_INVALID")
        attempt.update({"status":"NOT_DISPATCHED", "dispatch_confirmed":False,
                        "failure_class":"FLOW_FALSE_DISPATCH_ACK", "reconciliation_evidence":dict(evidence)})
        entry.update({"status":"FAILED_RETRYABLE", "failure_class":"FLOW_FALSE_DISPATCH_ACK",
                      "reconciled_at":_now(), "reconciliation":"verified_prompt_retained_and_no_media"})
        atomic_write_json(path, manifest)

def adopt_manual_recovery(runtime_root: Path | str, project_id: str, request_id: str, source: Path, *, settings: dict, attribution: str) -> dict:
    """Adopt one attributable human-recovered Flow output without a new submit."""
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest=_manifest(paths, project_id); entry=next((e for e in manifest["requests"] if e.get("request_id")==request_id),None)
        if not entry or entry.get("status") not in {"AMBIGUOUS", "NOT_DISPATCHED", "FAILED_RETRYABLE"} or not attribution: raise FlowError("MANUAL_RECOVERY_ATTRIBUTION_INSUFFICIENT")
        metadata=validate_image(source) if entry["media_type"]=="IMAGE" else validate_video(source)
        number=len(entry["attempts"])+1
        try: request=next(item for item in read_json(paths.artifact_path("output/generation_requests.json"))["requests"] if item.get("request_id")==request_id)
        except Exception: request={}
        production=request.get("execution_tier")=="STANDARD_PRODUCTION"
        raw_suffix = source.suffix.lower() or (".png" if entry["media_type"] == "IMAGE" else ".mp4")
        raw_label = "manual_recovery_raw" if production and entry["media_type"] == "IMAGE" else "manual_recovery"
        rel=f"assets/{entry['media_type'].lower()}/{request_id}/{raw_label}_{number:03d}{raw_suffix}"
        target=paths.artifact_path(rel);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        attempt={"attempt":number,"status":"SUCCEEDED","dispatch_origin":"human_manual_recovery","attribution_evidence":attribution,"provider_settings":settings,"asset_path":rel,"asset_sha256":metadata["sha256"],"metadata":metadata,"completed_at":_now()}
        if production and entry["media_type"] == "IMAGE":
            attempt["production_image_postprocess_required"] = True
        entry["attempts"].append(attempt)
        if production and entry["media_type"] == "IMAGE":
            try:
                selected = _process_raw_image(paths, entry, attempt)
            except FlowImagePostprocessError as error:
                atomic_write_json(path, manifest)
                raise FlowError(error.failure_class, str(error)) from error
        else:
            selected={"path":rel,"sha256":metadata["sha256"],"attempt":number,"metadata":metadata,
                      "production_qc":"PENDING" if production else "ENGINEERING_FIXTURE"}
            entry.update({"status":"QC_PENDING" if production else "SUCCEEDED","selected_asset":selected,
                          "failure_class":None,"updated_at":_now()})
        atomic_write_json(path,manifest);return selected


def reuse_exact_flow_asset(runtime_root: Path | str, project_id: str, source_request_id: str,
                           target_request_id: str, *, attribution: str) -> dict:
    """Bind an exact prior Flow asset to a materially revised request.

    The source must be a successfully acquired, non-ambiguous attempt. The new
    request still returns to semantic and temporal QC; no prior approval is
    inherited.
    """
    if not isinstance(attribution, str) or not attribution.strip():
        raise FlowError("EXACT_ASSET_REUSE_ATTRIBUTION_REQUIRED")
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    with ProjectLock(paths.runtime, project_id):
        path, manifest = _manifest(paths, project_id)
        requests = {item["request_id"]: item for item in read_json(paths.artifact_path("output/generation_requests.json"))["requests"]}
        target_request = requests.get(target_request_id)
        source_entry = next((item for item in manifest["requests"] if item.get("request_id") == source_request_id), None)
        source_selected = source_entry.get("selected_asset") if isinstance(source_entry, dict) else None
        if not target_request or not isinstance(source_selected, dict):
            raise FlowError("EXACT_FLOW_ASSET_REUSE_INVALID")
        source_attempt = next((item for item in source_entry.get("attempts", [])
                               if item.get("attempt") == source_selected.get("attempt")), None)
        if not isinstance(source_attempt, dict) or source_attempt.get("status") != "SUCCEEDED":
            raise FlowError("EXACT_FLOW_ASSET_REUSE_INVALID")
        legacy_lineage = source_attempt.get("asset_sha256") == source_selected.get("sha256")
        processing = next((item for item in source_entry.get("postprocess_attempts", [])
                           if item.get("status") == "SUCCEEDED"
                           and item.get("source_provider_attempt") == source_attempt.get("attempt")
                           and item.get("source_sha256") == source_attempt.get("asset_sha256")
                           and item.get("output_sha256") == source_selected.get("sha256")), None)
        processed_lineage = (
            isinstance(processing, dict)
            and source_selected.get("source_provider_attempt") == source_attempt.get("attempt")
            and source_selected.get("source_sha256") == source_attempt.get("asset_sha256")
        )
        if not legacy_lineage and not processed_lineage:
            raise FlowError("EXACT_FLOW_ASSET_REUSE_INVALID")
        try:
            raw_source = paths.artifact_path(source_attempt["asset_path"])
            raw_metadata = validate_video(raw_source) if source_entry.get("media_type") == "VIDEO" else validate_image(raw_source)
        except (KeyError, AssetValidationError):
            raise FlowError("EXACT_FLOW_ASSET_REUSE_INVALID")
        if raw_metadata["sha256"] != source_attempt.get("asset_sha256"):
            raise FlowError("EXACT_FLOW_ASSET_REUSE_INVALID")
        source = paths.artifact_path(source_selected["path"])
        if not source.is_file():
            raise FlowError("EXACT_FLOW_ASSET_REUSE_INVALID")
        entry = next((item for item in manifest["requests"] if item.get("request_id") == target_request_id), None)
        if entry is None:
            entry = _entry(manifest, target_request)
        if entry is None or entry.get("status") not in {"PENDING", "NOT_DISPATCHED", "FAILED_RETRYABLE"}:
            raise FlowError("EXACT_FLOW_ASSET_REUSE_INVALID")
        metadata = validate_video(source) if target_request["media_type"] == "VIDEO" else validate_image(source)
        if metadata["sha256"] != source_selected.get("sha256"):
            raise FlowError("EXACT_FLOW_ASSET_REUSE_INVALID")
        number = len(entry["attempts"]) + 1
        rel = f"assets/{target_request['media_type'].lower()}/{target_request_id}/exact_reuse_{number:03d}{source.suffix}"
        target = paths.artifact_path(rel); target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)
        source_lineage = {
            "source_request_id": source_request_id,
            "source_provider_attempt": source_attempt.get("attempt"),
            "source_raw_path": source_attempt.get("asset_path"),
            "source_raw_sha256": source_attempt.get("asset_sha256"),
            "source_selected_path": source_selected.get("path"),
            "source_selected_sha256": source_selected.get("sha256"),
            "lineage_kind": "RAW_TO_DERIVATIVE" if processed_lineage else "LEGACY_RAW_EQUALS_SELECTED",
        }
        attempt = {"attempt": number, "status": "SUCCEEDED", "dispatch_origin": "prior_exact_flow_asset_repair",
                   "source_request_id": source_request_id, "source_asset_sha256": metadata["sha256"],
                   "source_lineage": source_lineage,
                   "attribution_evidence": attribution.strip(), "asset_path": rel, "asset_sha256": metadata["sha256"],
                   "metadata": metadata, "completed_at": _now()}
        entry["attempts"].append(attempt)
        entry.update({"status": "QC_PENDING", "failure_class": None, "updated_at": _now(),
                      "selected_asset": {"path": rel, "sha256": metadata["sha256"], "attempt": number,
                                         "metadata": metadata, "production_qc": "PENDING",
                                         "reuse_source_request_id": source_request_id,
                                         "source_lineage": source_lineage}})
        atomic_write_json(path, manifest)
        return entry["selected_asset"]

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
    if any(r.get("media_type") == "VIDEO" and not isinstance(r.get("motion_risk_analysis"), dict) for r in selected):
        raise FlowError("MOTION_PLAN_REQUIRED", "every VIDEO request requires motion-risk analysis")
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
            if _repair_local_image(paths, entry, request):
                atomic_write_json(path, manifest); entries[request["request_id"]] = entry
                continue
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
            if attempt_number > maximum:
                entry["status"] = "FAILED_PERMANENT"; entry["failure_class"]="FLOW_RETRY_STOP_LOSS"
                entry["updated_at"]=_now(); atomic_write_json(path,manifest); continue
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
                production = request.get("execution_tier") == "STANDARD_PRODUCTION"
                metadata = validate_image(temp) if request["media_type"] == "IMAGE" else validate_video(temp)
                raw_label = f"attempt_{attempt_number:03d}_raw" if production and request["media_type"] == "IMAGE" else f"attempt_{attempt_number:03d}"
                final_rel = f"assets/{request['media_type'].lower()}/{request['request_id']}/{raw_label}{temp.suffix}"
                final_path = paths.artifact_path(final_rel); final_path.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(temp), final_path)
                attempt.update({"status":"SUCCEEDED", "completed_at":_now(), "asset_path":final_rel,
                                "asset_sha256":metadata["sha256"], "metadata":metadata})
                if production and request["media_type"] == "IMAGE":
                    attempt["production_image_postprocess_required"] = True
                    try:
                        selected_asset = _process_raw_image(paths, entry, attempt)
                    except FlowImagePostprocessError:
                        selected_asset = None
                else:
                    selected_asset = {"path":final_rel,"sha256":metadata["sha256"],"attempt":attempt_number,
                                      "metadata":metadata,"production_qc":"PENDING" if production else "ENGINEERING_FIXTURE"}
                    entry.update({"status":"QC_PENDING" if production else "SUCCEEDED", "failure_class":None,
                                  "selected_asset":selected_asset, "updated_at":_now()})
                # Compare like-for-like identities: clean image derivative to
                # clean image derivative, and provider video bytes to video.
                if selected_asset is not None and production:
                    duplicate = _find_duplicate_selection(paths, manifest, request, selected_asset["metadata"], entry)
                    if duplicate is not None:
                        entry.pop("selected_asset", None)
                        entry.update({"status":"FAILED_RETRYABLE", "failure_class":"FLOW_STALE_RESULT", "updated_at":_now()})
                        entry.setdefault("stale_result_events", []).append({
                            "detected_at": _now(), "candidate_path": selected_asset["path"],
                            "candidate_sha256": selected_asset["sha256"],
                            "matches_request_id": duplicate["request_id"],
                        })
                        selected_asset = None
                if selected_asset is not None:
                    submissions += 1
            except (FlowError, FlowSessionError) as error:
                attempt["dispatch_confirmed"] = bool(getattr(executor.generate, "dispatch_confirmed", attempt.get("dispatch_confirmed", False)))
                attempt["provider_settings"] = getattr(executor.generate, "last_settings", None)
                state = "AMBIGUOUS" if error.failure_class in {"FLOW_TIMEOUT", "FLOW_RESULT_AMBIGUOUS"} else ("NOT_DISPATCHED" if error.failure_class == "FLOW_NOT_DISPATCHED" else ("AUTH_REQUIRED" if error.failure_class == "FLOW_AUTH_REQUIRED" else ("FAILED_PERMANENT" if error.failure_class in {"FLOW_PROJECT_MISMATCH", "FLOW_CAPABILITY_UNAVAILABLE", "FLOW_REFERENCE_VIDEO_CAPABILITY_BLOCKED"} else "FAILED_RETRYABLE")))
                attempt.update({"status":state, "failure_class":error.failure_class, "diagnostic":str(error), "completed_at":_now()}); entry.update({"status":state, "failure_class":error.failure_class, "updated_at":_now()})
            except AssetValidationError as error:
                attempt.update({"status":"FAILED_RETRYABLE", "failure_class":error.failure_class, "completed_at":_now()}); entry.update({"status":"FAILED_RETRYABLE", "failure_class":error.failure_class, "updated_at":_now()})
            atomic_write_json(path, manifest); entries[request["request_id"]] = entry
    return {"selected":len(selected), "new_submissions":submissions, "paused":paused, "manifest":"output/generation_manifest.json"}

"""Append-only Gemini media attempt integration with resumable job identity."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.providers.flow.validation import AssetValidationError, validate_image, validate_video

from .client import GeminiMediaClient, GeminiMediaError, MediaResult


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_selection(entry: dict[str, Any], root: Path) -> bool:
    selected = entry.get("selected_asset")
    if not isinstance(selected, dict) or not isinstance(selected.get("path"), str):
        return False
    path = root / selected["path"]
    try:
        metadata = validate_image(path) if entry["media_type"] == "IMAGE" else validate_video(path)
        return metadata["sha256"] == selected.get("sha256")
    except AssetValidationError:
        return False


def _entry(manifest: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    found = next((item for item in manifest.setdefault("requests", []) if item.get("request_id") == request["request_id"]), None)
    if found is not None:
        if found.get("request_identity_sha256") != request["request_identity_sha256"]:
            raise GeminiMediaError("REQUEST_IDENTITY_CONFLICT")
        return found
    found = {
        "request_id": request["request_id"], "request_identity_sha256": request["request_identity_sha256"],
        "media_type": request["media_type"], "provider": "google_gemini_api", "model": request["model"],
        "attempts": [], "status": "PENDING", "created_at": _now(),
    }
    manifest["requests"].append(found)
    return found


def execute_media_request(*, manifest_path: Path, artifact_root: Path, request: dict[str, Any],
                          references: list[Path], destination: Path, client: GeminiMediaClient) -> str:
    """Execute or resume one approved request; return RUN, RESUME, or SKIP."""
    manifest = read_json(manifest_path) if manifest_path.exists() else {
        "schema_version": "story-auto-generation-manifest/1.0.0", "requests": []}
    entry = _entry(manifest, request)
    if entry.get("status") == "SUCCEEDED" and _valid_selection(entry, artifact_root):
        return "SKIP"
    if entry.get("status") == "AMBIGUOUS":
        raise GeminiMediaError("AMBIGUOUS_RECONCILIATION_REQUIRED", dispatch_confirmed=True)
    attempts = entry.setdefault("attempts", [])
    active = attempts[-1] if attempts and attempts[-1].get("status") == "GENERATING" else None
    if active and not active.get("operation_name"):
        active.update({"status": "AMBIGUOUS", "failure_class": "AMBIGUOUS_POST_DISPATCH", "completed_at": _now()})
        entry.update({"status": "AMBIGUOUS", "failure_class": "AMBIGUOUS_POST_DISPATCH", "updated_at": _now()})
        atomic_write_json(manifest_path, manifest)
        raise GeminiMediaError("AMBIGUOUS_RECONCILIATION_REQUIRED", dispatch_confirmed=True)
    resumed = bool(active and active.get("operation_name") and request["model"].startswith("veo-"))
    if not resumed:
        active = {"attempt": len(attempts) + 1, "status": "GENERATING", "started_at": _now(),
                  "model": request["model"], "endpoint_identity": request["endpoint_identity"],
                  "reference_hashes": [sha256_file(path) for path in references]}
        attempts.append(active); entry["status"] = "GENERATING"; atomic_write_json(manifest_path, manifest)
    try:
        if request["media_type"] == "IMAGE":
            result = client.generate_image(model=request["model"], prompt=request["prompt"], references=references,
                                           destination=destination, aspect_ratio=request.get("aspect_ratio", "16:9"),
                                           image_size=request.get("image_size", "2K"))
        elif request["model"] == "gemini-omni-flash-preview":
            result = client.generate_omni_video(prompt=request["prompt"], references=references, destination=destination,
                                                task=request.get("reference_mode", "image_to_video"),
                                                aspect_ratio=request.get("aspect_ratio", "16:9"))
        elif request["model"] == "veo-3.1-generate-preview":
            operation = active.get("operation_name")
            if operation is None:
                operation = client.submit_veo(prompt=request["prompt"], references=references,
                                              mode=request.get("reference_mode", "REFERENCE_IMAGES"),
                                              aspect_ratio=request.get("aspect_ratio", "16:9"))
                active["operation_name"] = operation; atomic_write_json(manifest_path, manifest)
            result = client.complete_veo(operation_name=operation, destination=destination)
        else:
            raise GeminiMediaError("MODEL_UNSUPPORTED")
    except GeminiMediaError as error:
        active.update({"status": "AMBIGUOUS" if error.failure_class == "AMBIGUOUS_POST_DISPATCH" else "FAILED",
                       "failure_class": error.failure_class, "completed_at": _now()})
        entry.update({"status": active["status"], "failure_class": error.failure_class, "updated_at": _now()})
        atomic_write_json(manifest_path, manifest)
        raise
    relative = result.path.resolve().relative_to(artifact_root.resolve()).as_posix()
    active.update({"status": "SUCCEEDED", "completed_at": _now(), "request_id": result.request_id,
                   "operation_id": result.operation_id, "metadata": result.metadata, "asset_path": relative,
                   "asset_sha256": result.metadata["sha256"], "reference_mode": result.reference_mode,
                   "output_count": result.output_count})
    entry.update({"status": "SUCCEEDED", "failure_class": None, "updated_at": _now(),
                  "selected_asset": {"attempt": active["attempt"], "path": relative,
                                     "sha256": result.metadata["sha256"], "metadata": result.metadata,
                                     "production_qc": "PENDING"}})
    atomic_write_json(manifest_path, manifest)
    return "RESUME" if resumed else "RUN"

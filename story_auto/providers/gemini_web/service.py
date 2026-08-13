"""Append-only Gemini Web attempt ledger."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.providers.flow.validation import validate_image, validate_video

from .session import GeminiWebError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def execute_web_request(*, manifest_path: Path, artifact_root: Path, request: dict,
                        references: list[Path], destination: Path, generator,
                        allow_ambiguous_retry: bool = False) -> str:
    manifest = read_json(manifest_path) if manifest_path.exists() else {
        "schema_version": "story-auto-gemini-web-ledger/1.0.0", "requests": [],
    }
    entry = next((item for item in manifest["requests"] if item["request_id"] == request["request_id"]), None)
    if entry is None:
        entry = {
            "request_id": request["request_id"], "request_identity_sha256": request["request_identity_sha256"],
            "media_type": request["media_type"], "provider": "google_gemini_web",
            "attempts": [], "status": "PENDING", "created_at": _now(),
        }
        manifest["requests"].append(entry)
    elif entry["request_identity_sha256"] != request["request_identity_sha256"]:
        raise GeminiWebError("REQUEST_IDENTITY_CONFLICT")
    selected = entry.get("selected_asset")
    if entry.get("status") == "SUCCEEDED" and isinstance(selected, dict):
        path = artifact_root / selected["path"]
        metadata = (validate_image if request["media_type"] == "IMAGE" else validate_video)(path)
        if metadata["sha256"] == selected["sha256"]:
            return "SKIP"
    if entry.get("status") == "AMBIGUOUS" and not allow_ambiguous_retry:
        raise GeminiWebError("AMBIGUOUS_RECONCILIATION_REQUIRED", dispatch_confirmed=True)
    attempt = {
        "attempt": len(entry["attempts"]) + 1, "status": "GENERATING", "started_at": _now(),
        "reference_hashes": [sha256_file(path) for path in references], "dispatch_confirmed": False,
    }
    entry["attempts"].append(attempt)
    entry["status"] = "GENERATING"
    atomic_write_json(manifest_path, manifest)
    try:
        generator(request, references, destination)
        metadata = (validate_image if request["media_type"] == "IMAGE" else validate_video)(destination)
    except GeminiWebError as error:
        ambiguous = bool(error.dispatch_confirmed)
        attempt.update({
            "status": "AMBIGUOUS" if ambiguous else "FAILED", "failure_class": error.failure_class,
            "dispatch_confirmed": ambiguous, "completed_at": _now(),
            "failure_detail": error.detail or None,
            "provider_settings": generator.last_settings,
        })
        entry.update({"status": attempt["status"], "failure_class": error.failure_class, "updated_at": _now()})
        atomic_write_json(manifest_path, manifest)
        raise
    relative = destination.resolve().relative_to(artifact_root.resolve()).as_posix()
    attempt.update({
        "status": "SUCCEEDED", "completed_at": _now(), "dispatch_confirmed": True,
        "provider_settings": generator.last_settings, "asset_sha256": metadata["sha256"],
    })
    entry.update({
        "status": "SUCCEEDED", "failure_class": None, "updated_at": _now(),
        "selected_asset": {"attempt": attempt["attempt"], "path": relative,
                           "sha256": metadata["sha256"], "metadata": metadata},
    })
    atomic_write_json(manifest_path, manifest)
    return "RUN"


def reconcile_existing_web_asset(*, manifest_path: Path, artifact_root: Path, request: dict,
                                 destination: Path, generator) -> dict:
    """Resolve an acquisition-only failure without generating another candidate."""
    manifest = read_json(manifest_path)
    entry = next(item for item in manifest["requests"] if item["request_id"] == request["request_id"])
    if entry["request_identity_sha256"] != request["request_identity_sha256"]:
        raise GeminiWebError("REQUEST_IDENTITY_CONFLICT")
    if not entry.get("attempts"):
        raise GeminiWebError("AMBIGUOUS_RECONCILIATION_REQUIRED")
    generator.acquire_existing(request, destination)
    metadata = (validate_image if request["media_type"] == "IMAGE" else validate_video)(destination)
    relative = destination.resolve().relative_to(artifact_root.resolve()).as_posix()
    attempt = entry["attempts"][-1]
    attempt["reconciliation"] = {
        "at": _now(), "resolution": "EXISTING_ASSET_ACQUIRED",
        "original_status": attempt["status"], "original_failure_class": attempt.get("failure_class"),
        "new_dispatch": False,
    }
    attempt["asset_sha256"] = metadata["sha256"]
    entry.update({
        "status": "SUCCEEDED", "failure_class": None, "updated_at": _now(),
        "selected_asset": {"attempt": attempt["attempt"], "path": relative,
                           "sha256": metadata["sha256"], "metadata": metadata},
    })
    atomic_write_json(manifest_path, manifest)
    return entry["selected_asset"]

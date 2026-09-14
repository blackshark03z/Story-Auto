"""Durable shot-to-shot continuity references for Full Video I2V providers.

The lifecycle is provider-free.  It binds exact project-local bytes to an exact
production run and generation-request identity before any provider mutation.
Research ledgers and Flow entity references are intentionally not accepted as
production continuity authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock
from story_auto.providers.flow.validation import AssetValidationError, validate_image, validate_video


CONTINUITY_SCHEMA_VERSION = "story-auto-full-video-continuity/1.0.0"
REFERENCE_SNAPSHOT_VERSION = "story-auto-full-video-reference-snapshot/1.0.0"
FRAME_POLICY = "TARGET_END_MINUS_0_5_SECONDS"
_STATE_RELATIVE_PATH = "output/full_video_continuity.json"
_ACCEPTED_QC = frozenset({"OWNER_ACCEPTED", "AUTO_ACCEPTED", "APPROVED"})
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,159}$")


class FullVideoContinuityError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(failure_class + (f": {detail}" if detail else ""))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_token(value: str, failure_class: str) -> str:
    if not isinstance(value, str) or not _SAFE_TOKEN.fullmatch(value):
        raise FullVideoContinuityError(failure_class)
    return value


def _state_path(paths) -> Path:
    return paths.artifact_path(_STATE_RELATIVE_PATH)


def _load_state(paths, project_id: str) -> dict[str, Any]:
    path = _state_path(paths)
    if not path.is_file():
        return {"schema_version": CONTINUITY_SCHEMA_VERSION, "project_id": project_id, "runs": {}}
    try:
        value = read_json(path)
    except Exception as error:
        raise FullVideoContinuityError("CONTINUITY_STATE_INVALID") from error
    if (not isinstance(value, dict) or value.get("schema_version") != CONTINUITY_SCHEMA_VERSION
            or value.get("project_id") != project_id or not isinstance(value.get("runs"), dict)):
        raise FullVideoContinuityError("CONTINUITY_STATE_INVALID")
    return value


def _load_requests(paths) -> tuple[dict[str, Any], str]:
    path = paths.artifact_path("output/generation_requests.json")
    try:
        value = read_json(path)
    except Exception as error:
        raise FullVideoContinuityError("GENERATION_REQUESTS_INVALID") from error
    if not isinstance(value, dict) or not isinstance(value.get("requests"), list):
        raise FullVideoContinuityError("GENERATION_REQUESTS_INVALID")
    snapshot = value.get("full_video_provider_snapshot")
    if (not isinstance(snapshot, dict) or snapshot.get("generation_mode") != "i2v"
            or snapshot.get("reference_image_policy") != "REQUIRED"
            or snapshot.get("continuity_reference_policy") != "SHOT_TO_SHOT_ACCEPTED_FRAME"):
        raise FullVideoContinuityError("CONTINUITY_REFERENCE_NOT_REQUIRED")
    return value, sha256_file(path)


def _load_manifest(paths) -> dict[str, Any]:
    path = paths.artifact_path("output/generation_manifest.json")
    if not path.is_file():
        return {"requests": []}
    try:
        value = read_json(path)
    except Exception as error:
        raise FullVideoContinuityError("GENERATION_MANIFEST_INVALID") from error
    if not isinstance(value, dict) or not isinstance(value.get("requests"), list):
        raise FullVideoContinuityError("GENERATION_MANIFEST_INVALID")
    return value


def _video_requests(value: dict[str, Any]) -> list[dict[str, Any]]:
    requests = [item for item in value.get("requests", [])
                if isinstance(item, dict) and item.get("purpose") == "SHOT" and item.get("media_type") == "VIDEO"]
    if not requests:
        raise FullVideoContinuityError("CONTINUITY_VIDEO_REQUESTS_MISSING")
    for request in requests:
        _safe_token(request.get("request_id"), "CONTINUITY_REQUEST_ID_INVALID")
        if not isinstance(request.get("fingerprint"), str) or not request["fingerprint"]:
            raise FullVideoContinuityError("CONTINUITY_REQUEST_IDENTITY_MISSING")
        try:
            float(request.get("target_start")); float(request.get("target_end")); float(request.get("target_duration"))
        except (TypeError, ValueError) as error:
            raise FullVideoContinuityError("CONTINUITY_REQUEST_TIMING_INVALID") from error
    return sorted(requests, key=lambda item: (float(item["target_start"]), float(item["target_end"]),
                                               int(item.get("part_index") or 0), item["request_id"]))


def _request_by_id(value: dict[str, Any], request_id: str) -> dict[str, Any]:
    matches = [item for item in _video_requests(value) if item.get("request_id") == request_id]
    if len(matches) != 1:
        raise FullVideoContinuityError("CONTINUITY_TARGET_REQUEST_INVALID")
    return matches[0]


def _ensure_run(state: dict[str, Any], run_id: str, requests_sha256: str) -> tuple[dict[str, Any], bool]:
    run_id = _safe_token(run_id, "CONTINUITY_RUN_ID_INVALID")
    runs = state["runs"]
    existing = runs.get(run_id)
    if existing is not None:
        if (not isinstance(existing, dict) or existing.get("run_id") != run_id
                or existing.get("generation_requests_sha256") != requests_sha256
                or not isinstance(existing.get("bindings"), dict)):
            raise FullVideoContinuityError("CONTINUITY_RUN_PLAN_MISMATCH")
        return existing, False
    entry = {"run_id": run_id, "status": "ACTIVE", "generation_requests_sha256": requests_sha256,
             "started_at": _now(), "bindings": {}}
    runs[run_id] = entry
    return entry, True


def _manifest_entry(manifest: dict[str, Any], request_id: str) -> dict[str, Any] | None:
    matches = [item for item in manifest.get("requests", [])
               if isinstance(item, dict) and item.get("request_id") == request_id]
    if len(matches) > 1:
        raise FullVideoContinuityError("GENERATION_MANIFEST_INVALID")
    return matches[0] if matches else None


def _target_provider_boundary_entered(manifest: dict[str, Any], request_id: str) -> bool:
    entry = _manifest_entry(manifest, request_id)
    if not isinstance(entry, dict):
        return False
    if int(entry.get("provider_submissions") or 0) > 0:
        return True
    attempts = entry.get("attempts")
    if not isinstance(attempts, list):
        return False
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        if isinstance(attempt.get("provider_job_id"), str) and attempt["provider_job_id"]:
            return True
        if attempt.get("dispatch_confirmed") is True or attempt.get("provider_boundary_entered_at") is not None:
            return True
        if attempt.get("provider_execution_state") not in {None, "NOT_STARTED"}:
            return True
    return False


def _accepted_source(paths, manifest: dict[str, Any], request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    entry = _manifest_entry(manifest, request["request_id"])
    selected = entry.get("selected_asset") if isinstance(entry, dict) else None
    if (not isinstance(entry, dict) or entry.get("status") != "SUCCEEDED" or not isinstance(selected, dict)
            or selected.get("production_qc") not in _ACCEPTED_QC):
        raise FullVideoContinuityError("CONTINUITY_SOURCE_NOT_ACCEPTED")
    relative = selected.get("path")
    expected_sha = selected.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected_sha, str):
        raise FullVideoContinuityError("CONTINUITY_SOURCE_ASSET_INVALID")
    source = paths.artifact_path(relative)
    try:
        metadata = validate_video(source)
    except AssetValidationError as error:
        raise FullVideoContinuityError("CONTINUITY_SOURCE_ASSET_INVALID") from error
    if metadata.get("sha256") != expected_sha:
        raise FullVideoContinuityError("CONTINUITY_SOURCE_ASSET_CHANGED")
    return entry, selected, metadata


def _previous_accepted_source(paths, requests_value: dict[str, Any], manifest: dict[str, Any],
                              target: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    target_start = float(target["target_start"])
    prior = [item for item in _video_requests(requests_value)
             if item["request_id"] != target["request_id"] and float(item["target_end"]) <= target_start + 0.001]
    if not prior:
        raise FullVideoContinuityError("CONTINUITY_INITIAL_ANCHOR_REQUIRED")
    latest_end = max(float(item["target_end"]) for item in prior)
    immediate = [item for item in prior if abs(float(item["target_end"]) - latest_end) <= 0.001]
    accepted: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for request in immediate:
        try:
            entry, selected, metadata = _accepted_source(paths, manifest, request)
        except FullVideoContinuityError as error:
            if error.failure_class == "CONTINUITY_SOURCE_NOT_ACCEPTED":
                continue
            raise
        accepted.append((request, entry, selected, metadata))
    if not accepted:
        raise FullVideoContinuityError("CONTINUITY_PREVIOUS_ACCEPTED_SOURCE_MISSING")
    if len(accepted) != 1:
        raise FullVideoContinuityError("CONTINUITY_PREVIOUS_SOURCE_AMBIGUOUS")
    return accepted[0]


def _latest_binding(run: dict[str, Any], request_id: str) -> dict[str, Any] | None:
    history = run["bindings"].get(request_id)
    if history is None:
        return None
    if not isinstance(history, list) or any(not isinstance(item, dict) for item in history):
        raise FullVideoContinuityError("CONTINUITY_STATE_INVALID")
    return history[-1] if history else None


def _binding_history(run: dict[str, Any], request_id: str) -> list[dict[str, Any]]:
    history = run["bindings"].setdefault(request_id, [])
    if not isinstance(history, list):
        raise FullVideoContinuityError("CONTINUITY_STATE_INVALID")
    return history


def _reference_path(paths, run_id: str, request_id: str, revision: int, suffix: str) -> tuple[str, Path]:
    suffix = suffix.lower() if suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else ".png"
    relative = f"assets/continuity/{run_id}/{request_id}/reference_r{revision:03d}{suffix}"
    return relative, paths.artifact_path(relative)


def _copy_validated_anchor(source: Path, destination: Path) -> dict[str, Any]:
    try:
        metadata = validate_image(source)
    except AssetValidationError as error:
        raise FullVideoContinuityError("CONTINUITY_ANCHOR_INVALID") from error
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.stem + ".tmp" + destination.suffix)
    try:
        shutil.copyfile(source, temporary)
        copied = validate_image(temporary)
        if copied.get("sha256") != metadata.get("sha256"):
            raise FullVideoContinuityError("CONTINUITY_ANCHOR_COPY_MISMATCH")
        os.replace(temporary, destination)
    except FullVideoContinuityError:
        temporary.unlink(missing_ok=True)
        raise
    except Exception as error:
        temporary.unlink(missing_ok=True)
        raise FullVideoContinuityError("CONTINUITY_ANCHOR_COPY_FAILED") from error
    return copied


def _frame_timestamp(request: dict[str, Any], video_metadata: dict[str, Any]) -> float:
    target = float(request["target_duration"])
    duration = float(video_metadata["duration_seconds"])
    desired = target / 2.0 if target <= 0.5 else target - 0.5
    safe_latest = max(0.0, duration - 0.05)
    return round(max(0.0, min(desired, safe_latest)), 6)


def _extract_frame(source: Path, destination: Path, timestamp: float) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.stem + ".tmp.png")
    try:
        result = subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{timestamp:.6f}",
            "-i", str(source), "-frames:v", "1", str(temporary),
        ], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise FullVideoContinuityError("CONTINUITY_FRAME_EXTRACTION_FAILED", result.stderr[-500:])
        metadata = validate_image(temporary)
        os.replace(temporary, destination)
        return metadata
    except FileNotFoundError as error:
        temporary.unlink(missing_ok=True)
        raise FullVideoContinuityError("CONTINUITY_FFMPEG_UNAVAILABLE") from error
    except AssetValidationError as error:
        temporary.unlink(missing_ok=True)
        raise FullVideoContinuityError("CONTINUITY_FRAME_INVALID") from error
    except FullVideoContinuityError:
        temporary.unlink(missing_ok=True)
        raise


def _snapshot(run: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": REFERENCE_SNAPSHOT_VERSION,
        "run_id": run["run_id"],
        "generation_requests_sha256": run["generation_requests_sha256"],
        "target_request_id": binding["target_request_id"],
        "target_request_identity_sha256": binding["target_request_identity_sha256"],
        "binding_revision": binding["revision"],
        "source_kind": binding["source_kind"],
        "source_provenance": binding.get("source_provenance"),
        "source_request_id": binding.get("source_request_id"),
        "source_asset_path": binding.get("source_asset_path"),
        "source_asset_sha256": binding["source_asset_sha256"],
        "source_asset_attempt": binding.get("source_asset_attempt"),
        "source_quality_state": binding.get("source_quality_state"),
        "frame_policy": binding.get("frame_policy"),
        "frame_timestamp_seconds": binding.get("frame_timestamp_seconds"),
        "reference_path": binding["reference_path"],
        "reference_sha256": binding["reference_sha256"],
    }


def begin_continuity_run(runtime_root: Path | str, project_id: str, run_id: str) -> dict[str, Any]:
    runtime = RuntimeLayout.from_root(runtime_root)
    paths, _config = load_project(runtime, project_id)
    with ProjectLock(paths.runtime, project_id):
        _requests, requests_sha = _load_requests(paths)
        state = _load_state(paths, project_id)
        run, created = _ensure_run(state, run_id, requests_sha)
        if created:
            atomic_write_json(_state_path(paths), state)
        return {"status": "STARTED" if created else "REUSED", "run_id": run_id,
                "generation_requests_sha256": requests_sha}


def bind_initial_anchor(runtime_root: Path | str, project_id: str, run_id: str, target_request_id: str,
                        source_path: Path | str, *, source_provenance: str) -> dict[str, Any]:
    if not isinstance(source_provenance, str) or not source_provenance.strip():
        raise FullVideoContinuityError("CONTINUITY_ANCHOR_PROVENANCE_REQUIRED")
    runtime = RuntimeLayout.from_root(runtime_root)
    paths, _config = load_project(runtime, project_id)
    source = Path(source_path).expanduser().resolve()
    with ProjectLock(paths.runtime, project_id):
        requests_value, requests_sha = _load_requests(paths)
        ordered = _video_requests(requests_value)
        target = _request_by_id(requests_value, target_request_id)
        if ordered[0]["request_id"] != target_request_id:
            raise FullVideoContinuityError("CONTINUITY_INITIAL_ANCHOR_TARGET_INVALID")
        manifest = _load_manifest(paths)
        if _target_provider_boundary_entered(manifest, target_request_id):
            raise FullVideoContinuityError("CONTINUITY_TARGET_ALREADY_DISPATCHED")
        state = _load_state(paths, project_id)
        run, _created = _ensure_run(state, run_id, requests_sha)
        try:
            source_metadata = validate_image(source)
        except AssetValidationError as error:
            raise FullVideoContinuityError("CONTINUITY_ANCHOR_INVALID") from error
        latest = _latest_binding(run, target_request_id)
        if (isinstance(latest, dict) and latest.get("status") == "BOUND"
                and latest.get("source_kind") == "INITIAL_ANCHOR"
                and latest.get("source_asset_sha256") == source_metadata.get("sha256")
                and latest.get("target_request_identity_sha256") == target["fingerprint"]):
            resolved = _resolve_continuity_reference_locked(paths, project_id, run_id, target_request_id,
                                                            requests_value, requests_sha, state)
            return {**resolved, "idempotent": True}
        history = _binding_history(run, target_request_id)
        if isinstance(latest, dict) and latest.get("status") == "BOUND":
            latest.update({"status": "SUPERSEDED", "superseded_at": _now(), "supersession_reason": "ANCHOR_REBOUND_BEFORE_DISPATCH"})
        revision = len(history) + 1
        format_suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(str(source_metadata.get("format") or "").upper(), ".png")
        relative, destination = _reference_path(paths, run_id, target_request_id, revision, format_suffix)
        copied = _copy_validated_anchor(source, destination)
        binding = {
            "revision": revision, "status": "BOUND", "bound_at": _now(),
            "target_request_id": target_request_id, "target_request_identity_sha256": target["fingerprint"],
            "source_kind": "INITIAL_ANCHOR", "source_provenance": source_provenance.strip(),
            "source_asset_sha256": source_metadata["sha256"], "source_quality_state": "CANONICAL_ANCHOR",
            "frame_policy": "SOURCE_IMAGE_EXACT", "frame_timestamp_seconds": None,
            "reference_path": relative, "reference_sha256": copied["sha256"], "reference_metadata": copied,
        }
        history.append(binding)
        atomic_write_json(_state_path(paths), state)
        return _snapshot(run, binding)


def bind_previous_accepted_frame(runtime_root: Path | str, project_id: str, run_id: str,
                                 target_request_id: str) -> dict[str, Any]:
    runtime = RuntimeLayout.from_root(runtime_root)
    paths, _config = load_project(runtime, project_id)
    with ProjectLock(paths.runtime, project_id):
        requests_value, requests_sha = _load_requests(paths)
        target = _request_by_id(requests_value, target_request_id)
        manifest = _load_manifest(paths)
        if _target_provider_boundary_entered(manifest, target_request_id):
            raise FullVideoContinuityError("CONTINUITY_TARGET_ALREADY_DISPATCHED")
        source_request, _source_entry, selected, video_metadata = _previous_accepted_source(paths, requests_value, manifest, target)
        timestamp = _frame_timestamp(source_request, video_metadata)
        state = _load_state(paths, project_id)
        run, _created = _ensure_run(state, run_id, requests_sha)
        latest = _latest_binding(run, target_request_id)
        if (isinstance(latest, dict) and latest.get("status") == "BOUND"
                and latest.get("source_kind") == "ACCEPTED_PREVIOUS_VIDEO_FRAME"
                and latest.get("source_request_id") == source_request["request_id"]
                and latest.get("source_asset_sha256") == selected.get("sha256")
                and latest.get("source_asset_attempt") == selected.get("attempt")
                and latest.get("frame_timestamp_seconds") == timestamp
                and latest.get("target_request_identity_sha256") == target["fingerprint"]):
            resolved = _resolve_continuity_reference_locked(paths, project_id, run_id, target_request_id,
                                                            requests_value, requests_sha, state)
            return {**resolved, "idempotent": True}
        history = _binding_history(run, target_request_id)
        if isinstance(latest, dict) and latest.get("status") == "BOUND":
            latest.update({"status": "SUPERSEDED", "superseded_at": _now(),
                           "supersession_reason": "SOURCE_ASSET_REPLACED_BEFORE_TARGET_DISPATCH"})
        revision = len(history) + 1
        relative, destination = _reference_path(paths, run_id, target_request_id, revision, ".png")
        source_path = paths.artifact_path(selected["path"])
        frame_metadata = _extract_frame(source_path, destination, timestamp)
        binding = {
            "revision": revision, "status": "BOUND", "bound_at": _now(),
            "target_request_id": target_request_id, "target_request_identity_sha256": target["fingerprint"],
            "source_kind": "ACCEPTED_PREVIOUS_VIDEO_FRAME", "source_request_id": source_request["request_id"],
            "source_asset_path": selected["path"], "source_asset_sha256": selected["sha256"],
            "source_asset_attempt": selected.get("attempt"), "source_quality_state": selected.get("production_qc"),
            "frame_policy": FRAME_POLICY, "frame_timestamp_seconds": timestamp,
            "reference_path": relative, "reference_sha256": frame_metadata["sha256"], "reference_metadata": frame_metadata,
        }
        history.append(binding)
        atomic_write_json(_state_path(paths), state)
        return _snapshot(run, binding)


def _resolve_continuity_reference_locked(paths, project_id: str, run_id: str, target_request_id: str,
                                         requests_value: dict[str, Any], requests_sha: str,
                                         state: dict[str, Any]) -> dict[str, Any]:
    run = state["runs"].get(run_id)
    if not isinstance(run, dict):
        raise FullVideoContinuityError("CONTINUITY_RUN_NOT_FOUND")
    if run.get("generation_requests_sha256") != requests_sha:
        raise FullVideoContinuityError("CONTINUITY_RUN_PLAN_MISMATCH")
    target = _request_by_id(requests_value, target_request_id)
    binding = _latest_binding(run, target_request_id)
    if not isinstance(binding, dict) or binding.get("status") != "BOUND":
        raise FullVideoContinuityError("CONTINUITY_REFERENCE_MISSING")
    if binding.get("target_request_identity_sha256") != target["fingerprint"]:
        raise FullVideoContinuityError("CONTINUITY_TARGET_IDENTITY_CHANGED")
    reference = paths.artifact_path(binding["reference_path"])
    try:
        reference_metadata = validate_image(reference)
    except AssetValidationError as error:
        raise FullVideoContinuityError("CONTINUITY_REFERENCE_INVALID") from error
    if reference_metadata.get("sha256") != binding.get("reference_sha256"):
        raise FullVideoContinuityError("CONTINUITY_REFERENCE_CHANGED")
    if binding.get("source_kind") == "ACCEPTED_PREVIOUS_VIDEO_FRAME":
        source_request = _request_by_id(requests_value, binding.get("source_request_id"))
        _entry, selected, _metadata = _accepted_source(paths, _load_manifest(paths), source_request)
        if (selected.get("path") != binding.get("source_asset_path")
                or selected.get("sha256") != binding.get("source_asset_sha256")
                or selected.get("attempt") != binding.get("source_asset_attempt")):
            raise FullVideoContinuityError("CONTINUITY_SOURCE_ASSET_CHANGED")
    return _snapshot(run, binding)


def resolve_continuity_reference(runtime_root: Path | str, project_id: str, run_id: str,
                                 target_request_id: str) -> dict[str, Any]:
    runtime = RuntimeLayout.from_root(runtime_root)
    paths, _config = load_project(runtime, project_id)
    with ProjectLock(paths.runtime, project_id):
        requests_value, requests_sha = _load_requests(paths)
        state = _load_state(paths, project_id)
        return _resolve_continuity_reference_locked(paths, project_id, run_id, target_request_id,
                                                    requests_value, requests_sha, state)


def reconcile_continuity_run(runtime_root: Path | str, project_id: str, run_id: str) -> dict[str, Any]:
    runtime = RuntimeLayout.from_root(runtime_root)
    paths, _config = load_project(runtime, project_id)
    with ProjectLock(paths.runtime, project_id):
        requests_value, requests_sha = _load_requests(paths)
        state = _load_state(paths, project_id)
        run = state["runs"].get(run_id)
        if not isinstance(run, dict):
            raise FullVideoContinuityError("CONTINUITY_RUN_NOT_FOUND")
        invalidated: list[str] = []
        if run.get("generation_requests_sha256") != requests_sha:
            run["status"] = "STALE_PLAN"
            for request_id, history in run.get("bindings", {}).items():
                latest = history[-1] if isinstance(history, list) and history else None
                if isinstance(latest, dict) and latest.get("status") == "BOUND":
                    latest.update({"status": "INVALIDATED", "invalidated_at": _now(),
                                   "invalidation_reason": "GENERATION_REQUESTS_CHANGED"})
                    invalidated.append(request_id)
            atomic_write_json(_state_path(paths), state)
            return {"status": "STALE_PLAN", "run_id": run_id, "invalidated_request_ids": invalidated}
        manifest = _load_manifest(paths)
        for request_id, history in run.get("bindings", {}).items():
            latest = history[-1] if isinstance(history, list) and history else None
            if not isinstance(latest, dict) or latest.get("status") != "BOUND":
                continue
            reason = None
            try:
                reference = paths.artifact_path(latest["reference_path"])
                metadata = validate_image(reference)
                if metadata.get("sha256") != latest.get("reference_sha256"):
                    reason = "REFERENCE_CHANGED"
                elif latest.get("source_kind") == "ACCEPTED_PREVIOUS_VIDEO_FRAME":
                    source_request = _request_by_id(requests_value, latest.get("source_request_id"))
                    _entry, selected, _video = _accepted_source(paths, manifest, source_request)
                    if (selected.get("path") != latest.get("source_asset_path")
                            or selected.get("sha256") != latest.get("source_asset_sha256")
                            or selected.get("attempt") != latest.get("source_asset_attempt")):
                        reason = "SOURCE_ASSET_CHANGED"
            except (FullVideoContinuityError, AssetValidationError):
                reason = reason or "SOURCE_NO_LONGER_ACCEPTED"
            if reason:
                latest.update({"status": "INVALIDATED", "invalidated_at": _now(), "invalidation_reason": reason})
                invalidated.append(request_id)
        if invalidated:
            atomic_write_json(_state_path(paths), state)
        return {"status": "INVALIDATED" if invalidated else "CURRENT", "run_id": run_id,
                "invalidated_request_ids": invalidated}

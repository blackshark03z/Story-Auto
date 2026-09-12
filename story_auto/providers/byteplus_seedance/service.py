"""Durable Seedance task execution for Full Video.

Submission and observation are deliberately separated. Once a provider task ID
is known, every resume polls that same task. An ambiguous POST never authorizes
a second POST. Terminal provider failure also requires an explicit replacement
request rather than an automatic redispatch.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock
from story_auto.providers.flow.validation import validate_video
from .client import BytePlusSeedanceClient, BytePlusSeedanceError, NONTERMINAL_STATUSES


MANIFEST_VERSION = "story-auto-generation-manifest/1.0.0"
PROVIDER_ID = "byteplus_seedance"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def seedance_readiness(client: BytePlusSeedanceClient | None = None) -> dict[str, Any]:
    return (client or BytePlusSeedanceClient()).readiness()


def _manifest(paths, project_id: str) -> tuple[Path, dict[str, Any]]:
    path = paths.artifact_path("output/generation_manifest.json")
    if path.is_file():
        try:
            value = read_json(path)
        except Exception as error:
            raise BytePlusSeedanceError("GENERATION_MANIFEST_INVALID") from error
        if value.get("schema_version") != MANIFEST_VERSION or value.get("project_id") != project_id or not isinstance(value.get("requests"), list):
            raise BytePlusSeedanceError("GENERATION_MANIFEST_INVALID")
        return path, value
    value = {"schema_version": MANIFEST_VERSION, "project_id": project_id, "requests": []}
    return path, value


def _request_entry(manifest: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    matches = [item for item in manifest["requests"] if isinstance(item, dict) and item.get("request_id") == request["request_id"]]
    if len(matches) > 1:
        raise BytePlusSeedanceError("GENERATION_MANIFEST_INVALID")
    if matches:
        entry = matches[0]
        expected = (request.get("fingerprint"), request.get("shot_id"), request.get("media_type"), request.get("provider"))
        observed = (entry.get("request_identity_sha256"), entry.get("related_identity"), entry.get("media_type"), entry.get("provider"))
        if expected != observed:
            raise BytePlusSeedanceError("GENERATION_REQUEST_IDENTITY_MISMATCH")
        return entry
    entry = {
        "request_id": request["request_id"],
        "request_identity_sha256": request.get("fingerprint"),
        "related_identity": request.get("shot_id"),
        "media_type": request.get("media_type"),
        "provider": request.get("provider"),
        "status": "PENDING",
        "provider_submissions": 0,
        "attempts": [],
        "updated_at": _now(),
    }
    manifest["requests"].append(entry)
    return entry


def _selected_valid(paths, entry: dict[str, Any]) -> bool:
    selected = entry.get("selected_asset")
    if not isinstance(selected, dict) or not isinstance(selected.get("path"), str):
        return False
    path = paths.artifact_path(selected["path"])
    if not path.is_file():
        return False
    try:
        metadata = validate_video(path)
    except Exception:
        return False
    return metadata.get("sha256") == selected.get("sha256")


def _usage(task: dict[str, Any]) -> dict[str, Any] | None:
    value = task.get("usage")
    if not isinstance(value, dict):
        return None
    allowed = {key: value[key] for key in ("completion_tokens", "total_tokens") if isinstance(value.get(key), (int, float)) and not isinstance(value.get(key), bool)}
    return allowed or None


def _persist_terminal_failure(path: Path, manifest: dict[str, Any], entry: dict[str, Any], attempt: dict[str, Any], status: str) -> None:
    at = _now()
    attempt.update({"status": "FAILED_TERMINAL", "provider_execution_state": status.upper(), "completed_at": at})
    attempt.setdefault("terminal_evidence", []).append({
        "observed_at": at,
        "authoritative": True,
        "failure_family": "PROVIDER_TERMINAL_UNKNOWN",
        "exact_attribution_confirmed": True,
        "provider_task_status": status,
    })
    entry.update({"status": "FAILED_RETRYABLE", "failure_class": f"PROVIDER_TASK_{status.upper()}", "updated_at": at})
    atomic_write_json(path, manifest)


def _acquire(paths, path: Path, manifest: dict[str, Any], request: dict[str, Any], entry: dict[str, Any],
             attempt: dict[str, Any], task: dict[str, Any], client: BytePlusSeedanceClient) -> bool:
    number = int(attempt["attempt"])
    relative = f"assets/video/{request['request_id']}/attempt_{number:03d}.mp4"
    destination = paths.artifact_path(relative)
    try:
        metadata = client.acquire_video(task, destination)
    except BytePlusSeedanceError as error:
        attempt.update({"status": "SUCCEEDED_PENDING_ACQUISITION", "provider_execution_state": "SUCCEEDED",
                        "failure_class": error.failure_class, "last_observed_at": _now()})
        entry.update({"status": "GENERATING", "failure_class": error.failure_class, "updated_at": _now()})
        atomic_write_json(path, manifest)
        return False
    target = float(request.get("target_duration") or 0.0)
    if target > 0 and float(metadata.get("duration_seconds") or 0.0) + 0.10 < target:
        attempt.update({"status": "FAILED_TERMINAL", "provider_execution_state": "SUCCEEDED",
                        "failure_class": "VIDEO_TOO_SHORT", "completed_at": _now()})
        entry.update({"status": "FAILED_RETRYABLE", "failure_class": "VIDEO_TOO_SHORT", "updated_at": _now()})
        atomic_write_json(path, manifest)
        return False
    usage = _usage(task)
    attempt.update({
        "status": "SUCCEEDED", "provider_execution_state": "SUCCEEDED", "completed_at": _now(),
        "asset_path": relative, "asset_sha256": metadata["sha256"], "metadata": metadata,
        "attribution_state": "CONFIRMED", "attribution_status": "CONFIRMED",
        **({"usage": usage} if usage else {}),
    })
    attempt.pop("failure_class", None)
    entry.update({
        "status": "QC_PENDING", "failure_class": None, "updated_at": _now(),
        "selected_asset": {
            "path": relative, "sha256": metadata["sha256"], "attempt": number,
            "source_provider_attempt": number, "metadata": metadata, "production_qc": "PENDING",
        },
    })
    atomic_write_json(path, manifest)
    return True


def _observe_known_task(paths, path: Path, manifest: dict[str, Any], request: dict[str, Any], entry: dict[str, Any],
                        attempt: dict[str, Any], client: BytePlusSeedanceClient, *, poll_interval: float,
                        max_poll_seconds: float) -> tuple[str, bool]:
    task_id = attempt.get("provider_job_id")
    if not isinstance(task_id, str) or not task_id:
        return "AMBIGUOUS", False
    deadline = time.monotonic() + max(0.0, max_poll_seconds)
    transient_reads = 0
    while True:
        try:
            task = client.get_task(task_id)
            transient_reads = 0
        except BytePlusSeedanceError as error:
            if error.failure_class == "PROVIDER_TRANSIENT" and transient_reads < 2 and time.monotonic() < deadline:
                transient_reads += 1
                time.sleep(min(poll_interval, 2.0))
                continue
            attempt["last_poll_failure"] = error.failure_class
            attempt["last_observed_at"] = _now()
            entry.update({"status": "GENERATING", "failure_class": "PROVIDER_POLL_UNAVAILABLE", "updated_at": _now()})
            atomic_write_json(path, manifest)
            return "GENERATING", False
        status = str(task.get("status") or "").lower()
        attempt.update({"provider_execution_state": status.upper(), "last_observed_at": _now()})
        attempt.pop("last_poll_failure", None)
        entry["failure_class"] = None
        atomic_write_json(path, manifest)
        if status == "succeeded":
            return "QC_PENDING" if _acquire(paths, path, manifest, request, entry, attempt, task, client) else entry["status"], entry.get("status") == "QC_PENDING"
        if status in {"failed", "expired", "cancelled"}:
            _persist_terminal_failure(path, manifest, entry, attempt, status)
            return entry["status"], False
        if status not in NONTERMINAL_STATUSES:
            entry.update({"status": "AMBIGUOUS", "failure_class": "PROVIDER_TASK_STATE_UNKNOWN", "updated_at": _now()})
            attempt.update({"status": "AMBIGUOUS", "attribution_state": "UNCERTAIN"})
            atomic_write_json(path, manifest)
            return "AMBIGUOUS", False
        entry["status"] = "GENERATING"
        atomic_write_json(path, manifest)
        if time.monotonic() >= deadline:
            return "GENERATING", False
        time.sleep(max(0.05, poll_interval))


def execute_seedance_generation(runtime_root: Path | str, project_id: str, *,
                                client: BytePlusSeedanceClient | None = None,
                                request_ids: set[str] | None = None, max_requests: int | None = None,
                                poll_interval: float = 5.0, max_poll_seconds: float = 900.0) -> dict[str, Any]:
    runtime = RuntimeLayout.from_root(runtime_root)
    paths, config = load_project(runtime, project_id)
    if config.render_mode != "full_video_ai":
        raise BytePlusSeedanceError("SEEDANCE_MODE_INVALID")
    seedance_settings = config.settings.get("seedance", {}) if isinstance(config.settings, dict) else {}
    resolution = str(seedance_settings.get("resolution", "720p")) if isinstance(seedance_settings, dict) else "720p"
    active = client or BytePlusSeedanceClient()
    if active.readiness()["status"] != "READY":
        raise BytePlusSeedanceError("CREDENTIAL_MISSING")
    with ProjectLock(paths.runtime, project_id):
        try:
            requests_value = read_json(paths.artifact_path("output/generation_requests.json"))
        except Exception as error:
            raise BytePlusSeedanceError("GENERATION_REQUESTS_INVALID") from error
        requests = [item for item in requests_value.get("requests", []) if isinstance(item, dict)]
        candidates = [item for item in requests if item.get("media_type") == "VIDEO" and item.get("purpose") == "SHOT"]
        if request_ids is not None:
            candidates = [item for item in candidates if item.get("request_id") in request_ids]
        if any(item.get("provider") != PROVIDER_ID for item in candidates):
            raise BytePlusSeedanceError("SEEDANCE_PROVIDER_MISMATCH")
        path, manifest = _manifest(paths, project_id)
        new_submissions = resumed_tasks = completed_assets = 0
        considered = 0
        blocked_request_id = None
        for request in candidates:
            entry = _request_entry(manifest, request)
            if entry.get("status") in {"SUCCEEDED", "QC_PENDING"} and _selected_valid(paths, entry):
                continue
            attempts = entry.get("attempts") if isinstance(entry.get("attempts"), list) else []
            latest = attempts[-1] if attempts else None
            if isinstance(latest, dict) and isinstance(latest.get("provider_job_id"), str):
                resumed_tasks += 1
                _status, complete = _observe_known_task(paths, path, manifest, request, entry, latest, active,
                                                        poll_interval=poll_interval, max_poll_seconds=max_poll_seconds)
                completed_assets += int(complete)
                if entry.get("status") not in {"QC_PENDING", "SUCCEEDED"}:
                    blocked_request_id = request["request_id"]
                    break
                continue
            if attempts:
                blocked_request_id = request["request_id"]
                break
            if max_requests is not None and considered >= max_requests:
                break
            considered += 1
            number = 1
            attempt = {
                "attempt": number, "status": "PRE_DISPATCH", "started_at": _now(),
                "provider_mode": "VIDEO", "provider_model": active.model,
                "provider_execution_state": "NOT_STARTED", "dispatch_confirmed": False,
                "attribution_state": "NOT_STARTED", "attribution_status": "NOT_STARTED",
                "provider_settings": {"resolution": resolution, "aspect_ratio": request.get("aspect_ratio", "16:9"),
                                      "target_duration": request.get("target_duration")},
            }
            attempts.append(attempt)
            entry.update({"attempts": attempts, "status": "GENERATING", "failure_class": None, "updated_at": _now()})
            atomic_write_json(path, manifest)
            try:
                provider_duration = max(4.0, float(request.get("target_duration") or 0.0))
                task_id = active.create_task(prompt=request.get("prompt", ""), duration=provider_duration,
                                             aspect_ratio=str(request.get("aspect_ratio") or "16:9"), resolution=resolution)
            except BytePlusSeedanceError as error:
                if error.dispatch_state == "AMBIGUOUS":
                    attempt.update({"status": "AMBIGUOUS", "provider_execution_state": "DISPATCH_UNCERTAIN",
                                    "dispatch_confirmed": False, "attribution_state": "UNCERTAIN",
                                    "attribution_status": "UNCERTAIN", "failure_class": error.failure_class})
                    entry.update({"status": "AMBIGUOUS", "failure_class": error.failure_class, "updated_at": _now()})
                else:
                    attempt.update({"status": "FAILED_PRE_DISPATCH", "provider_execution_state": "NOT_STARTED",
                                    "dispatch_confirmed": False, "attribution_state": "NOT_STARTED",
                                    "failure_class": error.failure_class,
                                    "canonical_no_dispatch_proof": True})
                    entry.update({"status": "FAILED_RETRYABLE", "failure_class": error.failure_class, "updated_at": _now()})
                atomic_write_json(path, manifest)
                blocked_request_id = request["request_id"]
                break
            new_submissions += 1
            entry["provider_submissions"] = int(entry.get("provider_submissions", 0)) + 1
            attempt.update({"status": "SUBMITTED", "provider_job_id": task_id,
                            "provider_execution_state": "QUEUED", "dispatch_confirmed": True,
                            "attribution_state": "CONFIRMED", "attribution_status": "CONFIRMED",
                            "provider_submission_recorded": True, "submitted_at": _now()})
            atomic_write_json(path, manifest)
            _status, complete = _observe_known_task(paths, path, manifest, request, entry, attempt, active,
                                                    poll_interval=poll_interval, max_poll_seconds=max_poll_seconds)
            completed_assets += int(complete)
            if entry.get("status") not in {"QC_PENDING", "SUCCEEDED"}:
                blocked_request_id = request["request_id"]
                break
        return {
            "status": "BLOCKED" if blocked_request_id else "READY_FOR_QUALITY",
            "project_id": project_id,
            "provider": PROVIDER_ID,
            "model": active.model,
            "new_submissions": new_submissions,
            "resumed_tasks": resumed_tasks,
            "completed_assets": completed_assets,
            "blocked": blocked_request_id is not None,
            "blocked_request_id": blocked_request_id,
        }

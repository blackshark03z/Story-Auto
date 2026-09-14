"""Gated production adapter for Elyum Seedance I2V.

This module uses Story Auto's canonical generation manifest and Slice B
continuity snapshots. It never reads or writes Goal 54 research ledgers. The
adapter is intentionally not wired into Operator routing yet; callers must pass
``dispatch_authorized=True`` and product routing remains disabled by the Full
Video provider capability contract until later integration slices are accepted.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable
import urllib.request

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.full_video_continuity import (FullVideoContinuityError,
                                                   resolve_continuity_reference_under_lock)
from story_auto.core.full_video_provider import resolve_full_video_provider
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock
from story_auto.providers.flow.validation import AssetValidationError, validate_video
from .client import DEFAULT_FAST_I2V_MODEL, ElyumSeedanceClient, ElyumSeedanceError


MANIFEST_VERSION = "story-auto-generation-manifest/1.0.0"
PROVIDER_ID = "elyum_seedance"
DEFAULT_RESOLUTION = "480p"
DEFAULT_PROVIDER_DURATION_SECONDS = 4
DEFAULT_MAX_CREDITS = 44


class ElyumProductionError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(failure_class + (f": {detail}" if detail else ""))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _manifest(paths, project_id: str) -> tuple[Path, dict[str, Any]]:
    path = paths.artifact_path("output/generation_manifest.json")
    if not path.is_file():
        return path, {"schema_version": MANIFEST_VERSION, "project_id": project_id, "requests": []}
    try:
        value = read_json(path)
    except Exception as error:
        raise ElyumProductionError("GENERATION_MANIFEST_INVALID") from error
    if (not isinstance(value, dict) or value.get("schema_version") != MANIFEST_VERSION
            or value.get("project_id") != project_id or not isinstance(value.get("requests"), list)):
        raise ElyumProductionError("GENERATION_MANIFEST_INVALID")
    return path, value


def _request_entry(manifest: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    matches = [item for item in manifest["requests"]
               if isinstance(item, dict) and item.get("request_id") == request["request_id"]]
    if len(matches) > 1:
        raise ElyumProductionError("GENERATION_MANIFEST_INVALID")
    if matches:
        entry = matches[0]
        expected = (request.get("fingerprint"), request.get("shot_id"), request.get("media_type"), request.get("provider"))
        observed = (entry.get("request_identity_sha256"), entry.get("related_identity"), entry.get("media_type"), entry.get("provider"))
        if expected != observed:
            raise ElyumProductionError("GENERATION_REQUEST_IDENTITY_MISMATCH")
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


def _client_ref(project_id: str, run_id: str, request: dict[str, Any], reference: dict[str, Any],
                model: str, provider_duration: int, resolution: str) -> str:
    identity = {
        "project_id": project_id,
        "run_id": run_id,
        "request_id": request["request_id"],
        "request_identity_sha256": request.get("fingerprint"),
        "reference_sha256": reference["reference_sha256"],
        "binding_revision": reference["binding_revision"],
        "model": model,
        "provider_duration": provider_duration,
        "resolution": resolution,
        "aspect_ratio": request.get("aspect_ratio", "16:9"),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return "story-auto-prod-" + digest[:48]


def _default_preview_fetcher(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "StoryAuto-ElyumProduction/1", "Accept": "video/mp4,*/*"})
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.stem + ".tmp" + destination.suffix)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
        if not payload:
            raise ElyumProductionError("ELYUM_PREVIEW_EMPTY")
        temporary.write_bytes(payload)
        temporary.replace(destination)
    except ElyumProductionError:
        temporary.unlink(missing_ok=True)
        raise
    except Exception as error:
        temporary.unlink(missing_ok=True)
        raise ElyumProductionError("ELYUM_PREVIEW_DOWNLOAD_FAILED") from error


def _preview_valid(paths, attempt: dict[str, Any]) -> bool:
    asset = attempt.get("preview_asset")
    if not isinstance(asset, dict) or not isinstance(asset.get("path"), str):
        return False
    path = paths.artifact_path(asset["path"])
    if not path.is_file():
        return False
    try:
        metadata = validate_video(path)
    except AssetValidationError:
        return False
    return metadata.get("sha256") == asset.get("sha256")


def _selected_valid(paths, entry: dict[str, Any]) -> bool:
    selected = entry.get("selected_asset")
    if (entry.get("status") != "SUCCEEDED" or not isinstance(selected, dict)
            or selected.get("production_qc") != "OWNER_ACCEPTED"
            or not isinstance(selected.get("path"), str)):
        return False
    path = paths.artifact_path(selected["path"])
    if not path.is_file():
        return False
    try:
        metadata = validate_video(path)
    except AssetValidationError:
        return False
    return metadata.get("sha256") == selected.get("sha256")


def _find_entry(manifest: dict[str, Any], request_id: str) -> dict[str, Any]:
    matches = [item for item in manifest.get("requests", [])
               if isinstance(item, dict) and item.get("request_id") == request_id]
    if len(matches) != 1:
        raise ElyumProductionError("ELYUM_REQUEST_NOT_FOUND")
    return matches[0]


def _latest_attempt(entry: dict[str, Any]) -> dict[str, Any]:
    attempts = entry.get("attempts")
    latest = attempts[-1] if isinstance(attempts, list) and attempts else None
    if not isinstance(latest, dict):
        raise ElyumProductionError("ELYUM_ATTEMPT_NOT_FOUND")
    return latest


def _require_elyum_project(runtime_root: Path | str, project_id: str):
    runtime = RuntimeLayout.from_root(runtime_root)
    paths, config = load_project(runtime, project_id)
    if config.render_mode != "full_video_ai" or resolve_full_video_provider(config.settings) != PROVIDER_ID:
        raise ElyumProductionError("ELYUM_PRODUCTION_MODE_INVALID")
    return paths, config


def _record_preflight(entry: dict[str, Any], *, balance: int, estimate: int, max_credits: int) -> None:
    entry.setdefault("preflight_events", []).append({
        "observed_at": _now(), "balance": int(balance), "estimate_credits": int(estimate),
        "max_credits": int(max_credits), "provider": PROVIDER_ID,
    })


def _acquire_preview(paths, manifest_path: Path, manifest: dict[str, Any], request: dict[str, Any],
                     entry: dict[str, Any], attempt: dict[str, Any], result: Any,
                     client: ElyumSeedanceClient, preview_fetcher: Callable[[str, Path], None]) -> dict[str, Any]:
    gen_id = client.gen_id(result)
    execution_state = client.execution_state(result)
    urls = client.preview_urls(result)
    unlock_credits = client.unlock_credits(result)
    attempt.update({"last_observed_at": _now(), "provider_execution_state": execution_state,
                    **({"unlock_credits": unlock_credits} if unlock_credits is not None else {})})
    if not gen_id:
        if execution_state in {"failed", "error", "cancelled", "canceled"}:
            attempt.update({"status": "FAILED_TERMINAL", "failure_class": f"PROVIDER_{str(execution_state).upper()}"})
            entry.update({"status": "FAILED_RETRYABLE", "failure_class": attempt["failure_class"], "updated_at": _now()})
        else:
            attempt["status"] = "GENERATING"
            entry.update({"status": "GENERATING", "failure_class": None, "updated_at": _now()})
        atomic_write_json(manifest_path, manifest)
        return {"status": entry["status"], "request_id": request["request_id"], "job_id": attempt.get("provider_job_id")}
    attempt["gen_id"] = gen_id
    if not urls:
        attempt.update({"status": "PREVIEW_ACQUISITION_FAILED", "failure_class": "ELYUM_PREVIEW_URL_MISSING"})
        entry.update({"status": "FAILED_RETRYABLE", "failure_class": "ELYUM_PREVIEW_URL_MISSING", "updated_at": _now()})
        atomic_write_json(manifest_path, manifest)
        return {"status": "FAILED_RETRYABLE", "request_id": request["request_id"], "job_id": attempt.get("provider_job_id")}
    number = int(attempt["attempt"])
    relative = f"assets/video/{request['request_id']}/attempt_{number:03d}_locked_preview.mp4"
    destination = paths.artifact_path(relative)
    preview_fetcher(urls[0], destination)
    try:
        metadata = validate_video(destination)
    except AssetValidationError as error:
        destination.unlink(missing_ok=True)
        attempt.update({"status": "PREVIEW_ACQUISITION_FAILED", "failure_class": "VIDEO_ASSET_INVALID"})
        entry.update({"status": "FAILED_RETRYABLE", "failure_class": "VIDEO_ASSET_INVALID", "updated_at": _now()})
        atomic_write_json(manifest_path, manifest)
        raise ElyumProductionError("VIDEO_ASSET_INVALID") from error
    target = float(request.get("target_duration") or 0.0)
    if target > 0 and float(metadata.get("duration_seconds") or 0.0) + 0.10 < target:
        attempt.update({"status": "PREVIEW_ACQUISITION_FAILED", "failure_class": "VIDEO_TOO_SHORT"})
        entry.update({"status": "FAILED_RETRYABLE", "failure_class": "VIDEO_TOO_SHORT", "updated_at": _now()})
        atomic_write_json(manifest_path, manifest)
        return {"status": "FAILED_RETRYABLE", "request_id": request["request_id"], "job_id": attempt.get("provider_job_id")}
    attempt.update({"status": "PREVIEW_READY", "failure_class": None, "preview_asset": {
        "path": relative, "sha256": metadata["sha256"], "metadata": metadata,
        "locked": True, "production_qc": "PENDING",
    }})
    entry.update({"status": "PREVIEW_READY", "failure_class": None, "updated_at": _now()})
    atomic_write_json(manifest_path, manifest)
    return {"status": "PREVIEW_READY", "request_id": request["request_id"],
            "job_id": attempt.get("provider_job_id"), "gen_id": gen_id,
            "preview_path": relative, "preview_sha256": metadata["sha256"],
            "unlock_credits": unlock_credits}


def elyum_production_readiness(client: ElyumSeedanceClient | None = None) -> dict[str, Any]:
    return (client or ElyumSeedanceClient()).readiness()


def review_elyum_preview(runtime_root: Path | str, project_id: str, request_id: str, *,
                         decision: str, reason: str) -> dict[str, Any]:
    """Record the Owner oracle for one exact locked preview without provider calls."""
    decision = str(decision or "").upper()
    if decision not in {"ACCEPT", "REJECT"}:
        raise ElyumProductionError("ELYUM_PREVIEW_DECISION_INVALID")
    if not isinstance(reason, str) or not reason.strip():
        raise ElyumProductionError("ELYUM_PREVIEW_REVIEW_REASON_REQUIRED")
    paths, _config = _require_elyum_project(runtime_root, project_id)
    with ProjectLock(paths.runtime, project_id):
        manifest_path, manifest = _manifest(paths, project_id)
        entry = _find_entry(manifest, request_id)
        attempt = _latest_attempt(entry)
        existing = attempt.get("preview_review")
        expected_status = "KEEP_REQUIRED" if decision == "ACCEPT" else "PREVIEW_REJECTED"
        if (isinstance(existing, dict) and existing.get("decision") == decision
                and attempt.get("status") == expected_status):
            return {"status": expected_status, "project_id": project_id, "request_id": request_id,
                    "preview_sha256": existing.get("preview_sha256"), "idempotent": True}
        if attempt.get("status") != "PREVIEW_READY" or entry.get("status") != "PREVIEW_READY":
            raise ElyumProductionError("ELYUM_PREVIEW_NOT_REVIEWABLE")
        if not _preview_valid(paths, attempt):
            raise ElyumProductionError("ELYUM_PREVIEW_ASSET_INVALID")
        preview = attempt["preview_asset"]
        review = {
            "reviewed_at": _now(), "actor": "OWNER", "decision": decision,
            "reason": reason.strip(), "preview_path": preview["path"],
            "preview_sha256": preview["sha256"], "gen_id": attempt.get("gen_id"),
            "unlock_credits": attempt.get("unlock_credits"),
        }
        attempt["preview_review"] = review
        if decision == "ACCEPT":
            preview["production_qc"] = "OWNER_ACCEPTED"
            attempt.update({"status": "KEEP_REQUIRED", "failure_class": None})
            entry.update({"status": "KEEP_REQUIRED", "failure_class": None, "updated_at": review["reviewed_at"]})
        else:
            preview["production_qc"] = "REJECTED"
            attempt.update({"status": "PREVIEW_REJECTED", "failure_class": "PREVIEW_REJECTED"})
            entry.update({"status": "PREVIEW_REJECTED", "failure_class": "PREVIEW_REJECTED",
                          "updated_at": review["reviewed_at"]})
        atomic_write_json(manifest_path, manifest)
        return {"status": attempt["status"], "project_id": project_id, "request_id": request_id,
                "preview_sha256": preview["sha256"], "gen_id": attempt.get("gen_id"),
                "unlock_credits": attempt.get("unlock_credits")}


def _acquire_kept_output(paths, manifest_path: Path, manifest: dict[str, Any], entry: dict[str, Any],
                         attempt: dict[str, Any], request_id: str, urls: list[str],
                         output_fetcher: Callable[[str, Path], None]) -> dict[str, Any]:
    if not urls:
        attempt.update({"status": "KEEP_ACQUISITION_REQUIRED", "failure_class": "ELYUM_KEPT_OUTPUT_URL_MISSING"})
        entry.update({"status": "KEEP_ACQUISITION_REQUIRED", "failure_class": "ELYUM_KEPT_OUTPUT_URL_MISSING",
                      "updated_at": _now()})
        atomic_write_json(manifest_path, manifest)
        return {"status": "KEEP_ACQUISITION_REQUIRED", "project_id": manifest["project_id"],
                "request_id": request_id, "failure_class": "ELYUM_KEPT_OUTPUT_URL_MISSING"}
    number = int(attempt["attempt"])
    relative = f"assets/video/{request_id}/attempt_{number:03d}_kept.mp4"
    destination = paths.artifact_path(relative)
    try:
        output_fetcher(urls[0], destination)
        metadata = validate_video(destination)
    except Exception as error:
        destination.unlink(missing_ok=True)
        attempt.update({"status": "KEEP_ACQUISITION_REQUIRED", "failure_class": "ELYUM_KEPT_OUTPUT_ACQUISITION_FAILED"})
        entry.update({"status": "KEEP_ACQUISITION_REQUIRED", "failure_class": "ELYUM_KEPT_OUTPUT_ACQUISITION_FAILED",
                      "updated_at": _now()})
        atomic_write_json(manifest_path, manifest)
        return {"status": "KEEP_ACQUISITION_REQUIRED", "project_id": manifest["project_id"],
                "request_id": request_id, "failure_class": "ELYUM_KEPT_OUTPUT_ACQUISITION_FAILED"}
    target = float(attempt.get("provider_settings", {}).get("target_duration") or 0.0)
    if target > 0 and float(metadata.get("duration_seconds") or 0.0) + 0.10 < target:
        destination.unlink(missing_ok=True)
        attempt.update({"status": "KEEP_ACQUISITION_REQUIRED", "failure_class": "VIDEO_TOO_SHORT"})
        entry.update({"status": "KEEP_ACQUISITION_REQUIRED", "failure_class": "VIDEO_TOO_SHORT", "updated_at": _now()})
        atomic_write_json(manifest_path, manifest)
        return {"status": "KEEP_ACQUISITION_REQUIRED", "project_id": manifest["project_id"],
                "request_id": request_id, "failure_class": "VIDEO_TOO_SHORT"}
    review = attempt.get("preview_review") or {}
    selected = {
        "path": relative, "sha256": metadata["sha256"], "attempt": number,
        "source_provider_attempt": number, "metadata": metadata,
        "production_qc": "OWNER_ACCEPTED", "source_preview_sha256": review.get("preview_sha256"),
        "owner_reviewed_at": review.get("reviewed_at"),
    }
    attempt.update({"status": "SUCCEEDED", "failure_class": None, "asset_path": relative,
                    "asset_sha256": metadata["sha256"], "completed_at": _now()})
    entry.update({"status": "SUCCEEDED", "failure_class": None, "selected_asset": selected, "updated_at": _now()})
    atomic_write_json(manifest_path, manifest)
    return {"status": "SUCCEEDED", "project_id": manifest["project_id"], "request_id": request_id,
            "path": relative, "sha256": metadata["sha256"], "kept": True}


def keep_elyum_preview(runtime_root: Path | str, project_id: str, request_id: str, *,
                       client: ElyumSeedanceClient | None = None, confirm_spend: bool = False,
                       output_fetcher: Callable[[str, Path], None] | None = None) -> dict[str, Any]:
    """Explicitly Keep one Owner-accepted preview, never retrying ambiguous spend."""
    paths, _config = _require_elyum_project(runtime_root, project_id)
    active = client or ElyumSeedanceClient()
    if active.readiness().get("status") != "READY":
        raise ElyumProductionError(active.readiness().get("reason_code") or "CREDENTIAL_MISSING")
    fetcher = output_fetcher or _default_preview_fetcher
    with ProjectLock(paths.runtime, project_id):
        manifest_path, manifest = _manifest(paths, project_id)
        entry = _find_entry(manifest, request_id)
        if _selected_valid(paths, entry):
            return {"status": "SUCCEEDED", "project_id": project_id, "request_id": request_id,
                    "path": entry["selected_asset"]["path"], "sha256": entry["selected_asset"]["sha256"],
                    "kept": True, "idempotent": True}
        attempt = _latest_attempt(entry)
        status = attempt.get("status")
        if status in {"KEEP_AMBIGUOUS", "KEEP_DISPATCHING"}:
            raise ElyumProductionError("ELYUM_KEEP_OUTCOME_AMBIGUOUS")
        if status == "KEEP_ACQUISITION_REQUIRED":
            if attempt.get("keep_confirmed") is not True:
                raise ElyumProductionError("ELYUM_KEEP_STATE_INVALID")
            urls = list(attempt.get("kept_output_urls") or [])
            if not urls and isinstance(attempt.get("provider_job_id"), str):
                try:
                    observed = active.job_status(attempt["provider_job_id"], thumbnails=False)
                    urls = list(active.downloadable_urls(observed))
                except ElyumSeedanceError:
                    urls = []
                if urls:
                    attempt["kept_output_urls"] = urls
                    atomic_write_json(manifest_path, manifest)
            return _acquire_kept_output(paths, manifest_path, manifest, entry, attempt, request_id, urls, fetcher)
        if confirm_spend is not True:
            raise ElyumProductionError("ELYUM_KEEP_CONFIRMATION_REQUIRED")
        if status != "KEEP_REQUIRED" or entry.get("status") != "KEEP_REQUIRED":
            raise ElyumProductionError("ELYUM_KEEP_NOT_ALLOWED")
        if not _preview_valid(paths, attempt):
            raise ElyumProductionError("ELYUM_PREVIEW_ASSET_INVALID")
        gen_id = attempt.get("gen_id")
        if not isinstance(gen_id, str) or not gen_id:
            raise ElyumProductionError("ELYUM_GEN_ID_MISSING")
        intent = {
            "action": "KEEP", "recorded_at": _now(), "gen_id": gen_id,
            "preview_sha256": attempt["preview_asset"]["sha256"],
            "unlock_credits": attempt.get("unlock_credits"),
        }
        attempt["consequence_intent"] = intent
        attempt.update({"status": "KEEP_DISPATCHING", "failure_class": None,
                        "keep_calls_started": int(attempt.get("keep_calls_started", 0)) + 1})
        entry.update({"status": "OWNER_DECISION_REQUIRED", "failure_class": None, "updated_at": _now()})
        atomic_write_json(manifest_path, manifest)
        try:
            result = active.keep(gen_id)
        except ElyumSeedanceError as error:
            attempt.update({"status": "KEEP_AMBIGUOUS", "failure_class": error.failure_class,
                            "keep_ambiguous_at": _now()})
            entry.update({"status": "OWNER_DECISION_REQUIRED", "failure_class": "KEEP_OUTCOME_AMBIGUOUS",
                          "updated_at": _now()})
            atomic_write_json(manifest_path, manifest)
            return {"status": "KEEP_AMBIGUOUS", "project_id": project_id, "request_id": request_id,
                    "failure_class": error.failure_class}
        urls = list(active.downloadable_urls(result))
        attempt.update({"status": "KEEP_CONFIRMED", "keep_confirmed": True, "kept_at": _now(),
                        "kept_output_urls": urls, "failure_class": None})
        entry.update({"status": "KEEP_ACQUISITION_REQUIRED", "failure_class": None, "updated_at": _now()})
        atomic_write_json(manifest_path, manifest)
        return _acquire_kept_output(paths, manifest_path, manifest, entry, attempt, request_id, urls, fetcher)


def kill_elyum_preview(runtime_root: Path | str, project_id: str, request_id: str, *,
                       client: ElyumSeedanceClient | None = None, confirm_kill: bool = False,
                       reason: str) -> dict[str, Any]:
    """Explicitly Kill a rejected preview; ambiguous consequence is never retried."""
    if confirm_kill is not True:
        raise ElyumProductionError("ELYUM_KILL_CONFIRMATION_REQUIRED")
    if not isinstance(reason, str) or not reason.strip():
        raise ElyumProductionError("ELYUM_KILL_REASON_REQUIRED")
    paths, _config = _require_elyum_project(runtime_root, project_id)
    active = client or ElyumSeedanceClient()
    if active.readiness().get("status") != "READY":
        raise ElyumProductionError(active.readiness().get("reason_code") or "CREDENTIAL_MISSING")
    with ProjectLock(paths.runtime, project_id):
        manifest_path, manifest = _manifest(paths, project_id)
        entry = _find_entry(manifest, request_id)
        attempt = _latest_attempt(entry)
        if attempt.get("status") == "KILLED" and entry.get("status") == "KILLED":
            return {"status": "KILLED", "project_id": project_id, "request_id": request_id, "idempotent": True}
        if attempt.get("status") in {"KILL_AMBIGUOUS", "KILL_DISPATCHING"}:
            raise ElyumProductionError("ELYUM_KILL_OUTCOME_AMBIGUOUS")
        if attempt.get("status") != "PREVIEW_REJECTED" or entry.get("status") != "PREVIEW_REJECTED":
            raise ElyumProductionError("ELYUM_KILL_NOT_ALLOWED")
        gen_id = attempt.get("gen_id")
        if not isinstance(gen_id, str) or not gen_id:
            raise ElyumProductionError("ELYUM_GEN_ID_MISSING")
        attempt["consequence_intent"] = {
            "action": "KILL", "recorded_at": _now(), "gen_id": gen_id,
            "preview_sha256": attempt.get("preview_asset", {}).get("sha256"), "reason": reason.strip(),
        }
        attempt.update({"status": "KILL_DISPATCHING", "failure_class": None,
                        "kill_calls_started": int(attempt.get("kill_calls_started", 0)) + 1})
        entry.update({"status": "OWNER_DECISION_REQUIRED", "failure_class": None, "updated_at": _now()})
        atomic_write_json(manifest_path, manifest)
        try:
            active.kill(gen_id, reason=reason.strip())
        except ElyumSeedanceError as error:
            attempt.update({"status": "KILL_AMBIGUOUS", "failure_class": error.failure_class,
                            "kill_ambiguous_at": _now()})
            entry.update({"status": "OWNER_DECISION_REQUIRED", "failure_class": "KILL_OUTCOME_AMBIGUOUS",
                          "updated_at": _now()})
            atomic_write_json(manifest_path, manifest)
            return {"status": "KILL_AMBIGUOUS", "project_id": project_id, "request_id": request_id,
                    "failure_class": error.failure_class}
        attempt.update({"status": "KILLED", "failure_class": "PREVIEW_REJECTED", "killed_at": _now(),
                        "kill_reason": reason.strip()})
        entry.update({"status": "KILLED", "failure_class": "PREVIEW_REJECTED", "updated_at": _now()})
        atomic_write_json(manifest_path, manifest)
        return {"status": "KILLED", "project_id": project_id, "request_id": request_id}


def authorize_elyum_replacement(runtime_root: Path | str, project_id: str, request_id: str, *,
                                reason: str, confirm_replace: bool = False) -> dict[str, Any]:
    """Authorize exactly one new logical attempt after a rejected result was killed.

    This boundary is provider-free. It preserves the killed attempt, copies its
    exact continuity snapshot, and creates a new durable attempt identity with a
    distinct clientRef. Provider preflight/upload/create remain deferred until a
    later explicit production continuation.
    """
    if confirm_replace is not True:
        raise ElyumProductionError("ELYUM_REPLACEMENT_CONFIRMATION_REQUIRED")
    if not isinstance(reason, str) or not reason.strip():
        raise ElyumProductionError("ELYUM_REPLACEMENT_REASON_REQUIRED")
    paths, config = _require_elyum_project(runtime_root, project_id)
    settings = config.settings.get("elyum", {}) if isinstance(config.settings.get("elyum"), dict) else {}
    model = str(settings.get("model") or DEFAULT_FAST_I2V_MODEL)
    resolution = str(settings.get("resolution") or DEFAULT_RESOLUTION)
    provider_duration = int(settings.get("provider_duration_seconds", DEFAULT_PROVIDER_DURATION_SECONDS))
    if model != DEFAULT_FAST_I2V_MODEL or resolution != "480p" or provider_duration != 4:
        raise ElyumProductionError("ELYUM_QUALIFIED_ENVELOPE_INVALID")
    with ProjectLock(paths.runtime, project_id):
        manifest_path, manifest = _manifest(paths, project_id)
        entry = _find_entry(manifest, request_id)
        latest = _latest_attempt(entry)
        if latest.get("replacement_authorized") is True and latest.get("dispatch_confirmed") is not True:
            return {"status": latest.get("status", "REPLACEMENT_AUTHORIZED"), "project_id": project_id,
                    "request_id": request_id, "attempt": latest.get("attempt"), "idempotent": True}
        if latest.get("status") != "KILLED" or entry.get("status") != "KILLED":
            raise ElyumProductionError("ELYUM_REPLACEMENT_NOT_ALLOWED")
        try:
            requests_value = read_json(paths.artifact_path("output/generation_requests.json"))
            request = next(item for item in requests_value.get("requests", [])
                           if isinstance(item, dict) and item.get("request_id") == request_id)
        except Exception as error:
            raise ElyumProductionError("GENERATION_REQUESTS_INVALID") from error
        reference = latest.get("continuity_reference")
        previous_ref = latest.get("client_ref")
        if not isinstance(reference, dict) or not isinstance(previous_ref, str) or not previous_ref:
            raise ElyumProductionError("ELYUM_REPLACEMENT_IDENTITY_INVALID")
        target_duration = float(request.get("target_duration") or 0.0)
        if target_duration <= 0 or target_duration > provider_duration + 0.001:
            raise ElyumProductionError("ELYUM_TARGET_DURATION_UNSUPPORTED")
        attempts = entry.get("attempts")
        if not isinstance(attempts, list):
            raise ElyumProductionError("GENERATION_MANIFEST_INVALID")
        number = int(latest.get("attempt") or len(attempts)) + 1
        client_ref = f"{previous_ref}-r{number}"
        if len(client_ref) > 120:
            raise ElyumProductionError("CLIENT_REF_INVALID")
        replacement = {
            "attempt": number, "status": "REPLACEMENT_AUTHORIZED", "started_at": _now(),
            "provider_mode": "VIDEO", "provider_model": model,
            "provider_execution_state": "NOT_STARTED", "dispatch_confirmed": False,
            "attribution_state": "NOT_STARTED", "attribution_status": "NOT_STARTED",
            "client_ref": client_ref,
            "continuity_reference": json.loads(json.dumps(reference)),
            "provider_settings": {"mode": "i2v", "resolution": resolution,
                                  "aspect_ratio": request.get("aspect_ratio", "16:9"),
                                  "provider_duration_seconds": provider_duration,
                                  "target_duration": target_duration},
            "replacement_authorized": True, "replacement_of_attempt": latest.get("attempt"),
            "replacement_reason": reason.strip(), "replacement_authorized_at": _now(),
        }
        attempts.append(replacement)
        entry.update({"status": "REPLACEMENT_AUTHORIZED", "failure_class": None,
                      "selected_asset": None, "updated_at": _now()})
        entry.setdefault("replacement_events", []).append({
            "authorized_at": replacement["replacement_authorized_at"], "actor": "OWNER",
            "reason": reason.strip(), "replaces_attempt": latest.get("attempt"), "new_attempt": number,
        })
        atomic_write_json(manifest_path, manifest)
        return {"status": "REPLACEMENT_AUTHORIZED", "project_id": project_id,
                "request_id": request_id, "attempt": number, "client_ref": client_ref}


def execute_elyum_generation(runtime_root: Path | str, project_id: str, *, run_id: str,
                             client: ElyumSeedanceClient | None = None,
                             request_ids: set[str] | None = None, max_requests: int | None = 1,
                             dispatch_authorized: bool = False, wait_seconds: int = 50,
                             preview_fetcher: Callable[[str, Path], None] | None = None) -> dict[str, Any]:
    """Create/resume at most one logical Elyum generation per canonical request.

    Keep/unlock is intentionally absent. A PREVIEW_READY entry is a consequence
    boundary for Slice D; this function never calls ``elyum_keep`` or ``elyum_kill``.
    """
    if dispatch_authorized is not True:
        raise ElyumProductionError("ELYUM_PRODUCTION_DISPATCH_NOT_AUTHORIZED")
    if not isinstance(run_id, str) or not run_id:
        raise ElyumProductionError("CONTINUITY_RUN_ID_INVALID")
    runtime = RuntimeLayout.from_root(runtime_root)
    paths, config = load_project(runtime, project_id)
    if config.render_mode != "full_video_ai" or resolve_full_video_provider(config.settings) != PROVIDER_ID:
        raise ElyumProductionError("ELYUM_PRODUCTION_MODE_INVALID")
    active = client or ElyumSeedanceClient()
    readiness = active.readiness()
    if readiness.get("status") != "READY":
        raise ElyumProductionError(readiness.get("reason_code") or "CREDENTIAL_MISSING")
    settings = config.settings.get("elyum", {}) if isinstance(config.settings.get("elyum"), dict) else {}
    model = str(settings.get("model") or DEFAULT_FAST_I2V_MODEL)
    resolution = str(settings.get("resolution") or DEFAULT_RESOLUTION)
    max_credits = int(settings.get("max_credits", DEFAULT_MAX_CREDITS))
    provider_duration = int(settings.get("provider_duration_seconds", DEFAULT_PROVIDER_DURATION_SECONDS))
    if (model != DEFAULT_FAST_I2V_MODEL or resolution != "480p" or provider_duration != 4
            or max_credits < 1 or max_credits > DEFAULT_MAX_CREDITS):
        raise ElyumProductionError("ELYUM_QUALIFIED_ENVELOPE_INVALID")
    fetcher = preview_fetcher or _default_preview_fetcher

    with ProjectLock(paths.runtime, project_id):
        try:
            requests_value = read_json(paths.artifact_path("output/generation_requests.json"))
        except Exception as error:
            raise ElyumProductionError("GENERATION_REQUESTS_INVALID") from error
        snapshot = requests_value.get("full_video_provider_snapshot") if isinstance(requests_value, dict) else None
        if (not isinstance(snapshot, dict) or snapshot.get("provider_id") != PROVIDER_ID
                or snapshot.get("generation_mode") != "i2v"):
            raise ElyumProductionError("ELYUM_PROVIDER_SNAPSHOT_INVALID")
        requests = [item for item in requests_value.get("requests", []) if isinstance(item, dict)]
        candidates = [item for item in requests if item.get("purpose") == "SHOT" and item.get("media_type") == "VIDEO"]
        candidates.sort(key=lambda item: (float(item.get("target_start") or 0.0), int(item.get("part_index") or 0), item.get("request_id", "")))
        if request_ids is not None:
            candidates = [item for item in candidates if item.get("request_id") in request_ids]
        if any(item.get("provider") != PROVIDER_ID for item in candidates):
            raise ElyumProductionError("ELYUM_PROVIDER_MISMATCH")
        manifest_path, manifest = _manifest(paths, project_id)
        considered = 0
        for request in candidates:
            entry = _request_entry(manifest, request)
            attempts = entry.get("attempts") if isinstance(entry.get("attempts"), list) else []
            latest = attempts[-1] if attempts else None
            if _selected_valid(paths, entry):
                continue
            if entry.get("status") == "SUCCEEDED" and isinstance(latest, dict) and latest.get("keep_confirmed") is True:
                latest.update({"status": "KEEP_ACQUISITION_REQUIRED", "failure_class": "CLEAN_OUTPUT_INVALID"})
                entry.update({"status": "KEEP_ACQUISITION_REQUIRED", "failure_class": "CLEAN_OUTPUT_INVALID", "updated_at": _now()})
                atomic_write_json(manifest_path, manifest)
                return {"status": "KEEP_ACQUISITION_REQUIRED", "project_id": project_id,
                        "request_id": request["request_id"], "provider": PROVIDER_ID,
                        "new_submissions": 0, "resumed_tasks": 0, "failure_class": "CLEAN_OUTPUT_INVALID"}
            consequence_boundaries = {"KEEP_REQUIRED", "PREVIEW_REJECTED", "KEEP_AMBIGUOUS", "KEEP_DISPATCHING",
                                      "KEEP_ACQUISITION_REQUIRED", "KILL_AMBIGUOUS", "KILL_DISPATCHING", "KILLED"}
            if isinstance(latest, dict) and latest.get("status") in consequence_boundaries:
                reference = latest.get("continuity_reference")
                if not isinstance(reference, dict) or reference.get("run_id") != run_id:
                    raise ElyumProductionError("ELYUM_CONTINUITY_SNAPSHOT_MISMATCH")
                return {"status": latest["status"], "project_id": project_id, "request_id": request["request_id"],
                        "provider": PROVIDER_ID, "new_submissions": 0, "resumed_tasks": 0,
                        "failure_class": latest.get("failure_class")}
            if isinstance(latest, dict) and latest.get("status") == "PREVIEW_READY" and _preview_valid(paths, latest):
                reference = latest.get("continuity_reference")
                if not isinstance(reference, dict) or reference.get("run_id") != run_id:
                    raise ElyumProductionError("ELYUM_CONTINUITY_SNAPSHOT_MISMATCH")
                return {"status": "PREVIEW_READY", "project_id": project_id, "request_id": request["request_id"],
                        "provider": PROVIDER_ID, "new_submissions": 0, "resumed_tasks": 0}
            if attempts and not isinstance(latest, dict):
                raise ElyumProductionError("GENERATION_MANIFEST_INVALID")
            replacement_pending = bool(isinstance(latest, dict) and latest.get("replacement_authorized") is True
                                       and latest.get("dispatch_confirmed") is not True
                                       and not latest.get("provider_job_id"))
            new_logical_attempt = not attempts or replacement_pending
            if max_requests is not None and considered >= max_requests and new_logical_attempt:
                break
            considered += int(new_logical_attempt)

            if not attempts or replacement_pending:
                if not attempts:
                    try:
                        reference = resolve_continuity_reference_under_lock(paths, project_id, run_id, request["request_id"])
                    except FullVideoContinuityError as error:
                        raise ElyumProductionError(error.failure_class) from error
                    target_duration = float(request.get("target_duration") or 0.0)
                else:
                    reference = latest.get("continuity_reference")
                    if not isinstance(reference, dict) or reference.get("run_id") != run_id:
                        raise ElyumProductionError("ELYUM_CONTINUITY_SNAPSHOT_MISMATCH")
                    target_duration = float(latest.get("provider_settings", {}).get("target_duration") or request.get("target_duration") or 0.0)
                if target_duration <= 0 or target_duration > provider_duration + 0.001:
                    raise ElyumProductionError("ELYUM_TARGET_DURATION_UNSUPPORTED")
                balance = active.account_balance()
                estimate = active.estimate_video(model=model, duration=provider_duration, mode="i2v")
                _record_preflight(entry, balance=balance, estimate=estimate, max_credits=max_credits)
                if estimate > max_credits:
                    if replacement_pending:
                        latest.update({"status": "COST_BLOCKED", "failure_class": "ESTIMATE_EXCEEDS_BOUND",
                                       "balance_before": balance, "estimate_credits": estimate})
                    entry.update({"status": "COST_BLOCKED", "failure_class": "ESTIMATE_EXCEEDS_BOUND", "updated_at": _now()})
                    atomic_write_json(manifest_path, manifest)
                    return {"status": "COST_BLOCKED", "project_id": project_id, "request_id": request["request_id"],
                            "estimate_credits": estimate, "max_credits": max_credits}
                if balance < estimate:
                    if replacement_pending:
                        latest.update({"status": "CREDIT_BLOCKED", "failure_class": "INSUFFICIENT_CREDIT_BALANCE",
                                       "balance_before": balance, "estimate_credits": estimate})
                    entry.update({"status": "CREDIT_BLOCKED", "failure_class": "INSUFFICIENT_CREDIT_BALANCE", "updated_at": _now()})
                    atomic_write_json(manifest_path, manifest)
                    return {"status": "CREDIT_BLOCKED", "project_id": project_id, "request_id": request["request_id"],
                            "balance": balance, "estimate_credits": estimate}
                if not attempts:
                    client_ref = _client_ref(project_id, run_id, request, reference, model, provider_duration, resolution)
                    latest = {
                        "attempt": 1, "status": "PRE_DISPATCH", "started_at": _now(),
                        "provider_mode": "VIDEO", "provider_model": model,
                        "provider_execution_state": "NOT_STARTED", "dispatch_confirmed": False,
                        "attribution_state": "NOT_STARTED", "attribution_status": "NOT_STARTED",
                        "client_ref": client_ref, "continuity_reference": reference,
                        "balance_before": balance, "estimate_credits": estimate,
                        "provider_settings": {"mode": "i2v", "resolution": resolution,
                                              "aspect_ratio": request.get("aspect_ratio", "16:9"),
                                              "provider_duration_seconds": provider_duration,
                                              "target_duration": target_duration},
                    }
                    attempts.append(latest)
                else:
                    latest.update({"status": "PRE_DISPATCH", "provider_execution_state": "NOT_STARTED",
                                   "failure_class": None, "balance_before": balance, "estimate_credits": estimate})
                entry.update({"attempts": attempts, "status": "GENERATING", "failure_class": None, "updated_at": _now()})
                atomic_write_json(manifest_path, manifest)
            else:
                reference = latest.get("continuity_reference")
                if not isinstance(reference, dict) or reference.get("run_id") != run_id:
                    raise ElyumProductionError("ELYUM_CONTINUITY_SNAPSHOT_MISMATCH")
                if latest.get("status") in {"FAILED_TERMINAL", "PREVIEW_ACQUISITION_FAILED"}:
                    return {"status": "BLOCKED", "project_id": project_id, "request_id": request["request_id"],
                            "failure_class": latest.get("failure_class")}

            if not isinstance(latest.get("provider_reference_url"), str):
                reference_path = paths.artifact_path(latest["continuity_reference"]["reference_path"])
                try:
                    provider_reference_url = active.upload_file(reference_path)
                except ElyumSeedanceError as error:
                    latest.update({"status": "REFERENCE_UPLOAD_RETRYABLE", "failure_class": error.failure_class,
                                   "last_observed_at": _now()})
                    entry.update({"status": "FAILED_RETRYABLE", "failure_class": error.failure_class, "updated_at": _now()})
                    atomic_write_json(manifest_path, manifest)
                    return {"status": "FAILED_RETRYABLE", "project_id": project_id,
                            "request_id": request["request_id"], "failure_class": error.failure_class}
                latest.update({"provider_reference_url": provider_reference_url, "reference_uploaded_at": _now()})
                atomic_write_json(manifest_path, manifest)

            job_id = latest.get("provider_job_id")
            new_submission = 0
            if not isinstance(job_id, str) or not job_id:
                try:
                    latest["provider_create_calls"] = int(latest.get("provider_create_calls", 0)) + 1
                    atomic_write_json(manifest_path, manifest)
                    job_id, _create = active.make_video(
                        client_ref=latest["client_ref"], model=model, prompt=request.get("prompt", ""),
                        duration=provider_duration, mode="i2v", aspect_ratio=str(request.get("aspect_ratio") or "16:9"),
                        resolution=resolution, image_url=latest["provider_reference_url"], audio=False,
                    )
                except ElyumSeedanceError as error:
                    if error.dispatch_state == "RECONCILE_BY_CLIENT_REF":
                        latest.update({"status": "REPLAY_SAME_CLIENT_REF", "provider_execution_state": "DISPATCH_UNCERTAIN",
                                       "failure_class": error.failure_class, "last_observed_at": _now()})
                        entry.update({"status": "AMBIGUOUS", "failure_class": error.failure_class, "updated_at": _now()})
                        atomic_write_json(manifest_path, manifest)
                        return {"status": "REPLAY_SAME_CLIENT_REF", "project_id": project_id,
                                "request_id": request["request_id"], "client_ref": latest["client_ref"]}
                    latest.update({"status": "FAILED_PRE_DISPATCH", "provider_execution_state": "NOT_STARTED",
                                   "failure_class": error.failure_class, "canonical_no_dispatch_proof": True})
                    entry.update({"status": "FAILED_RETRYABLE", "failure_class": error.failure_class, "updated_at": _now()})
                    atomic_write_json(manifest_path, manifest)
                    return {"status": "FAILED_RETRYABLE", "project_id": project_id,
                            "request_id": request["request_id"], "failure_class": error.failure_class}
                latest.update({"status": "SUBMITTED", "provider_job_id": job_id,
                               "provider_execution_state": "QUEUED", "dispatch_confirmed": True,
                               "attribution_state": "CONFIRMED", "attribution_status": "CONFIRMED",
                               "submitted_at": _now(), "failure_class": None})
                entry["provider_submissions"] = int(entry.get("provider_submissions", 0)) + 1
                entry.update({"status": "GENERATING", "failure_class": None, "updated_at": _now()})
                atomic_write_json(manifest_path, manifest)
                new_submission = 1

            try:
                result = active.wait(job_id, timeout_seconds=wait_seconds, thumbnails=True)
            except ElyumSeedanceError as error:
                latest.update({"status": "WAIT_UNAVAILABLE", "failure_class": error.failure_class,
                               "last_observed_at": _now()})
                entry.update({"status": "GENERATING", "failure_class": "PROVIDER_POLL_UNAVAILABLE", "updated_at": _now()})
                atomic_write_json(manifest_path, manifest)
                return {"status": "WAIT_UNAVAILABLE", "project_id": project_id, "request_id": request["request_id"],
                        "job_id": job_id, "new_submissions": new_submission, "resumed_tasks": int(not new_submission)}
            observed = _acquire_preview(paths, manifest_path, manifest, request, entry, latest, result, active, fetcher)
            return {**observed, "project_id": project_id, "provider": PROVIDER_ID,
                    "new_submissions": new_submission, "resumed_tasks": int(not new_submission)}
        return {"status": "NO_WORK", "project_id": project_id, "provider": PROVIDER_ID,
                "new_submissions": 0, "resumed_tasks": 0}

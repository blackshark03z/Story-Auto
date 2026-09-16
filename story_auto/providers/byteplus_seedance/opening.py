"""BytePlus Seedance acquisition for Hybrid Visual opening slots.

Provider state is persisted on the exact OPENING_O* slot before any external
mutation. Known tasks resume by task id; ambiguous POSTs are never redispatched.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import time
from typing import Any

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock
from story_auto.core.visual.opening_builder import (
    OPENING_BUILDER_VERSION,
    OPENING_MANIFEST_PATH,
    import_opening_clip,
    opening_builder_view,
)
from .client import BytePlusSeedanceClient, BytePlusSeedanceError

PROVIDER_ID = "byteplus_seedance"
OPENING_API_VERSION = "story-auto-opening-api-byteplus/1.0.0"
_TERMINAL = {"failed", "expired", "cancelled"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project(runtime_root: Path | str, project_id: str):
    runtime = RuntimeLayout.from_root(runtime_root)
    paths, config = load_project(runtime, project_id)
    if config.render_mode != "hybrid_hook":
        raise BytePlusSeedanceError("OPENING_API_MODE_INVALID")
    return runtime, paths, config


def _load_slot(paths, project_id: str, slot_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = paths.artifact_path(OPENING_MANIFEST_PATH)
    if not path.is_file():
        raise BytePlusSeedanceError("OPENING_NOT_CONFIGURED")
    manifest = read_json(path)
    if manifest.get("schema_version") != OPENING_BUILDER_VERSION or manifest.get("project_id") != project_id:
        raise BytePlusSeedanceError("OPENING_MANIFEST_INVALID")
    slot = next(
        (item for item in manifest.get("slots", [])
         if isinstance(item, dict) and item.get("slot_id") == slot_id),
        None,
    )
    if slot is None:
        raise BytePlusSeedanceError("OPENING_SLOT_NOT_FOUND")
    return manifest, slot


def _persist(paths, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = _now()
    atomic_write_json(paths.artifact_path(OPENING_MANIFEST_PATH), manifest)


def _safe_view(runtime_root: Path | str, project_id: str) -> dict[str, Any]:
    return opening_builder_view(runtime_root, project_id) or {}


def generate_opening_slot_api(
    runtime_root: Path | str,
    project_id: str,
    slot_id: str,
    *,
    client: BytePlusSeedanceClient | None = None,
    resolution: str = "720p",
    poll_interval: float = 2.0,
    max_poll_seconds: float = 60.0,
) -> dict[str, Any]:
    """Generate or resume exactly one opening slot through BytePlus."""
    runtime, paths, _config = _project(runtime_root, project_id)
    active = client or BytePlusSeedanceClient()
    if active.readiness().get("status") != "READY":
        raise BytePlusSeedanceError("CREDENTIAL_MISSING")
    if resolution not in {"480p", "720p"}:
        raise BytePlusSeedanceError("RESOLUTION_UNSUPPORTED", resolution)

    task_id: str | None = None
    with ProjectLock(paths.runtime, project_id):
        manifest, slot = _load_slot(paths, project_id, slot_id)
        if slot.get("status") == "READY" and isinstance(slot.get("normalized_asset"), dict):
            return _safe_view(runtime.root, project_id)
        prompt = str(slot.get("prompt") or "").strip()
        duration = float(slot.get("duration_seconds") or 0.0)
        if not prompt or not 4.0 <= duration <= 30.0:
            raise BytePlusSeedanceError("OPENING_API_SLOT_INVALID")
        generation = slot.get("api_generation")
        if isinstance(generation, dict):
            if generation.get("provider") != PROVIDER_ID:
                raise BytePlusSeedanceError("OPENING_API_PROVIDER_MISMATCH")
            if generation.get("status") in {"AMBIGUOUS", "FAILED_TERMINAL"}:
                return _safe_view(runtime.root, project_id)
            existing_task = generation.get("provider_task_id")
            if isinstance(existing_task, str) and existing_task.strip():
                task_id = existing_task.strip()
            elif generation.get("status") not in {"FAILED_PRE_DISPATCH", "PRE_DISPATCH"}:
                raise BytePlusSeedanceError("OPENING_API_STATE_INVALID")
        else:
            generation = {
                "schema_version": OPENING_API_VERSION,
                "provider": PROVIDER_ID,
                "provider_model": active.model,
                "status": "PRE_DISPATCH",
                "provider_submissions": 0,
                "resolution": resolution,
                "prompt_sha256": slot.get("prompt_sha256"),
                "duration_seconds": duration,
                "created_at": _now(),
                "updated_at": _now(),
            }
            slot["api_generation"] = generation
            _persist(paths, manifest)

    if task_id is None:
        try:
            task_id = active.create_task(
                prompt=prompt,
                duration=duration,
                aspect_ratio="16:9",
                resolution=resolution,
            )
        except BytePlusSeedanceError as error:
            with ProjectLock(paths.runtime, project_id):
                manifest, slot = _load_slot(paths, project_id, slot_id)
                generation = slot.get("api_generation")
                if not isinstance(generation, dict):
                    raise
                if error.dispatch_state == "AMBIGUOUS":
                    generation.update({
                        "status": "AMBIGUOUS",
                        "failure_class": error.failure_class,
                        "dispatch_state": "AMBIGUOUS",
                        "updated_at": _now(),
                    })
                else:
                    generation.update({
                        "status": "FAILED_PRE_DISPATCH",
                        "failure_class": error.failure_class,
                        "dispatch_state": "NOT_DISPATCHED",
                        "updated_at": _now(),
                    })
                _persist(paths, manifest)
            return _safe_view(runtime.root, project_id)
        with ProjectLock(paths.runtime, project_id):
            manifest, slot = _load_slot(paths, project_id, slot_id)
            generation = slot.get("api_generation")
            if not isinstance(generation, dict):
                raise BytePlusSeedanceError("OPENING_API_STATE_INVALID")
            generation.update({
                "status": "SUBMITTED",
                "provider_task_id": task_id,
                "provider_submissions": int(generation.get("provider_submissions") or 0) + 1,
                "dispatch_state": "CONFIRMED",
                "submitted_at": _now(),
                "updated_at": _now(),
                "failure_class": None,
            })
            _persist(paths, manifest)

    deadline = time.monotonic() + max(0.0, float(max_poll_seconds))
    while True:
        task = active.get_task(task_id)
        observed = str(task.get("status") or "").lower()
        with ProjectLock(paths.runtime, project_id):
            manifest, slot = _load_slot(paths, project_id, slot_id)
            generation = slot.get("api_generation")
            if not isinstance(generation, dict) or generation.get("provider_task_id") != task_id:
                raise BytePlusSeedanceError("OPENING_API_TASK_IDENTITY_MISMATCH")
            generation.update({
                "provider_task_status": observed,
                "status": "GENERATING" if observed in {"queued", "running"} else generation.get("status"),
                "last_observed_at": _now(),
                "updated_at": _now(),
            })
            if observed in _TERMINAL:
                generation.update({
                    "status": "FAILED_TERMINAL",
                    "failure_class": f"PROVIDER_TASK_{observed.upper()}",
                    "completed_at": _now(),
                })
            _persist(paths, manifest)

        if observed == "succeeded":
            temporary_dir = runtime.temp / "opening_api" / project_id / slot_id
            temporary_dir.mkdir(parents=True, exist_ok=True)
            source = temporary_dir / f"{task_id}.mp4"
            try:
                active.acquire_video(task, source)
                import_opening_clip(
                    runtime.root,
                    project_id,
                    slot_id,
                    source,
                    original_filename=f"byteplus_{slot_id}.mp4",
                )
            finally:
                shutil.rmtree(temporary_dir, ignore_errors=True)
            with ProjectLock(paths.runtime, project_id):
                manifest, slot = _load_slot(paths, project_id, slot_id)
                generation = slot.get("api_generation")
                if not isinstance(generation, dict) or generation.get("provider_task_id") != task_id:
                    raise BytePlusSeedanceError("OPENING_API_TASK_IDENTITY_MISMATCH")
                generation.update({
                    "status": "SUCCEEDED",
                    "provider_task_status": "succeeded",
                    "failure_class": None,
                    "completed_at": _now(),
                    "updated_at": _now(),
                })
                _persist(paths, manifest)
            return _safe_view(runtime.root, project_id)

        if observed in _TERMINAL:
            return _safe_view(runtime.root, project_id)
        if time.monotonic() >= deadline:
            return _safe_view(runtime.root, project_id)
        time.sleep(max(0.05, float(poll_interval)))
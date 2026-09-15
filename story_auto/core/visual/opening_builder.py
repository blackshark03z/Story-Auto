"""Provider-independent Hybrid Visual opening-slot planning and manual import.

This module deliberately does not release-enable ``hybrid_hook`` and never calls
an external generation provider. It owns only the durable Opening Builder
contract: exact prompts, stable slot identity, local media normalization, and
hash-bound manual asset adoption.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock
from story_auto.core.render.compiler import compile_video
from story_auto.core.render.media import MediaError, MediaTarget, probe_media


OPENING_BUILDER_VERSION = "story-auto-opening-builder/1.0.0"
OPENING_MANIFEST_PATH = "output/opening_manifest.json"
_MIN_OPENING_SECONDS = 15.0
_MAX_OPENING_SECONDS = 20.0
_MIN_SLOT_SECONDS = 5.0
_MAX_SLOT_SECONDS = 10.0
_MIN_SLOT_COUNT = 2
_MAX_SLOT_COUNT = 4


class OpeningBuilderError(RuntimeError):
    """Stable product-facing Opening Builder failure."""

    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(failure_class + (f": {detail}" if detail else ""))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_value(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_project(runtime_root: Path | str, project_id: str):
    runtime = RuntimeLayout.from_root(runtime_root)
    paths, config = load_project(runtime, project_id)
    if config.render_mode != "hybrid_hook":
        raise OpeningBuilderError("OPENING_BUILDER_MODE_INVALID")
    return paths, config


def _target(config) -> MediaTarget:
    value = config.settings.get("render", {}) if isinstance(config.settings, dict) else {}
    if not isinstance(value, dict):
        raise OpeningBuilderError("OPENING_RENDER_SETTINGS_INVALID")
    try:
        return MediaTarget(int(value.get("width", 1920)), int(value.get("height", 1080)),
                           int(value.get("fps", 30)), str(value.get("pixel_format", "yuv420p")))
    except Exception as error:
        raise OpeningBuilderError("OPENING_RENDER_SETTINGS_INVALID") from error


def _manifest_path(paths) -> Path:
    return paths.artifact_path(OPENING_MANIFEST_PATH)


def _validate_slot_specs(slot_specs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float]:
    if not isinstance(slot_specs, list) or not (_MIN_SLOT_COUNT <= len(slot_specs) <= _MAX_SLOT_COUNT):
        raise OpeningBuilderError("OPENING_SLOT_COUNT_INVALID")
    normalized: list[dict[str, Any]] = []
    cursor = 0.0
    for index, raw in enumerate(slot_specs, start=1):
        if not isinstance(raw, dict):
            raise OpeningBuilderError("OPENING_SLOT_INVALID")
        prompt = raw.get("prompt")
        purpose = raw.get("purpose")
        try:
            duration = float(raw.get("duration_seconds"))
        except (TypeError, ValueError) as error:
            raise OpeningBuilderError("OPENING_SLOT_DURATION_INVALID") from error
        if not (_MIN_SLOT_SECONDS <= duration <= _MAX_SLOT_SECONDS):
            raise OpeningBuilderError("OPENING_SLOT_DURATION_INVALID", str(duration))
        if not isinstance(prompt, str) or not prompt.strip():
            raise OpeningBuilderError("OPENING_SLOT_PROMPT_REQUIRED")
        if not isinstance(purpose, str) or not purpose.strip():
            raise OpeningBuilderError("OPENING_SLOT_PURPOSE_REQUIRED")
        start = round(cursor, 6)
        end = round(cursor + duration, 6)
        slot_id = f"OPENING_O{index}"
        normalized.append({
            "slot_id": slot_id,
            "index": index,
            "start": start,
            "end": end,
            "duration_seconds": round(duration, 6),
            "purpose": purpose.strip(),
            "prompt": prompt.strip(),
            "prompt_sha256": _hash_text(prompt.strip()),
            "source_request_id": raw.get("source_request_id") if isinstance(raw.get("source_request_id"), str) else None,
            "required": True,
            "status": "MISSING",
            "revision": 0,
            "source_asset": None,
            "normalized_asset": None,
            "replacement_history": [],
        })
        cursor = end
    if not (_MIN_OPENING_SECONDS <= cursor <= _MAX_OPENING_SECONDS):
        raise OpeningBuilderError("OPENING_DURATION_INVALID", str(cursor))
    return normalized, round(cursor, 6)


def _plan_identity(project_id: str, shared_context: str, slots: list[dict[str, Any]], target: MediaTarget) -> str:
    return _hash_value({
        "project_id": project_id,
        "shared_context": shared_context,
        "render_target": {"width": target.width, "height": target.height, "fps": target.fps,
                          "pixel_format": target.pixel_format},
        "slots": [{"slot_id": slot["slot_id"], "start": slot["start"], "end": slot["end"],
                   "purpose": slot["purpose"], "prompt_sha256": slot["prompt_sha256"],
                   "source_request_id": slot.get("source_request_id")} for slot in slots],
    })


def configure_opening_builder(runtime_root: Path | str, project_id: str, *, shared_context: str,
                              slot_specs: list[dict[str, Any]]) -> dict[str, Any]:
    """Create the durable opening-slot contract without provider mutation.

    Reconfiguring an untouched plan is allowed. Once any slot owns a normalized
    asset, changing the plan is rejected so imported clips can never silently
    move to different semantic/timing slots.
    """
    if not isinstance(shared_context, str) or not shared_context.strip():
        raise OpeningBuilderError("OPENING_SHARED_CONTEXT_REQUIRED")
    paths, config = _require_project(runtime_root, project_id)
    slots, total = _validate_slot_specs(slot_specs)
    target = _target(config)
    shared = shared_context.strip()
    plan_sha = _plan_identity(project_id, shared, slots, target)
    unchanged = False
    with ProjectLock(paths.runtime, project_id):
        path = _manifest_path(paths)
        existing = read_json(path) if path.is_file() else None
        if isinstance(existing, dict) and existing.get("plan_sha256") == plan_sha:
            unchanged = True
        if isinstance(existing, dict) and not unchanged:
            for slot in existing.get("slots", []):
                if isinstance(slot, dict) and isinstance(slot.get("normalized_asset"), dict):
                    raise OpeningBuilderError("OPENING_PLAN_LOCKED")
        if unchanged:
            manifest = existing
        else:
            manifest = {
            "schema_version": OPENING_BUILDER_VERSION,
            "project_id": project_id,
            "render_mode": "hybrid_hook",
            "status": "NOT_READY",
            "opening_duration_seconds": total,
            "shared_context": shared,
            "shared_context_sha256": _hash_text(shared),
            "render_target": {"width": target.width, "height": target.height, "fps": target.fps,
                              "pixel_format": target.pixel_format},
            "plan_sha256": plan_sha,
            "slots": slots,
            "created_at": _now(),
                "updated_at": _now(),
            }
            atomic_write_json(path, manifest)
    return opening_builder_view(runtime_root, project_id)


def _canonical_shared_context(paths) -> str:
    continuity_path = paths.artifact_path("output/continuity_bible.json")
    if not continuity_path.is_file():
        return "Preserve the canonical character identity, wardrobe, location, props, lighting, and visual style across every opening clip."
    try:
        value = read_json(continuity_path)
    except Exception as error:
        raise OpeningBuilderError("OPENING_CONTINUITY_INVALID") from error
    parts = ["Preserve canonical continuity across every opening clip."]
    for group, label in (("characters", "Character"), ("locations", "Location"), ("props", "Prop")):
        items = value.get(group, []) if isinstance(value, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("entity_id") or label)
            details = []
            for key in ("visual_design", "constraints", "facts"):
                candidate = item.get(key)
                if candidate:
                    details.append(f"{key.replace('_',' ')}: {candidate}")
            parts.append(f"{label} {name}" + (" — " + "; ".join(details) if details else ""))
    return "\n".join(parts)


def prepare_opening_builder_from_plan(runtime_root: Path | str, project_id: str) -> dict[str, Any]:
    """Materialize the manual Opening Builder from canonical planned VIDEO requests.

    The adapter intentionally consumes existing prompts rather than invoking a
    provider or another LLM. It takes the earliest contiguous required video
    parts until the opening reaches 15–20 seconds, preserving exact request
    prompt text and request identity for external manual generation.
    """
    paths, _config = _require_project(runtime_root, project_id)
    request_path = paths.artifact_path("output/generation_requests.json")
    if not request_path.is_file():
        raise OpeningBuilderError("OPENING_GENERATION_REQUESTS_MISSING")
    try:
        value = read_json(request_path)
    except Exception as error:
        raise OpeningBuilderError("OPENING_GENERATION_REQUESTS_INVALID") from error
    candidates = [item for item in value.get("requests", []) if isinstance(item, dict)
                  and item.get("purpose") == "SHOT" and item.get("media_type") == "VIDEO"
                  and item.get("requirement") == "REQUIRED"]
    candidates.sort(key=lambda item: (float(item.get("target_start") or 0.0),
                                      int(item.get("part_index") or 0), str(item.get("request_id") or "")))
    if not candidates or abs(float(candidates[0].get("target_start") or 0.0)) > .05:
        raise OpeningBuilderError("OPENING_REQUIRED_VIDEO_PLAN_MISSING")
    specs: list[dict[str, Any]] = []
    cursor = 0.0
    for item in candidates:
        start = float(item.get("target_start") or 0.0)
        duration = float(item.get("target_duration") or 0.0)
        if abs(start - cursor) > .05:
            break
        if not (_MIN_SLOT_SECONDS <= duration <= _MAX_SLOT_SECONDS):
            raise OpeningBuilderError("OPENING_REQUEST_DURATION_UNSUPPORTED", str(duration))
        if cursor + duration > _MAX_OPENING_SECONDS + .05:
            break
        prompt = item.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise OpeningBuilderError("OPENING_SLOT_PROMPT_REQUIRED")
        shot = str(item.get("shot_id") or "opening")
        part = int(item.get("part_index") or 1)
        specs.append({"duration_seconds": duration,
                      "purpose": f"{shot} · opening beat {part}",
                      "prompt": prompt,
                      "source_request_id": item.get("request_id")})
        cursor += duration
        if cursor >= _MIN_OPENING_SECONDS - .05:
            break
        if len(specs) >= _MAX_SLOT_COUNT:
            break
    if not (_MIN_OPENING_SECONDS <= cursor <= _MAX_OPENING_SECONDS):
        raise OpeningBuilderError("OPENING_DURATION_INVALID", str(cursor))
    return configure_opening_builder(runtime_root, project_id,
                                     shared_context=_canonical_shared_context(paths), slot_specs=specs)


def _asset_valid(paths, asset: Any) -> bool:
    if not isinstance(asset, dict):
        return False
    path = asset.get("path")
    digest = asset.get("sha256")
    if not isinstance(path, str) or not isinstance(digest, str):
        return False
    target = paths.artifact_path(path)
    return target.is_file() and sha256_file(target) == digest


def _project_relative(paths, path: Path) -> str:
    return path.resolve().relative_to(paths.root.resolve()).as_posix()


def _refresh_status(paths, manifest: dict[str, Any]) -> str:
    slots = manifest.get("slots", [])
    ready = bool(slots)
    for slot in slots:
        valid = isinstance(slot, dict) and slot.get("status") == "READY" and _asset_valid(paths, slot.get("normalized_asset"))
        if not valid:
            ready = False
    manifest["status"] = "READY" if ready else "NOT_READY"
    return manifest["status"]


def opening_builder_view(runtime_root: Path | str, project_id: str) -> dict[str, Any] | None:
    """Return a safe product projection with copyable exact prompt text."""
    paths, config = _require_project(runtime_root, project_id)
    path = _manifest_path(paths)
    if not path.is_file():
        return {"status": "NOT_CONFIGURED", "opening_duration_seconds": None, "slots": [],
                "copy_all_prompts": "", "ready": False}
    manifest = read_json(path)
    if manifest.get("schema_version") != OPENING_BUILDER_VERSION or manifest.get("project_id") != project_id:
        raise OpeningBuilderError("OPENING_MANIFEST_INVALID")
    slots = []
    for raw in manifest.get("slots", []):
        if not isinstance(raw, dict):
            raise OpeningBuilderError("OPENING_MANIFEST_INVALID")
        item = deepcopy(raw)
        item["asset_ready"] = _asset_valid(paths, raw.get("normalized_asset"))
        slots.append(item)
    status = "READY" if slots and all(slot["status"] == "READY" and slot["asset_ready"] for slot in slots) else "NOT_READY"
    pack: list[str] = ["OPENING SHARED CONTEXT", manifest.get("shared_context", ""), ""]
    for slot in slots:
        pack.extend([
            f"{slot['slot_id']} — {slot['duration_seconds']} sec — {slot['purpose']}",
            slot["prompt"],
            "",
        ])
    return {
        "schema_version": manifest["schema_version"],
        "status": status,
        "ready": status == "READY",
        "opening_duration_seconds": manifest.get("opening_duration_seconds"),
        "shared_context": manifest.get("shared_context"),
        "shared_context_sha256": manifest.get("shared_context_sha256"),
        "plan_sha256": manifest.get("plan_sha256"),
        "render_target": deepcopy(manifest.get("render_target")),
        "slots": slots,
        "copy_all_prompts": "\n".join(pack).strip(),
    }


def import_opening_clip(runtime_root: Path | str, project_id: str, slot_id: str,
                        source_path: Path | str, *, original_filename: str | None = None) -> dict[str, Any]:
    """Adopt one user-generated clip into one exact opening slot.

    Long sources are trimmed to the slot duration. A small shortage may be
    repaired with a bounded frozen tail; larger shortages fail closed. The
    normalized asset is always silent and matches the project render target.
    """
    if not isinstance(slot_id, str) or not slot_id.startswith("OPENING_O"):
        raise OpeningBuilderError("OPENING_SLOT_ID_INVALID")
    source = Path(source_path)
    if not source.is_file():
        raise OpeningBuilderError("OPENING_IMPORT_SOURCE_MISSING")
    paths, config = _require_project(runtime_root, project_id)
    target = _target(config)
    try:
        source_meta = probe_media(source)
    except MediaError as error:
        raise OpeningBuilderError("OPENING_IMPORT_MEDIA_INVALID", error.failure_class) from error
    if source_meta.get("video") is None:
        raise OpeningBuilderError("OPENING_IMPORT_VIDEO_REQUIRED")
    source_duration = float(source_meta["duration_seconds"])
    with ProjectLock(paths.runtime, project_id):
        manifest_path = _manifest_path(paths)
        if not manifest_path.is_file():
            raise OpeningBuilderError("OPENING_NOT_CONFIGURED")
        manifest = read_json(manifest_path)
        slot = next((item for item in manifest.get("slots", [])
                     if isinstance(item, dict) and item.get("slot_id") == slot_id), None)
        if slot is None:
            raise OpeningBuilderError("OPENING_SLOT_NOT_FOUND")
        duration = float(slot["duration_seconds"])
        shortage = duration - source_duration
        allowed_shortage = min(1.0, duration * 0.15)
        if shortage > allowed_shortage + 1e-6:
            raise OpeningBuilderError("OPENING_IMPORT_TOO_SHORT", f"need {duration:.3f}s, got {source_duration:.3f}s")
        revision = int(slot.get("revision") or 0) + 1
        source_sha = str(source_meta["sha256"])
        suffix = source.suffix.lower() if source.suffix else ".bin"
        source_rel = f"assets/opening/imports/{slot_id}/r{revision:03d}_{source_sha[:12]}{suffix}"
        normalized_rel = f"assets/opening/normalized/{slot_id}/r{revision:03d}.mp4"
        durable_source = paths.artifact_path(source_rel)
        normalized = paths.artifact_path(normalized_rel)
        durable_source.parent.mkdir(parents=True, exist_ok=True)
        normalized.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, durable_source)
        try:
            normalized_meta = compile_video(durable_source, normalized, duration=duration,
                                            short_policy="FREEZE_TAIL" if shortage > 0.04 else "BLOCK",
                                            target=target)
        except Exception:
            normalized.unlink(missing_ok=True)
            durable_source.unlink(missing_ok=True)
            raise
        previous = None
        if isinstance(slot.get("normalized_asset"), dict):
            previous = {
                "revision": slot.get("revision"),
                "source_asset": deepcopy(slot.get("source_asset")),
                "normalized_asset": deepcopy(slot.get("normalized_asset")),
                "replaced_at": _now(),
            }
        if previous is not None:
            slot.setdefault("replacement_history", []).append(previous)
        slot["revision"] = revision
        slot["status"] = "READY"
        slot["source_asset"] = {
            "path": source_rel,
            "sha256": sha256_file(durable_source),
            "original_filename": Path(original_filename or source.name).name,
            "duration_seconds": source_duration,
            "width": source_meta["video"]["width"],
            "height": source_meta["video"]["height"],
            "frame_rate": source_meta["video"]["frame_rate"],
            "had_audio": bool(source_meta.get("audio")),
            "imported_at": _now(),
        }
        slot["normalized_asset"] = {
            "path": normalized_rel,
            "sha256": normalized_meta["sha256"],
            "duration_seconds": normalized_meta["duration_seconds"],
            "width": normalized_meta["video"]["width"],
            "height": normalized_meta["video"]["height"],
            "frame_rate": normalized_meta["video"]["frame_rate"],
            "audio_stripped": True,
            "normalized_at": _now(),
        }
        slot["updated_at"] = _now()
        _refresh_status(paths, manifest)
        manifest["updated_at"] = _now()
        atomic_write_json(manifest_path, manifest)
    return opening_builder_view(runtime_root, project_id) or {}

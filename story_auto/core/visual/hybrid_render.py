"""Development-only mixed Hybrid Visual compositor.

This module proves the final V1 visual recipe without release-enabling
``hybrid_hook``. Visual clips are always silent; narration/subtitles/waveform
remain owned by the existing Story Auto master-track compositor.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock
from story_auto.core.render.compiler import compile_image
from story_auto.core.render.compositor import compose
from story_auto.core.render.media import MediaError, probe_media, validate_video
from story_auto.core.render.service import resolve_render_settings
from story_auto.core.render.waveform import visualizer_spec
from story_auto.core.subtitles import build_subtitles
from story_auto.core.visual.hybrid_body import HYBRID_BODY_PATH, HybridBodyError, hybrid_body_view
from story_auto.core.visual.opening_builder import opening_builder_view


HYBRID_PREVIEW_VERSION = "story-auto-hybrid-preview/1.0.0"
HYBRID_PREVIEW_PATH = "output/hybrid_preview.mp4"
HYBRID_PREVIEW_MANIFEST_PATH = "output/hybrid_preview_manifest.json"


class HybridRenderError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(failure_class + (f": {detail}" if detail else ""))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_project(runtime_root: Path | str, project_id: str):
    runtime = RuntimeLayout.from_root(runtime_root)
    paths, config = load_project(runtime, project_id)
    if config.render_mode != "hybrid_hook":
        raise HybridRenderError("HYBRID_RENDER_MODE_INVALID")
    return paths, config


def _valid_asset(paths, asset: Any) -> bool:
    if not isinstance(asset, dict):
        return False
    relative, digest = asset.get("path"), asset.get("sha256")
    if not isinstance(relative, str) or not isinstance(digest, str):
        return False
    path = paths.artifact_path(relative)
    return path.is_file() and sha256_file(path) == digest


def _motion(effect: str | None) -> str:
    return {
        "ZOOM_IN": "AUTO_CONTINUOUS_ZOOM_IN",
        "ZOOM_OUT": "AUTO_CONTINUOUS_ZOOM_OUT",
        "PAN_LEFT": "SUBTLE_PAN_LEFT",
        "PAN_RIGHT": "SUBTLE_PAN_RIGHT",
        "SLOW_PUSH": "SLOW_PUSH",
    }.get(str(effect or "SLOW_PUSH").upper(), "SLOW_PUSH")


def hybrid_preview_readiness(runtime_root: Path | str, project_id: str) -> dict[str, Any]:
    paths, _config = _require_project(runtime_root, project_id)
    opening = opening_builder_view(runtime_root, project_id)
    body = hybrid_body_view(runtime_root, project_id)
    missing: list[dict[str, str]] = []
    if not opening or not opening.get("ready"):
        missing.append({"slot_id": "OPENING", "reason": "OPENING_CLIPS_REQUIRED"})
    if not body:
        missing.append({"slot_id": "BODY", "reason": "HYBRID_BODY_PLAN_REQUIRED"})
    else:
        for slot in body.get("slots", []):
            if slot.get("visual_type") == "IMAGE":
                if not _valid_asset(paths, slot.get("source_asset")):
                    missing.append({"slot_id": str(slot.get("slot_id")), "reason": "IMAGE_REQUIRED"})
            elif slot.get("visual_type") == "STOCK_VIDEO":
                stock_ready = slot.get("status") == "READY" and _valid_asset(paths, slot.get("normalized_asset"))
                fallback_ready = _valid_asset(paths, slot.get("fallback_image_asset"))
                if not stock_ready and not fallback_ready:
                    missing.append({"slot_id": str(slot.get("slot_id")), "reason": "STOCK_OR_IMAGE_FALLBACK_REQUIRED"})
            else:
                missing.append({"slot_id": str(slot.get("slot_id")), "reason": "VISUAL_TYPE_INVALID"})
    alignment = paths.artifact_path("output/alignment.json")
    if not alignment.is_file():
        missing.append({"slot_id": "MASTER", "reason": "ALIGNMENT_REQUIRED"})
    return {"status": "READY" if not missing else "NOT_READY", "ready": not missing, "missing": missing}


def _build_visual_clips(paths, config, opening: dict[str, Any], body: dict[str, Any]):
    settings, target = resolve_render_settings(config)
    clips: list[Path] = []
    segments: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    previous_end = 0.0
    for slot in opening.get("slots", []):
        start, end = float(slot["start"]), float(slot["end"])
        if abs(start - previous_end) > .001 or not _valid_asset(paths, slot.get("normalized_asset")):
            raise HybridRenderError("HYBRID_OPENING_TIMELINE_INVALID", str(slot.get("slot_id")))
        clip = paths.artifact_path(slot["normalized_asset"]["path"])
        try:
            meta = probe_media(clip)
        except MediaError as error:
            raise HybridRenderError("HYBRID_OPENING_MEDIA_INVALID", error.failure_class) from error
        if meta.get("audio"):
            raise HybridRenderError("HYBRID_VISUAL_AUDIO_LEAK", str(slot.get("slot_id")))
        duration = end - start
        clips.append(clip)
        segments.append({"segment_id": slot["slot_id"], "target_duration": duration,
                         "transition": {"type": "CUT", "duration": 0.0}})
        timeline.append({"slot_id": slot["slot_id"], "start": start, "end": end,
                         "source_kind": "OPENING_VIDEO", "compiled_path": slot["normalized_asset"]["path"],
                         "source_sha256": slot["normalized_asset"]["sha256"]})
        previous_end = end
    for slot in body.get("slots", []):
        start, end = float(slot["start"]), float(slot["end"])
        if abs(start - previous_end) > .001 or end <= start:
            raise HybridRenderError("HYBRID_BODY_TIMELINE_INVALID", str(slot.get("slot_id")))
        duration = end - start
        slot_id = str(slot["slot_id"])
        if slot.get("visual_type") == "IMAGE":
            asset = slot.get("source_asset")
            if not _valid_asset(paths, asset):
                raise HybridRenderError("HYBRID_IMAGE_REQUIRED", slot_id)
            source_kind = "IMAGE"
            source = paths.artifact_path(asset["path"])
            source_hash = asset["sha256"]
            compiled_rel = f"assets/hybrid/compiled/{slot_id}.mp4"
            compiled = paths.artifact_path(compiled_rel)
            compile_image(source, compiled, duration=duration, motion=_motion(slot.get("effect")), target=target,
                          finishing_profile=settings.get("finishing_profile", "NONE"))
            clip = compiled
        elif slot.get("visual_type") == "STOCK_VIDEO":
            asset = slot.get("normalized_asset")
            if slot.get("status") == "READY" and _valid_asset(paths, asset):
                clip = paths.artifact_path(asset["path"])
                source_kind = "STOCK_VIDEO"
                source_hash = asset["sha256"]
                compiled_rel = asset["path"]
                if probe_media(clip).get("audio"):
                    raise HybridRenderError("HYBRID_VISUAL_AUDIO_LEAK", slot_id)
            else:
                fallback = slot.get("fallback_image_asset")
                if not _valid_asset(paths, fallback):
                    raise HybridRenderError("HYBRID_STOCK_OR_FALLBACK_REQUIRED", slot_id)
                source = paths.artifact_path(fallback["path"])
                source_hash = fallback["sha256"]
                source_kind = "STOCK_IMAGE_FALLBACK"
                compiled_rel = f"assets/hybrid/compiled/{slot_id}_fallback.mp4"
                clip = paths.artifact_path(compiled_rel)
                compile_image(source, clip, duration=duration, motion="SLOW_PUSH", target=target,
                              finishing_profile=settings.get("finishing_profile", "NONE"))
        else:
            raise HybridRenderError("HYBRID_VISUAL_TYPE_INVALID", slot_id)
        meta = validate_video(clip, target=target, silent=True, expected_duration=duration, tolerance=.08)
        clips.append(clip)
        segments.append({"segment_id": slot_id, "target_duration": duration,
                         "transition": {"type": "CUT", "duration": 0.0}})
        timeline.append({"slot_id": slot_id, "start": start, "end": end, "source_kind": source_kind,
                         "compiled_path": compiled_rel, "compiled_sha256": meta["sha256"],
                         "source_sha256": source_hash})
        previous_end = end
    return settings, target, clips, segments, timeline, previous_end


def render_hybrid_preview(runtime_root: Path | str, project_id: str) -> dict[str, Any]:
    """Compile and compose the mixed Hybrid Visual timeline with existing master tracks."""
    paths, config = _require_project(runtime_root, project_id)
    readiness = hybrid_preview_readiness(runtime_root, project_id)
    if not readiness["ready"]:
        error = HybridRenderError("HYBRID_PREVIEW_NOT_READY")
        error.readiness = readiness
        raise error
    opening = opening_builder_view(runtime_root, project_id)
    body = hybrid_body_view(runtime_root, project_id)
    assert opening is not None and body is not None
    alignment = read_json(paths.artifact_path("output/alignment.json"))
    try:
        master_duration = float(alignment["duration_seconds"])
        narration_rel = str(alignment["audio_path"])
    except Exception as error:
        raise HybridRenderError("HYBRID_ALIGNMENT_INVALID") from error
    narration = paths.artifact_path(narration_rel)
    if not narration.is_file():
        raise HybridRenderError("HYBRID_NARRATION_MISSING")
    settings, target, clips, segments, timeline, visual_end = _build_visual_clips(paths, config, opening, body)
    if abs(visual_end - master_duration) > .001 or abs(float(body.get("master_duration_seconds") or 0) - master_duration) > .001:
        raise HybridRenderError("HYBRID_MASTER_TIMELINE_MISMATCH", f"visual={visual_end}, audio={master_duration}")
    style = settings["subtitle_style"]
    srt = paths.artifact_path("output/hybrid_subtitles.srt")
    ass = paths.artifact_path("output/hybrid_subtitles.ass")
    build_subtitles(alignment, srt, ass, width=int(style.get("width", 44)),
                    font_name=str(style.get("font_name", "Arial")), font_size=int(style.get("font_size", 48)),
                    margin_left=int(style.get("margin_left", 90)), margin_right=int(style.get("margin_right", 260)))
    audio = config.settings.get("audio", {}) if isinstance(config.settings, dict) else {}
    bgm_rel = audio.get("bgm_path") if isinstance(audio, dict) else None
    bgm = paths.artifact_path(bgm_rel) if isinstance(bgm_rel, str) and bgm_rel else None
    hybrid = config.settings.get("hybrid_visual", {}) if isinstance(config.settings, dict) else {}
    waveform_enabled = hybrid.get("audio_visualizer", True) if isinstance(hybrid, dict) else True
    waveform = visualizer_spec(enabled=bool(waveform_enabled), target_width=target.width, target_height=target.height)
    output = paths.artifact_path(HYBRID_PREVIEW_PATH)
    candidate = output.with_name(output.stem + ".candidate.mp4")
    candidate.unlink(missing_ok=True)
    try:
        metadata = compose(clips=clips, segments=segments, narration=narration, output=candidate,
                           master_duration=master_duration, subtitles_ass=ass, bgm=bgm,
                           bgm_volume=float(audio.get("bgm_volume", .12)) if isinstance(audio, dict) else .12,
                           target=target, audio_visualizer=waveform)
        os.replace(candidate, output)
    finally:
        candidate.unlink(missing_ok=True)
    metadata = validate_video(output, target=target, silent=False, expected_duration=master_duration, tolerance=.12)
    manifest = {
        "schema_version": HYBRID_PREVIEW_VERSION,
        "project_id": project_id,
        "status": "READY",
        "preview_path": HYBRID_PREVIEW_PATH,
        "preview_sha256": metadata["sha256"],
        "duration_seconds": metadata["duration_seconds"],
        "master_duration_seconds": master_duration,
        "narration": {"path": narration_rel, "sha256": sha256_file(narration)},
        "subtitles": {"srt": "output/hybrid_subtitles.srt", "srt_sha256": sha256_file(srt),
                      "ass": "output/hybrid_subtitles.ass", "ass_sha256": sha256_file(ass)},
        "audio_visualizer": deepcopy(waveform),
        "source_video_audio": "MUTED_BY_CONTRACT",
        "timeline": timeline,
        "streams": {"video": metadata["video"], "audio": metadata["audio"]},
        "rendered_at": _now(),
        "release_activation": "BLOCKED_UNTIL_E2E_PRODUCT_ACCEPTANCE",
    }
    with ProjectLock(paths.runtime, project_id):
        atomic_write_json(paths.artifact_path(HYBRID_PREVIEW_MANIFEST_PATH), manifest)
    return deepcopy(manifest)


def hybrid_preview_view(runtime_root: Path | str, project_id: str) -> dict[str, Any]:
    paths, _config = _require_project(runtime_root, project_id)
    readiness = hybrid_preview_readiness(runtime_root, project_id)
    manifest_path = paths.artifact_path(HYBRID_PREVIEW_MANIFEST_PATH)
    manifest = read_json(manifest_path) if manifest_path.is_file() else None
    if isinstance(manifest, dict):
        preview = manifest.get("preview_path")
        digest = manifest.get("preview_sha256")
        valid = isinstance(preview, str) and isinstance(digest, str) and paths.artifact_path(preview).is_file() and sha256_file(paths.artifact_path(preview)) == digest
    else:
        valid = False
    return {"readiness": readiness, "preview_ready": valid,
            "preview_path": manifest.get("preview_path") if valid else None,
            "preview_sha256": manifest.get("preview_sha256") if valid else None,
            "timeline": deepcopy(manifest.get("timeline", [])) if valid else []}

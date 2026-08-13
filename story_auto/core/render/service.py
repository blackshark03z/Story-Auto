"""Checkpoint-aware render application service."""

from __future__ import annotations

import os
import hashlib
import json
from pathlib import Path
from typing import Any

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.checkpoint import CheckpointStore, fingerprint
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock
from story_auto.core.resources import ensure_free_space
from story_auto.core.subtitles import SUBTITLE_VERSION, build_subtitles

from .compiler import compile_hold, compile_image, compile_video
from .compositor import COMPOSER_VERSION, compose
from .media import MediaTarget, probe_media, transition_output_durations, validate_video
from .plan import RENDER_PLAN_VERSION, resolve_render_plan, validate_render_plan


RENDER_STAGE_VERSION = "story-auto-render-stage/1.0.0"
FINAL_MANIFEST_VERSION = "story-auto-final-manifest/1.0.0"
AUDIO_PLAN_VERSION = "story-auto-audio-plan/1.0.0"


def _render_settings(config) -> tuple[dict[str, Any], MediaTarget]:
    value = config.settings.get("render", {})
    if not isinstance(value, dict):
        raise ValueError("settings.render must be an object")
    target = MediaTarget(int(value.get("width", 1920)), int(value.get("height", 1080)),
                         int(value.get("fps", 30)), str(value.get("pixel_format", "yuv420p")))
    settings = {
        "width": target.width, "height": target.height, "fps": target.fps,
        "pixel_format": target.pixel_format,
        "fit_policy": value.get("fit_policy", "COVER_CENTER_CROP"),
        "trim_policy": value.get("trim_policy", "TRIM_HEAD"),
        "short_video_policy": value.get("short_video_policy", "BLOCK"),
        "transition": value.get("transition", {"type": "CUT", "duration": 0.0}),
        "hold_color": value.get("hold_color", "black"),
        "finishing_profile": str(value.get("finishing_profile", "NONE")).upper(),
        "subtitle_style": value.get("subtitle_style", {"width": 44, "font_name": "Arial", "font_size": 48}),
    }
    if settings["finishing_profile"] not in {"NONE", "NATURAL_SOFT"}:
        raise ValueError("settings.render.finishing_profile must be NONE or NATURAL_SOFT")
    return settings, target


def _load_required(paths, name: str) -> dict[str, Any]:
    return read_json(paths.artifact_path(f"output/{name}.json"))


def _hash_value(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _valid_plan(path: Path, project_root: Path) -> bool:
    try:
        validate_render_plan(read_json(path), project_root=project_root)
        return True
    except Exception:
        return False


def _atomic_media_publish(target: Path, producer) -> Any:
    """Publish validated media without exposing partial bytes at the target."""
    candidate=target.with_name(f".{target.stem}.candidate{target.suffix}")
    try:
        result=producer(candidate)
        os.replace(candidate,target)
        return result
    finally:
        candidate.unlink(missing_ok=True)


def run_render_stages(runtime_root: Path | str, project_id: str) -> dict[str, Any]:
    paths, config = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    storage=config.settings.get("storage",{})
    if not isinstance(storage,dict): raise ValueError("settings.storage must be an object")
    ensure_free_space(paths.runtime.temp,minimum_free_bytes=int(storage.get("minimum_free_bytes",64*1024*1024)))
    settings, target = _render_settings(config)
    alignment = _load_required(paths, "alignment")
    shot_plan = _load_required(paths, "shot_plan")
    media_plan = _load_required(paths, "media_plan")
    requests = _load_required(paths, "generation_requests")
    manifest = _load_required(paths, "generation_manifest")
    actions: dict[str, Any] = {"clips": {}}
    with ProjectLock(paths.runtime, project_id):
        checkpoints = CheckpointStore(paths)
        plan_inputs = {name: sha256_file(paths.artifact_path(f"output/{name}.json")) for name in
                       ("alignment", "shot_plan", "media_plan")}
        # Publishing requests share the provider ledger but are not render inputs.
        # Hash only shot selection state so publishing changes cannot invalidate video.
        plan_inputs["generation_requests"] = _hash_value([
            item for item in requests.get("requests", []) if item.get("purpose") == "SHOT"
        ])
        shot_request_ids = {item.get("request_id") for item in requests.get("requests", []) if item.get("purpose") == "SHOT"}
        plan_inputs["generation_manifest"] = _hash_value([
            item for item in manifest.get("requests", []) if item.get("request_id") in shot_request_ids
        ])
        plan_fp = fingerprint(stage_name="render_plan", producer_version=RENDER_STAGE_VERSION,
                              artifact_schema_version=RENDER_PLAN_VERSION, direct_inputs=plan_inputs, settings=settings)
        plan_path = paths.artifact_path("output/render_plan.json")
        decision = checkpoints.decide("render_plan", plan_fp)
        if decision.action == "SKIP" and _valid_plan(plan_path, paths.root):
            render_plan, actions["render_plan"] = read_json(plan_path), "SKIP"
        else:
            render_plan = resolve_render_plan(project_id=project_id, project_root=paths.root,
                                              render_mode=config.render_mode, alignment=alignment,
                                              shot_plan=shot_plan, media_plan=media_plan,
                                              generation_requests=requests, generation_manifest=manifest,
                                              settings=settings)
            atomic_write_json(plan_path, render_plan)
            checkpoints.record("render_plan", fingerprint=plan_fp, status="SUCCESS",
                               outputs=["output/render_plan.json"], producer_version=RENDER_STAGE_VERSION)
            actions["render_plan"] = "RUN"
        compile_durations, computed_duration = transition_output_durations(render_plan["segments"])
        if abs(computed_duration - float(render_plan["master_duration"])) > .01:
            raise ValueError("transition duration math does not preserve narration duration")
        clips: list[Path] = []
        for segment, compile_duration in zip(render_plan["segments"], compile_durations):
            segment_id = segment.get("segment_id", segment["shot_id"])
            relative = f"output/scenes/{segment_id}.mp4"
            clip_path = paths.artifact_path(relative)
            clip_fp = fingerprint(stage_name=f"render_clip_{segment_id}", producer_version=RENDER_STAGE_VERSION,
                                  artifact_schema_version="story-auto-normalized-scene/1.0.0",
                                  direct_inputs={"source_hash": segment["source_hash"]},
                                  settings={"segment": segment, "compile_duration": compile_duration,
                                            "target": settings | {"subtitle_style": None}})
            stage = f"render_clip_{segment_id}"
            decision = checkpoints.decide(stage, clip_fp)
            valid = False
            if decision.action == "SKIP":
                try:
                    validate_video(clip_path, target=target, silent=True, expected_duration=compile_duration)
                    valid = True
                except Exception:
                    valid = False
            if valid:
                actions["clips"][segment_id] = "SKIP"
            else:
                def produce(candidate):
                    if segment["source_media_type"] == "IMAGE":
                        return compile_image(paths.artifact_path(segment["source_asset"]), candidate,
                                  duration=compile_duration, motion=segment["image_motion_policy"], target=target,
                                  finishing_profile=settings["finishing_profile"])
                    if segment["source_media_type"] == "VIDEO":
                        return compile_video(paths.artifact_path(segment["source_asset"]), candidate,
                                  duration=compile_duration, short_policy=segment["short_video_policy"], target=target,
                                  finishing_profile=settings["finishing_profile"])
                    return compile_hold(candidate,duration=compile_duration,color=settings["hold_color"],target=target)
                _atomic_media_publish(clip_path,produce)
                checkpoints.record(stage, fingerprint=clip_fp, status="SUCCESS", outputs=[relative],
                                   producer_version=RENDER_STAGE_VERSION)
                actions["clips"][segment_id] = "RUN"
            clips.append(clip_path)
        style = settings["subtitle_style"]
        subtitle_fp = fingerprint(stage_name="subtitles", producer_version=SUBTITLE_VERSION,
                                  artifact_schema_version=SUBTITLE_VERSION,
                                  direct_inputs={"alignment_sha256": plan_inputs["alignment"]}, settings=style)
        srt_rel, ass_rel = "output/subtitles.srt", "output/subtitles.ass"
        srt_path, ass_path = paths.artifact_path(srt_rel), paths.artifact_path(ass_rel)
        decision = checkpoints.decide("subtitles", subtitle_fp)
        if decision.action == "SKIP" and srt_path.stat().st_size > 0 and ass_path.stat().st_size > 0:
            actions["subtitles"] = "SKIP"
        else:
            build_subtitles(alignment, srt_path, ass_path, width=int(style.get("width", 44)),
                            font_name=str(style.get("font_name", "Arial")), font_size=int(style.get("font_size", 48)))
            checkpoints.record("subtitles", fingerprint=subtitle_fp, status="SUCCESS", outputs=[srt_rel, ass_rel],
                               producer_version=SUBTITLE_VERSION)
            actions["subtitles"] = "RUN"
        narration_rel = alignment["audio_path"]
        narration_path = paths.artifact_path(narration_rel)
        narration_hash = sha256_file(narration_path)
        audio_settings = config.settings.get("audio", {})
        if not isinstance(audio_settings, dict):
            raise ValueError("settings.audio must be an object")
        bgm_rel = audio_settings.get("bgm_path")
        bgm_path = paths.artifact_path(bgm_rel) if bgm_rel else None
        bgm_hash = sha256_file(bgm_path) if bgm_path else None
        audio_plan = {"schema_version": AUDIO_PLAN_VERSION, "project_id": project_id,
                      "narration": {"path": narration_rel, "sha256": narration_hash},
                      "source_video_audio": "MUTE",
                      "bgm": {"path": bgm_rel, "sha256": bgm_hash, "loop": bool(bgm_path),
                              "volume": float(audio_settings.get("bgm_volume", .12)),
                              "fade_in_seconds": 1.0, "fade_out_seconds": 1.5}}
        audio_plan_path = paths.artifact_path("output/audio_plan.json")
        audio_fp = fingerprint(stage_name="audio_plan", producer_version=RENDER_STAGE_VERSION,
                               artifact_schema_version=AUDIO_PLAN_VERSION,
                               direct_inputs={"narration_sha256": narration_hash, "bgm_sha256": bgm_hash or "NONE"},
                               settings=audio_plan["bgm"])
        if checkpoints.decide("audio_plan", audio_fp).action == "SKIP" and audio_plan_path.is_file():
            actions["audio_plan"] = "SKIP"
        else:
            atomic_write_json(audio_plan_path, audio_plan)
            checkpoints.record("audio_plan", fingerprint=audio_fp, status="SUCCESS", outputs=["output/audio_plan.json"],
                               producer_version=RENDER_STAGE_VERSION)
            actions["audio_plan"] = "RUN"
        clip_hashes = [sha256_file(path) for path in clips]
        final_inputs = {"render_plan_sha256": sha256_file(plan_path), "narration_sha256": narration_hash,
                        "srt_sha256": sha256_file(srt_path), "ass_sha256": sha256_file(ass_path),
                        "bgm_sha256": bgm_hash or "NONE", **{f"clip_{i}": value for i, value in enumerate(clip_hashes)}}
        final_fp = fingerprint(stage_name="final_render", producer_version=COMPOSER_VERSION,
                               artifact_schema_version=FINAL_MANIFEST_VERSION, direct_inputs=final_inputs,
                               settings={"target": settings, "bgm_volume": audio_plan["bgm"]["volume"]})
        final_rel, manifest_rel = "output/final.mp4", "output/final_manifest.json"
        final_path, final_manifest_path = paths.artifact_path(final_rel), paths.artifact_path(manifest_rel)
        decision = checkpoints.decide("final_render", final_fp)
        final_valid = False
        upstream_ran = (actions["render_plan"] == "RUN" or actions["subtitles"] == "RUN" or
                        actions["audio_plan"] == "RUN" or any(value == "RUN" for value in actions["clips"].values()))
        if decision.action == "SKIP" and not upstream_ran:
            try:
                current_manifest = read_json(final_manifest_path)
                metadata = validate_video(final_path, target=target, silent=False,
                                          expected_duration=float(render_plan["master_duration"]), tolerance=.12)
                final_valid = current_manifest.get("final_sha256") == metadata["sha256"]
            except Exception:
                final_valid = False
        if final_valid:
            actions["final_render"] = "SKIP"
            final_manifest = read_json(final_manifest_path)
        else:
            def produce_final(candidate):
                return compose(clips=clips, segments=render_plan["segments"], narration=narration_path,
                                   output=candidate, master_duration=float(render_plan["master_duration"]),
                                   subtitles_ass=ass_path, bgm=bgm_path,
                                   bgm_volume=audio_plan["bgm"]["volume"], target=target)
            metadata=_atomic_media_publish(final_path,produce_final)
            metadata = validate_video(final_path, target=target, silent=False,
                                      expected_duration=float(render_plan["master_duration"]), tolerance=.12)
            final_manifest = {
                "schema_version": FINAL_MANIFEST_VERSION, "project_id": project_id, "final_path": final_rel,
                "final_sha256": metadata["sha256"], "duration_seconds": metadata["duration_seconds"],
                "width": metadata["video"]["width"], "height": metadata["video"]["height"],
                "render_plan_sha256": final_inputs["render_plan_sha256"],
                "alignment_sha256": plan_inputs["alignment"], "audio_plan_sha256": sha256_file(audio_plan_path),
                "subtitle_sha256": final_inputs["ass_sha256"],
                "subtitle_hashes": {"srt": final_inputs["srt_sha256"], "ass": final_inputs["ass_sha256"]},
                "selected_asset_hashes": [segment["source_hash"] for segment in render_plan["segments"]],
                "narration_sha256": narration_hash, "bgm_sha256": bgm_hash,
                "composer": {"version": COMPOSER_VERSION, "settings": settings},
                "streams": {"video": metadata["video"], "audio": metadata["audio"]},
                "publishing_package_sha256": (sha256_file(paths.artifact_path("output/publishing_package.json"))
                                                 if paths.artifact_path("output/publishing_package.json").is_file() else None),
            }
            atomic_write_json(final_manifest_path, final_manifest)
            checkpoints.record("final_render", fingerprint=final_fp, status="SUCCESS",
                               outputs=[final_rel, manifest_rel], producer_version=COMPOSER_VERSION)
            actions["final_render"] = "RUN"
    return {"actions": actions, "final_manifest": final_manifest}

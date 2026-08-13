"""Resolve frozen planning artifacts to exact validated local render sources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from story_auto.core.artifacts import sha256_file
from story_auto.providers.flow.validation import validate_image, validate_video


RENDER_PLAN_VERSION = "story-auto-render-plan/1.0.0"


class RenderPlanError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(failure_class + (f": {detail}" if detail else ""))


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _selected_by_request(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item.get("request_id"): item for item in manifest.get("requests", []) if isinstance(item, dict)}


def _shot_requests(requests: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for request in requests.get("requests", []):
        if request.get("purpose") == "SHOT" and isinstance(request.get("shot_id"), str):
            result.setdefault(request["shot_id"], []).append(request)
    return result


def validate_render_plan(value: Any, *, project_root: Path | None = None) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != RENDER_PLAN_VERSION:
        raise RenderPlanError("RENDER_PLAN_INVALID")
    segments = value.get("segments")
    if value.get("render_mode") not in {"hybrid_hook", "full_video_ai"} or not isinstance(segments, list) or not segments:
        raise RenderPlanError("RENDER_PLAN_INVALID")
    previous = 0.0
    for segment in segments:
        try:
            start, end, duration = float(segment["target_start"]), float(segment["target_end"]), float(segment["target_duration"])
        except (KeyError, TypeError, ValueError) as error:
            raise RenderPlanError("RENDER_PLAN_INVALID") from error
        if abs(start - previous) > .01 or end <= start or abs((end - start) - duration) > .01:
            raise RenderPlanError("RENDER_TIMELINE_INVALID")
        previous = end
        if segment.get("source_media_type") not in {"IMAGE", "VIDEO", "HOLD"}:
            raise RenderPlanError("RENDER_PLAN_INVALID")
        if value["render_mode"] == "full_video_ai" and segment["source_media_type"] != "VIDEO":
            raise RenderPlanError("RENDER_BLOCKED_REQUIRED_VIDEO_MISSING")
        if project_root is not None and segment["source_media_type"] != "HOLD":
            path = project_root / segment["source_asset"]
            if not path.is_file() or sha256_file(path) != segment.get("source_hash"):
                raise RenderPlanError("RENDER_SOURCE_INVALID", segment.get("shot_id", ""))
    if abs(previous - float(value.get("master_duration", -1))) > .01:
        raise RenderPlanError("RENDER_TIMELINE_INVALID")


def resolve_render_plan(
    *, project_id: str, project_root: Path, render_mode: str, alignment: dict[str, Any],
    shot_plan: dict[str, Any], media_plan: dict[str, Any], generation_requests: dict[str, Any],
    generation_manifest: dict[str, Any], settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = settings or {}
    media_by_shot = {item["shot_id"]: item for item in media_plan.get("shots", [])}
    requests_by_shot = _shot_requests(generation_requests)
    requests_by_id = {item.get("request_id"): item for item in generation_requests.get("requests", []) if isinstance(item, dict)}
    manifest_by_request = _selected_by_request(generation_manifest)
    default_transition = settings.get("transition", {"type": "CUT", "duration": 0.0})
    segments: list[dict[str, Any]] = []
    for shot in shot_plan.get("shots", []):
        shot_id = shot["shot_id"]
        media = media_by_shot.get(shot_id)
        if not media:
            raise RenderPlanError("REQUIRED_MEDIA_UNRESOLVED", shot_id)
        desired = media["media_type"]
        source_kind = desired
        selected_request: dict[str, Any] | None = None
        selected_asset: dict[str, Any] | None = None
        if desired != "HOLD":
            candidates = requests_by_shot.get(shot_id, [])
            if media.get("selected_request_id"):
                explicit = requests_by_id.get(media["selected_request_id"])
                candidates = [explicit] if explicit else []
            for request in candidates:
                if request.get("media_type") != desired:
                    continue
                entry = manifest_by_request.get(request["request_id"], {})
                selected = entry.get("selected_asset")
                if entry.get("status") == "SUCCEEDED" and isinstance(selected, dict):
                    selected_request, selected_asset = request, selected
                    break
        fallback: dict[str, Any] | None = None
        if selected_asset is None and desired != "HOLD":
            if media.get("requirement") == "REQUIRED":
                failure = "RENDER_BLOCKED_REQUIRED_VIDEO_MISSING" if desired == "VIDEO" else "REQUIRED_MEDIA_UNRESOLVED"
                raise RenderPlanError(failure, shot_id)
            policy = media.get("fallback_policy", "BLOCK")
            if policy == "HOLD":
                source_kind = "HOLD"
                fallback = {"used": True, "policy": "HOLD", "reason": "preferred_source_unavailable"}
            elif policy == "IMAGE":
                for request in requests_by_shot.get(shot_id, []):
                    entry = manifest_by_request.get(request["request_id"], {})
                    if request.get("media_type") == "IMAGE" and entry.get("status") == "SUCCEEDED":
                        selected_request, selected_asset, source_kind = request, entry.get("selected_asset"), "IMAGE"
                        fallback = {"used": True, "policy": "IMAGE", "reason": "preferred_video_unavailable"}
                        break
            if selected_asset is None and source_kind != "HOLD":
                raise RenderPlanError("REQUIRED_MEDIA_UNRESOLVED", shot_id)
        source_path = None if source_kind == "HOLD" else selected_asset.get("path")
        source_hash = _canonical_hash({"kind": "HOLD", "shot_id": shot_id}) if source_kind == "HOLD" else selected_asset.get("sha256")
        provenance: dict[str, Any] = {"request_id": None, "attempt": None, "provider": None}
        if source_path:
            absolute = project_root / source_path
            metadata = validate_image(absolute) if source_kind == "IMAGE" else validate_video(absolute)
            if metadata["sha256"] != source_hash:
                raise RenderPlanError("RENDER_SOURCE_INVALID", shot_id)
            provenance = {"request_id": selected_request["request_id"], "attempt": selected_asset.get("attempt"),
                          "provider": selected_request.get("provider"), "asset_metadata": metadata}
        transition = dict(default_transition)
        if transition.get("type", "CUT") not in {"CUT", "CROSSFADE"}:
            raise RenderPlanError("TRANSITION_POLICY_INVALID")
        if transition.get("type", "CUT") == "CUT":
            transition["duration"] = 0.0
        segments.append({
            "shot_id": shot_id, "source_asset": source_path, "source_media_type": source_kind,
            "desired_media_type": desired, "source_hash": source_hash,
            "target_start": float(shot["start"]), "target_end": float(shot["end"]),
            "target_duration": float(shot["end"]) - float(shot["start"]),
            "trim_policy": settings.get("trim_policy", "TRIM_HEAD"),
            "short_video_policy": settings.get("short_video_policy", "BLOCK"),
            "fit_policy": settings.get("fit_policy", "COVER_CENTER_CROP"),
            "image_motion_policy": media.get("image_motion_policy", "STATIC") if source_kind == "IMAGE" else "NONE",
            "transition": transition, "source_audio_policy": "MUTE", "fallback_resolution": fallback,
            "provenance": provenance,
        })
    value = {"schema_version": RENDER_PLAN_VERSION, "project_id": project_id, "render_mode": render_mode,
             "master_duration": float(alignment["duration_seconds"]), "settings": settings, "segments": segments}
    validate_render_plan(value, project_root=project_root)
    return value

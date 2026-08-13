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
    segment_ids: set[str] = set()
    for segment in segments:
        try:
            start, end, duration = float(segment["target_start"]), float(segment["target_end"]), float(segment["target_duration"])
        except (KeyError, TypeError, ValueError) as error:
            raise RenderPlanError("RENDER_PLAN_INVALID") from error
        if abs(start - previous) > .01 or end <= start or abs((end - start) - duration) > .01:
            raise RenderPlanError("RENDER_TIMELINE_INVALID")
        previous = end
        segment_id = segment.get("segment_id") or segment.get("shot_id")
        if not isinstance(segment_id, str) or segment_id in segment_ids:
            raise RenderPlanError("RENDER_PLAN_INVALID")
        segment_ids.add(segment_id)
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
    if default_transition.get("type", "CUT") not in {"CUT", "CROSSFADE"}:
        raise RenderPlanError("TRANSITION_POLICY_INVALID")
    segments: list[dict[str, Any]] = []
    seen_hashes: dict[str, str] = {}

    def successful(request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
        entry = manifest_by_request.get(request.get("request_id"), {})
        selected = entry.get("selected_asset")
        valid = entry.get("status") == "SUCCEEDED" and isinstance(selected, dict)
        if valid and settings.get("visual_narration_alignment", {}).get("require_semantic_qc"):
            valid = selected.get("alignment_classification") in {
                "PASS_DIRECT", "PASS_SUPPORTIVE", "PASS_ATMOSPHERIC"
            }
        return (request, selected) if valid else None

    for shot in shot_plan.get("shots", []):
        shot_id = shot["shot_id"]
        if settings.get("visual_narration_alignment", {}).get("fail_on_unplanned_reuse"):
            max_beat = float(settings.get("visual_narration_alignment", {}).get("max_visual_beat_seconds", 120.0))
            if float(shot.get("end", 0)) - float(shot.get("start", 0)) > max_beat:
                raise RenderPlanError("VISUAL_BEAT_UNDERSEGMENTED", shot_id)
        media = media_by_shot.get(shot_id)
        if not media:
            raise RenderPlanError("RENDER_SHOT_ASSET_UNRESOLVED", shot_id)
        desired, source_kind = media["media_type"], media["media_type"]
        candidates = [item for item in requests_by_shot.get(shot_id, []) if item.get("media_type") == desired]
        if media.get("selected_request_id"):
            explicit = requests_by_id.get(media["selected_request_id"])
            candidates = [explicit] if (explicit and explicit.get("purpose") == "SHOT" and
                explicit.get("shot_id") == shot_id and explicit.get("media_type") == desired) else []
        candidates.sort(key=lambda item: (int(item.get("part_index", 1)), item.get("request_id", "")))
        resolved = [pair for request in candidates if (pair := successful(request)) is not None]
        expected_parts = max((int(item.get("part_count", 1)) for item in candidates), default=1)
        complete = len(resolved) == expected_parts and [int(item[0].get("part_index", 1)) for item in resolved] == list(range(1, expected_parts + 1))
        fallback: dict[str, Any] | None = None

        if desired == "HOLD":
            resolved = []
            complete = True
        elif not complete:
            if media.get("requirement") == "REQUIRED":
                failure = "RENDER_BLOCKED_REQUIRED_VIDEO_MISSING" if desired == "VIDEO" else "RENDER_SHOT_ASSET_UNRESOLVED"
                raise RenderPlanError(failure, shot_id)
            policy = media.get("fallback_policy", "BLOCK")
            if policy == "HOLD":
                resolved, source_kind = [], "HOLD"
                fallback = {"used": True, "policy": "HOLD", "reason": "preferred_source_unavailable"}
            elif policy == "IMAGE":
                replacement = next((successful(item) for item in requests_by_shot.get(shot_id, []) if item.get("media_type") == "IMAGE" and successful(item)), None)
                if replacement:
                    resolved, source_kind = [replacement], "IMAGE"
                    fallback = {"used": True, "policy": "IMAGE", "reason": "preferred_video_unavailable"}
                else:
                    raise RenderPlanError("RENDER_SHOT_ASSET_UNRESOLVED", shot_id)
            else:
                raise RenderPlanError("RENDER_SHOT_ASSET_UNRESOLVED", shot_id)

        render_parts: list[tuple[dict[str, Any] | None, dict[str, Any] | None]] = resolved or [(None, None)]
        cursor = float(shot["start"])
        for index, (selected_request, selected_asset) in enumerate(render_parts, 1):
            is_last = index == len(render_parts)
            if selected_request and len(render_parts) > 1:
                start = float(selected_request.get("target_start", cursor))
                end = float(selected_request.get("target_end", shot["end"] if is_last else start + float(selected_request["target_duration"])))
            else:
                start, end = float(shot["start"]), float(shot["end"])
            if abs(start - cursor) > .01 or (is_last and abs(end - float(shot["end"])) > .01):
                raise RenderPlanError("GENERATION_PARTITION_INVALID", shot_id)
            cursor = end
            source_path = None if source_kind == "HOLD" else selected_asset.get("path")
            source_hash = _canonical_hash({"kind": "HOLD", "shot_id": shot_id}) if source_kind == "HOLD" else selected_asset.get("sha256")
            provenance: dict[str, Any] = {"request_id": None, "attempt": None, "provider": None}
            if source_path:
                absolute = project_root / source_path
                metadata = validate_image(absolute) if source_kind == "IMAGE" else validate_video(absolute)
                if metadata["sha256"] != source_hash:
                    raise RenderPlanError("RENDER_SOURCE_INVALID", shot_id)
                provenance = {"request_id": selected_request["request_id"], "attempt": selected_asset.get("attempt"), "provider": selected_request.get("provider"), "asset_metadata": metadata}
                # Reuse is only safe when the frozen media item explicitly says so.
                # Never let a valid asset silently cover an unrelated story beat.
                if settings.get("visual_narration_alignment", {}).get("fail_on_unplanned_reuse"):
                    prior = seen_hashes.get(source_hash)
                    if prior and prior != shot_id and not media.get("allow_asset_reuse", False):
                        raise RenderPlanError("VISUAL_NARRATION_ALIGNMENT_MISMATCH", f"asset {source_hash} reused by {prior} and {shot_id}")
                    seen_hashes[source_hash] = shot_id
            transition = dict(default_transition if is_last else {"type": "CUT", "duration": 0.0})
            if transition.get("type", "CUT") == "CUT": transition["duration"] = 0.0
            segment_id = shot_id if len(render_parts) == 1 else f"{shot_id}_part_{index:03d}"
            segments.append({
                "segment_id": segment_id, "shot_id": shot_id, "part_index": index, "part_count": len(render_parts),
                "source_asset": source_path, "source_media_type": source_kind, "desired_media_type": desired,
                "source_hash": source_hash, "target_start": start, "target_end": end, "target_duration": end - start,
                "trim_policy": settings.get("trim_policy", "TRIM_HEAD"),
                "short_video_policy": "BLOCK" if render_mode == "full_video_ai" else settings.get("short_video_policy", "BLOCK"),
                "fit_policy": settings.get("fit_policy", "COVER_CENTER_CROP"),
                "image_motion_policy": media.get("image_motion_policy", "STATIC") if source_kind == "IMAGE" else "NONE",
                "transition": transition, "source_audio_policy": "MUTE", "fallback_resolution": fallback,
                "provenance": provenance,
            })
    value = {"schema_version": RENDER_PLAN_VERSION, "project_id": project_id, "render_mode": render_mode,
             "master_duration": float(alignment["duration_seconds"]), "settings": settings, "segments": segments}
    validate_render_plan(value, project_root=project_root)
    return value

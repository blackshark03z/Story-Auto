"""Data-driven Ambient Story style and deterministic presentation policy."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any


AMBIENT_PRESENTATION_VERSION = "story-auto-ambient-presentation/1.0.0"
AMBIENT_STYLES = frozenset({"quiet_verdict", "hidden_mastery"})
AMBIENT_MOTIONS = frozenset({
    "STATIC", "SUBTLE_PUSH", "SUBTLE_PULL", "SUBTLE_PAN_LEFT",
    "SUBTLE_PAN_RIGHT", "MICRO_DRIFT",
})


@dataclass(frozen=True)
class AmbientStyleProfile:
    style_id: str
    label: str
    preferred_images: tuple[int, int]
    hard_max_images: int
    prompt_directive: str
    motion_cycle: tuple[str, ...]
    overlay: str
    transition: tuple[str, float]
    subtitle_width: int
    subtitle_size: int


STYLE_PROFILES: dict[str, AmbientStyleProfile] = {
    "quiet_verdict": AmbientStyleProfile(
        style_id="quiet_verdict",
        label="Quiet Verdict",
        preferred_images=(2, 5),
        hard_max_images=8,
        prompt_directive=(
            "Cool-neutral restrained natural realism in a serious institutional environment; "
            "clear character hierarchy, restrained contrast, and meaningful negative space; no glossy or HDR treatment"
        ),
        motion_cycle=("STATIC", "STATIC", "SUBTLE_PUSH", "STATIC", "MICRO_DRIFT"),
        overlay="FINE_GRAIN",
        transition=("CUT", 0.0),
        subtitle_width=44,
        subtitle_size=48,
    ),
    "hidden_mastery": AmbientStyleProfile(
        style_id="hidden_mastery",
        label="Hidden Mastery",
        preferred_images=(4, 7),
        hard_max_images=10,
        prompt_directive=(
            "Warm restrained natural realism in a tactile human-scale environment; ordinary-looking protagonist, "
            "object-centered composition when relevant, and subtle continuity before and after the reveal"
        ),
        motion_cycle=("SUBTLE_PUSH", "SUBTLE_PAN_LEFT", "MICRO_DRIFT", "SUBTLE_PAN_RIGHT", "SUBTLE_PULL"),
        overlay="FINE_GRAIN",
        transition=("CROSSFADE", 0.35),
        subtitle_width=46,
        subtitle_size=46,
    ),
}


def ambient_style_profile(style_id: str) -> AmbientStyleProfile:
    try:
        return STYLE_PROFILES[style_id]
    except KeyError as error:
        raise ValueError(f"invalid ambient style: {style_id!r}") from error


def ambient_style_label(style_id: str | None) -> str | None:
    return ambient_style_profile(style_id).label if style_id else None


def ambient_prompt_directive(style_id: str) -> str:
    return ambient_style_profile(style_id).prompt_directive


def temporal_video_qc_applicability(render_mode: str) -> str:
    return "NOT_APPLICABLE" if render_mode == "ambient_story" else "APPLICABLE"


def _seed(project_id: str, shot: dict[str, Any], style_id: str) -> int:
    identity = "|".join((project_id, style_id, str(shot.get("shot_id", "")), str(shot.get("story_state", ""))))
    return int(hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8], 16)


def compile_ambient_presentation(
    project_id: str, shot: dict[str, Any], style_id: str, *,
    motion_enabled: bool = True, overlay_enabled: bool = True,
) -> dict[str, Any]:
    """Resolve a stable, bounded image treatment without provider semantics."""
    profile = ambient_style_profile(style_id)
    seed = _seed(project_id, shot, style_id)
    primitive = profile.motion_cycle[seed % len(profile.motion_cycle)] if motion_enabled else "STATIC"
    scale = 0.0 if primitive == "STATIC" else 0.01 + ((seed >> 5) % 2001) / 100_000
    translation = 0.0
    if primitive in {"SUBTLE_PAN_LEFT", "SUBTLE_PAN_RIGHT"}:
        translation = 0.01 + ((seed >> 11) % 2001) / 100_000
    elif primitive == "MICRO_DRIFT":
        translation = 0.005 + ((seed >> 11) % 501) / 100_000
    value = {
        "schema_version": AMBIENT_PRESENTATION_VERSION,
        "style_id": style_id,
        "motion": primitive,
        "total_scale_change": round(scale, 5),
        "translation_fraction": round(translation, 5),
        "overlay": profile.overlay if overlay_enabled else "NONE",
        "overlay_strength": 0.55 if overlay_enabled else 0.0,
        "seed": seed,
    }
    validate_ambient_presentation(value)
    return value


def validate_ambient_presentation(value: Any) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != AMBIENT_PRESENTATION_VERSION:
        raise ValueError("AMBIENT_PRESENTATION_INVALID")
    if value.get("style_id") not in AMBIENT_STYLES or value.get("motion") not in AMBIENT_MOTIONS:
        raise ValueError("AMBIENT_PRESENTATION_INVALID")
    scale = float(value.get("total_scale_change", -1))
    translation = float(value.get("translation_fraction", -1))
    if value["motion"] == "STATIC" and (scale != 0 or translation != 0):
        raise ValueError("AMBIENT_MOTION_BOUNDS_INVALID")
    if value["motion"] != "STATIC" and not 0.01 <= scale <= 0.03:
        raise ValueError("AMBIENT_MOTION_BOUNDS_INVALID")
    if not 0 <= translation <= 0.03:
        raise ValueError("AMBIENT_MOTION_BOUNDS_INVALID")
    if value.get("overlay") not in {"NONE", "FINE_GRAIN"}:
        raise ValueError("AMBIENT_PRESENTATION_INVALID")
    strength = float(value.get("overlay_strength", -1))
    if not 0 <= strength <= 1 or not isinstance(value.get("seed"), int):
        raise ValueError("AMBIENT_PRESENTATION_INVALID")


def ambient_render_defaults(style_id: str) -> dict[str, Any]:
    profile = ambient_style_profile(style_id)
    return {
        "transition": {"type": profile.transition[0], "duration": profile.transition[1]},
        "subtitle_style": {
            "width": profile.subtitle_width,
            "font_name": "Arial",
            "font_size": profile.subtitle_size,
            "margin_left": 100,
            "margin_right": 260,
            "provider_mark_safe_area": "BOTTOM_RIGHT",
            "preset": style_id,
        },
    }

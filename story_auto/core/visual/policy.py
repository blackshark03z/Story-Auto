"""Provider-independent visual DNA and prompt compilation."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

VISUAL_POLICY_VERSION = "story-auto-visual-policy/1.0.0"

DEFAULT_VISUAL_POLICY: dict[str, Any] = {
    "schema_version": VISUAL_POLICY_VERSION,
    "realism_style": "NATURAL_SOFT_REALISM",
    "lighting_style": "AVAILABLE_PRACTICAL_LIGHT",
    "contrast_profile": "MODERATE_SOFT_ROLLOFF",
    "palette": "NEUTRAL_RESTRAINED",
    "skin_texture_policy": "NATURAL_VISIBLE_TEXTURE",
    "material_texture_policy": "REAL_IMPERFECT_SURFACES",
    "lens_profile": "OBSERVATIONAL_35_50MM",
    "depth_of_field": "MODERATE_CONTEXT_PRESERVING",
    "composition_style": "OBSERVATIONAL_ASYMMETRY",
    "grain_policy": "SUBTLE_ORGANIC",
    "motion_style": "RESTRAINED",
}

_REQUIRED = tuple(key for key in DEFAULT_VISUAL_POLICY if key != "schema_version")
_IMAGE_RENDERING = {
    "realism_style": "naturalistic photographic realism, softly observed rather than commercial",
    "lighting_style": "believable available, window, daylight, or practical light",
    "contrast_profile": "moderate contrast with shadow detail and gentle highlight rolloff",
    "palette": "neutral restrained color and saturation",
    "skin_texture_policy": "natural facial skin texture without beauty retouching",
    "material_texture_policy": "visible real fabric, wood, and metal texture with small imperfections",
    "lens_profile": "realistic observational 35 to 50 mm perspective where appropriate",
    "depth_of_field": "moderate depth of field that preserves environmental context",
    "composition_style": "observational composition with slight real-world asymmetry",
    "grain_policy": "subtle fine organic grain",
}
_ANTI_POLISH = (
    "Avoid waxy or porcelain skin, glossy beauty retouching, plastic sheen, "
    "over-sharpened HDR, excessive bokeh, studio-perfect illumination, gratuitous rim light, "
    "volumetric god rays, default teal-orange grading, pristine showroom surfaces, perfect symmetry, and CGI material response."
)
_MOTION = {
    "STATIC": "locked observational camera",
    "SUBTLE_HANDHELD": "subtle grounded handheld movement",
    "SLOW_OBSERVATIONAL_PUSH": "slow observational push",
    "GENTLE_PAN": "gentle motivated pan",
}


def default_visual_policy() -> dict[str, Any]:
    return deepcopy(DEFAULT_VISUAL_POLICY)


def validate_visual_policy(value: Any) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != VISUAL_POLICY_VERSION:
        raise ValueError("VISUAL_POLICY_INVALID")
    if set(value) != {"schema_version", *_REQUIRED}:
        raise ValueError("VISUAL_POLICY_INVALID")
    if any(not isinstance(value.get(key), str) or not value[key].strip() for key in _REQUIRED):
        raise ValueError("VISUAL_POLICY_INVALID")
    if value["realism_style"] != "NATURAL_SOFT_REALISM":
        raise ValueError("VISUAL_POLICY_INVALID")


def compile_image_prompt(intent: str, policy: dict[str, Any], *, continuity: str = "") -> str:
    validate_visual_policy(policy)
    parts = [intent.strip()]
    if continuity.strip():
        parts.append("Continuity identity and environment: " + continuity.strip())
    parts.extend(_IMAGE_RENDERING[key] for key in _IMAGE_RENDERING)
    parts.append(_ANTI_POLISH)
    return ". ".join(part.rstrip(". ") for part in parts if part) + "."


def compile_video_prompt(
    *, subject_motion: str, environmental_motion: str, camera_motion: str, timing: str,
) -> str:
    """Compile motion only; the reference image owns appearance and treatment."""
    camera = camera_motion.strip().upper().replace(" ", "_")
    camera_text = _MOTION.get(camera, _MOTION["STATIC"])
    parts = [
        f"Subject motion: {subject_motion.strip() or 'natural minimal movement'}",
        f"Environmental motion: {environmental_motion.strip() or 'only subtle physically plausible movement'}",
        f"Camera motion: {camera_text}",
        f"Timing: {timing.strip()}",
        "Preserve the supplied reference image identity, environment, lighting, palette, and material treatment",
        "Restrained realistic motion; no floating, orbiting, sweeping, morphing, or artificial speed ramps",
    ]
    return ". ".join(part.rstrip(". ") for part in parts) + "."

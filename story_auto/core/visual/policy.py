"""Provider-independent visual DNA and prompt compilation."""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

VISUAL_POLICY_VERSION = "story-auto-visual-policy/1.4.0"
FLOW_IMAGE_PROMPT_HARD_LIMIT = 1_200
AMBIENT_IMAGE_PROMPT_INTERNAL_TARGET = 1_100

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
    "provider_mark_safe_area": "BOTTOM_RIGHT",
    "provider_mark_safe_area_strength": "SOFT_COMPOSITION_CONSTRAINT",
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
    "Avoid retouching, wax, CGI, HDR, heavy bokeh, stylization, pristine surfaces, and symmetry."
)
_FLOW_MARK_SAFE_AREA = (
    "Keep key details out of the bottom-right provider-mark safe area"
)
_MOTION = {
    "STATIC": "locked observational camera",
    "SUBTLE_HANDHELD": "subtle grounded handheld movement",
    "SLOW_OBSERVATIONAL_PUSH": "slow observational push",
    "GENTLE_PAN": "gentle motivated pan",
}


class AmbientVisualBriefBudgetError(ValueError):
    """A structured Ambient brief cannot fit without dropping required intent."""

    def __init__(self, field: str, observed: int, limit: int) -> None:
        self.failure_class = "AMBIENT_VISUAL_BRIEF_OVER_BUDGET"
        self.field = field
        self.observed = observed
        self.limit = limit
        super().__init__(f"{self.failure_class}: field={field} observed={observed} limit={limit}")


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
    parts.append("Natural soft photo realism; practical light, soft rolloff, restrained color, natural skin and materials")
    parts.append("35-50 mm lens, contextual depth, asymmetry, grain")
    parts.append(_FLOW_MARK_SAFE_AREA)
    parts.append(_ANTI_POLISH)
    prompt = ". ".join(part.rstrip(". ") for part in parts if part) + "."
    if len(prompt) > FLOW_IMAGE_PROMPT_HARD_LIMIT:
        raise ValueError("FLOW_IMAGE_PROMPT_TOO_LONG")
    return prompt


def _prompt_sentence(label: str, value: str) -> str:
    return f"{label}: {value.strip().rstrip('. ')}."


def compile_ambient_image_prompt(
    brief: dict[str, Any], policy: dict[str, Any], *, style_directive: str,
) -> str:
    """Compile prioritized visual intent without concatenating narration summaries.

    P5 optional detail is removed first. Required identity, environment,
    continuity, provider-safe-area, style, and negative constraints are never
    sliced or removed merely to meet the provider limit.
    """
    validate_visual_policy(policy)
    required_fields = ("visual_anchor", "dominant_subject", "dominant_environment", "dominant_state")
    for field in required_fields:
        value = brief.get(field)
        if not isinstance(value, str) or not value.strip():
            raise AmbientVisualBriefBudgetError(field, len(str(value or "")), AMBIENT_IMAGE_PROMPT_INTERNAL_TARGET)
    requirements = brief.get("continuity_requirements", [])
    if not isinstance(requirements, list) or any(not isinstance(item, str) or not item.strip() for item in requirements):
        raise AmbientVisualBriefBudgetError("continuity_requirements", len(str(requirements)), AMBIENT_IMAGE_PROMPT_INTERNAL_TARGET)
    if not isinstance(style_directive, str) or not style_directive.strip():
        raise AmbientVisualBriefBudgetError("style_directive", len(str(style_directive or "")), AMBIENT_IMAGE_PROMPT_INTERNAL_TARGET)

    # P0 identity/action-state, P1 environment/composition, P2 continuity,
    # P3 provider-safe-area, and P4 style/safety are irreducible.
    required = [
        _prompt_sentence("Visual anchor", brief["visual_anchor"]),
        _prompt_sentence("Dominant subject", brief["dominant_subject"]),
        _prompt_sentence("Dominant state", brief["dominant_state"]),
        _prompt_sentence("Environment", brief["dominant_environment"]),
    ]
    composition = brief.get("composition_intent")
    if isinstance(composition, str) and composition.strip():
        required.append(_prompt_sentence("Composition", composition))
    if requirements:
        required.append(_prompt_sentence("Continuity", "; ".join(item.strip().rstrip(". ") for item in requirements)))
    required.extend((
        _FLOW_MARK_SAFE_AREA + ".",
        _prompt_sentence("Ambient style", style_directive),
        "Natural soft realism; practical light, restrained color, natural skin and materials.",
        _ANTI_POLISH,
    ))

    # P5 details are useful but intentionally expendable as complete fields.
    optional: list[tuple[str, str]] = []
    supporting = brief.get("optional_supporting_context")
    if isinstance(supporting, str) and supporting.strip():
        optional.append(("optional_supporting_context", _prompt_sentence("Supporting context", supporting)))
    motif = brief.get("important_object_or_motif")
    if isinstance(motif, str) and motif.strip():
        optional.append(("important_object_or_motif", _prompt_sentence("Motif", motif)))

    def assembled(extra: list[tuple[str, str]]) -> str:
        return " ".join((*required, *(sentence for _, sentence in extra)))

    prompt = assembled(optional)
    while len(prompt) > AMBIENT_IMAGE_PROMPT_INTERNAL_TARGET and optional:
        optional.pop(0)
        prompt = assembled(optional)
    if len(prompt) > AMBIENT_IMAGE_PROMPT_INTERNAL_TARGET:
        candidates = {
            **{field: len(str(brief.get(field, ""))) for field in required_fields},
            "continuity_requirements": len("; ".join(requirements)),
            "style_directive": len(style_directive),
            "required_compiled_prompt": len(prompt),
        }
        field, observed = max(candidates.items(), key=lambda item: item[1])
        raise AmbientVisualBriefBudgetError(field, observed, AMBIENT_IMAGE_PROMPT_INTERNAL_TARGET)
    if len(prompt) > FLOW_IMAGE_PROMPT_HARD_LIMIT:
        raise AmbientVisualBriefBudgetError("compiled_prompt", len(prompt), FLOW_IMAGE_PROMPT_HARD_LIMIT)
    return prompt


def compile_video_prompt(
    *, subject_motion: str, environmental_motion: str, camera_motion: str, timing: str,
) -> str:
    """Compile motion only; the reference image owns appearance and treatment."""
    camera = camera_motion.strip().upper().replace(" ", "_")
    camera_text = _MOTION.get(camera, _MOTION["STATIC"])
    motion = subject_motion.strip()
    motion = re.sub(r"\b(?:famous|renowned|celebrated|respected|prestigious|nationally respected)\b", "", motion, flags=re.I)
    motion = re.sub(r"\s{2,}", " ", motion).strip(" ,;:.\n")
    parts = [
        f"Subject motion: {motion or 'natural minimal movement'}",
        f"Environmental motion: {environmental_motion.strip() or 'only subtle physically plausible movement'}",
        f"Camera motion: {camera_text}",
        f"Timing: {timing.strip()}",
        "Preserve the supplied reference image identity, environment, lighting, palette, and material treatment",
        "Restrained realistic motion; no floating, orbiting, sweeping, morphing, or artificial speed ramps",
        _FLOW_MARK_SAFE_AREA,
    ]
    return ". ".join(part.rstrip(". ") for part in parts) + "."

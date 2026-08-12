"""Provider-local policy for resolving Story Auto intent to Flow settings."""
from __future__ import annotations

from dataclasses import dataclass

from .service import FlowError


@dataclass(frozen=True)
class ResolvedFlowGenerationSettings:
    media_type: str
    workflow_mode: str
    model_preference: str | None
    aspect_ratio: str
    output_count: int
    duration_seconds: float | None
    reference_mode: str | None
    quality_tier: str


def resolve_settings(request: dict, *, execution_tier: str = "STANDARD_PRODUCTION") -> ResolvedFlowGenerationSettings:
    media_type = request.get("media_type")
    if media_type not in {"IMAGE", "VIDEO"}: raise FlowError("FLOW_CAPABILITY_UNAVAILABLE", "unsupported media type")
    references = bool(request.get("depends_on"))
    tier = str(request.get("execution_tier", execution_tier)).upper()
    ratio = str(request.get("aspect_ratio", "16:9"))
    if media_type == "IMAGE":
        output = 1 if tier == "DEV_SMOKE" or request.get("purpose") == "SHOT" else 2
        return ResolvedFlowGenerationSettings("IMAGE", "IMAGE_GENERATION", request.get("model_override") or "Nano Banana 2", ratio, output, None, "INGREDIENTS" if references else None, tier)
    return ResolvedFlowGenerationSettings("VIDEO", "REFERENCE_TO_VIDEO" if references else "TEXT_TO_VIDEO", request.get("model_override"), ratio, int(request.get("output_count", 1)), request.get("target_duration"), "FRAME_OR_INGREDIENT" if references else None, tier)


def select_model(resolved: ResolvedFlowGenerationSettings, available: list[dict]) -> dict:
    """Choose a capability-compatible model without inventing an expensive default."""
    compatible = [m for m in available if resolved.media_type in set(m.get("media_types", []))]
    if not compatible: raise FlowError("FLOW_CAPABILITY_UNAVAILABLE", "no compatible Flow model")
    preferred = next((m for m in compatible if m.get("name") == resolved.model_preference), None)
    if preferred: return preferred
    # UI ordering is Flow's account/capability ordering; first compatible is the
    # least-assumptive fallback and gets recorded in attempt provenance.
    return compatible[0]

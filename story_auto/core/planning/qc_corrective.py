"""Bounded Gemini semantic correction with deterministic request compilation."""
from __future__ import annotations

import json
import re
from typing import Any

from story_auto.core.gemini_qc import compile_flow_motion_prompt, validate_motion_plan
from story_auto.core.visual import (caption_safe_effective_prompt, compile_image_prompt,
                                    default_visual_policy, validate_visual_policy)
from story_auto.providers.llm import GeminiReasoningRouter, ReasoningResult
from story_auto.providers.llm.gemini import LLMMedia


QC_CORRECTIVE_REPLAN_VERSION = "story-auto-qc-corrective-replan/1.0.0"
QC_CORRECTIVE_INTENT_SCHEMA_VERSION = "story-auto-qc-corrective-intent/1.0.0"

QC_CORRECTIVE_INTENT_SCHEMA = {
    "type": "object",
    "required": [
        "subject", "action", "location", "composition_intent",
        "continuity_requirements", "exclusions", "selected_reference_entity_ids",
        "semantic_delta", "reference_selection_rationale",
    ],
    "properties": {
        "subject": {"type": "string"},
        "action": {"type": "string"},
        "location": {"type": "string"},
        "composition_intent": {"type": "string"},
        "continuity_requirements": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "exclusions": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "selected_reference_entity_ids": {"type": "array", "items": {"type": "string"}},
        "semantic_delta": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "reference_selection_rationale": {"type": "string"},
    },
}


class QCCorrectiveReplanError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(failure_class + (f": {detail}" if detail else ""))


def validate_qc_corrective_intent(value: dict[str, Any], *, reference_entity_ids: set[str],
                                  reference_capacity: int | None = None) -> None:
    if not isinstance(value, dict):
        raise QCCorrectiveReplanError("QC_CORRECTIVE_REPLAN_STRUCTURED_OUTPUT_INVALID")
    for field in ("subject", "action", "location", "composition_intent", "reference_selection_rationale"):
        item = value.get(field)
        if not isinstance(item, str) or not item.strip() or len(item) > 600:
            raise QCCorrectiveReplanError("QC_CORRECTIVE_REPLAN_STRUCTURED_OUTPUT_INVALID", field)
    for field in ("continuity_requirements", "exclusions", "semantic_delta"):
        items = value.get(field)
        if (not isinstance(items, list) or not items or len(items) > 12
                or any(not isinstance(item, str) or not item.strip() or len(item) > 400 for item in items)):
            raise QCCorrectiveReplanError("QC_CORRECTIVE_REPLAN_STRUCTURED_OUTPUT_INVALID", field)
    selected = value.get("selected_reference_entity_ids")
    if (not isinstance(selected, list) or len(selected) != len(set(selected))
            or any(not isinstance(item, str) or item not in reference_entity_ids for item in selected)):
        raise QCCorrectiveReplanError("QC_CORRECTIVE_REPLAN_REFERENCE_SELECTION_INVALID")
    if reference_capacity is not None and (
            not isinstance(reference_capacity, int) or reference_capacity < 0
            or len(selected) > reference_capacity):
        raise QCCorrectiveReplanError("QC_CORRECTIVE_REPLAN_REFERENCE_CAPACITY_INVALID")


def plan_qc_corrective_intent(
    router: GeminiReasoningRouter,
    *,
    canonical_context: dict[str, Any],
    reference_entity_ids: set[str],
    reference_capacity: int,
    reference_media: tuple[LLMMedia, ...] = (),
) -> tuple[dict[str, Any], ReasoningResult]:
    """Ask the established router for structured semantics, never a provider side effect."""
    prompt = (
        "Correct one terminal QC-rejected SHOT generation intent (IMAGE or VIDEO). Use only the supplied canonical sources. "
        "Repair the latest QC contradiction materially; do not merely paraphrase the rejected prompt. "
        "Choose only reference entity IDs whose visual context supports the corrected continuity, and remove "
        "any conflicting reference. State exclusions that make the rejected relocation or contradiction impossible. "
        "When labeled candidate reference media is supplied, assess the actual visual context of each image as "
        "well as its canonical text evidence. Return structured JSON only. Canonical context:\n"
        + json.dumps(canonical_context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )

    def accept(value: dict[str, Any]) -> None:
        validate_qc_corrective_intent(
            value, reference_entity_ids=reference_entity_ids, reference_capacity=reference_capacity)

    result = router.reason(
        task="qc_corrective_replan",
        prompt=prompt,
        schema=QC_CORRECTIVE_INTENT_SCHEMA,
        tier="HARD",
        media=reference_media,
        prompt_version=QC_CORRECTIVE_REPLAN_VERSION,
        schema_version=QC_CORRECTIVE_INTENT_SCHEMA_VERSION,
        qc_policy_version="DETERMINISTIC_GENERATION_COMPILER",
        acceptance_validator=accept,
    )
    validate_qc_corrective_intent(
        result.value, reference_entity_ids=reference_entity_ids, reference_capacity=reference_capacity)
    return result.value, result


def compile_qc_corrected_image_request(
    prior_request: dict[str, Any],
    corrected_intent: dict[str, Any],
    *,
    reference_request_by_entity: dict[str, str],
) -> dict[str, Any]:
    """Compile structured correction through the existing provider-safe IMAGE compiler."""
    if prior_request.get("purpose") != "SHOT" or prior_request.get("media_type") != "IMAGE":
        raise QCCorrectiveReplanError("QC_CORRECTIVE_REPLAN_MEDIA_UNSUPPORTED")
    validate_qc_corrective_intent(corrected_intent, reference_entity_ids=set(reference_request_by_entity))
    visual_policy = prior_request.get("visual_policy")
    if visual_policy is None:
        visual_policy = default_visual_policy()
    try:
        validate_visual_policy(visual_policy)
    except ValueError as error:
        raise QCCorrectiveReplanError("QC_CORRECTIVE_REPLAN_VISUAL_POLICY_INVALID") from error
    selected_entities = list(corrected_intent["selected_reference_entity_ids"])
    continuity = "; ".join(item.strip() for item in corrected_intent["continuity_requirements"])
    exclusions = "; ".join(item.strip() for item in corrected_intent["exclusions"])
    semantic_intent = (
        f"Subject: {corrected_intent['subject'].strip()}. "
        f"Action: {corrected_intent['action'].strip()}. "
        f"Location: {corrected_intent['location'].strip()}. "
        f"Composition: {corrected_intent['composition_intent'].strip()}. "
        f"Exclude: {exclusions}"
    )
    try:
        prompt = compile_image_prompt(semantic_intent, visual_policy, continuity=continuity)
    except ValueError as error:
        raise QCCorrectiveReplanError(str(error)) from error
    rewritten = dict(prior_request)
    rewritten.update({
        "prompt": prompt,
        "visual_policy": visual_policy,
        "reference_asset_ids": selected_entities,
        "depends_on": [reference_request_by_entity[item] for item in selected_entities],
        "corrected_semantic_intent": dict(corrected_intent),
    })
    return rewritten


def _motion_words(value: str) -> set[str]:
    return {item for item in re.findall(r"[a-z0-9]+", value.lower()) if len(item) > 2}


def compile_qc_corrected_video_request(
    prior_request: dict[str, Any],
    corrected_intent: dict[str, Any],
    *,
    reference_request_by_entity: dict[str, str],
) -> dict[str, Any]:
    """Keep approved atomic mechanics while correcting VIDEO continuity semantics."""
    if prior_request.get("purpose") != "SHOT" or prior_request.get("media_type") != "VIDEO":
        raise QCCorrectiveReplanError("QC_CORRECTIVE_REPLAN_MEDIA_UNSUPPORTED")
    validate_qc_corrective_intent(corrected_intent, reference_entity_ids=set(reference_request_by_entity))
    evidence = prior_request.get("motion_risk_analysis")
    clip = evidence.get("atomic_clip") if isinstance(evidence, dict) else None
    required = ("schema_version", "source_request_id", "physical_complexity", "anatomy_risk", "looping_risk",
                "interaction_objects", "hand_object_contact", "atomic_clip")
    if (not isinstance(evidence, dict) or any(field not in evidence for field in required)
            or not isinstance(clip, dict)):
        raise QCCorrectiveReplanError("QC_CORRECTIVE_REPLAN_VIDEO_MOTION_EVIDENCE_INVALID")
    try:
        validate_motion_plan({"atomic_clips": [clip]}, original_action=str(clip.get("action", "")))
        duration = float(prior_request.get("target_duration", 0))
        if duration <= 0:
            raise ValueError("invalid duration")
    except (ValueError, TypeError) as error:
        raise QCCorrectiveReplanError("QC_CORRECTIVE_REPLAN_VIDEO_MOTION_EVIDENCE_INVALID") from error
    if not (_motion_words(str(clip.get("action", ""))) & _motion_words(corrected_intent["action"])):
        raise QCCorrectiveReplanError("QC_CORRECTIVE_REPLAN_VIDEO_MOTION_NOT_APPLICABLE")
    selected_entities = list(corrected_intent["selected_reference_entity_ids"])
    continuity = "; ".join(item.strip() for item in corrected_intent["continuity_requirements"])
    exclusions = "; ".join(item.strip() for item in corrected_intent["exclusions"])
    base = compile_flow_motion_prompt(
        subject=corrected_intent["subject"], location=corrected_intent["location"], clip=clip, duration=duration,
    ).rstrip(". ")
    prompt = caption_safe_effective_prompt(
        f"{base}. Corrective continuity: Location: {corrected_intent['location'].strip()}. "
        f"Direct continuation: {continuity}. Required semantic action: {corrected_intent['action'].strip()}. "
        f"Exclude: {exclusions}."
    )
    rewritten = dict(prior_request)
    rewritten.update({
        "prompt": prompt,
        "reference_asset_ids": selected_entities,
        "depends_on": [reference_request_by_entity[item] for item in selected_entities],
        "corrected_semantic_intent": dict(corrected_intent),
        "motion_risk_analysis": dict(evidence),
        "corrective_motion_evidence": {
            "preserved_from_request_id": prior_request["request_id"],
            "temporal_qc": "APPROVED",
            "scope": "CONTINUITY_ONLY",
        },
    })
    return rewritten


def compile_qc_corrected_request(
    prior_request: dict[str, Any],
    corrected_intent: dict[str, Any],
    *,
    reference_request_by_entity: dict[str, str],
) -> dict[str, Any]:
    if prior_request.get("media_type") == "IMAGE":
        return compile_qc_corrected_image_request(
            prior_request, corrected_intent, reference_request_by_entity=reference_request_by_entity)
    if prior_request.get("media_type") == "VIDEO":
        return compile_qc_corrected_video_request(
            prior_request, corrected_intent, reference_request_by_entity=reference_request_by_entity)
    raise QCCorrectiveReplanError("QC_CORRECTIVE_REPLAN_MEDIA_UNSUPPORTED")

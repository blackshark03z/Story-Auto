"""Deterministic two-stage narrative-state planning for Ambient Story."""

from __future__ import annotations

import re
from typing import Any


AMBIENT_VISUAL_BRIEF_LIMITS = {
    "visual_anchor": 220,
    "dominant_subject": 120,
    "dominant_environment": 140,
    "dominant_state": 140,
    "important_object_or_motif": 100,
    "composition_intent": 140,
    "optional_supporting_context": 180,
    "continuity_requirement": 140,
}

_FUNCTION_PATTERNS = (
    ("CONFRONTATION", ("confrontation", "confronts", "dismissed the charges", "refused", "defied", "tore", "tearing")),
    ("RETIREMENT_DEATH", ("retirement", "retired", "withdrew", "withdrawal", "self-imposed exile", "died", "death", "final years")),
    ("ACCUSATION", ("accusation", "accused", "charges", "trial", "investigation", "betrayal", "allegation")),
    ("REVEAL", ("reveal", "revealed", "discovery", "hidden mastery", "truth emerged", "identity exposed")),
    ("SCRUTINY", ("suspicion", "scrutiny", "distrust", "political concern", "politically alarming", "feared", "fear of", "individual dominance")),
    ("ACCOMPLISHMENT", ("victory", "victorious", "defeated", "triumphed", "secured", "saved", "success", "mastered", "accomplishment")),
    ("CONSEQUENCE", ("consequence", "aftermath", "punishment", "response", "falling action", "recognition")),
    ("LEGACY_ANALYSIS", ("thematic analysis", "thematic synthesis", "historical reflection", "legacy", "later generations", "later generals", "historical meaning", "constitutional", "republican norms")),
    ("RISING_ACTION", ("backstory", "rising action", "origin", "early career", "began", "stepped up", "escalation", "bold plan")),
    ("INCIDENT", ("incident", "opening conflict", "arrival", "disruption")),
)

_STATE_LABELS = {
    "INCIDENT": "an opening disruption establishes the central tension",
    "RISING_ACTION": "the protagonist advances through mounting stakes",
    "ACCOMPLISHMENT": "a decisive accomplishment changes the balance of power",
    "SCRUTINY": "the protagonist remains under institutional scrutiny",
    "ACCUSATION": "public accusation and political pressure define the moment",
    "CONFRONTATION": "the protagonist openly confronts opposing authority",
    "REVEAL": "a previously hidden truth or capability becomes visible",
    "CONSEQUENCE": "the consequences of the central conflict settle in",
    "RETIREMENT_DEATH": "withdrawal, retirement, or death closes an active life chapter",
    "LEGACY_ANALYSIS": "the story reflects on legacy, institutions, and later consequences",
    "CLOSURE": "a restrained final image carries the story's closing judgment",
}

_ENVIRONMENT_DEFAULTS = {
    "INCIDENT": "a restrained setting consistent with the opening conflict",
    "RISING_ACTION": "a grounded environment associated with the protagonist's ascent",
    "ACCOMPLISHMENT": "the concrete environment of the decisive accomplishment",
    "SCRUTINY": "a restrained civic or institutional setting",
    "ACCUSATION": "a restrained civic or institutional setting",
    "CONFRONTATION": "the concrete environment of the confrontation",
    "REVEAL": "a grounded human-scale setting where the reveal is legible",
    "CONSEQUENCE": "a quiet environment shaped by the prior conflict",
    "RETIREMENT_DEATH": "a quiet private setting associated with withdrawal",
    "LEGACY_ANALYSIS": "a timeless restrained setting suitable for historical reflection",
    "CLOSURE": "a quiet restrained setting suitable for closure",
}

_MOTIF_DEFAULTS = {
    "SCRUTINY": "records or civic symbols",
    "ACCUSATION": "records or evidence",
    "ACCOMPLISHMENT": "one restrained symbol of achievement",
    "RETIREMENT_DEATH": "one object associated with departure",
    "LEGACY_ANALYSIS": "one restrained institutional motif",
    "CLOSURE": "one recurring motif from the story",
}

_DIRECT_FUNCTIONS = frozenset({"ACCOMPLISHMENT", "CONFRONTATION", "REVEAL", "RETIREMENT_DEATH"})
_GENERIC_ENTITY_TOKENS = frozenset({
    "office", "workshop", "estate", "battlefield", "house", "forum", "room",
    "roman", "institutional", "financial", "account", "story", "central",
})


class AmbientPlanningPolicyError(ValueError):
    """Typed policy failure mapped to the public planning error by the service."""

    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        self.detail = detail
        super().__init__(failure_class + (f": {detail}" if detail else ""))


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" ,;:.\n")


def _bounded_words(value: Any, limit: int) -> str:
    """Keep complete words only; visual fields never inherit unbounded prose."""
    text = _clean(value)
    if len(text) <= limit:
        return text
    words: list[str] = []
    for word in text.split():
        candidate = " ".join((*words, word))
        if len(candidate) > limit:
            break
        words.append(word)
    return " ".join(words).rstrip(" ,;:.")


def _narrative_function(scene: dict[str, Any], index: int, count: int) -> str:
    role = _clean(scene.get("story_role")).lower()
    summary = _clean(scene.get("summary")).lower()
    text = f"{role} {summary}"
    if role in {"conclusion", "closure", "epilogue", "resolution"} or index == count - 1 and "conclusion" in role:
        return "CLOSURE"
    if any(term in role for term in ("thematic analysis", "historical reflection", "thematic synthesis")):
        return "LEGACY_ANALYSIS"
    patterns = dict(_FUNCTION_PATTERNS)
    for function in ("CONFRONTATION", "RETIREMENT_DEATH", "ACCUSATION", "REVEAL"):
        if any(term in text for term in patterns[function]):
            return function
    if "climax" in role:
        return "ACCOMPLISHMENT"
    if any(term in text for term in patterns["SCRUTINY"]):
        return "SCRUTINY"
    if any(term in role for term in ("backstory", "rising action")):
        return "RISING_ACTION"
    for function, terms in _FUNCTION_PATTERNS[5:]:
        if any(term in text for term in terms):
            return function
    if any(term in role for term in ("thematic", "analysis", "reflection", "synthesis")):
        return "LEGACY_ANALYSIS"
    if index == 0:
        return "INCIDENT"
    if index == count - 1:
        return "CLOSURE"
    return "RISING_ACTION"


def _entity_lookup(continuity: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    entities: dict[str, dict[str, Any]] = {}
    kinds: dict[str, str] = {}
    for kind in ("characters", "locations", "props"):
        for entity in continuity.get(kind, []):
            if isinstance(entity, dict) and isinstance(entity.get("entity_id"), str):
                entities[entity["entity_id"]] = entity
                kinds[entity["entity_id"]] = kind[:-1]
    return entities, kinds


def _entity_is_mentioned(entity: dict[str, Any], text: str) -> bool:
    name = _clean(entity.get("name")).lower()
    if name and name in text:
        return True
    tokens = [token for token in re.findall(r"[a-z0-9]+", name) if len(token) >= 5 and token not in _GENERIC_ENTITY_TOKENS]
    return any(re.search(rf"\b{re.escape(token)}\b", text) for token in tokens)


def _scene_entity_ids(scene: dict[str, Any], continuity: dict[str, Any]) -> list[str]:
    entities, _ = _entity_lookup(continuity)
    explicit = [item for item in scene.get("entity_ids", []) if item in entities]
    text = _clean(f"{scene.get('story_role', '')} {scene.get('summary', '')} {scene.get('narration_text', '')}").lower()
    inferred = [entity_id for entity_id, entity in entities.items() if _entity_is_mentioned(entity, text)]
    return list(dict.fromkeys((*explicit, *inferred)))


def _constraint_text(entity: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for constraint in entity.get("constraints", []):
        concise = _bounded_words(constraint, AMBIENT_VISUAL_BRIEF_LIMITS["continuity_requirement"])
        if concise:
            values.append(concise)
    design = entity.get("visual_design")
    if isinstance(design, dict) and design:
        concise = _bounded_words(
            "; ".join(f"{_clean(key)}: {_clean(value)}" for key, value in sorted(design.items())),
            AMBIENT_VISUAL_BRIEF_LIMITS["continuity_requirement"],
        )
        if concise:
            values.append(concise)
    return values


def _candidate(scene: dict[str, Any], index: int, count: int, continuity: dict[str, Any]) -> dict[str, Any]:
    entities, kinds = _entity_lookup(continuity)
    entity_ids = _scene_entity_ids(scene, continuity)
    character_ids = [item for item in entity_ids if kinds.get(item) == "character"]
    location_ids = [item for item in entity_ids if kinds.get(item) == "location"]
    prop_ids = [item for item in entity_ids if kinds.get(item) == "prop"]
    function = _narrative_function(scene, index, count)
    subject_names = [_clean(entities[item].get("name")) for item in character_ids[:1]]
    dominant_subject = _bounded_words(subject_names[0] if subject_names else "the central protagonist", AMBIENT_VISUAL_BRIEF_LIMITS["dominant_subject"])
    environment = _bounded_words(
        entities[location_ids[0]].get("name") if location_ids else _ENVIRONMENT_DEFAULTS[function],
        AMBIENT_VISUAL_BRIEF_LIMITS["dominant_environment"],
    )
    dominant_state = _bounded_words(_STATE_LABELS[function], AMBIENT_VISUAL_BRIEF_LIMITS["dominant_state"])
    motif = _bounded_words(
        entities[prop_ids[0]].get("name") if prop_ids else _MOTIF_DEFAULTS.get(function, ""),
        AMBIENT_VISUAL_BRIEF_LIMITS["important_object_or_motif"],
    )
    anchor = _bounded_words(
        f"{dominant_subject} in {environment}, {dominant_state}",
        AMBIENT_VISUAL_BRIEF_LIMITS["visual_anchor"],
    )
    requirements: list[str] = []
    for entity_id in (*character_ids[:2], *location_ids[:1], *prop_ids[:1]):
        requirements.extend(_constraint_text(entities[entity_id]))
    requirements = list(dict.fromkeys(requirements))[:2]
    anchor_kind = "DIRECT" if function in _DIRECT_FUNCTIONS else "SUPPORTIVE"
    return {
        "source_scene_ids": [scene["scene_id"]],
        "start": float(scene["start"]),
        "end": float(scene["end"]),
        "narration_segment_ids": list(scene["narration_segment_ids"]),
        "narrative_function": function,
        "narrative_summary": _clean(scene.get("summary")),
        "visual_anchor": anchor,
        "visual_anchor_kind": anchor_kind,
        "dominant_subject": dominant_subject,
        "dominant_environment": environment,
        "dominant_state": dominant_state,
        "important_object_or_motif": motif,
        "continuity_requirements": requirements,
        "composition_intent": "clear subject hierarchy with restrained negative space for readable subtitles",
        "optional_supporting_context": "",
        "character_ids": character_ids,
        "location_ids": location_ids,
        "prop_ids": prop_ids,
        "change_reason": "opening narrative state" if index == 0 else f"narrative function changes to {function}",
        "long_anchor_justification": None,
    }


def _compatible(left: dict[str, Any], right: dict[str, Any]) -> bool:
    compatible_functions = (
        left["narrative_function"] == right["narrative_function"]
        or {left["narrative_function"], right["narrative_function"]} <= {"SCRUTINY", "ACCUSATION"}
    )
    if not compatible_functions:
        return False
    same_subject = left["dominant_subject"] == right["dominant_subject"]
    same_motif = bool(left["important_object_or_motif"] and left["important_object_or_motif"] == right["important_object_or_motif"])
    if not (same_subject or same_motif):
        return False
    if left["dominant_environment"] == right["dominant_environment"]:
        return True
    return left["visual_anchor_kind"] == right["visual_anchor_kind"] == "SUPPORTIVE"


def _merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    merged["source_scene_ids"] = left["source_scene_ids"] + right["source_scene_ids"]
    merged["end"] = right["end"]
    merged["narration_segment_ids"] = left["narration_segment_ids"] + right["narration_segment_ids"]
    merged["narrative_summary"] = "; ".join(filter(None, (left["narrative_summary"], right["narrative_summary"])))
    if {left["narrative_function"], right["narrative_function"]} <= {"SCRUTINY", "ACCUSATION"}:
        merged["narrative_function"] = "SCRUTINY"
        merged["dominant_state"] = _STATE_LABELS["SCRUTINY"]
    merged["character_ids"] = list(dict.fromkeys(left["character_ids"] + right["character_ids"]))
    merged["location_ids"] = list(dict.fromkeys(left["location_ids"] + right["location_ids"]))
    merged["prop_ids"] = list(dict.fromkeys(left["prop_ids"] + right["prop_ids"]))
    merged["continuity_requirements"] = list(dict.fromkeys(left["continuity_requirements"] + right["continuity_requirements"]))[:2]
    merged["visual_anchor_kind"] = "SUPPORTIVE" if "SUPPORTIVE" in {left["visual_anchor_kind"], right["visual_anchor_kind"]} else "DIRECT"
    merged["long_anchor_justification"] = (
        f"One {merged['visual_anchor_kind'].lower()} premise-level anchor remains truthful across adjacent "
        f"{merged['narrative_function'].lower().replace('_', ' ')} states sharing {merged['dominant_subject']}; "
        "it does not claim to depict every narrated event."
    )
    merged["optional_supporting_context"] = _bounded_words(
        merged["long_anchor_justification"], AMBIENT_VISUAL_BRIEF_LIMITS["optional_supporting_context"]
    )
    merged["visual_anchor"] = _bounded_words(
        f"{merged['dominant_subject']} in {merged['dominant_environment']}, {merged['dominant_state']}",
        AMBIENT_VISUAL_BRIEF_LIMITS["visual_anchor"],
    )
    return merged


def validate_visual_brief(brief: dict[str, Any]) -> None:
    if not isinstance(brief, dict):
        raise AmbientPlanningPolicyError("AMBIENT_VISUAL_BRIEF_INVALID", "visual brief must be an object")
    required = ("visual_anchor", "dominant_subject", "dominant_environment", "dominant_state", "composition_intent")
    for field in required:
        value = brief.get(field)
        limit = AMBIENT_VISUAL_BRIEF_LIMITS[field]
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise AmbientPlanningPolicyError("AMBIENT_VISUAL_BRIEF_INVALID", f"{field} must be 1..{limit} characters")
    for field in ("important_object_or_motif", "optional_supporting_context"):
        value = brief.get(field, "")
        if not isinstance(value, str) or len(value) > AMBIENT_VISUAL_BRIEF_LIMITS[field]:
            raise AmbientPlanningPolicyError("AMBIENT_VISUAL_BRIEF_INVALID", f"{field} exceeds its concise field contract")
    requirements = brief.get("continuity_requirements", [])
    if not isinstance(requirements, list) or len(requirements) > 2 or any(
        not isinstance(item, str) or not item.strip() or len(item) > AMBIENT_VISUAL_BRIEF_LIMITS["continuity_requirement"]
        for item in requirements
    ):
        raise AmbientPlanningPolicyError("AMBIENT_VISUAL_BRIEF_INVALID", "continuity_requirements must contain at most two concise strings")
    if brief.get("visual_anchor_kind") not in {"DIRECT", "SUPPORTIVE", "ATMOSPHERIC"}:
        raise AmbientPlanningPolicyError("AMBIENT_VISUAL_BRIEF_INVALID", "visual_anchor_kind is invalid")


def reference_visual_brief(entity: dict[str, Any], kind: str) -> dict[str, Any]:
    """Create a concise continuity-reference brief from one durable entity."""
    name = _bounded_words(entity.get("name") or f"canonical {kind}", AMBIENT_VISUAL_BRIEF_LIMITS["dominant_subject"])
    requirements = _constraint_text(entity)[:2]
    brief = {
        "visual_anchor": _bounded_words(f"canonical continuity reference for {name}", AMBIENT_VISUAL_BRIEF_LIMITS["visual_anchor"]),
        "visual_anchor_kind": "DIRECT",
        "dominant_subject": name,
        "dominant_environment": "a neutral grounded reference setting that does not invent story events",
        "dominant_state": "stable canonical appearance and material identity",
        "important_object_or_motif": name if kind == "prop" else "",
        "continuity_requirements": requirements,
        "composition_intent": "single clear reference subject with readable identity and restrained context",
        "optional_supporting_context": "",
    }
    validate_visual_brief(brief)
    return brief


def plan_visual_chapters(
    timeline: dict[str, Any], continuity: dict[str, Any], *, preferred_min: int, preferred_max: int, hard_max: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Identify narrative states first, then merge only compatible visual anchors."""
    scenes = timeline.get("scenes", [])
    candidates = [_candidate(scene, index, len(scenes), continuity) for index, scene in enumerate(scenes)]
    chapters: list[dict[str, Any]] = []
    for candidate in candidates:
        if chapters and _compatible(chapters[-1], candidate):
            chapters[-1] = _merge(chapters[-1], candidate)
        else:
            chapters.append(candidate)
    if len(chapters) > hard_max:
        raise AmbientPlanningPolicyError(
            "AMBIENT_CHAPTER_HARD_MAX_EXCEEDED",
            f"{len(chapters)} incompatible visual states exceed hard_max={hard_max}",
        )
    for chapter in chapters:
        validate_visual_brief(chapter)
    if len(chapters) > preferred_max:
        exception = "SEMANTIC_STATE_INCOMPATIBILITY"
    elif len(chapters) < preferred_min:
        exception = "COMPATIBLE_STATE_CONSOLIDATION"
    else:
        exception = None
    budget = {
        "preferred_min": preferred_min,
        "preferred_max": preferred_max,
        "hard_max": hard_max,
        "planned_images": len(chapters),
        "budget_exception_reason": exception,
    }
    return chapters, budget

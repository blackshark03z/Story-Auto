"""Gemini-assisted planning and QC with deterministic production gates."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from story_auto.core.artifacts import atomic_write_json, sha256_file
from story_auto.providers.llm import GeminiReasoningRouter, LLMMedia, ReasoningResult

HOOK_PLAN_VERSION = "story-auto-hook-plan/1.0.0"
MOTION_PLAN_VERSION = "story-auto-motion-plan/1.2.0"
TEMPORAL_QC_VERSION = "story-auto-temporal-video-qc/1.1.0"
REPAIR_PLAN_VERSION = "story-auto-repair-plan/1.0.0"
FLOW_MOTION_PROMPT_VERSION = "story-auto-flow-motion-prompt/1.1.0"

HIGH_RISK_TERMS = ("door", "handle", "pick up", "put down", "tool", "piano", "instrument",
                   "finger", "sit", "stand", "pass", "hand", "stairs", "ladder")
TEMPORAL_REJECTS = {"REJECT_ACTION_LOGIC", "REJECT_ANATOMY", "REJECT_LOOP",
                    "REJECT_IDENTITY", "REJECT_BACKGROUND"}
TERMINAL_TEMPORAL_FAILURES = TEMPORAL_REJECTS | {"USABLE_TEMPORAL_WINDOW_INVALID"}

HOOK_SCHEMA = {"type": "object", "required": ["beats"], "properties": {"beats": {"type": "array", "minItems": 2, "items": {
    "type": "object", "required": ["start", "end", "new_information", "active_subject", "action", "location",
    "important_props", "visual_function", "emotional_function", "similarity_to_previous", "repetition_risk"],
    "properties": {"start": {"type": "number"}, "end": {"type": "number"}, "new_information": {"type": "string"},
    "active_subject": {"type": "string"}, "action": {"type": "string"}, "location": {"type": "string"},
    "important_props": {"type": "array", "items": {"type": "string"}}, "visual_function": {"type": "string"},
    "emotional_function": {"type": "string"}, "similarity_to_previous": {"type": "number"},
    "repetition_risk": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]}}}}}}

MOTION_CONTRACT_FIELDS = ("direction_sensitive", "ordered_action_steps", "progression_checkpoints",
                          "movement_direction", "forbidden_motion")

MOTION_SCHEMA = {"type": "object", "required": ["start_state", "end_state", "meaningful_actions", "interaction_objects",
    "hand_object_contact", "action_dependencies", "physical_complexity", "anatomy_risk", "looping_risk", "atomic_clips"],
    "properties": {"start_state": {"type": "string"}, "end_state": {"type": "string"},
    "meaningful_actions": {"type": "array", "items": {"type": "string"}},
    "interaction_objects": {"type": "array", "items": {"type": "string"}}, "hand_object_contact": {"type": "string"},
    "action_dependencies": {"type": "array", "items": {"type": "string"}},
    "physical_complexity": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
    "anatomy_risk": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
    "looping_risk": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
    "atomic_clips": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["start_state", "action", "end_state", "natural_stillness"],
        "properties": {"start_state": {"type": "string"}, "action": {"type": "string"}, "end_state": {"type": "string"}, "natural_stillness": {"type": "string"},
            "direction_sensitive": {"type": "boolean"}, "ordered_action_steps": {"type": "array", "items": {"type": "string"}},
            "progression_checkpoints": {"type": "array", "items": {"type": "string"}}, "movement_direction": {"type": "string"},
            "forbidden_motion": {"type": "array", "items": {"type": "string"}}}}}}}

SEMANTIC_SCHEMA = {"type": "object", "required": ["classification", "confidence", "observed", "contradictions"], "properties": {
    "classification": {"type": "string", "enum": ["PASS_DIRECT", "PASS_SUPPORTIVE", "PASS_ATMOSPHERIC", "FAIL_MISMATCH", "UNCERTAIN"]},
    "confidence": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW", "UNCERTAIN"]},
    "observed": {"type": "string"}, "contradictions": {"type": "array", "items": {"type": "string"}}}}

_TEMPORAL_DIMENSIONS = ("ACTION_CAUSALITY", "ORDERED_ACTION_SEQUENCE", "MOVEMENT_DIRECTION", "CHECKPOINT_PROGRESSION",
    "CAUSAL_CONTACT_ORDER", "LIMB_INTEGRITY", "HAND_OBJECT_CONTACT", "OBJECT_STATE_CONTINUITY", "ACTION_LOOPING",
    "MOTION_NATURALNESS", "START_END_STATE_LOGIC", "IDENTITY_STABILITY", "BACKGROUND_STABILITY", "PROP_STABILITY")
TEMPORAL_SCHEMA = {"type": "object", "required": ["state", "confidence", "dimensions", "defects", "usable_start", "usable_end"], "properties": {
    "state": {"type": "string", "enum": ["PASS_TEMPORAL", "PASS_WITH_USABLE_WINDOW", "REJECT_ACTION_LOGIC", "REJECT_ANATOMY", "REJECT_LOOP", "REJECT_IDENTITY", "REJECT_BACKGROUND", "UNCERTAIN"]},
    "confidence": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW", "UNCERTAIN"]},
    "dimensions": {"type": "object", "required": list(_TEMPORAL_DIMENSIONS),
        "properties": {name: {"type": "string", "enum": ["PASS", "MINOR", "MAJOR", "SEVERE", "UNCERTAIN"]} for name in _TEMPORAL_DIMENSIONS}},
    "defects": {"type": "array", "items": {"type": "object", "required": ["class", "severity", "start", "end", "evidence"],
        "properties": {"class": {"type": "string"}, "severity": {"type": "string", "enum": ["MINOR", "MAJOR", "SEVERE"]},
        "start": {"type": "number"}, "end": {"type": "number"}, "evidence": {"type": "string"}}}},
    "usable_start": {"type": "number"}, "usable_end": {"type": "number"}}}

REPAIR_SCHEMA = {"type": "object", "required": ["probable_cause", "revised_atomic_action", "revised_start_state", "revised_end_state",
    "motion_constraints", "recommended_decomposition", "regeneration_needed", "usable_window_suffices", "material_repair_rationale"], "properties": {
    "probable_cause": {"type": "string"}, "revised_atomic_action": {"type": "string"}, "revised_start_state": {"type": "string"},
    "revised_end_state": {"type": "string"}, "motion_constraints": {"type": "array", "items": {"type": "string"}},
    "recommended_decomposition": {"type": "array", "items": {"type": "string"}}, "regeneration_needed": {"type": "boolean"},
    "usable_window_suffices": {"type": "boolean"}, "material_repair_rationale": {"type": "string"}}}


class GeminiQCError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(failure_class + (f": {detail}" if detail else ""))


def _words(value: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", value.lower()) if len(x) > 2}


def validate_hook_plan(plan: dict[str, Any], *, start: float, end: float, max_similarity: float = .72,
                       max_beat_seconds: float = 8.1) -> None:
    beats = plan.get("beats", [])
    if not beats or abs(float(beats[0]["start"]) - start) > .05 or abs(float(beats[-1]["end"]) - end) > .05:
        raise GeminiQCError("HOOK_PLAN_TIMELINE_INVALID")
    previous_end, prior = start, None
    for beat in beats:
        if (abs(float(beat["start"]) - previous_end) > .05 or float(beat["end"]) <= float(beat["start"]) or
                float(beat["end"]) - float(beat["start"]) > max_beat_seconds):
            raise GeminiQCError("HOOK_PLAN_TIMELINE_INVALID")
        signature = _words(" ".join(str(beat.get(k, "")) for k in ("new_information", "active_subject", "action", "visual_function")))
        if prior is not None:
            similarity = len(signature & prior) / max(1, len(signature | prior))
            if similarity > max_similarity or str(beat.get("repetition_risk")).upper() == "HIGH":
                raise GeminiQCError("HOOK_SEMANTIC_REPETITION", f"adjacent similarity {similarity:.3f}")
        prior, previous_end = signature, float(beat["end"])


def plan_hook(router: GeminiReasoningRouter, *, narration: str, start: float, end: float) -> tuple[dict[str, Any], ReasoningResult]:
    prompt = f"""Plan the opening visual beats from {start:.3f} to {end:.3f} seconds. Each beat must be no longer than 8.0 seconds. New story information per visual beat is mandatory. Camera-angle changes do not count as new information. Keep exact contiguous timing. Prefer one atomic visible action per video clip and natural stillness. Return structured JSON only. Narration:\n{narration}"""
    result = router.reason(task="hook_planning", prompt=prompt, schema=HOOK_SCHEMA, tier="HARD",
        prompt_version="hook-planner/1.0.0", schema_version=HOOK_PLAN_VERSION)
    validate_hook_plan(result.value, start=start, end=end)
    return result.value, result


ACTION_NONE = "NONE"
_FAMILY_TRAJECTORY = {
    "ASCENT": "ASCENDING", "DESCENT": "DESCENDING", "TOWARD": "TOWARD_TARGET",
    "AWAY": "AWAY_FROM_TARGET", "FROM_TO": "FROM_TO_DESTINATION", "PICK_UP": "UP_AFTER_CONTACT",
    "PUT_DOWN": "DOWN_AFTER_CONTACT", "SIT": "SIT_DOWN", "STAND": "STAND_UP",
    "OPEN": "OPENING", "CLOSE": "CLOSING", "HANDOFF": "TRANSFER_TO_RECIPIENT",
    "CONTACT": "CONTACT_THEN_OBJECT_MOTION", "ENTER": "ENTERING", "EXIT": "EXITING",
    "TURN_MOVE": "TURN_THEN_FORWARD",
}
_TRAJECTORY_PROMPT = {
    "ASCENDING": "progress upward from lower to higher position", "DESCENDING": "progress downward from upper to lower position",
    "TOWARD_TARGET": "move toward the target", "AWAY_FROM_TARGET": "move away from the target",
    "FROM_TO_DESTINATION": "move from the stated origin to the stated destination", "UP_AFTER_CONTACT": "lift only after contact",
    "DOWN_AFTER_CONTACT": "lower only after contact", "SIT_DOWN": "progress from standing to seated",
    "STAND_UP": "progress from seated to standing", "OPENING": "change from closed to open after contact",
    "CLOSING": "change from open to closed after contact", "TRANSFER_TO_RECIPIENT": "transfer only after hand contact",
    "CONTACT_THEN_OBJECT_MOTION": "make contact before object movement", "ENTERING": "progress from outside to inside",
    "EXITING": "progress from inside to outside", "TURN_THEN_FORWARD": "turn before forward movement",
}
_FORBIDDEN_PROMPT = {
    "BACKWARD_MOTION": "backward motion", "DESCENDING": "descending", "ASCENDING": "ascending",
    "REVERSE_DIRECTION": "reverse direction", "OBJECT_BEFORE_CONTACT": "object movement before contact",
    "REVERSE_ORDER": "reverse causal order", "RESET": "resetting progress",
}


def classify_motion_action(action: str) -> str:
    """Return one canonical family for direction- or order-sensitive actions."""
    text = re.sub(r"\s+", " ", action.lower()).strip()
    if not text:
        return ACTION_NONE
    if re.search(r"\b(?:stand|stands|standing) still\b", text):
        return ACTION_NONE
    if re.search(r"\b(?:ascend(?:s|ed|ing)?|ascent|climb(?:s|ed|ing)?|walk(?:s|ed|ing)? up|go(?:es|ing)? up|move(?:s|d|ing)? up)\b", text):
        return "ASCENT"
    if re.search(r"\b(?:descend(?:s|ed|ing)?|descent|walk(?:s|ed|ing)? down|go(?:es|ing)? down|move(?:s|d|ing)? down)\b", text):
        return "DESCENT"
    if re.search(r"\b(?:pick(?:s|ed|ing)? up|pickup)\b", text):
        return "PICK_UP"
    if re.search(r"\b(?:put(?:s|ting)? down|place(?:s|d|ing)? down)\b", text):
        return "PUT_DOWN"
    if re.search(r"\b(?:sit|sits|sat|sitting)\b", text):
        return "SIT"
    if re.search(r"\b(?:stand|stands|stood|standing)\b", text):
        return "STAND"
    if re.search(r"\b(?:enter|enters|entered|entering)\b", text):
        return "ENTER"
    if re.search(r"\b(?:exit|exits|exited|exiting|leave|leaves|leaving)\b", text):
        return "EXIT"
    if re.search(r"\b(?:open|opens|opened|opening)\b", text):
        return "OPEN"
    if re.search(r"\b(?:close|closes|closed|closing)\b", text):
        return "CLOSE"
    if re.search(r"\b(?:pass|passes|passed|passing|give|gives|gave|giving)\b|\bhand(?:s|ed|ing)?\s+(?:over|to|(?:the|a|an)\s+\w+\s+to)\b", text):
        return "HANDOFF"
    if re.search(r"\b(?:approach|approaches|approached|approaching|reach|reaches|reached|reaching|touch|touches|touched|touching|grasp|grasps|grasped|grasping)\b", text):
        return "CONTACT"
    if re.search(r"\b(?:walk|walks|walked|walking|go|goes|went|going|move|moves|moved|moving|step|steps|stepped|stepping|travel|travels|travelled|traveling)\b.*\bfrom\b.*\bto\b", text):
        return "FROM_TO"
    if re.search(r"\b(?:toward|towards)\b", text):
        return "TOWARD"
    if re.search(r"\baway from\b", text):
        return "AWAY"
    if re.search(r"\bturn(?:s|ed|ing)?\b.*\b(?:then\s+)?(?:walk|go|move|step)(?:s|d|ing)?\b", text):
        return "TURN_MOVE"
    return ACTION_NONE


def is_direction_sensitive(action: str) -> bool:
    return classify_motion_action(action) != ACTION_NONE


def is_high_risk(action: str) -> bool:
    return (is_direction_sensitive(action)
            or bool(re.search(r"\b(?:door|handle|tool|piano|instrument|finger)\b", action.lower())))


def _require_ordered_steps(steps: list[str], expected: tuple[str, ...]) -> None:
    normalized = [item.strip().upper() for item in steps]
    positions = [normalized.index(item) if item in normalized else -1 for item in expected]
    if min(positions) < 0 or positions != sorted(positions):
        raise GeminiQCError("MOTION_ORDERED_ACTION_STEPS_INVALID")


def _require_progression(checkpoints: list[str], *, ascending: bool) -> None:
    normalized = [item.strip().upper() for item in checkpoints]
    canonical = ("LOWER", "MIDDLE", "UPPER")
    positions = [canonical.index(item) if item in canonical else -1 for item in normalized]
    if (len(normalized) < 2 or min(positions) < 0 or normalized[0] != ("LOWER" if ascending else "UPPER")
            or normalized[-1] != ("UPPER" if ascending else "LOWER")
            or positions != sorted(positions, reverse=not ascending)):
        raise GeminiQCError("MOTION_DIRECTIONAL_PROGRESSION_INVALID")


def _validate_directional_contract(clip: dict[str, Any]) -> None:
    """Fail closed when a direction/order-sensitive clip lacks usable structure."""
    action = str(clip.get("action", ""))
    family = classify_motion_action(action)
    declared = clip.get("direction_sensitive")
    has_contract = any(field in clip for field in MOTION_CONTRACT_FIELDS)
    if family == ACTION_NONE and not has_contract:
        return
    if declared is False and all(not clip.get(field) for field in MOTION_CONTRACT_FIELDS if field != "direction_sensitive"):
        if family != ACTION_NONE:
            raise GeminiQCError("MOTION_DIRECTIONAL_CONTRACT_REQUIRED")
        return
    if family == ACTION_NONE:
        raise GeminiQCError("MOTION_DIRECTIONAL_CONTRACT_NOT_APPLICABLE")
    if declared is not True:
        raise GeminiQCError("MOTION_DIRECTIONAL_CONTRACT_REQUIRED")
    steps = clip.get("ordered_action_steps")
    checkpoints = clip.get("progression_checkpoints")
    trajectory = clip.get("movement_direction")
    forbidden = clip.get("forbidden_motion")
    if (not isinstance(steps, list) or not steps or len(steps) > 8
            or any(not isinstance(item, str) or not item.strip() or len(item) > 300 for item in steps)
            or not isinstance(checkpoints, list) or len(checkpoints) < 2 or len(checkpoints) > 8
            or any(not isinstance(item, str) or not item.strip() or len(item) > 300 for item in checkpoints)
            or not isinstance(trajectory, str) or not trajectory.strip() or len(trajectory) > 500
            or not isinstance(forbidden, list) or not forbidden or len(forbidden) > 8
            or any(not isinstance(item, str) or not item.strip() or len(item) > 300 for item in forbidden)):
        raise GeminiQCError("MOTION_DIRECTIONAL_CONTRACT_INVALID")

    expected_trajectory = _FAMILY_TRAJECTORY[family]
    if trajectory.strip().upper() != expected_trajectory:
        raise GeminiQCError("MOTION_DIRECTIONAL_TRAJECTORY_INVALID")
    forbidden_codes = {item.strip().upper() for item in forbidden}
    required_forbidden = {
        "ASCENT": {"BACKWARD_MOTION", "DESCENDING", "REVERSE_DIRECTION"},
        "DESCENT": {"BACKWARD_MOTION", "ASCENDING", "REVERSE_DIRECTION"},
        "PICK_UP": {"OBJECT_BEFORE_CONTACT", "REVERSE_ORDER"},
        "PUT_DOWN": {"OBJECT_BEFORE_CONTACT", "REVERSE_ORDER"},
        "SIT": {"REVERSE_ORDER"}, "STAND": {"REVERSE_ORDER"},
    }.get(family, {"REVERSE_DIRECTION"})
    if not required_forbidden.issubset(forbidden_codes):
        raise GeminiQCError("MOTION_DIRECTIONAL_FORBIDDEN_MOTION_INVALID")
    if family == "ASCENT":
        _require_progression(checkpoints, ascending=True)
    elif family == "DESCENT":
        _require_progression(checkpoints, ascending=False)
    elif family == "PICK_UP":
        _require_ordered_steps(steps, ("APPROACH", "CONTACT", "LIFT"))
    elif family == "PUT_DOWN":
        _require_ordered_steps(steps, ("CONTACT", "LOWER", "RELEASE"))
    elif family == "SIT":
        _require_ordered_steps(steps, ("STANDING", "LOWERING", "SEATED"))
    elif family == "STAND":
        _require_ordered_steps(steps, ("SEATED", "RISING", "STANDING"))
    elif family == "OPEN":
        _require_ordered_steps(steps, ("CONTACT", "OPEN"))
    elif family == "CLOSE":
        _require_ordered_steps(steps, ("CONTACT", "CLOSE"))
    elif family == "CONTACT":
        _require_ordered_steps(steps, ("APPROACH", "CONTACT"))
    elif family == "HANDOFF":
        _require_ordered_steps(steps, ("CONTACT", "TRANSFER"))


def validate_motion_plan(plan: dict[str, Any], *, original_action: str,
                         required_atomic_clip_count: int | None = None) -> None:
    clips = plan.get("atomic_clips", [])
    if not clips: raise GeminiQCError("MOTION_PLAN_INVALID")
    if (required_atomic_clip_count is not None
            and (not isinstance(required_atomic_clip_count, int) or required_atomic_clip_count < 1
                 or len(clips) != required_atomic_clip_count)):
        raise GeminiQCError("MOTION_PLAN_ATOMIC_CLIP_COUNT_INVALID")
    multi_stage = bool(re.search(r"\b(?:and then|then)\b|;", original_action.lower()))
    if is_high_risk(original_action) and (len(plan.get("meaningful_actions", [])) > 1 or multi_stage) and len(clips) < 2:
        raise GeminiQCError("HIGH_RISK_ACTION_NOT_DECOMPOSED")
    for clip in clips:
        _validate_directional_contract(clip)
        if any(word in clip["action"].lower() for word in (" and then ", " then ", ";")):
            raise GeminiQCError("MOTION_ACTION_NOT_ATOMIC")


def plan_motion(router: GeminiReasoningRouter, intent: dict[str, Any]) -> tuple[dict[str, Any], ReasoningResult]:
    required_clip_count = intent.get("required_atomic_clip_count")
    if required_clip_count is not None and (not isinstance(required_clip_count, int) or required_clip_count < 1):
        raise GeminiQCError("MOTION_PLAN_ATOMIC_CLIP_COUNT_INVALID")
    count_instruction = (f" Return exactly {required_clip_count} atomic clip(s); do not split this request."
                         if required_clip_count is not None else "")
    prompt = ("Decompose this production VIDEO intent into physically plausible cinematic states. Default to one meaningful action per generated clip. "
              "Split high-risk contact mechanics with cuts. For direction- or order-sensitive actions, every affected atomic clip must set direction_sensitive=true and provide ordered_action_steps, progression_checkpoints, movement_direction, and forbidden_motion. "
              "movement_direction is a canonical code selected from the action family: ASCENDING, DESCENDING, TOWARD_TARGET, AWAY_FROM_TARGET, FROM_TO_DESTINATION, UP_AFTER_CONTACT, DOWN_AFTER_CONTACT, SIT_DOWN, STAND_UP, OPENING, CLOSING, TRANSFER_TO_RECIPIENT, CONTACT_THEN_OBJECT_MOTION, ENTERING, EXITING, or TURN_THEN_FORWARD. "
              "For stair or ladder ascent use LOWER, MIDDLE, UPPER checkpoints; for descent use UPPER, MIDDLE, LOWER. Use canonical ordered steps such as APPROACH, CONTACT, LIFT and canonical forbidden codes such as BACKWARD_MOTION, REVERSE_DIRECTION, OBJECT_BEFORE_CONTACT, and REVERSE_ORDER. "
              "Treat stair/ladder traversal, entering/exiting, sitting/standing, object pickup/place-down, opening/closing, hand-offs, turns before movement, and explicit toward/away motion as elevated risk. "
              "Use atomic clips when several causal actions cannot be safely executed together. Natural stillness is valid."
              + count_instruction + " Return JSON only. Intent:\n"
              + json.dumps(intent, ensure_ascii=False, sort_keys=True))
    def accept_motion_plan(plan: dict[str, Any]) -> None:
        validate_motion_plan(plan, original_action=str(intent.get("action", "")),
                             required_atomic_clip_count=required_clip_count)
    result = router.reason(task="motion_planning", prompt=prompt, schema=MOTION_SCHEMA, tier="HARD",
        prompt_version="motion-planner/1.2.0", schema_version=MOTION_PLAN_VERSION,
        acceptance_validator=accept_motion_plan)
    validate_motion_plan(result.value, original_action=str(intent.get("action", "")),
                         required_atomic_clip_count=required_clip_count)
    return result.value, result


def compile_flow_motion_prompt(*, subject: str, location: str, clip: dict[str, Any], duration: float) -> str:
    action = re.sub(r"\s+", " ", str(clip["action"])).strip().rstrip(".")
    if not action or len(action) > 240: raise GeminiQCError("FLOW_MOTION_PROMPT_INVALID")
    _validate_directional_contract(clip)
    directional = ""
    if clip.get("direction_sensitive") is True:
        steps = " -> ".join(item.strip() for item in clip["ordered_action_steps"])
        checkpoints = " -> ".join(item.strip() for item in clip["progression_checkpoints"])
        trajectory = _TRAJECTORY_PROMPT[clip["movement_direction"].strip().upper()]
        forbidden = "; ".join(_FORBIDDEN_PROMPT.get(item.strip().upper(), item.strip()) for item in clip["forbidden_motion"])
        directional = (f"Required ordered action sequence: {steps}. Required checkpoint progression: {checkpoints}. "
                       f"Trajectory intent: {trajectory}. Follow this progression only. "
                       f"Forbidden motion: {forbidden}. ")
    return (f"Fictional subject: {subject}. Location: {location}. Start state: {clip['start_state']}. "
            f"One visible action only: {action}. End state: {clip['end_state']}. "
            + directional + f"Natural stillness: {clip['natural_stillness']}. Duration {duration:.3f} seconds. "
            "Restrained locked or gently observational camera. Physically causal motion; hands contact objects before they move. "
            "No repeated action, no reset, no looping gesture, no object penetration, no limb mutation, no extra limbs, no identity drift. "
            "Preserve natural soft realism and the bottom-right provider-mark safe area.")


def sample_dense_frames(video: Path, destination: Path, *, risk: str, duration: float, max_frames: int = 48) -> list[dict[str, Any]]:
    fps = 6.0 if risk == "HIGH" else 4.0 if risk == "MEDIUM" else 2.0
    fps = min(fps, max_frames / max(duration, .001))
    destination.mkdir(parents=True, exist_ok=True)
    pattern = destination / "frame_%04d.jpg"
    subprocess.run(["ffmpeg", "-y", "-i", str(video), "-vf", f"fps={fps:.6f},scale=640:-2", "-q:v", "3", str(pattern)],
                   check=True, capture_output=True)
    files = sorted(destination.glob("frame_*.jpg"))
    return [{"index": index, "timestamp": min(duration, (index - .5) / fps), "path": str(path),
             "sha256": sha256_file(path)} for index, path in enumerate(files, 1)]


def validate_usable_window(start: float, end: float, *, duration: float, target_duration: float) -> None:
    if start < 0 or end > duration + .05 or end <= start or end - start + .05 < target_duration:
        raise GeminiQCError("USABLE_TEMPORAL_WINDOW_INVALID")


def _directional_contract_from_intent(intent: dict[str, Any]) -> dict[str, Any] | None:
    direct = intent.get("motion_contract")
    evidence = intent.get("motion_risk_analysis")
    candidate = direct if isinstance(direct, dict) else evidence.get("atomic_clip") if isinstance(evidence, dict) else None
    return candidate if isinstance(candidate, dict) and candidate.get("direction_sensitive") is True else None


def _has_progression_failure(result: dict[str, Any]) -> bool:
    dimensions = result.get("dimensions")
    if not isinstance(dimensions, dict):
        return False
    critical = ("ORDERED_ACTION_SEQUENCE", "MOVEMENT_DIRECTION", "CHECKPOINT_PROGRESSION", "CAUSAL_CONTACT_ORDER")
    return any(str(dimensions.get(name, "")).upper() in {"MAJOR", "SEVERE"} for name in critical)


def combine_temporal_qc(video_result: dict[str, Any], frames_result: dict[str, Any], *, duration: float,
                        target_duration: float, motion_contract: dict[str, Any] | None = None) -> dict[str, Any]:
    states = [video_result["state"], frames_result["state"]]
    rejects = [state for state in states if state in TEMPORAL_REJECTS]
    if rejects: state = rejects[0]
    elif motion_contract is not None and (_has_progression_failure(video_result) or _has_progression_failure(frames_result)):
        state = "REJECT_ACTION_LOGIC"
    elif "UNCERTAIN" in states: state = "UNCERTAIN"
    elif "PASS_WITH_USABLE_WINDOW" in states: state = "PASS_WITH_USABLE_WINDOW"
    else: state = "PASS_TEMPORAL"
    defects = list(video_result.get("defects", [])) + list(frames_result.get("defects", []))
    start = max(float(video_result.get("usable_start", 0)), float(frames_result.get("usable_start", 0)))
    end = min(float(video_result.get("usable_end", duration)), float(frames_result.get("usable_end", duration)))
    if state == "PASS_WITH_USABLE_WINDOW":
        try:
            validate_usable_window(start, end, duration=duration, target_duration=target_duration)
        except GeminiQCError as error:
            # The validator remains the authority.  A window that cannot
            # carry the requested shot is a terminal asset failure, not an
            # exception that leaves the selected bytes indefinitely pending.
            if error.failure_class != "USABLE_TEMPORAL_WINDOW_INVALID":
                raise
            state = error.failure_class
    if any(str(x.get("severity", "")).upper() == "SEVERE" for x in defects) and state not in TEMPORAL_REJECTS:
        raise GeminiQCError("TEMPORAL_HARD_GATE_CONTRADICTION")
    return {"schema_version": TEMPORAL_QC_VERSION, "state": state, "usable_start": start, "usable_end": end,
            "defects": defects, "video_level": video_result, "dense_frames": frames_result,
            "eligible": state in {"PASS_TEMPORAL", "PASS_WITH_USABLE_WINDOW"}}


def temporal_video_qc(router: GeminiReasoningRouter, *, video: Path, intent: dict[str, Any], frames: list[dict[str, Any]],
                      duration: float, target_duration: float,
                      review_epoch: str | None = None) -> tuple[dict[str, Any], list[ReasoningResult]]:
    """Run temporal QC, optionally binding a fresh appeal epoch into cache identity.

    A false-positive appeal must re-evaluate the same bytes.  Its epoch is
    intentionally included in both prompt and prompt-version identity so an
    earlier rejected cache entry cannot be reused as the fresh review.
    """
    if review_epoch is not None and (not isinstance(review_epoch, str) or not review_epoch.strip()):
        raise GeminiQCError("TEMPORAL_QC_REVIEW_EPOCH_INVALID")
    motion_contract = _directional_contract_from_intent(intent)
    dimensions = ", ".join(_TEMPORAL_DIMENSIONS)
    base = ("Judge actual temporal progression at normal playback. Severe visible physical, anatomy, looping, identity, background, or prop defects reject the clip. "
            f"Evaluate: {dimensions}. Intent: {json.dumps(intent, ensure_ascii=False, sort_keys=True)}. Duration={duration:.3f}. Return JSON only.")
    if motion_contract is not None:
        base += (" A structured directional/ordered motion contract is mandatory. Verify every ordered action step, checkpoint, "
                 "trajectory, start/end spatial relation, and contact-before-object-motion rule against the actual video. "
                 "Any reverse, skipped checkpoint, reset, unexplained direction change, wrong start/end logic, or object motion before contact "
                 "must set state REJECT_ACTION_LOGIC and mark the applicable progression dimensions MAJOR or SEVERE.")
    epoch_suffix = ""
    if review_epoch is not None:
        base += f" Fresh temporal-QC review epoch: {review_epoch}. Do not reuse any earlier temporal review conclusion."
        epoch_suffix = f";review-epoch={review_epoch}"
    video_media = (LLMMedia(video.read_bytes(), "video/mp4", "complete candidate video"),)
    video_result = router.reason(task="temporal_video_qc", prompt=base, schema=TEMPORAL_SCHEMA, tier="HARD", media=video_media,
        prompt_version="temporal-video-qc/1.1.0" + epoch_suffix, schema_version=TEMPORAL_QC_VERSION,
        qc_policy_version="temporal-hard-gates/1.1.0", confidence_field="confidence")
    frame_media = tuple(LLMMedia(Path(item["path"]).read_bytes(), "image/jpeg", f"frame {item['index']} timestamp {item['timestamp']:.3f}s") for item in frames)
    frame_prompt = base + " Inspect these ordered dense frames specifically for detachments, mutations, penetration, state inconsistency, repeated poses/resets, drift, and morphing."
    frame_result = router.reason(task="dense_frame_temporal_qc", prompt=frame_prompt, schema=TEMPORAL_SCHEMA, tier="HARD", media=frame_media,
        prompt_version="dense-frame-qc/1.1.0" + epoch_suffix, schema_version=TEMPORAL_QC_VERSION,
        qc_policy_version="temporal-hard-gates/1.1.0", confidence_field="confidence")
    return combine_temporal_qc(video_result.value, frame_result.value, duration=duration, target_duration=target_duration,
                               motion_contract=motion_contract), [video_result, frame_result]


def semantic_video_qc(router: GeminiReasoningRouter, *, video: Path, intent: dict[str, Any]) -> tuple[dict[str, Any], ReasoningResult]:
    prompt = "Compare the complete video to the structured story-shot intent. Judge subject, action, location, critical props, story beat, and continuity. UNCERTAIN must be explicit. Return JSON only. Intent:\n" + json.dumps(intent, ensure_ascii=False, sort_keys=True)
    result = router.reason(task="semantic_video_qc", prompt=prompt, schema=SEMANTIC_SCHEMA, tier="BULK",
        media=(LLMMedia(video.read_bytes(), "video/mp4", "complete candidate video"),),
        prompt_version="semantic-video-qc/1.0.0", schema_version="story-auto-semantic-video-qc/1.0.0",
        qc_policy_version="semantic-production/1.0.0", confidence_field="confidence")
    if result.value["classification"] in {"FAIL_MISMATCH", "UNCERTAIN"}:
        raise GeminiQCError("VISUAL_NARRATION_ALIGNMENT_MISMATCH" if result.value["classification"] == "FAIL_MISMATCH" else "GEMINI_QC_UNCERTAIN")
    return result.value, result


def repair_plan(router: GeminiReasoningRouter, *, intent: dict[str, Any], prior_prompt: str,
                temporal_result: dict[str, Any]) -> tuple[dict[str, Any], ReasoningResult]:
    prompt = "Produce a material repair strategy, not a cosmetic paraphrase. Prefer simpler atomic action or a validated usable window. Return JSON only.\n" + json.dumps({"intent": intent, "prior_prompt": prior_prompt, "temporal_qc": temporal_result}, ensure_ascii=False, sort_keys=True)
    result = router.reason(task="repair_planning", prompt=prompt, schema=REPAIR_SCHEMA, tier="HARD",
        prompt_version="repair-planner/1.0.0", schema_version=REPAIR_PLAN_VERSION,
        qc_policy_version="temporal-hard-gates/1.0.0")
    if result.value["regeneration_needed"] and not result.value["material_repair_rationale"].strip():
        raise GeminiQCError("REPAIR_RATIONALE_REQUIRED")
    return result.value, result


def write_qc_artifact(path: Path, value: dict[str, Any]) -> None:
    atomic_write_json(path, value)

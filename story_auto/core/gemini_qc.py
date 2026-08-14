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
MOTION_PLAN_VERSION = "story-auto-motion-plan/1.0.0"
TEMPORAL_QC_VERSION = "story-auto-temporal-video-qc/1.0.0"
REPAIR_PLAN_VERSION = "story-auto-repair-plan/1.0.0"
FLOW_MOTION_PROMPT_VERSION = "story-auto-flow-motion-prompt/1.0.0"

HIGH_RISK_TERMS = ("door", "handle", "pick up", "put down", "tool", "piano", "instrument",
                   "finger", "sit", "stand", "pass", "hand", "walk")
TEMPORAL_REJECTS = {"REJECT_ACTION_LOGIC", "REJECT_ANATOMY", "REJECT_LOOP",
                    "REJECT_IDENTITY", "REJECT_BACKGROUND"}

HOOK_SCHEMA = {"type": "object", "required": ["beats"], "properties": {"beats": {"type": "array", "minItems": 2, "items": {
    "type": "object", "required": ["start", "end", "new_information", "active_subject", "action", "location",
    "important_props", "visual_function", "emotional_function", "similarity_to_previous", "repetition_risk"],
    "properties": {"start": {"type": "number"}, "end": {"type": "number"}, "new_information": {"type": "string"},
    "active_subject": {"type": "string"}, "action": {"type": "string"}, "location": {"type": "string"},
    "important_props": {"type": "array", "items": {"type": "string"}}, "visual_function": {"type": "string"},
    "emotional_function": {"type": "string"}, "similarity_to_previous": {"type": "number"},
    "repetition_risk": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]}}}}}}

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
        "properties": {"start_state": {"type": "string"}, "action": {"type": "string"}, "end_state": {"type": "string"}, "natural_stillness": {"type": "string"}}}}}}

SEMANTIC_SCHEMA = {"type": "object", "required": ["classification", "confidence", "observed", "contradictions"], "properties": {
    "classification": {"type": "string", "enum": ["PASS_DIRECT", "PASS_SUPPORTIVE", "PASS_ATMOSPHERIC", "FAIL_MISMATCH", "UNCERTAIN"]},
    "confidence": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW", "UNCERTAIN"]},
    "observed": {"type": "string"}, "contradictions": {"type": "array", "items": {"type": "string"}}}}

_TEMPORAL_DIMENSIONS = ("ACTION_CAUSALITY", "LIMB_INTEGRITY", "HAND_OBJECT_CONTACT", "OBJECT_STATE_CONTINUITY",
    "ACTION_LOOPING", "MOTION_NATURALNESS", "START_END_STATE_LOGIC", "IDENTITY_STABILITY", "BACKGROUND_STABILITY", "PROP_STABILITY")
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


def is_high_risk(action: str) -> bool:
    lowered = action.lower(); return any(term in lowered for term in HIGH_RISK_TERMS)


def validate_motion_plan(plan: dict[str, Any], *, original_action: str) -> None:
    clips = plan.get("atomic_clips", [])
    if not clips: raise GeminiQCError("MOTION_PLAN_INVALID")
    if is_high_risk(original_action) and len(plan.get("meaningful_actions", [])) > 1 and len(clips) < 2:
        raise GeminiQCError("HIGH_RISK_ACTION_NOT_DECOMPOSED")
    for clip in clips:
        if any(word in clip["action"].lower() for word in (" and then ", " then ", ";")):
            raise GeminiQCError("MOTION_ACTION_NOT_ATOMIC")


def plan_motion(router: GeminiReasoningRouter, intent: dict[str, Any]) -> tuple[dict[str, Any], ReasoningResult]:
    prompt = "Decompose this production VIDEO intent into physically plausible cinematic states. Default to one meaningful action per generated clip. Split high-risk contact mechanics with cuts. Natural stillness is valid. Return JSON only. Intent:\n" + json.dumps(intent, ensure_ascii=False, sort_keys=True)
    result = router.reason(task="motion_planning", prompt=prompt, schema=MOTION_SCHEMA, tier="HARD",
        prompt_version="motion-planner/1.0.0", schema_version=MOTION_PLAN_VERSION)
    validate_motion_plan(result.value, original_action=str(intent.get("action", "")))
    return result.value, result


def compile_flow_motion_prompt(*, subject: str, location: str, clip: dict[str, Any], duration: float) -> str:
    action = re.sub(r"\s+", " ", str(clip["action"])).strip().rstrip(".")
    if not action or len(action) > 240: raise GeminiQCError("FLOW_MOTION_PROMPT_INVALID")
    return (f"Fictional subject: {subject}. Location: {location}. Start state: {clip['start_state']}. "
            f"One visible action only: {action}. End state: {clip['end_state']}. "
            f"Natural stillness: {clip['natural_stillness']}. Duration {duration:.3f} seconds. "
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


def combine_temporal_qc(video_result: dict[str, Any], frames_result: dict[str, Any], *, duration: float,
                        target_duration: float) -> dict[str, Any]:
    states = [video_result["state"], frames_result["state"]]
    rejects = [state for state in states if state in TEMPORAL_REJECTS]
    if rejects: state = rejects[0]
    elif "UNCERTAIN" in states: state = "UNCERTAIN"
    elif "PASS_WITH_USABLE_WINDOW" in states: state = "PASS_WITH_USABLE_WINDOW"
    else: state = "PASS_TEMPORAL"
    defects = list(video_result.get("defects", [])) + list(frames_result.get("defects", []))
    start = max(float(video_result.get("usable_start", 0)), float(frames_result.get("usable_start", 0)))
    end = min(float(video_result.get("usable_end", duration)), float(frames_result.get("usable_end", duration)))
    if state == "PASS_WITH_USABLE_WINDOW": validate_usable_window(start, end, duration=duration, target_duration=target_duration)
    if any(str(x.get("severity", "")).upper() == "SEVERE" for x in defects) and state not in TEMPORAL_REJECTS:
        raise GeminiQCError("TEMPORAL_HARD_GATE_CONTRADICTION")
    return {"schema_version": TEMPORAL_QC_VERSION, "state": state, "usable_start": start, "usable_end": end,
            "defects": defects, "video_level": video_result, "dense_frames": frames_result,
            "eligible": state in {"PASS_TEMPORAL", "PASS_WITH_USABLE_WINDOW"}}


def temporal_video_qc(router: GeminiReasoningRouter, *, video: Path, intent: dict[str, Any], frames: list[dict[str, Any]],
                      duration: float, target_duration: float) -> tuple[dict[str, Any], list[ReasoningResult]]:
    dimensions = "ACTION_CAUSALITY, LIMB_INTEGRITY, HAND_OBJECT_CONTACT, OBJECT_STATE_CONTINUITY, ACTION_LOOPING, MOTION_NATURALNESS, START_END_STATE_LOGIC, IDENTITY_STABILITY, BACKGROUND_STABILITY, PROP_STABILITY"
    base = ("Judge actual temporal progression at normal playback. Severe visible physical, anatomy, looping, identity, background, or prop defects reject the clip. "
            f"Evaluate: {dimensions}. Intent: {json.dumps(intent, ensure_ascii=False, sort_keys=True)}. Duration={duration:.3f}. Return JSON only.")
    video_media = (LLMMedia(video.read_bytes(), "video/mp4", "complete candidate video"),)
    video_result = router.reason(task="temporal_video_qc", prompt=base, schema=TEMPORAL_SCHEMA, tier="HARD", media=video_media,
        prompt_version="temporal-video-qc/1.0.0", schema_version=TEMPORAL_QC_VERSION,
        qc_policy_version="temporal-hard-gates/1.0.0", confidence_field="confidence")
    frame_media = tuple(LLMMedia(Path(item["path"]).read_bytes(), "image/jpeg", f"frame {item['index']} timestamp {item['timestamp']:.3f}s") for item in frames)
    frame_prompt = base + " Inspect these ordered dense frames specifically for detachments, mutations, penetration, state inconsistency, repeated poses/resets, drift, and morphing."
    frame_result = router.reason(task="dense_frame_temporal_qc", prompt=frame_prompt, schema=TEMPORAL_SCHEMA, tier="HARD", media=frame_media,
        prompt_version="dense-frame-qc/1.0.0", schema_version=TEMPORAL_QC_VERSION,
        qc_policy_version="temporal-hard-gates/1.0.0", confidence_field="confidence")
    return combine_temporal_qc(video_result.value, frame_result.value, duration=duration, target_duration=target_duration), [video_result, frame_result]


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

"""Alignment-authoritative planning artifacts, isolated from Gemini transport."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.checkpoint import CheckpointStore, fingerprint
from story_auto.core.content import narration_hash, parse_content_markdown
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock
from story_auto.core.visual import (
    DEFAULT_VISUAL_POLICY,
    compile_image_prompt,
    compile_video_prompt,
    validate_visual_policy,
)
from story_auto.providers.llm import GeminiProvider, GeminiProviderError, LLMRequest

TIMELINE_SCHEMA_VERSION = "story-auto-story-timeline/1.0.0"
CONTINUITY_SCHEMA_VERSION = "story-auto-continuity-bible/1.0.0"
REVIEW_SCHEMA_VERSION = "story-auto-review-state/1.0.0"
TIMELINE_PROMPT_VERSION = "story-auto-timeline-prompt/1.0.0"
CONTINUITY_PROMPT_VERSION = "story-auto-continuity-prompt/1.0.0"
SHOT_PROMPT_VERSION = "story-auto-shot-prompt/1.0.0"
MEDIA_POLICY_VERSION = "story-auto-media-policy/1.0.0"
GENERATION_PROMPT_VERSION = "story-auto-generation-prompt/2.0.0"
SHOT_SCHEMA_VERSION = "story-auto-shot-plan/1.0.0"
MEDIA_SCHEMA_VERSION = "story-auto-media-plan/1.0.0"
REQUEST_SCHEMA_VERSION = "story-auto-generation-requests/1.0.0"

class PlanningError(ValueError):
    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(failure_class + (f": {detail}" if detail else ""))

def _hash_text(value: str) -> str: return hashlib.sha256(value.encode("utf-8")).hexdigest()
def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:48] or "entity"

def _settings(config) -> tuple[str, dict[str, Any]]:
    llm = config.settings.get("llm")
    if not isinstance(llm, dict) or llm.get("provider") != "gemini":
        raise PlanningError("GEMINI_MODEL_UNAVAILABLE", "settings.llm.provider must be gemini")
    model = llm.get("model", "gemini-3.5-flash")
    if not isinstance(model, str) or not model.strip(): raise PlanningError("GEMINI_MODEL_UNAVAILABLE")
    return model, llm

def _timeline_schema() -> dict[str, Any]:
    return {"type":"object", "properties":{"groups":{"type":"array", "items":{"type":"object", "properties":{"segment_ids":{"type":"array", "items":{"type":"string"}}, "story_role":{"type":"string"}, "summary":{"type":"string"}, "entity_ids":{"type":"array", "items":{"type":"string"}}}, "required":["segment_ids","story_role","summary"]}}}, "required":["groups"]}
def _continuity_schema() -> dict[str, Any]:
    entity = {"type":"object", "properties":{"entity_id":{"type":"string"},"name":{"type":"string"},"facts":{"type":"object"},"visual_design":{"type":"object"},"constraints":{"type":"array","items":{"type":"string"}}},"required":["entity_id","name"]}
    return {"type":"object", "properties":{"style":{"type":"object"},"characters":{"type":"array","items":entity},"locations":{"type":"array","items":entity},"props":{"type":"array","items":entity}},"required":["style","characters","locations","props"]}

def _resolve_timeline(project_id: str, alignment: dict[str, Any], grouping: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    segments = alignment.get("segments")
    if not isinstance(segments, list) or not segments: raise PlanningError("TIMELINE_ALIGNMENT_MISMATCH")
    lookup = {s.get("segment_id"): s for s in segments if isinstance(s, dict)}
    groups = grouping.get("groups") if isinstance(grouping, dict) else None
    if not isinstance(groups, list) or not groups: raise PlanningError("STORY_TIMELINE_INVALID", "groups required")
    used, scenes = set(), []
    for index, group in enumerate(groups, 1):
        ids = group.get("segment_ids") if isinstance(group, dict) else None
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in lookup for i in ids): raise PlanningError("TIMELINE_ALIGNMENT_MISMATCH")
        positions = [next(i for i, s in enumerate(segments) if s.get("segment_id") == item) for item in ids]
        if positions != list(range(min(positions), max(positions) + 1)) or used.intersection(ids): raise PlanningError("STORY_TIMELINE_INVALID", "groups must be ordered unique contiguous segments")
        used.update(ids); first, last = lookup[ids[0]], lookup[ids[-1]]
        scenes.append({"scene_id": f"scn_{index:04d}", "start": first["start"], "end": last["end"], "narration_segment_ids": ids, "narration_text": "".join(lookup[item]["text"] for item in ids), "story_role": group.get("story_role", "story_beat"), "summary": group.get("summary", ""), "entity_ids": group.get("entity_ids", [])})
    if used != set(lookup): raise PlanningError("STORY_TIMELINE_INVALID", "all narration must be covered exactly once")
    # Spoken spans may leave canonical leading/trailing/inter-segment silence.
    # Assign silence deterministically to adjacent visual scenes so coverage
    # tiles the full narration master without changing alignment timestamps.
    scenes[0]["start"] = 0.0
    for index in range(1, len(scenes)):
        boundary = (float(scenes[index - 1]["end"]) + float(scenes[index]["start"])) / 2
        scenes[index - 1]["end"] = boundary
        scenes[index]["start"] = boundary
    scenes[-1]["end"] = float(alignment["duration_seconds"])
    return {"schema_version": TIMELINE_SCHEMA_VERSION, "project_id": project_id, "alignment_sha256": provenance["direct_input_hashes"]["alignment_sha256"], "scenes": scenes, "provenance": provenance, "review_status": "VALIDATED"}

def validate_timeline(value: Any, alignment: dict[str, Any]) -> None:
    try: scenes = value["scenes"]; segments = {s["segment_id"]: s for s in alignment["segments"]}
    except (KeyError, TypeError): raise PlanningError("STORY_TIMELINE_INVALID")
    if value.get("schema_version") != TIMELINE_SCHEMA_VERSION or not isinstance(scenes, list) or not scenes: raise PlanningError("STORY_TIMELINE_INVALID")
    used, previous = set(), 0.0
    for index, scene in enumerate(scenes, 1):
        ids = scene.get("narration_segment_ids") if isinstance(scene, dict) else None
        if scene.get("scene_id") != f"scn_{index:04d}" or not isinstance(ids, list) or not ids or any(i not in segments for i in ids): raise PlanningError("STORY_TIMELINE_INVALID")
        start, end = float(scene["start"]), float(scene["end"])
        if used.intersection(ids) or abs(start - previous) > .001 or end <= start: raise PlanningError("STORY_TIMELINE_INVALID")
        if start > float(segments[ids[0]]["start"]) or end < float(segments[ids[-1]]["end"]): raise PlanningError("TIMELINE_ALIGNMENT_MISMATCH")
        used.update(ids); previous = float(scene["end"])
    if used != set(segments) or abs(float(scenes[0]["start"])) > .001 or abs(float(scenes[-1]["end"]) - float(alignment["duration_seconds"])) > .001: raise PlanningError("TIMELINE_ALIGNMENT_MISMATCH")

def _continuity(project_id: str, proposed: dict[str, Any], timeline: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    result = {"schema_version": CONTINUITY_SCHEMA_VERSION, "project_id": project_id, "style": proposed.get("style", {}), "characters": [], "locations": [], "props": [], "provenance": provenance, "review_status": "VALIDATED"}
    seen = set()
    for kind, prefix in (("characters", "char_"), ("locations", "loc_"), ("props", "prop_")):
        values = proposed.get(kind)
        if not isinstance(values, list): raise PlanningError("CONTINUITY_INVALID")
        for item in values:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip(): raise PlanningError("CONTINUITY_INVALID")
            proposed_id = item.get("entity_id")
            entity_id = proposed_id if isinstance(proposed_id, str) and proposed_id.startswith(prefix) else prefix + _slug(item["name"])
            if entity_id in seen: raise PlanningError("CONTINUITY_INVALID", "stable unique entity IDs required")
            seen.add(entity_id); result[kind].append({"entity_id":entity_id, "name":item["name"], "facts":item.get("facts", {}), "visual_design":item.get("visual_design", {}), "constraints":item.get("constraints", [])})
    referenced = {entity for scene in timeline["scenes"] for entity in scene.get("entity_ids", [])}
    if not referenced.issubset(seen): raise PlanningError("CONTINUITY_REFERENCE_INVALID")
    return result

def validate_continuity(value: Any, timeline: dict[str, Any]) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != CONTINUITY_SCHEMA_VERSION: raise PlanningError("CONTINUITY_INVALID")
    seen = set()
    for kind, prefix in (("characters", "char_"), ("locations", "loc_"), ("props", "prop_")):
        if not isinstance(value.get(kind), list): raise PlanningError("CONTINUITY_INVALID")
        for entity in value[kind]:
            if not isinstance(entity, dict) or not isinstance(entity.get("entity_id"), str) or not entity["entity_id"].startswith(prefix) or entity["entity_id"] in seen: raise PlanningError("CONTINUITY_INVALID")
            seen.add(entity["entity_id"])
    refs = {entity for scene in timeline["scenes"] for entity in scene.get("entity_ids", [])}
    if not refs.issubset(seen): raise PlanningError("CONTINUITY_REFERENCE_INVALID")

def _shot_schema() -> dict[str, Any]:
    shot = {"type":"object", "properties":{"scene_id":{"type":"string"},"start":{"type":"number"},"end":{"type":"number"},"subject":{"type":"string"},"action":{"type":"string"},"character_ids":{"type":"array","items":{"type":"string"}},"location_id":{"type":"string"},"prop_ids":{"type":"array","items":{"type":"string"}},"wardrobe_state_refs":{"type":"array","items":{"type":"string"}},"time_of_day":{"type":"string"},"camera_intent":{"type":"string"},"composition_intent":{"type":"string"},"visual_emotional_purpose":{"type":"string"},"motion_value":{"type":"integer"}}, "required":["scene_id","start","end","subject","action","camera_intent","composition_intent","visual_emotional_purpose"]}
    return {"type":"object","properties":{"shots":{"type":"array","minItems":1,"items":shot}},"required":["shots"]}

def _entity_maps(continuity: dict[str, Any]) -> tuple[dict[str, str], set[str]]:
    kinds, ids = {}, set()
    for kind in ("characters", "locations", "props"):
        for entity in continuity.get(kind, []):
            if isinstance(entity, dict): kinds[entity.get("entity_id")] = kind[:-1]; ids.add(entity.get("entity_id"))
    return kinds, ids

def _resolve_shots(project_id: str, proposed: dict[str, Any], timeline: dict[str, Any], continuity: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    candidates = proposed.get("shots") if isinstance(proposed, dict) else None
    if not isinstance(candidates, list) or not candidates: raise PlanningError("SHOT_PLAN_INVALID", "shots required")
    scene_map = {s["scene_id"]: s for s in timeline["scenes"]}; kinds, entity_ids = _entity_maps(continuity); shots = []
    for index, raw in enumerate(candidates, 1):
        if not isinstance(raw, dict) or raw.get("scene_id") not in scene_map: raise PlanningError("SHOT_SCENE_REFERENCE_INVALID")
        scene = scene_map[raw["scene_id"]]
        try: start, end = float(raw["start"]), float(raw["end"])
        except (KeyError, TypeError, ValueError): raise PlanningError("SHOT_TIMING_INVALID")
        if start < float(scene["start"]) or end > float(scene["end"]) or end <= start: raise PlanningError("SHOT_TIMING_INVALID")
        chars, props, location = raw.get("character_ids", []), raw.get("prop_ids", []), raw.get("location_id")
        if not isinstance(chars, list) or not isinstance(props, list) or any(i not in entity_ids or kinds[i] != "character" for i in chars): raise PlanningError("SHOT_CHARACTER_REFERENCE_INVALID")
        if any(i not in entity_ids or kinds[i] != "prop" for i in props) or (location is not None and (location not in entity_ids or kinds[location] != "location")): raise PlanningError("SHOT_CONTINUITY_REFERENCE_INVALID")
        required_text = ("subject", "action", "camera_intent", "composition_intent", "visual_emotional_purpose")
        if any(not isinstance(raw.get(k), str) or not raw[k].strip() for k in required_text): raise PlanningError("SHOT_PLAN_INVALID")
        resolved = {"characters":chars,"location":location,"props":props,"wardrobe_state_refs":raw.get("wardrobe_state_refs", []),"time_of_day":raw.get("time_of_day")}
        shots.append({"shot_id":f"sh_{index:04d}","scene_id":raw["scene_id"],"start":start,"end":end,"narration_segment_ids":scene["narration_segment_ids"],"subject":raw["subject"],"action":raw["action"],"character_ids":chars,"location_id":location,"prop_ids":props,"wardrobe_state_refs":raw.get("wardrobe_state_refs", []),"time_of_day":raw.get("time_of_day"),"camera_intent":raw["camera_intent"],"composition_intent":raw["composition_intent"],"visual_emotional_purpose":raw["visual_emotional_purpose"],"motion_value":int(raw.get("motion_value", 0)),"resolved_continuity":resolved,"previous_shot_context": raw.get("previous_shot_context", ""),"next_shot_handoff":raw.get("next_shot_handoff", "")})
    return {"schema_version":SHOT_SCHEMA_VERSION,"project_id":project_id,"timeline_sha256":provenance["direct_input_hashes"]["timeline_sha256"],"continuity_sha256":provenance["direct_input_hashes"]["continuity_sha256"],"shots":shots,"provenance":provenance,"review_status":"VALIDATED"}

def validate_shot_plan(value: Any, timeline: dict[str, Any], continuity: dict[str, Any]) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != SHOT_SCHEMA_VERSION or not isinstance(value.get("shots"), list) or not value["shots"]: raise PlanningError("SHOT_PLAN_INVALID")
    scene_map = {s["scene_id"]: s for s in timeline["scenes"]}; kinds, ids = _entity_maps(continuity); previous = -1.0; seen = set()
    for index, shot in enumerate(value["shots"], 1):
        if not isinstance(shot, dict) or shot.get("shot_id") != f"sh_{index:04d}" or shot["shot_id"] in seen or shot.get("scene_id") not in scene_map: raise PlanningError("SHOT_PLAN_INVALID")
        seen.add(shot["shot_id"]); scene = scene_map[shot["scene_id"]]
        try: start, end = float(shot["start"]), float(shot["end"])
        except (KeyError, TypeError, ValueError): raise PlanningError("SHOT_TIMING_INVALID")
        if start < previous or start < float(scene["start"]) or end > float(scene["end"]) or end <= start: raise PlanningError("SHOT_TIMING_INVALID")
        previous = end
        if any(i not in ids or kinds[i] != "character" for i in shot.get("character_ids", [])): raise PlanningError("SHOT_CHARACTER_REFERENCE_INVALID")
        if any(i not in ids or kinds[i] != "prop" for i in shot.get("prop_ids", [])) or (shot.get("location_id") is not None and (shot["location_id"] not in ids or kinds[shot["location_id"]] != "location")): raise PlanningError("SHOT_CONTINUITY_REFERENCE_INVALID")
    for scene in timeline["scenes"]:
        scene_shots = [s for s in value["shots"] if s["scene_id"] == scene["scene_id"]]
        if not scene_shots or abs(float(scene_shots[0]["start"])-float(scene["start"])) > .001 or abs(float(scene_shots[-1]["end"])-float(scene["end"])) > .001: raise PlanningError("SHOT_COVERAGE_INVALID")

def _media_settings(config) -> dict[str, Any]:
    settings = config.settings.get("media", {})
    if not isinstance(settings, dict): raise PlanningError("MEDIA_POLICY_INVALID")
    return {"hook_seconds":float(settings.get("hook_seconds", 55)),"motion_spike_threshold":int(settings.get("motion_spike_threshold", 8)),"overrides":settings.get("overrides", {}),"max_attempts":int(settings.get("max_attempts", 2)),"aspect_ratio":settings.get("aspect_ratio", "16:9"),"large_batch_request_threshold":int(settings.get("large_batch_request_threshold", 20))}

def compile_media_plan(project_id: str, shot_plan: dict[str, Any], render_mode: str, settings: dict[str, Any]) -> dict[str, Any]:
    if render_mode not in {"hybrid_hook", "full_video_ai"}: raise PlanningError("MEDIA_POLICY_INVALID")
    hook_target, covered, hook_end = float(settings["hook_seconds"]), 0.0, None; planned = []
    for shot in shot_plan["shots"]:
        duration = float(shot["end"])-float(shot["start"])
        is_hook = render_mode == "hybrid_hook" and covered < hook_target
        if render_mode == "full_video_ai" or is_hook: media_type, requirement = "VIDEO", "REQUIRED"
        elif int(shot.get("motion_value", 0)) >= int(settings["motion_spike_threshold"]): media_type, requirement = "VIDEO", "PREFERRED"
        else: media_type, requirement = "IMAGE", "REQUIRED"
        if is_hook: covered += duration; hook_end = shot["end"]
        override = settings.get("overrides", {}).get(shot["shot_id"], {})
        if override:
            media_type, requirement = override.get("media_type", media_type), override.get("requirement", requirement)
        if render_mode == "full_video_ai" and (media_type != "VIDEO" or requirement != "REQUIRED"): raise PlanningError("MEDIA_OVERRIDE_REJECTED")
        planned.append({"shot_id":shot["shot_id"],"media_type":media_type,"requirement":requirement,"target_duration":duration,"fallback_policy":"BLOCK" if requirement == "REQUIRED" else "HOLD","reference_strategy":"CONTINUITY_REFERENCES","image_motion_policy":"SLOW_PUSH" if media_type == "IMAGE" else "NONE","generation_priority":0 if is_hook else (1 if requirement == "REQUIRED" else 2),"motion_spike": media_type == "VIDEO" and not is_hook and render_mode == "hybrid_hook"})
    return {"schema_version":MEDIA_SCHEMA_VERSION,"project_id":project_id,"render_mode":render_mode,"shot_plan_sha256":_hash_text(str(shot_plan)),"hook_target_seconds":hook_target,"resolved_hook_end":hook_end,"shots":planned,"review_status":"VALIDATED"}

def validate_media_plan(value: Any, shot_plan: dict[str, Any]) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != MEDIA_SCHEMA_VERSION: raise PlanningError("MEDIA_PLAN_INVALID")
    expected, actual = [s["shot_id"] for s in shot_plan["shots"]], [s.get("shot_id") for s in value.get("shots", [])]
    if expected != actual: raise PlanningError("MEDIA_COVERAGE_INVALID")
    for media in value["shots"]:
        if media.get("media_type") not in {"IMAGE","VIDEO","HOLD"} or media.get("requirement") not in {"REQUIRED","PREFERRED"}: raise PlanningError("MEDIA_PLAN_INVALID")
        if media.get("fallback_policy") not in {"BLOCK", "HOLD", "IMAGE"}: raise PlanningError("MEDIA_PLAN_INVALID")
        if media.get("requirement") == "REQUIRED" and media.get("fallback_policy") != "BLOCK": raise PlanningError("MEDIA_PLAN_INVALID")
        if value["render_mode"] == "full_video_ai" and (media["media_type"], media["requirement"]) != ("VIDEO","REQUIRED"): raise PlanningError("FULL_VIDEO_POLICY_INVALID")
    if value["render_mode"] == "hybrid_hook":
        hook = [m for m in value["shots"] if m["generation_priority"] == 0]
        if not hook or any(m["media_type"] != "VIDEO" or m["requirement"] != "REQUIRED" for m in hook): raise PlanningError("HYBRID_HOOK_POLICY_INVALID")

def _request_id(payload: dict[str, Any]) -> str: return "req_" + _hash_text(repr(sorted(payload.items())))[:20]
def compile_generation_requests(project_id: str, shot_plan: dict[str, Any], media_plan: dict[str, Any], continuity: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    requests, reference_ids = [], {}
    visual_policy = dict(DEFAULT_VISUAL_POLICY)
    validate_visual_policy(visual_policy)
    used = {i for s in shot_plan["shots"] for i in (s.get("character_ids", []) + s.get("prop_ids", []) + ([s["location_id"]] if s.get("location_id") else []))}
    kinds, _ = _entity_maps(continuity)
    entity_by_id = {entity["entity_id"]: entity for kind in ("characters", "locations", "props") for entity in continuity.get(kind, [])}
    for entity_id in sorted(used):
        purpose = f"{kinds[entity_id].upper()}_REFERENCE"; seed = {"purpose":purpose,"entity_id":entity_id,"continuity_entity":entity_by_id[entity_id],"prompt_version":GENERATION_PROMPT_VERSION}; request_id = _request_id(seed); reference_ids[entity_id] = request_id
        entity = entity_by_id[entity_id]
        intent = f"Canonical continuity reference for {entity['name']}. {entity.get('visual_design', {})}"
        requests.append({"request_id":request_id,"purpose":"REFERENCE","reference_type":purpose,"entity_id":entity_id,"media_type":"IMAGE","provider":"google_flow","prompt":compile_image_prompt(intent, visual_policy),"visual_policy":visual_policy,"output_count":1,"execution_tier":"STANDARD_PRODUCTION","reference_asset_ids":[],"depends_on":[],"target_duration":None,"aspect_ratio":settings["aspect_ratio"],"priority":0,"fingerprint":_hash_text(repr(seed))})
    media_by_shot = {m["shot_id"]:m for m in media_plan["shots"]}
    for shot in shot_plan["shots"]:
        media = media_by_shot[shot["shot_id"]]
        if media["media_type"] == "HOLD": continue
        refs = shot.get("character_ids", []) + shot.get("prop_ids", []) + ([shot["location_id"]] if shot.get("location_id") else [])
        deps = [reference_ids[i] for i in refs]; seed = {"shot_id":shot["shot_id"],"media_type":media["media_type"],"shot":shot,"media":media,"refs":deps,"prompt_version":GENERATION_PROMPT_VERSION}; request_id = _request_id(seed)
        intent = f"{shot['visual_emotional_purpose']}. {shot['subject']} {shot['action']}. {shot['composition_intent']}"
        if media["media_type"] == "IMAGE":
            prompt = compile_image_prompt(intent, visual_policy)
        else:
            prompt = compile_video_prompt(subject_motion=shot["action"], environmental_motion="subtle scene-appropriate movement", camera_motion=shot["camera_intent"], timing=f"continuous action across {media['target_duration']:.3f} seconds")
        requests.append({"request_id":request_id,"purpose":"SHOT","shot_id":shot["shot_id"],"media_type":media["media_type"],"requirement":media["requirement"],"provider":"google_flow","prompt":prompt,"visual_policy":visual_policy,"output_count":1,"execution_tier":"STANDARD_PRODUCTION","reference_asset_ids":refs,"depends_on":deps,"target_duration":media["target_duration"],"aspect_ratio":settings["aspect_ratio"],"priority":media["generation_priority"],"fingerprint":_hash_text(repr(seed))})
    requests.sort(key=lambda r:(r["priority"], r["purpose"] != "REFERENCE", r["request_id"]))
    required_videos = sum(r.get("requirement") == "REQUIRED" and r["media_type"] == "VIDEO" for r in requests)
    estimate = {"reference_image_requests":sum(r["purpose"] == "REFERENCE" for r in requests),"shot_image_requests":sum(r["purpose"] == "SHOT" and r["media_type"] == "IMAGE" for r in requests),"required_video_requests":required_videos,"preferred_video_requests":sum(r.get("requirement") == "PREFERRED" and r["media_type"] == "VIDEO" for r in requests),"total_generation_requests":len(requests),"max_attempts_per_request":settings["max_attempts"],"worst_case_attempt_count":len(requests)*settings["max_attempts"],"large_batch_request_threshold":settings["large_batch_request_threshold"],"requires_later_execution_confirmation":media_plan["render_mode"] == "full_video_ai" or len(requests) >= settings["large_batch_request_threshold"]}
    return {"schema_version":REQUEST_SCHEMA_VERSION,"project_id":project_id,"prompt_version":GENERATION_PROMPT_VERSION,"requests":requests,"guardrail_estimate":estimate,"provider_execution_authorized":False,"review_status":"VALIDATED"}

def validate_generation_requests(value: Any, media_plan: dict[str, Any], continuity: dict[str, Any]) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != REQUEST_SCHEMA_VERSION or not isinstance(value.get("requests"), list): raise PlanningError("GENERATION_REQUESTS_INVALID")
    requests, ids = value["requests"], set(); graph = {}
    for request in requests:
        if not isinstance(request, dict) or not isinstance(request.get("request_id"), str) or request["request_id"] in ids or not isinstance(request.get("prompt"), str) or not request["prompt"].strip(): raise PlanningError("GENERATION_REQUESTS_INVALID")
        ids.add(request["request_id"]); graph[request["request_id"]] = request.get("depends_on", [])
        if request.get("media_type") not in {"IMAGE","VIDEO"}: raise PlanningError("GENERATION_REQUESTS_INVALID")
        try: validate_visual_policy(request.get("visual_policy"))
        except ValueError as error: raise PlanningError("VISUAL_POLICY_INVALID") from error
        if request.get("media_type") == "IMAGE" and request.get("output_count") != 1: raise PlanningError("IMAGE_OUTPUT_COUNT_INVALID")
    if any(dep not in ids or dep == node for node, deps in graph.items() for dep in deps): raise PlanningError("REQUEST_DEPENDENCY_INVALID")
    def visit(node, trail):
        if node in trail: raise PlanningError("REQUEST_DEPENDENCY_CYCLE")
        for dep in graph[node]: visit(dep, trail | {node})
    for node in graph: visit(node, set())
    expected = {m["shot_id"]:m["media_type"] for m in media_plan["shots"] if m["media_type"] != "HOLD"}; actual = {r.get("shot_id"):r.get("media_type") for r in requests if r.get("purpose") == "SHOT"}
    if expected != actual: raise PlanningError("GENERATION_MEDIA_CONSISTENCY_INVALID")

def run_visual_planning_stages(runtime_root: Path | str, project_id: str, *, provider: GeminiProvider | None = None) -> tuple[str, str, str]:
    paths, config = load_project(RuntimeLayout.from_root(runtime_root), project_id); model, llm_settings = _settings(config); media_settings = _media_settings(config)
    timeline_path, continuity_path = paths.artifact_path("output/story_timeline.json"), paths.artifact_path("output/continuity_bible.json"); timeline, continuity = read_json(timeline_path), read_json(continuity_path); validate_timeline(timeline, read_json(paths.artifact_path("output/alignment.json"))); validate_continuity(continuity, timeline)
    timeline_sha, continuity_sha = sha256_file(timeline_path), sha256_file(continuity_path); active = provider or GeminiProvider()
    with ProjectLock(paths.runtime, project_id):
        checkpoints = CheckpointStore(paths); shot_path = paths.artifact_path("output/shot_plan.json"); shot_fp = fingerprint(stage_name="shot_plan", producer_version=SHOT_PROMPT_VERSION, artifact_schema_version=SHOT_SCHEMA_VERSION, direct_inputs={"timeline_sha256":timeline_sha,"continuity_sha256":continuity_sha,"model":model}, settings={k:v for k,v in llm_settings.items() if k != "api_key"}); decision = checkpoints.decide("shot_plan", shot_fp)
        if decision.action == "SKIP":
            try: shot_plan = read_json(shot_path); validate_shot_plan(shot_plan, timeline, continuity); shot_action="SKIP"
            except Exception: decision = type(decision)("RUN", "artifact invalid")
        if decision.action == "RUN":
            response = active.generate_structured(LLMRequest(model, f"{SHOT_PROMPT_VERSION}\\nProduce coherent visual shots wholly within scene time bounds. Cover every scene exactly with ordered shots. Use only continuity IDs.\\nTimeline:{timeline['scenes']}\\nContinuity:{continuity}", _shot_schema(), llm_settings, _hash_text(shot_fp)[:24], "shot_plan")); shot_plan = _resolve_shots(project_id, response.value, timeline, continuity, _provenance(model,"shot_plan",SHOT_PROMPT_VERSION,{"timeline_sha256":timeline_sha,"continuity_sha256":continuity_sha},response)); validate_shot_plan(shot_plan,timeline,continuity); atomic_write_json(shot_path,shot_plan); checkpoints.record("shot_plan",fingerprint=shot_fp,status="SUCCESS",outputs=["output/shot_plan.json"],producer_version=SHOT_PROMPT_VERSION); shot_action="RUN"
        shot_sha=sha256_file(shot_path); media_path=paths.artifact_path("output/media_plan.json"); media_fp=fingerprint(stage_name="media_plan",producer_version=MEDIA_POLICY_VERSION,artifact_schema_version=MEDIA_SCHEMA_VERSION,direct_inputs={"shot_plan_sha256":shot_sha,"render_mode":config.render_mode},settings=media_settings); decision=checkpoints.decide("media_plan",media_fp)
        if decision.action == "SKIP":
            try: media_plan=read_json(media_path); validate_media_plan(media_plan,shot_plan); media_action="SKIP"
            except Exception: decision=type(decision)("RUN","artifact invalid")
        if decision.action == "RUN":
            media_plan=compile_media_plan(project_id,shot_plan,config.render_mode,media_settings); media_plan["shot_plan_sha256"]=shot_sha; validate_media_plan(media_plan,shot_plan); atomic_write_json(media_path,media_plan); checkpoints.record("media_plan",fingerprint=media_fp,status="SUCCESS",outputs=["output/media_plan.json"],producer_version=MEDIA_POLICY_VERSION); media_action="RUN"
        media_sha=sha256_file(media_path); request_path=paths.artifact_path("output/generation_requests.json"); request_fp=fingerprint(stage_name="generation_requests",producer_version=GENERATION_PROMPT_VERSION,artifact_schema_version=REQUEST_SCHEMA_VERSION,direct_inputs={"shot_plan_sha256":shot_sha,"continuity_sha256":continuity_sha,"media_plan_sha256":media_sha,"prompt_version":GENERATION_PROMPT_VERSION},settings={"aspect_ratio":media_settings["aspect_ratio"],"max_attempts":media_settings["max_attempts"]}); decision=checkpoints.decide("generation_requests",request_fp)
        if decision.action == "SKIP":
            try: requests=read_json(request_path); validate_generation_requests(requests,media_plan,continuity); request_action="SKIP"
            except Exception: decision=type(decision)("RUN","artifact invalid")
        if decision.action == "RUN":
            requests=compile_generation_requests(project_id,shot_plan,media_plan,continuity,media_settings); validate_generation_requests(requests,media_plan,continuity); atomic_write_json(request_path,requests); checkpoints.record("generation_requests",fingerprint=request_fp,status="SUCCESS",outputs=["output/generation_requests.json"],producer_version=GENERATION_PROMPT_VERSION); request_action="RUN"
        review_path = paths.artifact_path("output/review_state.json")
        bound_hashes = {"timeline":timeline_sha,"continuity":continuity_sha,"shot_plan":shot_sha,"media_plan":media_sha}
        try: prior_review = read_json(review_path)
        except Exception: prior_review = {}
        prior_approval = prior_review.get("plan_approval", {}) if isinstance(prior_review, dict) else {}
        status = "APPROVED" if prior_approval.get("status") == "APPROVED" and prior_approval.get("bound_hashes") == bound_hashes else "VALIDATED"
        atomic_write_json(review_path, {"schema_version":REVIEW_SCHEMA_VERSION,"project_id":project_id,"plan_approval":{"status":status,"bound_hashes":bound_hashes},"references":prior_review.get("references", {}),"assets":prior_review.get("assets", {}),"batch_confirmations":prior_review.get("batch_confirmations", [])})
    return shot_action, media_action, request_action

def approve_shot_plan(runtime_root: Path | str, project_id: str) -> None:
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id); timeline=read_json(paths.artifact_path("output/story_timeline.json")); continuity=read_json(paths.artifact_path("output/continuity_bible.json")); shots=read_json(paths.artifact_path("output/shot_plan.json")); media=read_json(paths.artifact_path("output/media_plan.json")); requests=read_json(paths.artifact_path("output/generation_requests.json")); validate_shot_plan(shots,timeline,continuity); validate_media_plan(media,shots); validate_generation_requests(requests,media,continuity)
    with ProjectLock(paths.runtime,project_id): atomic_write_json(paths.artifact_path("output/review_state.json"),{"schema_version":REVIEW_SCHEMA_VERSION,"project_id":project_id,"plan_approval":{"status":"APPROVED","bound_hashes":{"timeline":sha256_file(paths.artifact_path("output/story_timeline.json")),"continuity":sha256_file(paths.artifact_path("output/continuity_bible.json")),"shot_plan":sha256_file(paths.artifact_path("output/shot_plan.json")),"media_plan":sha256_file(paths.artifact_path("output/media_plan.json"))}},"references":{},"assets":{},"batch_confirmations":[]})

def _provenance(model: str, stage: str, prompt_version: str, inputs: dict[str, str], response) -> dict[str, Any]:
    schemas = {"story_timeline": TIMELINE_SCHEMA_VERSION, "continuity": CONTINUITY_SCHEMA_VERSION, "shot_plan": SHOT_SCHEMA_VERSION}
    return {"provider":"gemini", "model":model, "planning_stage":stage, "prompt_version":prompt_version, "schema_version":schemas[stage], "direct_input_hashes":inputs, "request_id":response.request_id, "attempts":response.attempts, "latency_ms":response.latency_ms, "usage":response.usage}

def run_planning_stages(runtime_root: Path | str, project_id: str, *, provider: GeminiProvider | None = None) -> tuple[str, str]:
    paths, config = load_project(RuntimeLayout.from_root(runtime_root), project_id); model, settings = _settings(config)
    narration = parse_content_markdown(paths.content_file.read_text(encoding="utf-8")).narration; narration_sha = narration_hash(narration)
    alignment_path = paths.artifact_path("output/alignment.json"); alignment = read_json(alignment_path); alignment_sha = sha256_file(alignment_path)
    timeline_fp = fingerprint(stage_name="story_timeline", producer_version=TIMELINE_PROMPT_VERSION, artifact_schema_version=TIMELINE_SCHEMA_VERSION, direct_inputs={"alignment_sha256":alignment_sha,"narration_sha256":narration_sha,"model":model}, settings={k:v for k,v in settings.items() if k != "api_key"})
    active = provider or GeminiProvider()
    with ProjectLock(paths.runtime, project_id):
        checkpoints = CheckpointStore(paths); timeline_path = paths.artifact_path("output/story_timeline.json")
        decision = checkpoints.decide("story_timeline", timeline_fp)
        if decision.action == "SKIP":
            try: timeline = read_json(timeline_path); validate_timeline(timeline, alignment); timeline_action = "SKIP"
            except Exception: decision = type(decision)("RUN", "artifact invalid")
        if decision.action == "RUN":
            response = active.generate_structured(LLMRequest(model, f"{TIMELINE_PROMPT_VERSION}\nGroup these alignment segments exactly once by segment_id. Do not create timestamps.\nNarration:\n{narration}\nSegments:\n{alignment['segments']}", _timeline_schema(), settings, _hash_text(timeline_fp)[:24], "story_timeline"))
            timeline = _resolve_timeline(project_id, alignment, response.value, _provenance(model, "story_timeline", TIMELINE_PROMPT_VERSION, {"alignment_sha256":alignment_sha,"narration_sha256":narration_sha}, response)); validate_timeline(timeline, alignment); atomic_write_json(timeline_path, timeline); checkpoints.record("story_timeline", fingerprint=timeline_fp, status="SUCCESS", outputs=["output/story_timeline.json"], producer_version=TIMELINE_PROMPT_VERSION); timeline_action = "RUN"
        timeline_sha = sha256_file(timeline_path)
        continuity_fp = fingerprint(stage_name="continuity", producer_version=CONTINUITY_PROMPT_VERSION, artifact_schema_version=CONTINUITY_SCHEMA_VERSION, direct_inputs={"timeline_sha256":timeline_sha,"narration_sha256":narration_sha,"model":model}, settings={k:v for k,v in settings.items() if k != "api_key"})
        continuity_path = paths.artifact_path("output/continuity_bible.json"); continuity_decision = checkpoints.decide("continuity", continuity_fp)
        if continuity_decision.action == "SKIP":
            try: continuity = read_json(continuity_path); validate_continuity(continuity, timeline); return timeline_action, "SKIP"
            except Exception: continuity_decision = type(continuity_decision)("RUN", "artifact invalid")
        response = active.generate_structured(LLMRequest(model, f"{CONTINUITY_PROMPT_VERSION}\nExtract only supported story facts and label visual choices under visual_design. Use stable entity IDs.\nNarration:\n{narration}\nTimeline:\n{timeline['scenes']}", _continuity_schema(), settings, _hash_text(continuity_fp)[:24], "continuity"))
        continuity = _continuity(project_id, response.value, timeline, _provenance(model, "continuity", CONTINUITY_PROMPT_VERSION, {"story_timeline_sha256":timeline_sha,"narration_sha256":narration_sha}, response)); validate_continuity(continuity, timeline); atomic_write_json(continuity_path, continuity); checkpoints.record("continuity", fingerprint=continuity_fp, status="SUCCESS", outputs=["output/continuity_bible.json"], producer_version=CONTINUITY_PROMPT_VERSION)
        # A validated plan is durable but deliberately not human-approved.
        atomic_write_json(paths.artifact_path("output/review_state.json"), {"schema_version": REVIEW_SCHEMA_VERSION, "project_id": project_id, "plan_approval": {"status": "VALIDATED", "bound_hashes": {"timeline": timeline_sha, "continuity": sha256_file(continuity_path)}}, "references": {}, "assets": {}, "batch_confirmations": []})
    return timeline_action, "RUN"

def approve_plan(runtime_root: Path | str, project_id: str) -> None:
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    continuity_path = paths.artifact_path("output/continuity_bible.json"); timeline_path = paths.artifact_path("output/story_timeline.json")
    timeline, continuity = read_json(timeline_path), read_json(continuity_path); validate_continuity(continuity, timeline)
    with ProjectLock(paths.runtime, project_id):
        atomic_write_json(paths.artifact_path("output/review_state.json"), {"schema_version":REVIEW_SCHEMA_VERSION,"project_id":project_id,"plan_approval":{"status":"APPROVED","bound_hashes":{"timeline":sha256_file(timeline_path),"continuity":sha256_file(continuity_path)}},"references":{},"assets":{},"batch_confirmations":[]})

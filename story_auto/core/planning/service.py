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
from story_auto.providers.llm import GeminiProvider, GeminiProviderError, LLMRequest

TIMELINE_SCHEMA_VERSION = "story-auto-story-timeline/1.0.0"
CONTINUITY_SCHEMA_VERSION = "story-auto-continuity-bible/1.0.0"
REVIEW_SCHEMA_VERSION = "story-auto-review-state/1.0.0"
TIMELINE_PROMPT_VERSION = "story-auto-timeline-prompt/1.0.0"
CONTINUITY_PROMPT_VERSION = "story-auto-continuity-prompt/1.0.0"

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
    return {"schema_version": TIMELINE_SCHEMA_VERSION, "project_id": project_id, "alignment_sha256": provenance["direct_input_hashes"]["alignment_sha256"], "scenes": scenes, "provenance": provenance, "review_status": "VALIDATED"}

def validate_timeline(value: Any, alignment: dict[str, Any]) -> None:
    try: scenes = value["scenes"]; segments = {s["segment_id"]: s for s in alignment["segments"]}
    except (KeyError, TypeError): raise PlanningError("STORY_TIMELINE_INVALID")
    if value.get("schema_version") != TIMELINE_SCHEMA_VERSION or not isinstance(scenes, list) or not scenes: raise PlanningError("STORY_TIMELINE_INVALID")
    used, previous = set(), -1.0
    for index, scene in enumerate(scenes, 1):
        ids = scene.get("narration_segment_ids") if isinstance(scene, dict) else None
        if scene.get("scene_id") != f"scn_{index:04d}" or not isinstance(ids, list) or not ids or any(i not in segments for i in ids): raise PlanningError("STORY_TIMELINE_INVALID")
        if used.intersection(ids) or float(scene["start"]) < previous or float(scene["end"]) <= float(scene["start"]): raise PlanningError("STORY_TIMELINE_INVALID")
        if scene["start"] != segments[ids[0]]["start"] or scene["end"] != segments[ids[-1]]["end"]: raise PlanningError("TIMELINE_ALIGNMENT_MISMATCH")
        used.update(ids); previous = float(scene["end"])
    if used != set(segments) or abs(float(scenes[-1]["end"]) - float(alignment["duration_seconds"])) > .15: raise PlanningError("TIMELINE_ALIGNMENT_MISMATCH")

def _continuity(project_id: str, proposed: dict[str, Any], timeline: dict[str, Any], provenance: dict[str, Any]) -> dict[str, Any]:
    result = {"schema_version": CONTINUITY_SCHEMA_VERSION, "project_id": project_id, "style": proposed.get("style", {}), "characters": [], "locations": [], "props": [], "provenance": provenance, "review_status": "VALIDATED"}
    seen = set()
    for kind, prefix in (("characters", "char_"), ("locations", "loc_"), ("props", "prop_")):
        values = proposed.get(kind)
        if not isinstance(values, list): raise PlanningError("CONTINUITY_INVALID")
        for item in values:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip(): raise PlanningError("CONTINUITY_INVALID")
            entity_id = item.get("entity_id") or prefix + _slug(item["name"])
            if not isinstance(entity_id, str) or not entity_id.startswith(prefix) or entity_id in seen: raise PlanningError("CONTINUITY_INVALID", "stable unique entity IDs required")
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

def _provenance(model: str, stage: str, prompt_version: str, inputs: dict[str, str], response) -> dict[str, Any]:
    return {"provider":"gemini", "model":model, "planning_stage":stage, "prompt_version":prompt_version, "schema_version":TIMELINE_SCHEMA_VERSION if stage == "story_timeline" else CONTINUITY_SCHEMA_VERSION, "direct_input_hashes":inputs, "request_id":response.request_id, "attempts":response.attempts, "latency_ms":response.latency_ms, "usage":response.usage}

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

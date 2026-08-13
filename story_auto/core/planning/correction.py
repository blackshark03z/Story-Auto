"""Bounded corrective replanning from canonical alignment and an existing shot plan."""
from __future__ import annotations
from copy import deepcopy
from typing import Any

def replan_visual_beats(shot_plan: dict[str, Any], alignment: dict[str, Any], *, max_seconds: float = 45.0) -> dict[str, Any]:
    """Split overlong shots only at authoritative narration segment boundaries."""
    segments = {s.get("segment_id"): s for s in alignment.get("segments", []) if isinstance(s, dict)}
    result = deepcopy(shot_plan); result["shots"] = []
    for shot in shot_plan.get("shots", []):
        ids = [i for i in shot.get("narration_segment_ids", []) if i in segments]
        if not ids or float(shot.get("end", 0)) - float(shot.get("start", 0)) <= max_seconds:
            result["shots"].append(deepcopy(shot)); continue
        group: list[str] = []; start = float(shot["start"]); part = 1
        shot_end = float(shot["end"]); shot_duration = shot_end - start
        for position, sid in enumerate(ids):
            group.append(sid); end = float(segments[sid]["end"])
            target_end = shot_end if sid == ids[-1] else float(shot["start"]) + shot_duration * (position + 1) / len(ids)
            if target_end - start >= max_seconds or sid == ids[-1]:
                item = deepcopy(shot); item["shot_id"] = f"{shot['shot_id']}_beat_{part:03d}"
                item["start"], item["end"], item["narration_segment_ids"] = start, target_end, group
                item["scene_id"] = shot.get("scene_id"); item["visual_emotional_purpose"] = f"{shot.get('visual_emotional_purpose','')} (beat {part})"
                result["shots"].append(item); part += 1; group = []; start = target_end
    for index, item in enumerate(result["shots"], 1):
        item["shot_id"] = f"sh_{index:04d}"
    return result

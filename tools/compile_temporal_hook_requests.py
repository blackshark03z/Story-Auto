"""Compile the approved Gemini hook/motion plan into exact Flow requests."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.gemini_qc import compile_flow_motion_prompt
from story_auto.core.planning.service import validate_generation_requests


def digest(value: str) -> str: return hashlib.sha256(value.encode("utf-8")).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("project_root", type=Path)
args = parser.parse_args()
root = args.project_root.resolve(); output = root / "output"
document = read_json(output / "generation_requests.json")
hook = read_json(output / "hook_replan_gemini.json")["plan"]
motions = {x["hook_beat_index"]: x for x in read_json(output / "hook_motion_plans_gemini.json")["plans"]}
continuity = read_json(output / "continuity_bible.json")
references = {"julian": "req_15f6577feef388a2ca75", "academy": "req_1a62057609e0124974af",
              "hall": "req_4abe1054f1e397112783", "piano": "req_901644e9d3394e300160",
              "daniel": "req_fb7a178b8b6fec541070"}
old_hook = [x for x in document["requests"] if x.get("purpose") == "SHOT" and x.get("shot_id") == "sh_0001"]
if len(old_hook) != 6: raise SystemExit("expected the preserved six-part hook")
visual_policy = old_hook[0]["visual_policy"]

# Gemini proposes decomposition; deterministic production policy selects one
# bounded, low-risk action per narrative beat and substitutes supportive
# stillness where exact finger mechanics would create avoidable anatomy risk.
selected = {
    1: {"clip": motions[1]["motion_plan"]["atomic_clips"][0], "subject": "fictional late-forties conductor in a dark jacket", "reference": references["julian"]},
    2: {"clip": motions[2]["motion_plan"]["atomic_clips"][1], "subject": "fictional late-forties conductor in a dark jacket", "reference": references["julian"]},
    3: {"clip": {"start_state":"close view of a man's hand already resting flat on a metal exit push-bar; door fully closed",
                  "action":"the resting fingers become still without pushing or moving the door",
                  "end_state":"hand remains naturally attached and still on the bar; door fully closed",
                  "natural_stillness":"one subtle breath visible only as minute sleeve movement"},
        "subject":"fictional late-forties conductor's naturally proportioned hand and dark jacket sleeve", "reference":references["julian"]},
    4: {"clip": motions[4]["motion_plan"]["atomic_clips"][0], "subject":"an old locked black concert grand piano with a red disposal tag", "reference":references["piano"]},
    5: {"clip": {"start_state":"fictional older custodian seated in profile at the grand piano; forearms already resting at keyboard; fingers mostly obscured by piano rim",
                  "action":"he makes one small controlled wrist settling motion while remaining focused",
                  "end_state":"custodian remains seated in profile with hands resting; detailed key mechanics stay out of frame",
                  "natural_stillness":"quiet breathing and a single blink; music is implied rather than finger-simulated"},
        "subject":"fictional late-fifties academy custodian in a gray work shirt", "reference":references["daniel"]},
    6: {"clip": motions[6]["motion_plan"]["atomic_clips"][1], "subject":"fictional late-forties conductor in a dark jacket", "reference":references["julian"]},
    7: {"clip": motions[7]["motion_plan"]["atomic_clips"][0], "subject":"fictional late-forties conductor in a dark jacket", "reference":references["julian"]},
    8: {"clip": {"start_state":"fictional older custodian already seated at the grand piano in side profile; hands below the piano rim and not visible",
                  "action":"he lowers his gaze slightly as the phrase is implied by the scene",
                  "end_state":"custodian remains seated and composed, gaze lowered; piano and body geometry unchanged",
                  "natural_stillness":"one breath and slight head dip; no visible finger mechanics"},
        "subject":"fictional late-fifties academy custodian in a gray work shirt", "reference":references["daniel"]},
    9: {"clip": motions[9]["motion_plan"]["atomic_clips"][1], "subject":"fictional late-forties conductor in a dark jacket", "reference":references["julian"]},
}

new_requests = []
for index, beat in enumerate(hook["beats"], 1):
    choice = selected[index]; duration = float(beat["end"]) - float(beat["start"])
    prompt = compile_flow_motion_prompt(subject=choice["subject"], location=beat["location"],
                                        clip=choice["clip"], duration=duration)
    prompt += (f" Narrative function: {beat['new_information']}. Important visible props: "
               f"{', '.join(beat['important_props']) or 'none'}. The clip must communicate only this beat, not the entire hook.")
    identity = digest(f"temporal-v3|{index}|{beat['start']:.3f}|{beat['end']:.3f}|{prompt}|{choice['reference']}")
    new_requests.append({"request_id": "req_" + identity[:20], "fingerprint": identity,
        "purpose": "SHOT", "shot_id": "sh_0001", "media_type": "VIDEO", "provider": "google_flow",
        "prompt": prompt, "depends_on": [choice["reference"]], "reference_asset_ids": [choice["reference"]],
        "aspect_ratio": "16:9", "output_count": 1, "execution_tier": "STANDARD_PRODUCTION",
        "requirement": "REQUIRED", "priority": 0, "part_index": index, "part_count": len(hook["beats"]),
        "target_start": float(beat["start"]), "target_end": float(beat["end"]), "target_duration": duration,
        "visual_policy": visual_policy, "hook_beat": beat, "motion_contract": choice["clip"],
        "prompt_version": "story-auto-flow-motion-prompt/1.0.0", "motion_plan_version": "story-auto-motion-plan/1.0.0",
        "supersedes_request_ids": [x["request_id"] for x in old_hook]})

document["requests"] = [x for x in document["requests"] if x not in old_hook] + new_requests
document["prompt_version"] = "story-auto-generation-prompt/4.0.0-gemini-motion"
validate_generation_requests(document, read_json(output / "media_plan.json"), continuity)
atomic_write_json(output / "generation_requests.json", document)
atomic_write_json(output / "hook_request_replacement.json", {"schema_version":"story-auto-hook-request-replacement/1.0.0",
    "superseded_request_ids":[x["request_id"] for x in old_hook], "new_request_ids":[x["request_id"] for x in new_requests],
    "new_part_count":len(new_requests), "deterministic_policy":"ONE_BOUNDED_ACTION_PER_CLIP_WITH_SUPPORTIVE_STILLNESS_FOR_FINGER_MECHANICS"})
print({"superseded": len(old_hook), "compiled": len(new_requests), "request_ids": [x["request_id"] for x in new_requests]})

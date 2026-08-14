"""Compile Gemini repair plans and attribution retries into fresh hook request identities."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.gemini_qc import compile_flow_motion_prompt
from story_auto.core.planning.service import validate_generation_requests


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("project_root", type=Path)
args = parser.parse_args()
root = args.project_root.resolve()
output = root / "output"
document = read_json(output / "generation_requests.json")
continuity = read_json(output / "continuity_bible.json")
repairs = {int(item["part_index"]): item["repair_plan"] for item in read_json(output / "hook_repair_plans_gemini.json")["plans"]}
old_hook = sorted((item for item in document["requests"] if item.get("purpose") == "SHOT" and item.get("shot_id") == "sh_0001"),
                  key=lambda item: int(item["part_index"]))
if len(old_hook) != 9:
    raise SystemExit("expected nine Gemini-planned hook requests")

subject_overrides = {
    3: "a naturally proportioned adult hand in a dark suit sleeve",
    4: "an old locked black concert grand piano with a red disposal tag",
    5: "a fictional late-fifties academy custodian in a gray work shirt",
}
reference_overrides = {3: []}
narrative_overrides = {
    5: "An older custodian in gray uniform is revealed poised at the grand piano; the eight notes exist only in the narration soundtrack and are not mimed visually.",
    8: "The custodian's composed stillness supports the repeated musical phrase carried only by the narration soundtrack; no playing motion is shown.",
    9: "Julian freezes in recognition outside the closed recital-hall door.",
}

new_requests = []
decisions = []
for old in old_hook:
    part = int(old["part_index"])
    beat = dict(old["hook_beat"])
    clip = dict(old["motion_contract"])
    constraints = ["One continuous shot with no hard cut, jump cut, reset, or transition."]
    mode = "ATTRIBUTION_RETRY_NEW_IDENTITY"
    if part in repairs:
        repair = repairs[part]
        if not repair.get("regeneration_needed"):
            raise SystemExit(f"repair plan for part {part} does not authorize regeneration")
        clip.update({"start_state": repair["revised_start_state"], "action": repair["revised_atomic_action"],
                     "end_state": repair["revised_end_state"], "natural_stillness": "Subtle breathing or environmental stillness only."})
        constraints.extend(repair["motion_constraints"])
        mode = "GEMINI_MATERIAL_REPAIR"
    if part in narrative_overrides:
        beat["new_information"] = narrative_overrides[part]
    if part in {5, 8}:
        beat["action"] = "remains poised at the piano without visible playing mechanics"
    subject = subject_overrides.get(part, old["prompt"].split("Location:", 1)[0].removeprefix("Fictional subject:").strip().rstrip("."))
    references = reference_overrides.get(part, list(old.get("reference_asset_ids", [])))
    prompt = compile_flow_motion_prompt(subject=subject, location=beat["location"], clip=clip,
                                        duration=float(old["target_duration"]))
    prompt += " Motion constraints: " + " ".join(constraints)
    prompt += (f" Narrative function: {beat['new_information']} Important visible props: "
               f"{', '.join(beat['important_props']) or 'none'}. The clip must communicate only this beat, not the entire hook.")
    identity = digest(f"temporal-v4-repair|{part}|{old['request_id']}|{prompt}|{'|'.join(references)}")
    fresh = dict(old)
    fresh.update({"request_id": "req_" + identity[:20], "fingerprint": identity, "prompt": prompt,
                  "depends_on": references, "reference_asset_ids": references, "hook_beat": beat,
                  "motion_contract": clip, "prompt_version": "story-auto-flow-motion-prompt/1.1.0-repair",
                  "supersedes_request_ids": list(dict.fromkeys(old.get("supersedes_request_ids", []) + [old["request_id"]])),
                  "repair_mode": mode})
    new_requests.append(fresh)
    decisions.append({"part_index": part, "old_request_id": old["request_id"], "new_request_id": fresh["request_id"],
                      "mode": mode, "reference_asset_ids": references,
                      "gemini_material_repair_rationale": repairs.get(part, {}).get("material_repair_rationale")})

document["requests"] = [item for item in document["requests"] if item not in old_hook] + new_requests
document["prompt_version"] = "story-auto-generation-prompt/4.1.0-gemini-repair"
validate_generation_requests(document, read_json(output / "media_plan.json"), continuity)
atomic_write_json(output / "generation_requests.json", document)
atomic_write_json(output / "hook_repair_request_replacement.json", {
    "schema_version": "story-auto-hook-repair-request-replacement/1.0.0",
    "decisions": decisions,
    "deterministic_policy": "FRESH_IDENTITY_PER_REJECT_OR_AMBIGUOUS_RESULT; NO_MANUAL_ADOPTION; SUPPORTIVE_VISUALS_FOR_FRAGILE_PIANO_MECHANICS",
})
print({"compiled": len(new_requests), "request_ids": [item["request_id"] for item in new_requests]})

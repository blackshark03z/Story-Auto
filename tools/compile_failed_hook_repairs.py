"""Compile fresh identities only for current hook requests rejected by QC."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.gemini_qc import compile_flow_motion_prompt
from story_auto.core.planning.service import validate_generation_requests


parser = argparse.ArgumentParser()
parser.add_argument("project_root", type=Path)
args = parser.parse_args()
root = args.project_root.resolve()
output = root / "output"
document = read_json(output / "generation_requests.json")
manifest = {item["request_id"]: item for item in read_json(output / "generation_manifest.json")["requests"]}
repairs = {item["request_id"]: item["repair_plan"] for item in read_json(output / "hook_repair_plans_gemini.json")["plans"]}
replacements = []
for item in document["requests"]:
    old_id = item.get("request_id")
    if old_id not in repairs or manifest.get(old_id, {}).get("status") != "FAILED_RETRYABLE":
        continue
    repair = repairs[old_id]
    if not repair.get("regeneration_needed"):
        raise SystemExit(f"repair plan does not authorize regeneration for {old_id}")
    action = repair["revised_atomic_action"]
    if len(action) > 240:
        action = "The subject holds the stated start pose completely still; no pressing, finger motion, or object movement occurs."
    clip = dict(item["motion_contract"])
    clip.update({"start_state": repair["revised_start_state"], "action": action,
                 "end_state": repair["revised_end_state"], "natural_stillness": "Subtle breathing or environmental stillness only."})
    constraints = list(repair["motion_constraints"])
    # Piano-key simulation has failed the temporal gate twice. Enforce the
    # supportive-visual branch: preserve custodian/piano semantics while
    # removing hands and keyboard mechanics from the frame altogether.
    if int(item.get("part_index", 0)) == 5:
        clip = {"start_state": "tight head-and-shoulders side-profile portrait of the older custodian beside the grand piano lid edge; the crop ends above both elbows and the keyboard is below the frame",
                "action": "the custodian makes one slow natural blink while keeping his posture still",
                "end_state": "the same tight head-and-shoulders profile remains beside the piano lid edge; the crop still ends above both elbows",
                "natural_stillness": "quiet breathing only; no limb or playing motion is visible"}
        constraints = ["Use a tight shoulders-up portrait; the bottom edge of the frame remains above the custodian's elbows.",
                       "Both hands, all fingers, and the piano keyboard remain below and fully outside the frame for the entire shot.",
                       "No playing, key motion, wrist motion, or repeated gesture.",
                       "One continuous locked shot with no cut or transition."]
        item["hook_beat"]["important_props"] = ["gray work shirt", "stationary grand piano rim"]
    subject = item["prompt"].split("Location:", 1)[0].removeprefix("Fictional subject:").strip().rstrip(".")
    beat = item["hook_beat"]
    prompt = compile_flow_motion_prompt(subject=subject, location=beat["location"], clip=clip,
                                        duration=float(item["target_duration"]))
    prompt += " Motion constraints: " + " ".join(constraints)
    prompt += (f" Narrative function: {beat['new_information']} Important visible props: "
               f"{', '.join(beat['important_props']) or 'none'}. The clip must communicate only this beat, not the entire hook.")
    fingerprint = hashlib.sha256(f"failed-hook-repair-v2|{old_id}|{prompt}|{'|'.join(item.get('reference_asset_ids', []))}".encode("utf-8")).hexdigest()
    item.update({"request_id": "req_" + fingerprint[:20], "fingerprint": fingerprint, "prompt": prompt,
                 "motion_contract": clip, "repair_mode": "GEMINI_MATERIAL_REPAIR_AFTER_TEMPORAL_REJECT",
                 "prompt_version": "story-auto-flow-motion-prompt/1.2.0-temporal-repair",
                 "supersedes_request_ids": list(dict.fromkeys(item.get("supersedes_request_ids", []) + [old_id]))})
    replacements.append({"part_index": item["part_index"], "old_request_id": old_id, "new_request_id": item["request_id"],
                         "gemini_material_repair_rationale": repair["material_repair_rationale"]})

validate_generation_requests(document, read_json(output / "media_plan.json"), read_json(output / "continuity_bible.json"))
atomic_write_json(output / "generation_requests.json", document)
atomic_write_json(output / "hook_failed_repair_replacement.json", {
    "schema_version": "story-auto-hook-failed-repair-replacement/1.0.0",
    "replacements": replacements,
    "policy": "ONLY_FAILED_RETRYABLE_CURRENT_HOOK_REQUESTS_REPLACED",
})
print({"replaced": len(replacements), "replacements": replacements})

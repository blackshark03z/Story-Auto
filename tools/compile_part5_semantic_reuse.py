"""Compile a corrected supportive beat-5 intent for an exact prior Flow asset."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.gemini_qc import compile_flow_motion_prompt
from story_auto.core.planning.service import validate_generation_requests


parser = argparse.ArgumentParser(); parser.add_argument("project_root", type=Path); args = parser.parse_args()
root = args.project_root.resolve(); output = root / "output"
document = read_json(output / "generation_requests.json")
current = next(item for item in document["requests"] if item.get("purpose") == "SHOT" and item.get("shot_id") == "sh_0001" and int(item.get("part_index", 0)) == 5)
old_id = current["request_id"]
clip = {"start_state": "tight side-profile portrait of the older custodian seated beside the grand piano; both hands and all fingers are outside the frame; a stationary keyboard may be visible",
        "action": "the custodian makes one slow natural blink while keeping his posture still",
        "end_state": "the custodian remains in the same side-profile pose; hands stay outside the frame and every visible piano element remains stationary",
        "natural_stillness": "quiet breathing only; no limb or playing motion is visible"}
beat = dict(current["hook_beat"])
beat["important_props"] = ["gray work shirt", "stationary grand piano"]
beat["new_information"] = "An older custodian in gray uniform is revealed poised at the grand piano; the eight notes exist only in the narration soundtrack and are not mimed visually."
prompt = compile_flow_motion_prompt(subject="a fictional late-fifties academy custodian in a gray work shirt",
                                    location=beat["location"], clip=clip, duration=float(current["target_duration"]))
prompt += (" Motion constraints: Both hands and all fingers remain fully outside the frame. Any visible keyboard or piano surface remains completely stationary. "
           "No playing, key motion, wrist motion, or repeated gesture. One continuous locked shot with no cut or transition. "
           f"Narrative function: {beat['new_information']} Important visible props: {', '.join(beat['important_props'])}. "
           "The clip must communicate only this beat, not the entire hook.")
fingerprint = hashlib.sha256(f"part5-supportive-semantic-reuse-v1|{old_id}|{prompt}".encode("utf-8")).hexdigest()
current.update({"request_id": "req_" + fingerprint[:20], "fingerprint": fingerprint, "prompt": prompt,
                "depends_on": [], "reference_asset_ids": [], "hook_beat": beat, "motion_contract": clip,
                "repair_mode": "MATERIAL_SEMANTIC_REPAIR_EXACT_FLOW_ASSET_REUSE",
                "prompt_version": "story-auto-flow-motion-prompt/1.3.0-supportive-reuse",
                "supersedes_request_ids": list(dict.fromkeys(current.get("supersedes_request_ids", []) + [old_id]))})
validate_generation_requests(document, read_json(output / "media_plan.json"), read_json(output / "continuity_bible.json"))
atomic_write_json(output / "generation_requests.json", document)
atomic_write_json(output / "part5_semantic_reuse_decision.json", {
    "schema_version": "story-auto-exact-flow-asset-semantic-reuse/1.0.0", "old_request_id": old_id,
    "new_request_id": current["request_id"], "source_request_id": "req_bebf062ea8fd50f0df22",
    "source_asset_sha256": "8d8e9769beb5100602a4277a7a3820dbd6180f79c49cff59aedbe376d610df11",
    "material_change": "hands remain excluded; stationary keyboard is allowed; music remains soundtrack-only",
    "policy": "EXACT_PRIOR_FLOW_ASSET_ONLY; SEMANTIC_AND_TEMPORAL_QC_MUST_RERUN; NO_PRIOR_APPROVAL_INHERITED"})
print({"old_request_id": old_id, "new_request_id": current["request_id"]})

"""Derive a still supportive video from a clean frame of exact Flow beat-8 media."""
from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.gemini_qc import compile_flow_motion_prompt
from story_auto.core.planning.service import validate_generation_requests
from story_auto.core.render.compiler import compile_image
from story_auto.core.render.media import MediaTarget, run_command
from story_auto.providers.flow.validation import validate_video


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


parser = argparse.ArgumentParser(); parser.add_argument("project_root", type=Path); args = parser.parse_args()
root = args.project_root.resolve(); output = root / "output"
document = read_json(output / "generation_requests.json")
manifest = read_json(output / "generation_manifest.json")
source_request_id = "req_ed59858754001ed9cd73"
source_entry = next(item for item in manifest["requests"] if item.get("request_id") == source_request_id)
source_selected = source_entry["selected_asset"]
source = root / source_selected["path"]
if not source.is_file() or sha256_file(source) != source_selected["sha256"]:
    raise SystemExit("EXACT_FLOW_SOURCE_INVALID")
current = next(item for item in document["requests"] if item.get("purpose") == "SHOT" and item.get("shot_id") == "sh_0001" and int(item.get("part_index", 0)) == 8)
old_id = current["request_id"]
clip = {"start_state": "a motionless side-profile portrait of the older custodian already seated at the grand piano on the recital hall stage with his gaze lowered",
        "action": "the portrait holds completely still while the repeated musical phrase is carried only by the narration soundtrack",
        "end_state": "the same custodian and piano composition remains unchanged with gaze lowered",
        "natural_stillness": "intentional photographic stillness; no hand, finger, head, camera, or piano motion"}
beat = dict(current["hook_beat"])
beat["action"] = "holds a motionless lowered-gaze pose at the piano"
beat["new_information"] = "The custodian's motionless lowered-gaze portrait supports the repeated musical phrase carried only by the narration soundtrack; no playing mechanics are shown."
prompt = compile_flow_motion_prompt(subject="a fictional late-fifties academy custodian in a gray work shirt",
                                    location="Recital Hall Stage", clip=clip, duration=float(current["target_duration"]))
prompt += (" Motion constraints: intentional still portrait; no cut, transition, playing, key motion, limb motion, or camera motion. "
           f"Narrative function: {beat['new_information']} Important visible props: grand piano, gray work shirt. "
           "The clip must communicate only this beat, not the entire hook.")
fingerprint = hashlib.sha256(f"part8-flow-clean-frame-supportive-v1|{source_selected['sha256']}|1.000|{prompt}".encode("utf-8")).hexdigest()
request_id = "req_" + fingerprint[:20]
current.update({"request_id": request_id, "fingerprint": fingerprint, "prompt": prompt, "depends_on": [],
                "reference_asset_ids": [], "hook_beat": beat, "motion_contract": clip,
                "repair_mode": "SUPPORTIVE_STILL_VIDEO_FROM_VALIDATED_EXACT_FLOW_FRAME",
                "prompt_version": "story-auto-flow-motion-prompt/1.4.0-derived-still",
                "supersedes_request_ids": list(dict.fromkeys(current.get("supersedes_request_ids", []) + [old_id])),
                "derived_source_request_id": source_request_id, "derived_source_time": 1.0})
validate_generation_requests(document, read_json(output / "media_plan.json"), read_json(output / "continuity_bible.json"))
atomic_write_json(output / "generation_requests.json", document)

frame = root / f"assets/derived/{request_id}/flow_source_frame_001.png"
frame.parent.mkdir(parents=True, exist_ok=True)
run_command(["ffmpeg", "-y", "-ss", "1.000", "-i", str(source), "-frames:v", "1", str(frame)])
target = root / f"assets/video/{request_id}/derived_still_001.mp4"
compile_image(frame, target, duration=float(current["target_duration"]), motion="STATIC",
              target=MediaTarget(width=1920, height=1080, fps=30), finishing_profile="NONE")
metadata = validate_video(target)
if any(item.get("selected_asset", {}).get("sha256") == metadata["sha256"] for item in manifest["requests"]):
    raise SystemExit("DERIVED_VIDEO_HASH_NOT_UNIQUE")
entry = {"request_id": request_id, "request_identity_sha256": fingerprint, "related_identity": current["shot_id"],
         "media_type": "VIDEO", "provider": "google_flow", "prompt_sha256": fingerprint,
         "reference_asset_hashes": [], "attempts": [], "status": "QC_PENDING", "created_at": now()}
attempt = {"attempt": 1, "status": "SUCCEEDED", "dispatch_origin": "deterministic_supportive_video_from_exact_flow_frame",
           "source_request_id": source_request_id, "source_asset_sha256": source_selected["sha256"],
           "source_time_seconds": 1.0, "source_frame_sha256": sha256_file(frame),
           "asset_path": str(target.relative_to(root)).replace("\\", "/"), "asset_sha256": metadata["sha256"],
           "metadata": metadata, "completed_at": now()}
entry["attempts"].append(attempt)
entry["selected_asset"] = {"path": attempt["asset_path"], "sha256": metadata["sha256"], "attempt": 1,
                           "metadata": metadata, "production_qc": "PENDING",
                           "derived_source_request_id": source_request_id, "derived_source_time": 1.0}
manifest["requests"].append(entry)
atomic_write_json(output / "generation_manifest.json", manifest)
atomic_write_json(output / "part8_flow_frame_supportive_decision.json", {
    "schema_version": "story-auto-flow-frame-supportive-video/1.0.0", "old_request_id": old_id,
    "new_request_id": request_id, "source_request_id": source_request_id,
    "source_asset_sha256": source_selected["sha256"], "source_time_seconds": 1.0,
    "derived_asset_sha256": metadata["sha256"],
    "policy": "CLEAN_FRAME_AFTER_VALIDATED_0.25_SECOND_CONTAMINATION; STATIC_SUPPORTIVE_VIDEO; FRESH_SEMANTIC_AND_TEMPORAL_QC_REQUIRED"})
print({"request_id": request_id, "source_request_id": source_request_id, "sha256": metadata["sha256"]})

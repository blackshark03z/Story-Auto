"""Give only currently ambiguous hook requests fresh deterministic identities."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.planning.service import validate_generation_requests


parser = argparse.ArgumentParser()
parser.add_argument("project_root", type=Path)
args = parser.parse_args()
root = args.project_root.resolve()
output = root / "output"
document = read_json(output / "generation_requests.json")
manifest = {item["request_id"]: item for item in read_json(output / "generation_manifest.json")["requests"]}
replacements = []
for item in document["requests"]:
    if item.get("purpose") != "SHOT" or item.get("shot_id") != "sh_0001":
        continue
    entry = manifest.get(item["request_id"], {})
    if entry.get("status") != "AMBIGUOUS" and entry.get("failure_class") != "FLOW_STALE_RESULT":
        continue
    old_id = item["request_id"]
    if int(item.get("part_index", 0)) in {5, 8}:
        # Repeated reference-to-video jobs for the supportive custodian
        # portrait remained stuck. The shot's text already carries the
        # continuity traits; use text-to-video to remove the fragile uploaded
        # reference workflow while keeping the same semantic contract.
        item["depends_on"] = []
        item["reference_asset_ids"] = []
    fingerprint = hashlib.sha256(f"flow-attribution-retry-v2|{old_id}|{item['fingerprint']}".encode("utf-8")).hexdigest()
    item["request_id"] = "req_" + fingerprint[:20]
    item["fingerprint"] = fingerprint
    item["supersedes_request_ids"] = list(dict.fromkeys(item.get("supersedes_request_ids", []) + [old_id]))
    item["repair_mode"] = ("ATTRIBUTION_RETRY_TEXT_TO_VIDEO_AFTER_REFERENCE_TIMEOUTS"
                           if int(item.get("part_index", 0)) in {5, 8} else "ATTRIBUTION_RETRY_AFTER_DISPATCH_ACK_FIX")
    replacements.append({"part_index": item["part_index"], "old_request_id": old_id, "new_request_id": item["request_id"],
                         "reason": entry.get("failure_class")})

validate_generation_requests(document, read_json(output / "media_plan.json"), read_json(output / "continuity_bible.json"))
atomic_write_json(output / "generation_requests.json", document)
atomic_write_json(output / "hook_ambiguous_rekey.json", {
    "schema_version": "story-auto-hook-ambiguous-rekey/1.0.0",
    "replacements": replacements,
    "policy": "ONLY_AMBIGUOUS_REQUESTS_RECEIVE_FRESH_IDENTITIES; NO_PROVIDER_RESULT_ADOPTED",
})
print({"rekeyed": len(replacements), "replacements": replacements})

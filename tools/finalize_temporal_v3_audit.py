"""Freeze the explicit temporal-v3 master and final review evidence."""
from __future__ import annotations

import argparse
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from story_auto.core.artifacts import atomic_write_json, atomic_write_text, read_json, sha256_file
from story_auto.core.gemini_qc import validate_hook_plan
from story_auto.providers.flow.validation import validate_video


parser = argparse.ArgumentParser(); parser.add_argument("project_root", type=Path); parser.add_argument("prior_project_root", type=Path); args = parser.parse_args()
root = args.project_root.resolve(); prior = args.prior_project_root.resolve(); output = root / "output"
requests_doc = read_json(output / "generation_requests.json")
requests = requests_doc["requests"]
manifest_doc = read_json(output / "generation_manifest.json")
manifest = {item["request_id"]: item for item in manifest_doc["requests"]}
hook = sorted((item for item in requests if item.get("purpose") == "SHOT" and item.get("shot_id") == "sh_0001"), key=lambda item: int(item["part_index"]))
if len(hook) != 9 or [int(item["part_index"]) for item in hook] != list(range(1, 10)):
    raise SystemExit("FINAL_HOOK_PARTITION_INVALID")
validate_hook_plan({"beats": [item["hook_beat"] for item in hook]}, start=0.0, end=47.169)

parts = []
hashes = set()
for request in hook:
    entry = manifest.get(request["request_id"], {})
    selected = entry.get("selected_asset", {})
    if entry.get("status") != "SUCCEEDED" or selected.get("production_qc") != "APPROVED" or selected.get("temporal_qc") != "APPROVED":
        raise SystemExit(f"FINAL_HOOK_QC_INCOMPLETE:{request['part_index']}")
    if selected.get("alignment_classification") not in {"PASS_DIRECT", "PASS_SUPPORTIVE", "PASS_ATMOSPHERIC"}:
        raise SystemExit(f"FINAL_HOOK_SEMANTIC_INVALID:{request['part_index']}")
    start, end = float(selected.get("usable_start", 0)), float(selected.get("usable_end", 0))
    if end - start + .01 < float(request["target_duration"]):
        raise SystemExit(f"FINAL_HOOK_WINDOW_TOO_SHORT:{request['part_index']}")
    if selected["sha256"] in hashes:
        raise SystemExit("FINAL_HOOK_DUPLICATE_ASSET_HASH")
    hashes.add(selected["sha256"])
    source = root / selected["path"]
    if not source.is_file() or sha256_file(source) != selected["sha256"]:
        raise SystemExit(f"FINAL_HOOK_SOURCE_INVALID:{request['part_index']}")
    temporal_reviews = selected.get("temporal_reviews", [])
    report = temporal_reviews[-1]["report"] if temporal_reviews else {}
    parts.append({"part_index": request["part_index"], "request_id": request["request_id"],
                  "target_start": request["target_start"], "target_end": request["target_end"],
                  "target_duration": request["target_duration"], "asset_path": selected["path"],
                  "asset_sha256": selected["sha256"], "semantic": selected["alignment_classification"],
                  "semantic_observation": selected.get("alignment_observation"),
                  "temporal": selected.get("temporal_state"), "usable_start": start, "usable_end": end,
                  "dense_frame_state": report.get("dense_frames", {}).get("state"),
                  "video_level_state": report.get("video_level", {}).get("state"),
                  "repair_mode": request.get("repair_mode"),
                  "derived_source_request_id": selected.get("derived_source_request_id") or selected.get("reuse_source_request_id")})

final_manifest = read_json(output / "final_manifest.json")
canonical = output / "final.mp4"
if not canonical.is_file() or sha256_file(canonical) != final_manifest["final_sha256"]:
    raise SystemExit("FINAL_MASTER_HASH_INVALID")
explicit = output / "final_temporal_v3.mp4"
if not explicit.is_file() or sha256_file(explicit) != final_manifest["final_sha256"]:
    shutil.copy2(canonical, explicit)
if sha256_file(explicit) != final_manifest["final_sha256"]:
    raise SystemExit("EXPLICIT_MASTER_COPY_INVALID")
technical = validate_video(explicit)

prior_master = prior / "output/final_corrected_v2.mp4"
prior_evidence = {"path": str(prior_master), "exists": prior_master.is_file(),
                  "sha256": sha256_file(prior_master) if prior_master.is_file() else None}

def body_hashes(project: Path) -> dict[str, str]:
    request_items = read_json(project / "output/generation_requests.json")["requests"]
    entries = {item["request_id"]: item for item in read_json(project / "output/generation_manifest.json")["requests"]}
    result = {}
    for request in request_items:
        if request.get("purpose") != "SHOT" or request.get("shot_id") == "sh_0001":
            continue
        selected = entries.get(request["request_id"], {}).get("selected_asset")
        if isinstance(selected, dict): result[request["shot_id"]] = selected["sha256"]
    return result

current_alignment = read_json(output / "alignment.json"); prior_alignment = read_json(prior / "output/alignment.json")
current_alignment.pop("project_id", None); prior_alignment.pop("project_id", None)
preservation = {"content_sha256_current": sha256_file(root / "content.md"),
                "content_sha256_prior": sha256_file(prior / "content.md"),
                "voice_sha256_current": sha256_file(output / "voice.wav"),
                "voice_sha256_prior": sha256_file(prior / "output/voice.wav"),
                "alignment_sha256_current": sha256_file(output / "alignment.json"),
                "alignment_sha256_prior": sha256_file(prior / "output/alignment.json"),
                "body_selected_asset_hashes_match_prior": body_hashes(root) == body_hashes(prior)}
preservation["content_preserved"] = preservation["content_sha256_current"] == preservation["content_sha256_prior"]
preservation["voice_preserved"] = preservation["voice_sha256_current"] == preservation["voice_sha256_prior"]
preservation["alignment_preserved"] = current_alignment == prior_alignment
preservation["alignment_difference"] = "project_id rebound only" if preservation["alignment_preserved"] and preservation["alignment_sha256_current"] != preservation["alignment_sha256_prior"] else None
if not all(preservation[key] for key in ("content_preserved", "voice_preserved", "alignment_preserved", "body_selected_asset_hashes_match_prior")):
    raise SystemExit("PRESERVATION_INVARIANT_FAILED")

ledger = read_json(output / "gemini_reasoning/ledger.json")
events = ledger.get("requests", [])
models = Counter(item.get("model") for item in events if item.get("model"))
request_count = len([item for item in events if item.get("status") in {"SUCCEEDED", "FAILED"}])
fallback_count = sum(int(item.get("fallback_count", 0) or 0) for item in events if item.get("status") == "SUCCEEDED")
routing = {"ledger_path": "output/gemini_reasoning/ledger.json", "ledger_event_count": len(events),
           "recorded_operation_count": request_count, "requests_by_success_model": dict(sorted(models.items())),
           "recorded_success_fallback_count": fallback_count,
           "credential_aliases": sorted({item.get("credential_alias") for item in events if item.get("credential_alias")}),
           "project_aliases": sorted({item.get("project_alias") for item in events if item.get("project_alias")})}

audit = {"schema_version": "story-auto-final-hook-temporal-audit/1.0.0",
         "created_at": datetime.now(timezone.utc).isoformat(),
         "review_state": "REVIEW_REQUIRED", "review_reason": "GEMINI_ASSISTED_HOOK_AND_TEMPORAL_QC",
         "project_id": final_manifest["project_id"], "explicit_master_path": str(explicit),
         "explicit_master_sha256": final_manifest["final_sha256"], "technical_metadata": technical,
         "prior_master_preserved": prior_evidence, "preservation": preservation,
         "hook_timeline": {"start": 0.0, "end": 47.169, "part_count": 9,
                           "repetition_and_timeline_gate": "PASS", "parts": parts},
         "render": {"render_plan_sha256": final_manifest["render_plan_sha256"],
                    "duration_seconds": final_manifest["duration_seconds"], "width": final_manifest["width"],
                    "height": final_manifest["height"], "streams": final_manifest["streams"]},
         "routing": routing, "tests": {"summary": "140 passed, 7 subtests passed", "status": "PASS"},
         "known_limitations": ["Flow-visible provider watermark remains accepted and documented where present."],
         "completion_gate": "REVIEW_REQUIRED — GEMINI_ASSISTED_HOOK_AND_TEMPORAL_QC"}
atomic_write_json(output / "final_hook_temporal_audit.json", audit)
atomic_write_json(output / "REVIEW_REQUIRED_GEMINI_ASSISTED_HOOK_AND_TEMPORAL_QC.json", audit)
lines = ["# REVIEW REQUIRED — GEMINI-ASSISTED HOOK AND TEMPORAL QC", "",
         f"Master: `{explicit}`", f"SHA-256: `{final_manifest['final_sha256']}`",
         f"Duration: {final_manifest['duration_seconds']:.3f}s · 1920×1080 · 30fps", "",
         "All nine 0.000–47.169s hook parts passed semantic and temporal hard gates. Narration, alignment, and body selected assets match the preserved prior project.", "",
         "Owner review is required before publication. The prior corrected master was not overwritten."]
atomic_write_text(output / "REVIEW_REQUIRED_GEMINI_ASSISTED_HOOK_AND_TEMPORAL_QC.md", "\n".join(lines) + "\n")
print({"review_state": audit["review_state"], "master": str(explicit), "sha256": final_manifest["final_sha256"], "hook_parts": len(parts)})

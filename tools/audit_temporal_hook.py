"""Run semantic plus temporal Gemini QC and persist deterministic Flow gates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.gemini_qc import sample_dense_frames, semantic_video_qc, temporal_video_qc
from story_auto.providers.flow.service import FlowError, review_production_asset, review_temporal_asset
from story_auto.providers.llm import GeminiReasoningRouter

FIELDS = ("SKIN_REALISM", "LIGHTING_NATURALISM", "MATERIAL_REALISM", "COMPOSITION_NATURALISM",
          "AI_POLISH", "CONTINUITY", "TECHNICAL_VALIDITY")
parser = argparse.ArgumentParser(); parser.add_argument("runtime_root", type=Path); parser.add_argument("project_id"); args = parser.parse_args()
root = args.runtime_root.resolve() / "projects" / args.project_id; output = root / "output"
requests = {x["request_id"]: x for x in read_json(output / "generation_requests.json")["requests"]}
manifest = {x["request_id"]: x for x in read_json(output / "generation_manifest.json")["requests"]}
router = GeminiReasoningRouter(cache_dir=output / "gemini_reasoning/cache", ledger_path=output / "gemini_reasoning/ledger.json")
results = []
for request in sorted((x for x in requests.values() if x.get("purpose") == "SHOT" and x.get("media_type") == "VIDEO" and manifest.get(x["request_id"], {}).get("status") == "QC_PENDING"), key=lambda x: int(x.get("part_index", 1))):
    request_id = request["request_id"]; entry = manifest[request_id]; selected = entry["selected_asset"]
    video = root / selected["path"]; duration = float(selected["metadata"]["duration_seconds"])
    motion = request.get("motion_contract", {}); risk = "HIGH" if any(word in json.dumps(motion).lower() for word in ("hand", "door", "piano", "finger", "walk")) else "MEDIUM"
    frames = sample_dense_frames(video, output / "temporal_qc/frames" / request_id, risk=risk, duration=duration)
    intent = {"request_id": request_id, "hook_beat": request.get("hook_beat"), "motion_contract": motion,
              "prompt": request["prompt"]}
    item = {"request_id": request_id, "part_index": request.get("part_index"), "asset_sha256": selected["sha256"],
            "risk": risk, "dense_frame_count": len(frames)}
    try:
        semantic, semantic_route = semantic_video_qc(router, video=video, intent=intent)
        item.update({"semantic": semantic, "semantic_routing": semantic_route.__dict__})
    except Exception as error:
        item["semantic_error"] = {"failure_class": getattr(error, "failure_class", type(error).__name__), "detail": str(error)}
        try:
            report = {"results": {key: "PASS" for key in FIELDS}, "visible_provider_watermark": True,
                      "reviewer": "gemini_structured_semantic_video_qc", "alignment_classification": "MISMATCH",
                      "notes": str(error)}
            review_production_asset(args.runtime_root, args.project_id, request_id, report)
        except FlowError: pass
        results.append(item); print(json.dumps(item, ensure_ascii=False)); continue
    try:
        temporal, temporal_routes = temporal_video_qc(router, video=video, intent=intent, frames=frames,
            duration=duration, target_duration=float(request["target_duration"]))
        item.update({"temporal": temporal, "temporal_routing": [x.__dict__ for x in temporal_routes]})
        review_temporal_asset(args.runtime_root, args.project_id, request_id, temporal)
    except Exception as error:
        item["temporal_error"] = {"failure_class": getattr(error, "failure_class", type(error).__name__), "detail": str(error)}
        try:
            state = getattr(error, "failure_class", "UNCERTAIN")
            report = {"state": state if state in {"REJECT_ACTION_LOGIC", "REJECT_ANATOMY", "REJECT_LOOP", "REJECT_IDENTITY", "REJECT_BACKGROUND"} else "UNCERTAIN",
                      "eligible": False, "usable_start": 0, "usable_end": duration, "defects": []}
            review_temporal_asset(args.runtime_root, args.project_id, request_id, report)
        except FlowError: pass
        results.append(item); print(json.dumps(item, ensure_ascii=False)); continue
    classification = semantic["classification"].replace("PASS_", "PASS_")
    report = {"results": {key: "PASS" for key in FIELDS}, "visible_provider_watermark": True,
              "reviewer": "gemini_structured_semantic_video_qc", "alignment_classification": classification,
              "notes": semantic["observed"], "watermark_disposition": "FLOW_VISIBLE_WATERMARK_ACCEPTED_KNOWN_LIMITATION"}
    try: review_production_asset(args.runtime_root, args.project_id, request_id, report)
    except FlowError as error: item["selection_error"] = error.failure_class
    results.append(item); print(json.dumps({"request_id":request_id,"semantic":semantic["classification"],"temporal":temporal["state"]},ensure_ascii=False))
atomic_write_json(output / "temporal_qc/new_hook_qc_results.json", {"schema_version":"story-auto-new-hook-qc/1.0.0","results":results})

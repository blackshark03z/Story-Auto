"""Ask Gemini for material repairs for rejected, exactly attributed hook clips."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.gemini_qc import repair_plan
from story_auto.providers.llm import GeminiReasoningRouter


parser = argparse.ArgumentParser()
parser.add_argument("project_root", type=Path)
args = parser.parse_args()
root = args.project_root.resolve()
output = root / "output"
requests = {item["request_id"]: item for item in read_json(output / "generation_requests.json")["requests"]}
manifest = {item["request_id"]: item for item in read_json(output / "generation_manifest.json")["requests"]}
qc_items = {item["request_id"]: item for item in read_json(output / "temporal_qc/new_hook_qc_results.json")["results"]}


def cached_semantic(request_id: str) -> dict:
    for path in (output / "gemini_reasoning/cache").glob("*.json"):
        item = read_json(path)
        identity = item.get("identity", {})
        if identity.get("task") == "semantic_video_qc" and request_id in str(identity.get("prompt", "")):
            return item.get("value", {})
    return {}


def cached_temporal(request_id: str) -> dict:
    views = {}
    for path in (output / "gemini_reasoning/cache").glob("*.json"):
        item = read_json(path)
        identity = item.get("identity", {})
        task = identity.get("task")
        if task in {"temporal_video_qc", "dense_frame_temporal_qc"} and request_id in str(identity.get("prompt", "")):
            views[task] = item.get("value", {})
    if not views:
        return {}
    defects = []
    for value in views.values():
        defects.extend(value.get("defects", []))
    return {"state": "UNCERTAIN", "eligible": False, "usable_start": 0.0, "usable_end": 0.0,
            "defects": defects, "independent_views": views,
            "gate_reason": "independent usable windows do not overlap for the target duration"}


router = GeminiReasoningRouter(cache_dir=output / "gemini_reasoning/cache", ledger_path=output / "gemini_reasoning/ledger.json")
plans = []
failed_hook = [item for item in requests.values() if item.get("purpose") == "SHOT" and item.get("shot_id") == "sh_0001"
               and manifest.get(item["request_id"], {}).get("status") == "FAILED_RETRYABLE"]
for request in sorted(failed_hook, key=lambda item: int(item.get("part_index", 0))):
    request_id = request["request_id"]
    qc = qc_items.get(request_id, {})
    entry = manifest[request_id]
    if entry.get("status") != "FAILED_RETRYABLE":
        continue
    semantic = qc.get("semantic") or cached_semantic(request_id)
    temporal = qc.get("temporal") or cached_temporal(request_id) or {
        "state": "REJECT_ACTION_LOGIC",
        "eligible": False,
        "usable_start": 0.0,
        "usable_end": 0.0,
        "defects": [{"class": "SEMANTIC_MISMATCH", "severity": "SEVERE", "start": 0.0,
                     "end": float(request.get("target_duration", 0.0)),
                     "evidence": json.dumps(semantic, ensure_ascii=False, sort_keys=True)}],
    }
    intent = {"request_id": request_id, "hook_beat": request.get("hook_beat"),
              "motion_contract": request.get("motion_contract"), "semantic_qc": semantic}
    plan, route = repair_plan(router, intent=intent, prior_prompt=request["prompt"], temporal_result=temporal)
    plans.append({"request_id": request_id, "part_index": request.get("part_index"), "repair_plan": plan,
                  "routing": route.__dict__})
    print(json.dumps({"part_index": request.get("part_index"), "request_id": request_id,
                      "regeneration_needed": plan["regeneration_needed"], "model": route.model}, ensure_ascii=False))

atomic_write_json(output / "hook_repair_plans_gemini.json", {
    "schema_version": "story-auto-hook-repair-batch/1.0.0",
    "plans": plans,
})

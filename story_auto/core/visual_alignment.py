"""Durable visual/narration alignment audit and asset-reuse diagnostics."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

ALIGNMENT_SCHEMA_VERSION = "story-auto-visual-narration-alignment/1.0.0"

def classify_semantic_alignment(expected: dict[str, Any], observed: dict[str, Any]) -> str:
    """Classify a structured multimodal observation against shot intent."""
    # Mandatory contradictions override even a claimed passing label.
    if observed.get("contradictions") or any(observed.get(key) is False for key in (
        "primary_subject_compatible", "action_compatible", "location_compatible",
        "critical_props_present", "continuity_acceptable",
    )):
        return "MISMATCH"
    explicit = observed.get("classification") or observed.get("alignment_classification")
    if explicit in {"PASS_DIRECT", "PASS_SUPPORTIVE", "PASS_ATMOSPHERIC", "MISMATCH"}:
        if explicit == "PASS_ATMOSPHERIC" and not expected.get("atmospheric"):
            return "MISMATCH"
        return explicit
    mandatory = {str(x).lower() for x in expected.get("mandatory_characters", []) if x}
    required = {str(x).lower() for x in expected.get("characters", []) + expected.get("props", []) if x}
    seen = {str(x).lower() for x in observed.get("characters", []) + observed.get("props", []) if x}
    if mandatory and not mandatory.issubset(seen):
        return "MISMATCH"
    if required and not required.intersection(seen):
        return "MISMATCH"
    return "PASS_SUPPORTIVE" if seen else "PASS_ATMOSPHERIC"


def _excerpt(alignment: dict[str, Any], ids: list[str]) -> str:
    wanted = set(ids)
    return " ".join(str(s.get("text", "")).strip() for s in alignment.get("segments", [])
                    if s.get("segment_id") in wanted).strip()


def _intent(shot: dict[str, Any]) -> dict[str, Any]:
    return {"subject": shot.get("subject"), "action": shot.get("action"),
            "location": shot.get("location_id"), "props": shot.get("prop_ids", []),
            "characters": shot.get("character_ids", []),
            "emotional_beat": shot.get("visual_emotional_purpose")}


def _durable_classification(selected: dict[str, Any] | None, shot: dict[str, Any]) -> str:
    value = (selected or {}).get("alignment_classification")
    mapping = {
        "PASS_DIRECT": "DIRECT",
        "PASS_SUPPORTIVE": "SUPPORTIVE",
        "PASS_ATMOSPHERIC": "ATMOSPHERIC",
        "MISMATCH": "MISMATCH",
    }
    if value in mapping:
        return mapping[value]
    return "ATMOSPHERIC" if shot.get("atmospheric") else "UNREVIEWED"


def build_shot_mapping_audit(*, alignment: dict[str, Any], shot_plan: dict[str, Any],
                             media_plan: dict[str, Any], generation_requests: dict[str, Any],
                             generation_manifest: dict[str, Any], render_plan: dict[str, Any]) -> dict[str, Any]:
    requests = {r.get("request_id"): r for r in generation_requests.get("requests", []) if isinstance(r, dict)}
    manifest = {r.get("request_id"): r for r in generation_manifest.get("requests", []) if isinstance(r, dict)}
    media = {m.get("shot_id"): m for m in media_plan.get("shots", []) if isinstance(m, dict)}
    rendered = defaultdict(list)
    for seg in render_plan.get("segments", []): rendered[seg.get("shot_id")].append(seg)
    rows = []
    for shot in shot_plan.get("shots", []):
        sid = shot.get("shot_id"); reqs = [r for r in generation_requests.get("requests", [])
                if r.get("purpose") == "SHOT" and r.get("shot_id") == sid]
        for seg in rendered.get(sid, []) or [{"target_start": shot.get("start"), "target_end": shot.get("end")}]:
            rid = (seg.get("provenance") or {}).get("request_id")
            req = requests.get(rid) if rid else (reqs[0] if len(reqs) == 1 else None)
            entry = manifest.get(rid, {}) if rid else {}
            selected = entry.get("selected_asset") if isinstance(entry, dict) else None
            rows.append({"shot_id": sid, "scene_id": shot.get("scene_id"),
                "narration_start": shot.get("start"), "narration_end": shot.get("end"),
                "narration_excerpt": _excerpt(alignment, shot.get("narration_segment_ids", [])),
                "intended": _intent(shot), "generation_request_id": rid,
                "request_prompt": (req or {}).get("prompt"),
                "selected_attempt": (selected or {}).get("attempt"),
                "selected_asset_path": (selected or {}).get("path") or seg.get("source_asset"),
                "selected_asset_sha": (selected or {}).get("sha256") or seg.get("source_hash"),
                "render_plan_entry": seg, "normalized_clip": f"output/scenes/{seg.get('segment_id', sid)}.mp4",
                "final_timeline_start": seg.get("target_start", shot.get("start")),
                "final_timeline_end": seg.get("target_end", shot.get("end")),
                "explicit_atmospheric": bool(shot.get("atmospheric")),
                "alignment_observation": (selected or {}).get("alignment_observation"),
                "alignment_classification": _durable_classification(selected, shot)})
    by_sha = defaultdict(list)
    for row in rows:
        if row["selected_asset_sha"]: by_sha[row["selected_asset_sha"]].append(row)
    for values in by_sha.values():
        if len({r["shot_id"] for r in values}) > 1:
            for row in values:
                row["alignment_classification"] = "MISMATCH"
    reuse = []
    longest_continuous = 0.0
    for sha, values in by_sha.items():
        ordered = sorted(values, key=lambda r: float(r["final_timeline_start"] or 0))
        durations = [float(r["final_timeline_end"] or 0) - float(r["final_timeline_start"] or 0) for r in ordered]
        run_start = run_end = None
        longest = 0.0
        for row in ordered:
            start, end = float(row["final_timeline_start"] or 0), float(row["final_timeline_end"] or 0)
            if run_end is not None and abs(start - run_end) <= .01:
                run_end = end
            else:
                if run_start is not None: longest = max(longest, run_end - run_start)
                run_start, run_end = start, end
        if run_start is not None: longest = max(longest, run_end - run_start)
        longest_continuous = max(longest_continuous, longest)
        if len(values) > 1:
            narration_spans = {(r["narration_start"], r["narration_end"]) for r in values}
            cross_shot = len({r["shot_id"] for r in values}) > 1
            reuse.append({"sha256": sha, "shot_ids": [r["shot_id"] for r in values],
                          "reuse_count": len(values), "narration_span_count": len(narration_spans),
                          "cumulative_screen_duration": sum(durations),
                          "longest_continuous_screen_duration": longest,
                          "suspicious_unplanned_reuse": cross_shot})
    classes = {name: sum(r["alignment_classification"] == name for r in rows)
               for name in ("DIRECT", "SUPPORTIVE", "ATMOSPHERIC", "MISMATCH", "UNREVIEWED")}
    cross_shot_reuse = any(len({r["shot_id"] for r in values}) > 1 for values in by_sha.values())
    return {"schema_version": ALIGNMENT_SCHEMA_VERSION, "rows": rows,
            "metrics": {"total_final_shots": len(rows), "unique_selected_asset_hashes": len(by_sha),
                        "unique_asset_ratio": (len(by_sha) / len(rows)) if rows else 0.0,
                        "asset_reuse": reuse, "max_asset_reuse_count": max((x["reuse_count"] for x in reuse), default=1),
                        "longest_continuous_asset_use_seconds": longest_continuous,
                        "maximum_single_still_screen_duration_seconds": max((
                            float(r["final_timeline_end"] or 0) - float(r["final_timeline_start"] or 0)
                            for r in rows if r.get("render_plan_entry", {}).get("source_media_type") == "IMAGE"
                        ), default=0.0),
                        "maximum_narration_spans_per_asset": max((x["narration_span_count"] for x in reuse), default=1),
                        "classification_counts": classes,
                        "mismatch_count": classes["MISMATCH"],
                        "unreviewed_count": classes["UNREVIEWED"]},
            "root_cause": "UNPLANNED_CROSS_SHOT_REUSE" if cross_shot_reuse else "NONE_CORRECTED",
            "acceptance": "REVIEW_REQUIRED"}


def validate_visual_alignment_audit(value: dict[str, Any]) -> None:
    if value.get("schema_version") != ALIGNMENT_SCHEMA_VERSION or not isinstance(value.get("rows"), list):
        raise ValueError("VISUAL_NARRATION_ALIGNMENT_INVALID")
    if value.get("metrics", {}).get("mismatch_count", 0):
        raise ValueError("VISUAL_NARRATION_ALIGNMENT_MISMATCH")
    if value.get("metrics", {}).get("unreviewed_count", 0):
        raise ValueError("VISUAL_NARRATION_ALIGNMENT_QC_REQUIRED")

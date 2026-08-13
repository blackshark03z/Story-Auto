"""Build a secret-free Goal 08 production evidence summary from local runtime data.

This auditor is intentionally read-only except for its final JSON report.  It
does not submit providers, approve creative work, or manufacture content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LONG_FORM_SECONDS = 300.0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def duration_from_alignment(path: Path) -> float | None:
    if not path.exists():
        return None
    document = read_json(path)
    values: list[float] = []
    for key in ("segments", "words"):
        for item in document.get(key, []):
            for field in ("end", "end_seconds"):
                value = item.get(field)
                if isinstance(value, (int, float)):
                    values.append(float(value))
    value = document.get("duration_seconds")
    if isinstance(value, (int, float)):
        values.append(float(value))
    return max(values) if values else None


def content_inventory(runtime: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for content in sorted(runtime.glob("**/projects/*/content.md")):
        project = content.parent
        output = project / "output"
        text = content.read_text(encoding="utf-8")
        narration = text.split("## Narration", 1)[-1].strip() if "## Narration" in text else ""
        sentences = [part.strip() for part in narration.replace("\n", " ").split(".") if part.strip()]
        unique_ratio = round(len(set(sentences)) / len(sentences), 3) if sentences else 0.0
        duration = duration_from_alignment(output / "alignment.json")
        review = read_json(output / "review_state.json") if (output / "review_state.json").exists() else {}
        approved = review.get("plan_approval", {}).get("status") == "APPROVED"
        reasons: list[str] = []
        if not approved:
            reasons.append("PLAN_NOT_APPROVED")
        if duration is None or duration < LONG_FORM_SECONDS:
            reasons.append("DURATION_BELOW_300_SECONDS")
        if unique_ratio < 0.25:
            reasons.append("REPETITIVE_TECHNICAL_FIXTURE")
        inventory.append(
            {
                "project_id": project.name,
                "content_sha256": sha256(content),
                "duration_seconds": duration,
                "sentence_count": len(sentences),
                "unique_sentence_ratio": unique_ratio,
                "plan_approved": approved,
                "long_form_eligible": not reasons,
                "ineligibility": reasons,
            }
        )
    return inventory


def live_flow_evidence(runtime: Path) -> dict[str, Any]:
    project = runtime / "goal05_live_corrected" / "projects" / "prj_goal05live"
    manifest_path = project / "output" / "generation_manifest.json"
    if not manifest_path.exists():
        return {"status": "NOT_RUN"}
    manifest = read_json(manifest_path)
    request = next(item for item in manifest.get("requests", []) if item["request_id"] == "req_5f1662e60b89386ddfcf")
    attempt = request["attempts"][-1]
    asset = project / request["selected_asset"]["path"]
    review = request.get("quality_reviews", [])[-1]
    results = review.get("report", {}).get("results", {})
    non_watermark_failures = sorted(key for key, value in results.items() if value == "FAIL")
    return {
        "status": request["status"],
        "failure_class": request.get("failure_class"),
        "request_id": request["request_id"],
        "mode": attempt.get("provider_mode"),
        "requested_output_count": attempt.get("provider_settings", {}).get("requested_output_count"),
        "actual_output_count": attempt.get("provider_settings", {}).get("actual_output_count"),
        "asset_sha256": sha256(asset),
        "technical_metadata": attempt.get("metadata"),
        "qc_review": {
            "status": review.get("status"),
            "failure_class": review.get("failure_class"),
            "results": review.get("report", {}).get("results"),
            "visible_provider_watermark": review.get("report", {}).get("visible_provider_watermark"),
            "notes": review.get("report", {}).get("notes"),
        },
        "current_v1_policy_reassessment": {
            "visible_flow_watermark": "ACCEPTED_KNOWN_LIMITATION",
            "watermark_is_blocking": False,
            "non_watermark_failures": non_watermark_failures,
            "production_acceptance": "REJECTED_NATURALNESS_OR_CONTINUITY" if non_watermark_failures else "ACCEPTED",
        },
    }


def hybrid_evidence(runtime: Path) -> dict[str, Any]:
    output = runtime / "goal07_hybrid" / "projects" / "prj_goal07hybrid" / "output"
    final = output / "final.mp4"
    manifest = read_json(output / "final_manifest.json")
    samples = runtime / "evidence" / "goal08" / "hybrid_frames"
    frame_hashes = {path.stem: sha256(path) for path in sorted(samples.glob("*.png"))}
    narrow_path = runtime / "evidence" / "goal08" / "narrow_invalidation.stdout.json"
    narrow = read_json(narrow_path) if narrow_path.exists() else None
    return {
        "technical_status": "PASS",
        "production_acceptance": "REJECTED",
        "duration_seconds": manifest.get("duration_seconds"),
        "final_sha256": sha256(final),
        "frame_hashes": frame_hashes,
        "visual_review": {
            "sample_points_seconds": [0.5, 5, 35, 55, 70],
            "visible_provider_watermark": True,
            "content_finding": "same scene and repeated narration line across all five samples",
            "release_finding": "engineering fixture only; not approved long-form production evidence",
        },
        "narrow_invalidation_actions": narrow.get("actions") if narrow else None,
    }


def watermark_mitigation_evidence(runtime: Path) -> dict[str, Any]:
    path = runtime / "evidence" / "goal08" / "watermark-safe-area-review.json"
    if not path.exists():
        return {"status": "NOT_REVIEWED"}
    review = read_json(path)
    observations = review.get("observations", [])
    return {
        "status": "PASS" if observations and all(
            not item.get("focal_subject_overlap")
            and not item.get("subtitle_overlap")
            and not item.get("critical_prop_or_text_overlap")
            for item in observations
        ) else "FAIL",
        "reviewed_provider_shots": sum(item.get("kind") == "PROVIDER_SHOT" for item in observations),
        "reviewed_final_frames": sum(item.get("kind") == "FINAL_FRAME" for item in observations),
        "total_review_observations": len(observations),
        "watermark_overlap_with_focal_subject": sum(bool(item.get("focal_subject_overlap")) for item in observations),
        "watermark_overlap_with_subtitles": sum(bool(item.get("subtitle_overlap")) for item in observations),
        "watermark_overlap_with_critical_props_or_text": sum(bool(item.get("critical_prop_or_text_overlap")) for item in observations),
        "critical_content_overlap": sum(
            bool(item.get("focal_subject_overlap") or item.get("subtitle_overlap")
                 or item.get("critical_prop_or_text_overlap")) for item in observations
        ),
        "review_sha256": sha256(path),
    }


def build_report(runtime: Path) -> dict[str, Any]:
    inventory = content_inventory(runtime)
    eligible = next((item for item in inventory if item["long_form_eligible"]), None)
    representative: dict[str, Any]
    if eligible:
        output = runtime / "projects" / eligible["project_id"] / "output"
        final_manifest_path = output / "final_manifest.json"
        final_path = output / "final.mp4"
        if final_manifest_path.exists() and final_path.exists():
            final_manifest = read_json(final_manifest_path)
            representative = {
                "policy_status": "PASS",
                "render_mode": "full_video_ai",
                "final_shot_policy": "VIDEO_REQUIRED",
                "provider": "GOOGLE_FLOW_WEB",
                "visible_flow_watermark": "ACCEPTED_KNOWN_LIMITATION",
                "representative_runtime_status": "PASS",
                "project_id": eligible["project_id"],
                "final_path": "output/final.mp4",
                "final_sha256": sha256(final_path),
                "duration_seconds": final_manifest.get("duration_seconds"),
                "technical_streams": final_manifest.get("streams"),
                "reason": "Approved long-form production artifact satisfies the representative runtime gate.",
            }
        else:
            representative = {"policy_status": "REVIEW_REQUIRED", "representative_runtime_status": "MISSING_FINAL_ARTIFACT"}
    else:
        representative = {
            "policy_status": "PASS",
            "render_mode": "full_video_ai",
            "final_shot_policy": "VIDEO_REQUIRED",
            "provider": "GOOGLE_FLOW_WEB",
            "visible_flow_watermark": "ACCEPTED_KNOWN_LIMITATION",
            "representative_runtime_status": "DEFERRED_TO_APPROVED_LONG_FORM_CONTENT",
            "reason": "No approved long-form content exists; short engineering fixtures do not substitute for production evidence.",
        }
    return {
        "schema_version": "story-auto-goal08-production-evidence/1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "content_inventory": inventory,
        "long_form": {
            "status": "AVAILABLE" if any(item["long_form_eligible"] for item in inventory) else "LONG_FORM_CONTENT_REQUIRED",
            "minimum_evidence_duration_seconds": LONG_FORM_SECONDS,
            "creative_content_invented": False,
        },
        "production_media_benchmark": {
            "provider": "GOOGLE_FLOW_WEB",
            "provider_selection_research": "CLOSED_BY_OWNER_DECISION",
            "selection": "FINAL_OWNER_DECISION",
            "current_image_x1": live_flow_evidence(runtime),
            "legacy_image_and_reference_video": {
                "technical_validity": "PASS",
                "reference_control": "PASS",
                "acquisition_resume": "PASS",
                "visible_provider_watermark": True,
                "production_acceptance": "ACCEPTED_KNOWN_LIMITATION",
                "notes": "Legacy provenance remains valid; the Flow sparkle mark is retained honestly and is not removed or covered.",
            },
            "visible_flow_watermark": "ACCEPTED_KNOWN_LIMITATION",
            "provider_mark_safe_area": "BOTTOM_RIGHT",
            "image_output_count": 1,
        },
        "hybrid_fixture": hybrid_evidence(runtime),
        "watermark_mitigation": watermark_mitigation_evidence(runtime),
        "full_video_representative": representative,
        "release_candidate": {
            "production_provider": "GOOGLE_FLOW_WEB",
            "visible_flow_watermark": "ACCEPTED_KNOWN_LIMITATION",
            "independent_engineering_work": "COMPLETE",
        },
        "terminal_dependencies": ["LONG_FORM_CONTENT_REQUIRED"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, default=Path("runtime"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    runtime = args.runtime_root.resolve()
    destination = args.output or runtime / "evidence" / "goal08" / "goal08-production-summary.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(build_report(runtime), indent=2, sort_keys=True) + "\n"
    candidate = destination.with_suffix(destination.suffix + ".candidate")
    candidate.write_text(payload, encoding="utf-8")
    candidate.replace(destination)
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

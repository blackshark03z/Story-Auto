"""Canonical production-state projection for the project-gated Hybrid Visual CUJ."""
from __future__ import annotations

from typing import Any

from story_auto.core.artifacts import read_json, sha256_file
from story_auto.core.visual.opening_builder import opening_builder_view
from story_auto.core.visual.hybrid_body import hybrid_body_view
from story_auto.core.visual.hybrid_render import hybrid_preview_readiness, hybrid_final_input_binding


HYBRID_QUALITY_PATH = "output/hybrid_quality.json"


def hybrid_cuj_enabled(config) -> bool:
    if config.render_mode != "hybrid_hook" or not isinstance(config.settings, dict):
        return False
    hybrid = config.settings.get("hybrid_visual", {})
    return isinstance(hybrid, dict) and hybrid.get("cuj_enabled") is True


def _stage(status: str, execution: str = "RUN", message: str | None = None) -> dict[str, Any]:
    return {"status": status, "execution": execution, "human_message": message}


def _valid_final(paths, config) -> bool:
    final = paths.artifact_path("output/final.mp4")
    manifest_path = paths.artifact_path("output/final_manifest.json")
    if not final.is_file() or not manifest_path.is_file():
        return False
    try:
        manifest = read_json(manifest_path)
        inputs = manifest.get("input_hashes", {}) if isinstance(manifest.get("input_hashes"), dict) else {}
        current = {
            "alignment": paths.artifact_path("output/alignment.json"),
            "opening_manifest": paths.artifact_path("output/opening_manifest.json"),
            "hybrid_body_plan": paths.artifact_path("output/hybrid_body_plan.json"),
            "hybrid_preview_manifest": paths.artifact_path("output/hybrid_preview_manifest.json"),
        }
        return (
            manifest.get("schema_version") == "story-auto-hybrid-final/1.0.0"
            and manifest.get("project_id") == paths.project_id
            and manifest.get("current_input_binding") == hybrid_final_input_binding(paths, config)
            and manifest.get("final_sha256") == sha256_file(final)
            and all(path.is_file() and inputs.get(name) == sha256_file(path) for name, path in current.items())
        )
    except Exception:
        return False


def _valid_quality(paths) -> bool:
    path = paths.artifact_path(HYBRID_QUALITY_PATH)
    if not path.is_file():
        return False
    try:
        value = read_json(path)
        inputs = value.get("input_hashes", {}) if isinstance(value.get("input_hashes"), dict) else {}
        current = {
            "alignment": paths.artifact_path("output/alignment.json"),
            "opening": paths.artifact_path("output/opening_manifest.json"),
            "body": paths.artifact_path("output/hybrid_body_plan.json"),
        }
        return (value.get("project_id") == paths.project_id and value.get("status") == "TECHNICAL_ACCEPTED"
                and all(target.is_file() and inputs.get(name) == sha256_file(target) for name, target in current.items()))
    except Exception:
        return False


def _missing_groups(readiness: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    opening: list[str] = []
    images: list[str] = []
    stock: list[str] = []
    for item in readiness.get("missing", []):
        reason = str(item.get("reason") or "")
        slot_id = str(item.get("slot_id") or "")
        if reason == "OPENING_CLIPS_REQUIRED":
            opening.append(slot_id)
        elif reason == "IMAGE_REQUIRED":
            images.append(slot_id)
        elif reason == "STOCK_OR_IMAGE_FALLBACK_REQUIRED":
            stock.append(slot_id)
    return opening, images, stock


def hybrid_production_query(paths, config, *, flow: dict[str, Any] | None = None) -> dict[str, Any]:
    """Project product-state adapter; preserves the canonical six outer stages."""
    content_ready = paths.artifact_path("output/content_manifest.json").is_file()
    timing_ready = paths.artifact_path("output/alignment.json").is_file()
    story_ready = (
        paths.artifact_path("output/story_timeline.json").is_file()
        and paths.artifact_path("output/continuity_bible.json").is_file()
    )
    opening = opening_builder_view(paths.runtime.root, paths.project_id) if timing_ready else None
    body = hybrid_body_view(paths.runtime.root, paths.project_id) if timing_ready else None
    plan_ready = story_ready and bool(opening and opening.get("status") != "NOT_CONFIGURED") and body is not None

    if timing_ready:
        readiness = hybrid_preview_readiness(paths.runtime.root, paths.project_id)
    else:
        readiness = {"status": "NOT_READY", "ready": False, "missing": [{"slot_id": "MASTER", "reason": "ALIGNMENT_REQUIRED"}]}
    opening_missing, image_missing, stock_missing = _missing_groups(readiness)
    visuals_ready = plan_ready and readiness.get("ready") is True
    quality_ready = visuals_ready and _valid_quality(paths)
    final_ready = quality_ready and _valid_final(paths, config)

    stages = {
        "SOURCE": _stage("COMPLETE" if content_ready else "READY"),
        "TIMING": _stage("COMPLETE" if timing_ready else ("READY" if content_ready else "NOT_STARTED")),
        "PLAN": _stage("COMPLETE" if plan_ready else ("READY" if timing_ready else "NOT_STARTED")),
        "VISUALS": _stage("COMPLETE" if visuals_ready else ("READY" if plan_ready else "NOT_STARTED")),
        "QUALITY": _stage("COMPLETE" if quality_ready else ("READY" if visuals_ready else "NOT_STARTED")),
        "RENDER": _stage("COMPLETE" if final_ready else ("READY" if quality_ready else "NOT_STARTED")),
    }

    blocker = None
    active_stage = next((name for name in ("SOURCE", "TIMING", "PLAN", "VISUALS", "QUALITY", "RENDER")
                         if stages[name]["status"] != "COMPLETE"), "RENDER")
    pipeline_status = "COMPLETE" if final_ready else "READY"
    next_action = {"action": "open_final", "label": "Open final video"} if final_ready else {
        "action": "run_to_final",
        "label": "Create video" if active_stage == "SOURCE" else "Continue production",
    }

    if plan_ready and opening_missing:
        blocker = {
            "reason_code": "HYBRID_OPENING_CLIPS_REQUIRED",
            "human_message": "Create the opening clips from the prepared prompts, then import each clip into its matching Opening slot.",
            "retryable": True,
            "requires_owner_decision": True,
            "stage": "VISUALS",
            "next_action": "Import opening clips",
        }
        active_stage = "VISUALS"
        pipeline_status = "OWNER_DECISION_REQUIRED"
        next_action = {"action": "focus_opening_builder", "label": "Import opening clips"}
        stages["VISUALS"] = _stage("BLOCKED", "BLOCK", blocker["human_message"])
    elif plan_ready and image_missing and isinstance(flow, dict) and flow.get("status") != "CONNECTED":
        blocker = {
            "reason_code": str(flow.get("status") or "FLOW_NOT_CONFIGURED"),
            "human_message": str(flow.get("human_message") or "Connect Flow to create the body images."),
            "retryable": True,
            "requires_owner_decision": False,
            "stage": "VISUALS",
            "next_action": str((flow.get("next_action") or {}).get("label") or "Connect Flow"),
        }
        active_stage = "VISUALS"
        pipeline_status = str(flow.get("status") or "BLOCKED")
        next_action = dict(flow.get("next_action") or {"action": "settings", "label": "Connect Flow"})
        stages["VISUALS"] = _stage("BLOCKED", "BLOCK", blocker["human_message"])

    recovery = {
        "status": "COMPLETE" if final_ready else pipeline_status,
        "reason_code": blocker["reason_code"] if blocker else None,
        "human_message": blocker["human_message"] if blocker else None,
        "automatic_recovery_available": bool(stock_missing and not image_missing),
        "provider_dispatches_per_continue": 1 if image_missing else 0,
        "requires_owner_decision": bool(blocker and blocker.get("requires_owner_decision")),
        "next_action": next_action.get("label"),
    }
    return {
        "pipeline_status": pipeline_status,
        "active_stage": active_stage,
        "stages": stages,
        "source_mode": config.settings.get("ui", {}).get("input_source", "STORY_CONTENT"),
        "quality": {
            "status": stages["QUALITY"]["status"],
            "policy": "TECHNICAL_ONLY_V1",
            "technical_passed": 1 if visuals_ready else 0,
            "pending_review": 0,
            "accepted": 1 if quality_ready else 0,
            "rejected": 0,
            "requires_owner_decision": False,
            "human_message": "Visual quality optimization is deferred; this gate checks technical integrity only.",
            "next_action": "Continue production" if visuals_ready and not quality_ready else None,
        },
        "planning": {
            "story_plan_ready": story_ready,
            "opening_plan_ready": bool(opening and opening.get("status") != "NOT_CONFIGURED"),
            "body_plan_ready": body is not None,
        },
        "recovery": recovery,
        "blocker": blocker,
        "next_action": next_action,
        "flow": flow,
        "provider_dispatches": 0,
        "hybrid": {
            "opening": opening,
            "body": body,
            "readiness": readiness,
            "missing_body_images": image_missing,
            "missing_stock": stock_missing,
        },
        "evidence": [],
        "evidence_fingerprint": None,
        "final_output": {"present": final_ready, "path": "output/final.mp4" if final_ready else None},
    }

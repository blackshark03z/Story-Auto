"""Compact, rebuildable production read model for a project.

The files inspected here remain the canonical evidence.  This module only
materializes a small operational summary for queries and coordination.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.project.execution import execution_mode, stage_policy
from story_auto.core.project.quality_policy import AI_REVIEW, AUTO_ACCEPT, MANUAL_REVIEW, effective_qc_policy
from story_auto.core.visual.recovery import (
    AttemptOutcome,
    DispatchCertainty,
    FailureFamily,
    RecoveryAction,
    RecoveryInput,
    evaluate_recovery,
)


PRODUCTION_STATE_SCHEMA_VERSION = "story-auto-production-state/1.0.8"
PRODUCTION_STAGES = ("SOURCE", "TIMING", "PLAN", "VISUALS", "QUALITY", "RENDER")
DEFAULT_STUCK_PENDING_SECONDS = 900


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def stuck_pending_evidence(entry: dict[str, Any], *, now: datetime, threshold_seconds: int) -> dict[str, Any]:
    attempts = entry.get("attempts") if isinstance(entry, dict) else None
    latest = attempts[-1] if isinstance(attempts, list) and attempts and isinstance(attempts[-1], dict) else None
    if not isinstance(latest, dict) or latest.get("terminal_evidence"):
        return {"eligible": False, "stuck": False, "deadline": None}
    settings = latest.get("provider_settings") if isinstance(latest.get("provider_settings"), dict) else {}
    binding = settings.get("provider_poll_authoritative_binding")
    lineage = latest.get("provider_lineage_card_id")
    eligible = (
        latest.get("provider_execution_state") == "PROVIDER_BOUNDARY_ENTERED"
        and latest.get("provider_submission_recorded") is True
        and latest.get("dispatch_confirmed") is True
        and isinstance(lineage, str) and bool(lineage)
        and isinstance(binding, dict)
        and binding.get("resulting_dispatch_state") == "CONFIRMED"
        and binding.get("resulting_attribution_state") == "WAITING"
        and binding.get("durable_identity_used") == "card:" + lineage
    )
    started = _instant(latest.get("provider_boundary_entered_at"))
    if not eligible or started is None:
        return {"eligible": False, "stuck": False, "deadline": None}
    deadline = started.timestamp() + threshold_seconds
    return {"eligible": True, "stuck": now.timestamp() >= deadline,
            "deadline": datetime.fromtimestamp(deadline, tz=timezone.utc).isoformat().replace("+00:00", "Z")}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read(path: Path, default: Any) -> Any:
    try:
        return read_json(path)
    except Exception:
        return default


def _signature(paths, relative: str) -> dict[str, Any]:
    path = paths.artifact_path(relative)
    if not path.is_file():
        return {"path": relative, "present": False}
    stat = path.stat()
    return {"path": relative, "present": True, "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


@dataclass(frozen=True)
class ProjectProductionState:
    """A deliberately small JSON-safe query model, never a source of truth."""

    value: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.value))

    @property
    def pipeline_status(self) -> str:
        return str(self.value["pipeline_status"])

    @property
    def active_stage(self) -> str:
        return str(self.value["active_stage"])


class ProductionStateReconciler:
    """Rebuild compact state lazily from durable project artifacts."""

    _evidence_files = (
        "output/content_manifest.json", "output/audio_manifest.json", "output/srt_manifest.json",
        "output/alignment.json", "output/story_timeline.json", "output/continuity_bible.json",
        "output/shot_plan.json", "output/media_plan.json", "output/generation_requests.json",
        "output/generation_manifest.json", "output/review_state.json", "output/render_plan.json",
        "output/final_manifest.json", "output/final.mp4", "output/execution_control.json",
    )

    def __init__(self, *, clock=None):
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def state_path(paths) -> Path:
        return paths.artifact_path("output/production_state.json")

    def reconcile(self, paths, config) -> ProjectProductionState:
        evidence = [_signature(paths, item) for item in self._evidence_files]
        evidence_fingerprint = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        manifest_for_assets = _read(paths.artifact_path("output/generation_manifest.json"), {"requests": []})
        visual_asset_evidence = self._selected_asset_evidence(paths, manifest_for_assets)
        evidence.extend(visual_asset_evidence)
        existing = _read(self.state_path(paths), {})
        rebuilt = self._derive(paths, config, evidence, evidence_fingerprint, existing)
        # Do not churn the file when canonical evidence and compact projection agree.
        comparable = dict(existing) if isinstance(existing, dict) else {}
        if comparable.get("schema_version") == PRODUCTION_STATE_SCHEMA_VERSION:
            comparable.pop("updated_at", None)
            candidate = dict(rebuilt); candidate.pop("updated_at", None)
            if comparable == candidate:
                return ProjectProductionState(existing)
        atomic_write_json(self.state_path(paths), rebuilt)
        return ProjectProductionState(rebuilt)

    def _derive(self, paths, config, evidence: list[dict[str, Any]], fingerprint: str, existing: Any) -> dict[str, Any]:
        present = {item["path"]: item["present"] for item in evidence}
        review = _read(paths.artifact_path("output/review_state.json"), {})
        requests = _read(paths.artifact_path("output/generation_requests.json"), {"requests": []})
        manifest = _read(paths.artifact_path("output/generation_manifest.json"), {"requests": []})
        control = _read(paths.artifact_path("output/execution_control.json"), {})
        old_run = existing.get("run", {}) if isinstance(existing, dict) and isinstance(existing.get("run"), dict) else {}
        from story_auto.core.project.lock import project_lock_owned_by_live_process
        active_project_operation = (old_run.get("status") == "RUNNING"
                                    and project_lock_owned_by_live_process(paths.runtime, paths.project_id))
        # Quality totals deliberately describe timeline shots only.  Recovery,
        # however, must cover the same complete request queue that
        # execute_generation() can select: an unresolved reference asset is a
        # hard serial boundary before any later shot can be submitted.
        request_ids = {item.get("request_id") for item in requests.get("requests", []) if item.get("purpose") == "SHOT" and item.get("request_id")}
        recovery_request_ids = {item.get("request_id") for item in requests.get("requests", []) if item.get("request_id")}
        entries = {item.get("request_id"): item for item in manifest.get("requests", []) if item.get("request_id")}
        statuses = [str(entries[item].get("status", "NOT_STARTED")) for item in request_ids if item in entries]
        required_entries = [entries.get(item, {}) for item in request_ids]
        accepted_markers = {"APPROVED", "OWNER_ACCEPTED", "AUTO_ACCEPTED"}
        selected = bool(request_ids) and all(
            entry.get("status") == "SUCCEEDED" and isinstance(entry.get("selected_asset"), dict)
            and self._selected_asset_usable(paths, entry)
            and entry["selected_asset"].get("production_qc") in accepted_markers
            for entry in required_entries
        )
        generated_for_quality = bool(request_ids) and all(
            entry.get("status") in {"QC_PENDING", "SUCCEEDED"} and isinstance(entry.get("selected_asset"), dict)
            and self._selected_asset_usable(paths, entry)
            for entry in required_entries
        )
        recovery_settings = config.settings.get("provider_recovery", {}) if isinstance(config.settings, dict) else {}
        threshold = recovery_settings.get("stuck_pending_seconds", DEFAULT_STUCK_PENDING_SECONDS) if isinstance(recovery_settings, dict) else DEFAULT_STUCK_PENDING_SECONDS
        if isinstance(threshold, bool) or not isinstance(threshold, int) or not 300 <= threshold <= 86400:
            threshold = DEFAULT_STUCK_PENDING_SECONDS
        qc_policy, qc_policy_explicit = effective_qc_policy(config.settings)
        recovery = self._visual_recovery(
            paths, requests, manifest, entries, recovery_request_ids, generated_for_quality,
            active_project_operation=active_project_operation,
            threshold_seconds=threshold,
            automatic_quality_recovery=qc_policy == AUTO_ACCEPT,
        )
        quality = {
            "status": "NOT_STARTED", "policy": qc_policy, "policy_explicit": qc_policy_explicit,
            "technical_passed": sum(1 for entry in required_entries if entry.get("status") in {"QC_PENDING", "SUCCEEDED"}
                                    and self._selected_asset_usable(paths, entry)),
            "pending_review": sum(1 for entry in required_entries if entry.get("status") == "QC_PENDING"
                                  and self._selected_asset_usable(paths, entry)),
            "accepted": sum(1 for entry in required_entries if entry.get("status") == "SUCCEEDED"
                            and self._selected_asset_usable(paths, entry)
                            and entry["selected_asset"].get("production_qc") in accepted_markers),
            "rejected": sum(1 for entry in required_entries if entry.get("status") in {"AMBIGUOUS", "FAILED_RETRYABLE", "FAILED_PERMANENT", "FAILED_FATAL", "CANCELLED"}),
            "requires_owner_decision": False, "human_message": None, "next_action": None,
        }
        policy = stage_policy(execution_mode(config.settings), has_valid_audio=present["output/alignment.json"], has_accepted_visuals=selected)
        stages: dict[str, dict[str, Any]] = {}
        stages["SOURCE"] = self._stage("COMPLETE" if present["output/content_manifest.json"] else "READY", "RUN")
        timing_execution = policy["audio"].action
        stages["TIMING"] = self._stage("COMPLETE" if present["output/alignment.json"] else ("BLOCKED" if timing_execution == "BLOCK" else "READY"), timing_execution, policy["audio"].reason)
        approval = review.get("plan_approval", {}) if isinstance(review, dict) else {}
        bound_hashes = approval.get("bound_hashes", {}) if isinstance(approval, dict) else {}
        current_hashes = {
            name: sha256_file(paths.artifact_path(f"output/{filename}"))
            for name, filename in (
                ("timeline", "story_timeline.json"),
                ("continuity", "continuity_bible.json"),
                ("shot_plan", "shot_plan.json"),
                ("media_plan", "media_plan.json"),
            )
            if paths.artifact_path(f"output/{filename}").is_file()
        }
        approved = approval.get("status") == "APPROVED"
        # The two planning approvals bind different canonical artifacts.  The
        # coordinator needs this read-only distinction to know whether it must
        # approve the story, compile visuals, or approve the compiled plan.
        story_plan_approved = (approved
                               and all(name in current_hashes and bound_hashes.get(name) == current_hashes[name]
                                       for name in ("timeline", "continuity")))
        visual_plan_approved = (story_plan_approved
                                and all(name in current_hashes and bound_hashes.get(name) == current_hashes[name]
                                        for name in ("shot_plan", "media_plan")))
        planning = {
            "story_plan_approved": story_plan_approved,
            "visual_plan_approved": visual_plan_approved,
        }
        # Compiled requests are not authority to submit provider work.  Their
        # own shot/media approval is the second canonical planning boundary.
        # Treat an unapproved request file as a blocked plan so the coordinator
        # can apply AUTO_ACCEPT or preserve the Manual owner decision.
        plan_ready = present["output/continuity_bible.json"] or present["output/generation_requests.json"]
        plan_complete = present["output/generation_requests.json"] and visual_plan_approved
        stages["PLAN"] = self._stage("COMPLETE" if plan_complete else ("BLOCKED" if plan_ready else "READY"), policy["planning"].action, "Planning approval is required." if plan_ready and not visual_plan_approved else policy["planning"].reason)
        visual_status = "COMPLETE" if generated_for_quality else recovery["status"]
        stages["VISUALS"] = self._stage(visual_status, policy["visuals"].action, policy["visuals"].reason)
        stages["VISUALS"]["reason_code"] = recovery["reason_code"]
        stages["VISUALS"]["human_message"] = recovery["human_message"] or stages["VISUALS"]["human_message"]
        stages["VISUALS"]["recoverable"] = recovery["status"] == "RECOVERY_READY"
        stages["VISUALS"]["requires_owner_decision"] = recovery["requires_owner_decision"]
        stages["VISUALS"]["completed_items"] = sum(1 for status in statuses if status in {"QC_PENDING", "SUCCEEDED"})
        stages["VISUALS"]["total_items"] = len(request_ids)
        if not request_ids:
            quality_status = "NOT_STARTED"
        elif selected:
            quality_status = "COMPLETE"
        elif qc_policy == MANUAL_REVIEW and quality["pending_review"]:
            quality_status = "BLOCKED"; quality.update({"requires_owner_decision": True, "human_message": "Generated visuals are ready for your review.", "next_action": "Review visuals"})
        elif qc_policy == AUTO_ACCEPT and quality["pending_review"]:
            quality_status = "READY"; quality.update({"human_message": "Eligible visuals will receive automatic quality and story-fit review.", "next_action": "Continue production"})
        elif qc_policy == AI_REVIEW:
            quality_status = "BLOCKED"; quality.update({"human_message": "AI review is reserved but is not available in this version.", "next_action": "Choose a supported quality review policy"})
        elif quality["rejected"] and recovery["status"] not in {"RECOVERY_READY", "RUNNING"}:
            quality_status = "BLOCKED"; quality.update({"human_message": "A technical or provenance safety check needs recovery before quality can continue.", "next_action": "Review recovery"})
        else:
            quality_status = "READY"
        quality["status"] = quality_status
        stages["QUALITY"] = self._stage(quality_status, "RUN", quality["human_message"])
        stages["QUALITY"]["requires_owner_decision"] = quality["requires_owner_decision"]
        # A planning failure invalidates all downstream artifacts.  A stale
        # final.mp4 must never eclipse the durable fail-closed review state.
        planning_invalidated = review.get("visual_planning", {}).get("status") == "NEEDS_REGENERATION" if isinstance(review, dict) else False
        final_present = present["output/final.mp4"] and not planning_invalidated
        stages["RENDER"] = self._stage("COMPLETE" if final_present else ("BLOCKED" if policy["render"].action == "BLOCK" else "READY"), policy["render"].action, policy["render"].reason)

        blocker = None
        planning_failure = old_run.get("failure", {})
        current_planning_failure = (old_run.get("status") == "SAFETY_BLOCKED"
            and planning_failure.get("stage") == "PLAN"
            and planning_failure.get("evidence_fingerprint") == fingerprint
            and self._first_incomplete(stages) == "PLAN")
        if control.get("pause_requested") is True:
            blocker = self._blocker("PAUSED_BY_OWNER", "Production is paused by the owner.", "Continue production", True, False)
        elif current_planning_failure:
            blocker = self._blocker(planning_failure["reason_code"],
                "Story Auto couldn't produce a complete visual plan. Your audio and timing are saved. Try again.",
                "Retry planning", True, False, "PLAN")
        elif stages["PLAN"]["status"] == "BLOCKED" and qc_policy != AUTO_ACCEPT:
            blocker = self._blocker("OWNER_DECISION_REQUIRED", "Review and approve the production plan before visuals are created.", "Review plan", True, True, "PLAN")
        elif recovery["status"] == "BLOCKED":
            blocker = self._blocker(recovery["reason_code"], recovery["human_message"], recovery["next_action"], True,
                                    recovery["requires_owner_decision"], "VISUALS")
        elif recovery["status"] in {"NEEDS_ATTENTION", "STUCK_PENDING"}:
            blocker = self._blocker(recovery["reason_code"], recovery["human_message"], recovery["next_action"], True,
                                    True, "VISUALS")
        elif any(status == "AUTH_REQUIRED" for status in statuses):
            blocker = self._blocker("AUTH_REQUIRED", "Sign in to Flow to continue.", "Open Flow sign-in", True, False, "VISUALS")
        elif stages["VISUALS"]["status"] == "BLOCKED":
            blocker = self._blocker("SAFETY_BLOCKED", "Visual generation needs reconciliation or provider recovery before another request is sent.", "Review recovery", True, False, "VISUALS")
        elif stages["QUALITY"]["status"] == "BLOCKED" and qc_policy == MANUAL_REVIEW:
            blocker = self._blocker("OWNER_DECISION_REQUIRED", "Generated visuals need the existing quality decision before rendering.", "Review visuals", True, True, "QUALITY")
        elif stages["QUALITY"]["status"] == "BLOCKED":
            blocker = self._blocker("SAFETY_BLOCKED", quality["human_message"] or "Quality cannot continue safely.", quality["next_action"] or "Review recovery", True, False, "QUALITY")
        elif stages["TIMING"]["status"] == "BLOCKED":
            blocker = self._blocker("SAFETY_BLOCKED", stages["TIMING"]["human_message"] or "Narration audio is required.", "Review project", True, False, "TIMING")

        if final_present:
            pipeline_status, active_stage, next_action = "COMPLETE", "RENDER", {"action": "open_final", "label": "Open final video"}
            recovery = {**recovery, "status": "COMPLETE", "reason_code": "COMPLETE", "human_message": "All required production outputs are valid.",
                        "affected_request_id": None, "automatic_recovery_available": False,
                        "provider_dispatches_per_continue": 0, "requires_owner_decision": False,
                        "next_action": "Open final video"}
        elif blocker:
            canonical_actions = {"Review plan": "review_plan", "Review visuals": "review_visuals", "Review recovery": "review_recovery", "Open Flow sign-in": "open_flow_sign_in", "Continue production": "continue_production", "Review project": "review_project"}
            pipeline_status = recovery["status"] if blocker.get("stage") == "VISUALS" and recovery["status"] in {"BLOCKED", "NEEDS_ATTENTION", "STUCK_PENDING"} else blocker["reason_code"]
            active_stage, next_action = blocker.get("stage") or self._first_incomplete(stages), {"action": canonical_actions.get(blocker["next_action"], blocker["next_action"].lower().replace(" ", "_")), "label": blocker["next_action"]}
        else:
            active_stage = self._first_incomplete(stages)
            pipeline_status = recovery["status"] if active_stage == "VISUALS" and recovery["status"] in {"RUNNING", "RECOVERY_READY"} else "READY"
            next_action = {"action": "run_to_final", "label": "Create video" if active_stage == "SOURCE" else "Continue production"}
        if current_planning_failure and blocker and blocker.get("stage") == "PLAN" and not final_present:
            pipeline_status = "SAFETY_BLOCKED"
            next_action = {"action": "run_to_final", "label": "Retry planning"}
        revision = int(existing.get("state_revision", 0)) + 1 if isinstance(existing, dict) else 1
        if isinstance(existing, dict) and existing.get("evidence_fingerprint") == fingerprint:
            revision = int(existing.get("state_revision", 1))
        return {
            "schema_version": PRODUCTION_STATE_SCHEMA_VERSION, "project_id": paths.project_id, "state_revision": revision,
            "intent": execution_mode(config.settings), "source_mode": config.settings.get("ui", {}).get("input_source", "STORY_CONTENT"),
            "pipeline_status": pipeline_status, "active_stage": active_stage,
            "run": {**old_run, "run_id": old_run.get("run_id"), "status": old_run.get("status", "IDLE")}, "stages": stages, "quality": quality, "planning": planning,
            "recovery": recovery, "blocker": blocker, "next_action": next_action,
            "visual_asset_evidence": [item for item in evidence if item["path"].startswith("assets/")],
            "final_output": {"present": final_present, "path": "output/final.mp4" if final_present else None},
            "evidence_fingerprint": fingerprint, "evidence": evidence, "updated_at": _now(),
        }

    @staticmethod
    def _selected_asset_evidence(paths, manifest: dict[str, Any]) -> list[dict[str, Any]]:
        """Keep the compact cache honest when selected local bytes disappear."""
        items: list[dict[str, Any]] = []
        for entry in manifest.get("requests", []) if isinstance(manifest, dict) else []:
            selected = entry.get("selected_asset") if isinstance(entry, dict) else None
            relative = selected.get("path") if isinstance(selected, dict) else None
            if isinstance(relative, str) and relative.startswith("assets/"):
                items.append(_signature(paths, relative))
        return items

    @staticmethod
    def _selected_asset_present(paths, entry: dict[str, Any]) -> bool:
        """Confirm only that the projected selected bytes still exist locally.

        Provider-grade validation remains owned by the Flow service.  This
        compact read model merely avoids declaring a missing selection complete
        and lets the existing provider-free repair seam make the final call.
        """
        selected = entry.get("selected_asset") if isinstance(entry, dict) else None
        if not isinstance(selected, dict) or not isinstance(selected.get("path"), str):
            return False
        try:
            path = paths.artifact_path(selected["path"])
            return path.is_file() and path.stat().st_size > 0
        except Exception:
            return False

    @classmethod
    def _selected_asset_usable(cls, paths, entry: dict[str, Any]) -> bool:
        """A selected asset is usable only when its local bytes still exist."""
        selected = entry.get("selected_asset") if isinstance(entry, dict) else None
        if not isinstance(selected, dict):
            return False
        return cls._selected_asset_present(paths, entry)

    def _visual_recovery(self, paths, requests: dict[str, Any], manifest: dict[str, Any], entries: dict[str, dict[str, Any]],
                         request_ids: set[str], generated_for_quality: bool, *, active_project_operation: bool,
                         threshold_seconds: int = DEFAULT_STUCK_PENDING_SECONDS,
                         automatic_quality_recovery: bool = False) -> dict[str, Any]:
        """Project Slice 1-3 evidence without creating a second dispatch path."""
        base = {
            "status": "READY", "reason_code": "NO_VISUAL_RECOVERY_REQUIRED", "human_message": None,
            "affected_request_id": None, "automatic_recovery_available": False,
            "provider_dispatches_per_continue": 0, "requires_owner_decision": False,
            "next_action": "Continue production",
        }
        if not request_ids:
            return base
        if generated_for_quality:
            return {**base, "status": "COMPLETE", "reason_code": "VISUALS_COMPLETE",
                    "human_message": "Required visuals are valid and ready for quality.", "next_action": "Continue production"}

        session_blocker = manifest.get("session_preparation_blocker") if isinstance(manifest, dict) else None
        if (isinstance(session_blocker, dict) and session_blocker.get("scope") == "FLOW_SESSION"
                and session_blocker.get("canonical_no_dispatch_proof") is True
                and isinstance(session_blocker.get("request_id"), str)):
            return {**base, "status": "NEEDS_ATTENTION", "reason_code": "FLOW_SESSION_PREPARATION_FAILED",
                    "human_message": "Flow preparation failed before Generate. Review the Flow session before continuing.",
                    "affected_request_id": session_blocker["request_id"], "requires_owner_decision": True,
                    "next_action": "Review recovery"}

        # ProjectLock ownership plus the current bounded run marker is durable
        # live-work evidence only while it agrees with a persisted, boundary-
        # entered GENERATING attempt.  Status or a stale run marker alone is
        # never enough to paint production as active.
        if active_project_operation:
            for request_id in request_ids:
                entry = entries.get(request_id)
                attempts = entry.get("attempts") if isinstance(entry, dict) else None
                latest = attempts[-1] if isinstance(attempts, list) and attempts else None
                if (isinstance(entry, dict) and entry.get("status") == "GENERATING"
                        and isinstance(latest, dict)
                        and latest.get("provider_execution_state") == "PROVIDER_BOUNDARY_ENTERED"):
                    return {**base, "status": "RUNNING", "reason_code": "LIVE_PROJECT_OPERATION",
                            "human_message": "A confirmed Flow generation is currently executing.",
                            "affected_request_id": request_id, "next_action": "Continue production"}

        pending_deadlines = {}
        for request_id in request_ids:
            entry = entries.get(request_id)
            pending = stuck_pending_evidence(entry, now=self.clock(), threshold_seconds=threshold_seconds)
            if pending["eligible"]:
                pending_deadlines[request_id] = pending["deadline"]
            if pending["eligible"] and pending["stuck"]:
                return {**base, "status":"STUCK_PENDING", "reason_code":"STUCK_PENDING",
                        "human_message":"Flow generation appears stuck. Provider job has remained pending beyond Story Auto's normal operational window. Automatic continuation is blocked.",
                        "affected_request_id":request_id, "requires_owner_decision":True,
                        "automatic_recovery_available":False, "provider_dispatches_per_continue":0,
                        "next_action":"Recheck status", "stuck_pending_at":pending["deadline"],
                        "threshold_seconds":threshold_seconds}

        # These deterministic environment outcomes never authorize a Flow
        # call, regardless of a stale attempt status elsewhere in the manifest.
        blocked_statuses = {
            "AUTH_REQUIRED": ("AUTH_REQUIRED", "Sign in to Flow to continue.", "Open Flow sign-in"),
            "CREDIT_BLOCKED": ("CREDIT_BLOCKED", "Provider credit is required before visuals can continue.", "Review provider access"),
        }
        capability_failures = {"FLOW_CAPABILITY_UNAVAILABLE", "FLOW_PROJECT_MISMATCH", "FLOW_REFERENCE_VIDEO_CAPABILITY_BLOCKED"}
        decisions: list[tuple[str, Any]] = []
        for request_id in request_ids:
            entry = entries.get(request_id)
            if not isinstance(entry, dict):
                decisions.append((request_id, evaluate_recovery(RecoveryInput(
                    FailureFamily.INITIAL_ATTEMPT, AttemptOutcome.NOT_STARTED, DispatchCertainty.NOT_DISPATCHED,
                ))))
                continue
            status = entry.get("status")
            # A valid selected asset is completed work, not an unresolved
            # recovery candidate.  Do not let its historical attempt evidence
            # block a different logical visual that Continue must resume.
            if (status in {"SUCCEEDED", "QC_PENDING"}
                    and self._selected_asset_usable(paths, entry)):
                continue
            if status in blocked_statuses:
                code, message, action = blocked_statuses[status]
                return {**base, "status": "BLOCKED", "reason_code": code, "human_message": message,
                        "affected_request_id": request_id, "next_action": action}
            if entry.get("failure_class") in capability_failures:
                return {**base, "status": "BLOCKED", "reason_code": entry["failure_class"],
                        "human_message": "The current Flow project cannot satisfy this visual requirement.",
                        "affected_request_id": request_id, "next_action": "Review provider access"}
            preserved_raw = any(
                isinstance(attempt, dict) and attempt.get("status") == "SUCCEEDED"
                and (attempt.get("production_image_postprocess_required") is True
                     or attempt.get("production_video_postprocess_required") is True)
                for attempt in entry.get("attempts", [])
            )
            if (isinstance(entry.get("selected_asset"), dict)
                    and not self._selected_asset_present(paths, entry)
                    and preserved_raw):
                return {**base, "status": "RECOVERY_READY", "reason_code": "LOCAL_ASSET_REPAIR_AVAILABLE",
                        "human_message": "A saved provider result can be repaired locally without another generation.",
                        "affected_request_id": request_id, "automatic_recovery_available": True,
                        "next_action": "Continue production"}
            if (status in {"SUCCEEDED", "QC_PENDING"} and isinstance(entry.get("selected_asset"), dict)
                    and not self._selected_asset_usable(paths, entry)):
                return {**base, "status": "NEEDS_ATTENTION", "reason_code": "LOCAL_ASSET_EVIDENCE_INSUFFICIENT",
                        "human_message": "The selected visual is missing and no preserved raw result proves a local repair.",
                        "affected_request_id": request_id, "requires_owner_decision": True,
                        "next_action": "Review recovery"}
            if automatic_quality_recovery and self._automatic_qc_corrective_ready(entry):
                return {
                    **base,
                    "status": "RECOVERY_READY",
                    "reason_code": "AUTO_QC_CORRECTIVE_REPLAN_READY",
                    "human_message": "Automatic quality review found a correctable visual defect.",
                    "affected_request_id": request_id,
                    "automatic_recovery_available": True,
                    "provider_dispatches_per_continue": 1,
                    "next_action": "Continue production",
                }
            # BytePlus Full Video owns a durable server task ID. A known task is
            # safe to poll again because polling cannot duplicate generation.
            # By contrast, an ambiguous POST or terminal provider failure never
            # authorizes a replacement POST automatically.
            if entry.get("provider") == "byteplus_seedance":
                attempts = entry.get("attempts") if isinstance(entry.get("attempts"), list) else []
                latest = attempts[-1] if attempts and isinstance(attempts[-1], dict) else None
                if (status == "GENERATING" and isinstance(latest, dict)
                        and isinstance(latest.get("provider_job_id"), str)
                        and latest.get("attribution_state") == "CONFIRMED"):
                    return {**base, "status": "RECOVERY_READY", "reason_code": "SEEDANCE_TASK_RESUME_READY",
                            "human_message": "The identified Seedance task can be safely polled again without another generation.",
                            "affected_request_id": request_id, "automatic_recovery_available": True,
                            "provider_dispatches_per_continue": 0, "next_action": "Continue production"}
                if status == "AMBIGUOUS":
                    return {**base, "status": "NEEDS_ATTENTION", "reason_code": "SEEDANCE_DISPATCH_AMBIGUOUS",
                            "human_message": "The Seedance submission outcome is unknown. Story Auto will not submit it again automatically.",
                            "affected_request_id": request_id, "requires_owner_decision": True,
                            "automatic_recovery_available": False, "provider_dispatches_per_continue": 0,
                            "next_action": "Review recovery"}
                if (status == "FAILED_RETRYABLE" and isinstance(latest, dict)
                        and latest.get("provider_execution_state") in {"FAILED", "EXPIRED", "CANCELLED", "SUCCEEDED"}):
                    return {**base, "status": "NEEDS_ATTENTION", "reason_code": entry.get("failure_class") or "SEEDANCE_TASK_TERMINAL",
                            "human_message": "The identified Seedance task ended without an accepted asset. A new provider task requires an explicit replacement decision.",
                            "affected_request_id": request_id, "requires_owner_decision": True,
                            "automatic_recovery_available": False, "provider_dispatches_per_continue": 0,
                            "next_action": "Review recovery"}
            # This local import deliberately reuses the exact Slice 3 durable
            # evidence normalization; it only reads evidence and cannot reach
            # the provider adapter from the compact projection.
            from story_auto.providers.flow.service import _recovery_input_from_entry
            decisions.append((request_id, evaluate_recovery(_recovery_input_from_entry(entry))))

        # Any unresolved/owner boundary dominates a concurrent or dispatchable
        # entry.  This preserves serial safety and never lets a status label
        # silently bypass ambiguity.
        for request_id, decision in decisions:
            if decision.action in {RecoveryAction.RECONCILE_FIRST, RecoveryAction.OWNER_ACTION,
                                   RecoveryAction.PROMPT_REPAIR, RecoveryAction.MANUAL_REGENERATE,
                                   RecoveryAction.CREATIVE_REGENERATE, RecoveryAction.NO_RETRY}:
                return {**base, "status": "NEEDS_ATTENTION", "reason_code": decision.reason_code.value,
                        "human_message": "This visual needs evidence reconciliation or an owner decision before production can continue.",
                        "affected_request_id": request_id, "requires_owner_decision": True,
                        "next_action": "Review recovery"}
        for request_id, decision in decisions:
            if decision.action is RecoveryAction.RESUME_POLLING:
                return {**base, "status": "RUNNING", "reason_code": decision.reason_code.value,
                        "human_message": "A confirmed Flow generation is still active.", "affected_request_id": request_id,
                        "next_action": "Continue production", "stuck_pending_at": pending_deadlines.get(request_id),
                        "threshold_seconds": threshold_seconds}
        for request_id, decision in decisions:
            if decision.safe_to_dispatch or decision.action in {RecoveryAction.WAIT_AND_RETRY, RecoveryAction.REACQUIRE,
                                                                 RecoveryAction.REVALIDATE, RecoveryAction.REPOSTPROCESS}:
                return {**base, "status": "RECOVERY_READY", "reason_code": decision.reason_code.value,
                        "human_message": "Saved evidence authorizes a bounded recovery when you continue production.",
                        "affected_request_id": request_id, "automatic_recovery_available": True,
                        "provider_dispatches_per_continue": int(decision.provider_generation_required or decision.action is RecoveryAction.WAIT_AND_RETRY),
                        "next_action": "Continue production"}
        return {**base, "status": "NEEDS_ATTENTION", "reason_code": "RECOVERY_EVIDENCE_INSUFFICIENT",
                "human_message": "Visual recovery needs more durable evidence before production can continue.",
                "affected_request_id": next(iter(request_ids)), "requires_owner_decision": True,
                "next_action": "Review recovery"}

    @staticmethod
    def _automatic_qc_corrective_ready(entry: dict[str, Any]) -> bool:
        """Recognize one exact, attributed AUTO_ACCEPT rejection lineage tip."""
        if (not isinstance(entry, dict) or entry.get("status") != "FAILED_RETRYABLE"
                or not isinstance(entry.get("failure_class"), str)
                or not entry["failure_class"].endswith("_QC_REJECTED")):
            return False
        selected = entry.get("selected_asset")
        reviews = entry.get("quality_reviews")
        if (not isinstance(selected, dict) or selected.get("production_qc") != "REJECTED"
                or not isinstance(reviews, list) or not reviews):
            return False
        latest = reviews[-1]
        if (not isinstance(latest, dict) or latest.get("status") != "REJECTED"
                or latest.get("failure_class") != entry.get("failure_class")
                or latest.get("selected_asset_path") != selected.get("path")
                or latest.get("selected_asset_sha256") != selected.get("sha256")):
            return False
        selected_attempt = selected.get("attempt")
        return any(
            isinstance(attempt, dict)
            and attempt.get("attempt") == selected_attempt
            and attempt.get("attribution_state") == "CONFIRMED"
            and (attempt.get("dispatch_confirmation_state") == "CONFIRMED"
                 or attempt.get("dispatch_confirmed") is True)
            for attempt in entry.get("attempts", [])
        )

    @staticmethod
    def _stage(status: str, execution: str, human_message: str | None = None) -> dict[str, Any]:
        return {"status": status, "execution": execution, "progress": 100 if status == "COMPLETE" else 0, "reason_code": None, "human_message": human_message, "recoverable": status == "BLOCKED", "requires_owner_decision": False, "evidence": []}

    @staticmethod
    def _blocker(code: str, message: str, action: str, recoverable: bool, owner: bool, stage: str | None = None) -> dict[str, Any]:
        return {"reason_code": code, "human_message": message, "next_action": action, "recoverable": recoverable, "requires_owner_decision": owner, "stage": stage}

    @staticmethod
    def _first_incomplete(stages: dict[str, dict[str, Any]]) -> str:
        return next((name for name in PRODUCTION_STAGES if stages[name]["status"] != "COMPLETE"), "RENDER")

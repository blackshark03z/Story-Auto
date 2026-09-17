"""Bounded Run-to-Final orchestration over existing canonical stage services."""
from __future__ import annotations

import json
import uuid
from typing import Callable


class ProductionCoordinator:
    def __init__(self, query: Callable[[str], dict], operations: dict[str, Callable[[str], object]], record_run: Callable[[str, str, str], None] | None = None, record_failure=None):
        self.query = query
        self.operations = operations
        self.record_run = record_run
        self.record_failure = record_failure

    def _result(self, project_id: str, run_id: str, outcome: str, invoked: list[str], state: dict, **extra) -> dict:
        if self.record_run:
            self.record_run(project_id, run_id, outcome)
        if self.record_failure and outcome == "SAFETY_BLOCKED" and extra.get("stage") == "PLAN" and extra.get("reason_code"):
            self.record_failure(project_id, run_id, extra["reason_code"])
            state = self.query(project_id)
        return {"outcome": outcome, "run_id": run_id, "invoked_stages": invoked, "production": state, **extra}

    @staticmethod
    def _progress_fingerprint(state: dict) -> str:
        """Keep bounded orchestration from repeating an unchanged stage.

        The run record itself is intentionally omitted: only canonical
        production progress or a new canonical recovery boundary can authorize
        another operation in this invocation.
        """
        hybrid = state.get("hybrid", {}) if isinstance(state.get("hybrid"), dict) else {}
        readiness = hybrid.get("readiness", {}) if isinstance(hybrid.get("readiness"), dict) else {}
        missing = readiness.get("missing", []) if isinstance(readiness.get("missing"), list) else []
        hybrid_progress = {
            "ready": readiness.get("ready"),
            "missing": sorted(
                (str(item.get("slot_id") or ""), str(item.get("reason") or ""))
                for item in missing if isinstance(item, dict)
            ),
            "missing_body_images": sorted(str(item) for item in hybrid.get("missing_body_images", []) if item is not None),
            "missing_stock": sorted(str(item) for item in hybrid.get("missing_stock", []) if item is not None),
        } if hybrid else None
        meaningful = {
            "pipeline_status": state.get("pipeline_status"),
            "active_stage": state.get("active_stage"),
            "stages": state.get("stages"),
            "quality": state.get("quality"),
            "blocker": state.get("blocker"),
            "next_action": state.get("next_action"),
            "final_output": state.get("final_output"),
            "evidence": state.get("evidence"),
            "evidence_fingerprint": state.get("evidence_fingerprint"),
            "flow": state.get("flow"),
            "hybrid_progress": hybrid_progress,
        }
        return json.dumps(meaningful, sort_keys=True, default=str, separators=(",", ":"))

    def run_until(self, project_id: str, requested_outcome: str = "FINAL_VIDEO") -> dict:
        if requested_outcome != "FINAL_VIDEO":
            raise ValueError("FINAL_VIDEO is the only supported Phase A production outcome")
        run_id = f"run_{uuid.uuid4().hex}"
        invoked: list[str] = []
        if self.record_run:
            self.record_run(project_id, run_id, "RUNNING")
        state: dict | None = None
        for _ in range(12):
            if state is None:
                state = self.query(project_id)
            if state["pipeline_status"] == "COMPLETE":
                return self._result(project_id, run_id, "FINAL_VIDEO_COMPLETE", invoked, state)
            # AUTO_ACCEPT treats the two durable planning approvals as normal
            # one-click production work.  Manual review retains its owner
            # boundary below.  Handle this before generic READY-stage routing:
            # the ordinary PLAN operation is compilation only and must never
            # bypass an approval that is still absent.
            automatic_plan = (
                state.get("active_stage") == "PLAN"
                and state.get("quality", {}).get("policy") == "AUTO_ACCEPT"
                and state.get("stages", {}).get("PLAN", {}).get("status") == "BLOCKED"
            )
            if automatic_plan:
                evidence = {item.get("path"): item.get("present") for item in state.get("evidence", [])}
                compiled = bool(evidence.get("output/generation_requests.json"))
                planning = state.get("planning", {})
                if not compiled:
                    # Story approval is durable evidence, not an action to
                    # replay.  Once it is current, compilation is the
                    # expected mutation; a repeated approval is correctly
                    # idempotent and must not cause a false no-progress
                    # safety stop.
                    approval = "plan" if planning.get("story_plan_approved") else "approve_plan"
                else:
                    approval = "approve_shots"
                try:
                    self.operations[approval](project_id)
                    invoked.append(approval)
                    after = self.query(project_id)
                    if self._progress_fingerprint(state) == self._progress_fingerprint(after):
                        return self._result(project_id, run_id, "SAFETY_BLOCKED", invoked, after,
                                            reason_code="STAGE_NO_PROGRESS", stage="PLAN", operation=approval)
                    # The first approval authorizes compilation; it does
                    # not itself create a shot/media/generation plan. Run
                    # that provider-free planning operation once before
                    # evaluating the distinct compiled-plan approval.
                    if approval == "approve_plan":
                        self.operations["plan"](project_id)
                        invoked.append("plan")
                        planned = self.query(project_id)
                        if self._progress_fingerprint(after) == self._progress_fingerprint(planned):
                            return self._result(project_id, run_id, "SAFETY_BLOCKED", invoked, planned,
                                                reason_code="STAGE_NO_PROGRESS", stage="PLAN", operation="plan")
                        state = planned
                        continue
                    state = after
                    continue
                except Exception as error:
                    code = getattr(error, "failure_class", type(error).__name__)
                    return self._result(project_id, run_id, "SAFETY_BLOCKED", invoked, self.query(project_id),
                                        error=str(error), reason_code=code, stage="PLAN")
            if state["pipeline_status"] in {"RUNNING", "RECOVERING", "RECOVERY_READY", "NEEDS_ATTENTION", "STUCK_PENDING", "BLOCKED",
                                            "OWNER_DECISION_REQUIRED", "AUTH_RECOVERY_REQUIRED", "SAFETY_BLOCKED", "PAUSED_BY_OWNER"}:
                if state["pipeline_status"] in {"RUNNING", "RECOVERING", "NEEDS_ATTENTION", "STUCK_PENDING", "BLOCKED"}:
                    return self._result(project_id, run_id, state["pipeline_status"], invoked, state)
                if state["pipeline_status"] != "RECOVERY_READY":
                    return self._result(project_id, run_id, state["pipeline_status"], invoked, state)
            flow = state.get("flow", {})
            if state.get("active_stage") == "VISUALS" and flow.get("required") and flow.get("status") != "CONNECTED":
                return self._result(project_id, run_id, flow["status"], invoked, state, flow=flow)
            stage = state["active_stage"]
            operation = {"SOURCE": "prepare", "TIMING": "prepare", "PLAN": "plan", "VISUALS": "visuals", "QUALITY": "quality", "RENDER": "render"}[stage]
            try:
                before = self._progress_fingerprint(state)
                operation_result = self.operations[operation](project_id)
                invoked.append(operation)
                after = self.query(project_id)
                if before == self._progress_fingerprint(after):
                    return self._result(project_id, run_id, "SAFETY_BLOCKED", invoked, after,
                                        reason_code="STAGE_NO_PROGRESS", stage=stage, operation=operation)
                if operation == "quality" and isinstance(operation_result, dict) and operation_result.get("ineligible_assets"):
                    return self._result(project_id, run_id, "SAFETY_BLOCKED", invoked, after,
                                        reason_code="QC_TECHNICAL_INTEGRITY_REQUIRED")
                state = after
            except Exception as error:
                code = getattr(error, "failure_class", type(error).__name__)
                flow = self.query(project_id).get("flow", {})
                outcome = flow.get("status") if str(code).startswith("FLOW_") and flow.get("status") != "CONNECTED" else "SAFETY_BLOCKED"
                failed_stage = "PLAN" if code == "STORY_TIMELINE_INVALID" else stage
                return self._result(project_id, run_id, outcome, invoked, self.query(project_id), error=str(error), reason_code=code, stage=failed_stage)
        return self._result(project_id, run_id, "SAFETY_BLOCKED", invoked, self.query(project_id), reason_code="COORDINATOR_BOUND_EXCEEDED")

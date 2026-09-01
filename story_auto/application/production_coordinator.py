"""Bounded Run-to-Final orchestration over existing canonical stage services."""
from __future__ import annotations

import json
import uuid
from typing import Callable


class ProductionCoordinator:
    def __init__(self, query: Callable[[str], dict], operations: dict[str, Callable[[str], object]], record_run: Callable[[str, str, str], None] | None = None):
        self.query = query
        self.operations = operations
        self.record_run = record_run

    def _result(self, project_id: str, run_id: str, outcome: str, invoked: list[str], state: dict, **extra) -> dict:
        if self.record_run:
            self.record_run(project_id, run_id, outcome)
        return {"outcome": outcome, "run_id": run_id, "invoked_stages": invoked, "production": state, **extra}

    @staticmethod
    def _progress_fingerprint(state: dict) -> str:
        """Keep bounded orchestration from repeating an unchanged stage.

        The run record itself is intentionally omitted: only canonical
        production progress or a new canonical recovery boundary can authorize
        another operation in this invocation.
        """
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
            if state["pipeline_status"] in {"OWNER_DECISION_REQUIRED", "AUTH_RECOVERY_REQUIRED", "SAFETY_BLOCKED", "PAUSED_BY_OWNER"}:
                # Automatic quality is an explicit request to continue through
                # validated planning.  There are two canonical plan approvals:
                # the story plan, then the compiled shot/media plan.  Keep every
                # other owner boundary intact, especially Manual review.
                automatic_plan = (
                    state["pipeline_status"] == "OWNER_DECISION_REQUIRED"
                    and state.get("active_stage") == "PLAN"
                    and state.get("quality", {}).get("policy") == "AUTO_ACCEPT"
                )
                if automatic_plan:
                    evidence = {item.get("path"): item.get("present") for item in state.get("evidence", [])}
                    approval = "approve_shots" if evidence.get("output/generation_requests.json") else "approve_plan"
                    try:
                        self.operations[approval](project_id)
                        invoked.append(approval)
                        after = self.query(project_id)
                        if self._progress_fingerprint(state) == self._progress_fingerprint(after):
                            return self._result(project_id, run_id, "SAFETY_BLOCKED", invoked, after,
                                                reason_code="STAGE_NO_PROGRESS", stage="PLAN", operation=approval)
                        state = after
                        continue
                    except Exception as error:
                        code = getattr(error, "failure_class", type(error).__name__)
                        return self._result(project_id, run_id, "SAFETY_BLOCKED", invoked, self.query(project_id),
                                            error=str(error), reason_code=code)
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
                return self._result(project_id, run_id, outcome, invoked, self.query(project_id), error=str(error), reason_code=code)
        return self._result(project_id, run_id, "SAFETY_BLOCKED", invoked, self.query(project_id), reason_code="COORDINATOR_BOUND_EXCEEDED")

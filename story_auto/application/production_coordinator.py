"""Bounded Run-to-Final orchestration over existing canonical stage services."""
from __future__ import annotations

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

    def run_until(self, project_id: str, requested_outcome: str = "FINAL_VIDEO") -> dict:
        if requested_outcome != "FINAL_VIDEO":
            raise ValueError("FINAL_VIDEO is the only supported Phase A production outcome")
        run_id = f"run_{uuid.uuid4().hex}"
        invoked: list[str] = []
        if self.record_run:
            self.record_run(project_id, run_id, "RUNNING")
        for _ in range(12):
            state = self.query(project_id)
            if state["pipeline_status"] == "COMPLETE":
                return self._result(project_id, run_id, "FINAL_VIDEO_COMPLETE", invoked, state)
            if state["pipeline_status"] in {"OWNER_DECISION_REQUIRED", "AUTH_RECOVERY_REQUIRED", "SAFETY_BLOCKED", "PAUSED_BY_OWNER"}:
                return self._result(project_id, run_id, state["pipeline_status"], invoked, state)
            stage = state["active_stage"]
            operation = {"SOURCE": "prepare", "TIMING": "prepare", "PLAN": "plan", "VISUALS": "visuals", "QUALITY": "quality", "RENDER": "render"}[stage]
            if operation == "quality":
                # Quality policy stays owner-driven in Phase A.
                return self._result(project_id, run_id, "OWNER_DECISION_REQUIRED", invoked, state)
            try:
                self.operations[operation](project_id)
                invoked.append(operation)
            except Exception as error:
                code = getattr(error, "failure_class", type(error).__name__)
                outcome = "AUTH_RECOVERY_REQUIRED" if str(code).startswith("FLOW_") else "SAFETY_BLOCKED"
                return self._result(project_id, run_id, outcome, invoked, self.query(project_id), error=str(error), reason_code=code)
        return self._result(project_id, run_id, "SAFETY_BLOCKED", invoked, self.query(project_id), reason_code="COORDINATOR_BOUND_EXCEEDED")

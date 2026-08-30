"""Read-only application queries over compact production state."""
from __future__ import annotations

from datetime import datetime, timezone

from story_auto.core.project.production_state import ProductionStateReconciler
from story_auto.core.artifacts import atomic_write_json


class ProductionQueries:
    def __init__(self, runtime, flow_connections=None):
        self.runtime = runtime
        self.flow_connections = flow_connections
        self.reconciler = ProductionStateReconciler()

    def production_query(self, project_id: str) -> dict:
        """Return the compact state when its artifact signatures are still current.

        This is the ordinary UI path.  It deliberately avoids opening a large
        generation manifest merely to paint a project page; reconciliation only
        runs when the compact projection is absent or stale.
        """
        from story_auto.core.project import load_project
        from story_auto.core.artifacts import read_json
        import hashlib
        import json
        paths, config = load_project(self.runtime, project_id)
        try:
            existing=read_json(self.reconciler.state_path(paths))
            evidence=[self._signature(paths, relative) for relative in self.reconciler._evidence_files]
            fingerprint=hashlib.sha256(json.dumps(evidence,sort_keys=True,separators=(",", ":")).encode()).hexdigest()
            required = {"pipeline_status", "active_stage", "stages", "quality", "next_action", "final_output"}
            if (isinstance(existing,dict) and existing.get("schema_version") == "story-auto-production-state/1.0.1"
                    and required.issubset(existing) and existing.get("evidence_fingerprint") == fingerprint):
                return self._with_flow_summary(project_id, config, existing)
        except Exception:
            pass
        return self._with_flow_summary(project_id, config, self.reconciler.reconcile(paths, config).to_dict())

    def _with_flow_summary(self, project_id: str, config, state: dict) -> dict:
        """Attach the small product model without persisting browser evidence."""
        result = dict(state)
        if self.flow_connections is None:
            return result
        from story_auto.application.flow_product import product_flow_status, required_capabilities
        needed = required_capabilities(config)
        if not needed or result.get("pipeline_status") == "COMPLETE":
            result["flow"] = {"status": "CONNECTED", "human_message": "Flow is not required for this operation.",
                              "recoverable": False, "next_action": {"action": "continue_production", "label": "Continue production"},
                              "required": False}
            return result
        flow = product_flow_status(self.flow_connections, project_id, config,
                                   auth_required=result.get("pipeline_status") == "AUTH_REQUIRED")
        flow["required"] = True
        result["flow"] = flow
        if flow["status"] != "CONNECTED" and result.get("active_stage") == "VISUALS" and result.get("pipeline_status") == "READY":
            result["pipeline_status"] = flow["status"]
            result["blocker"] = {"reason_code": flow["status"], "human_message": flow["human_message"],
                                 "next_action": flow["next_action"]["label"], "recoverable": True,
                                 "requires_owner_decision": flow["status"] == "PROJECT_MISMATCH", "stage": "VISUALS"}
            result["next_action"] = dict(flow["next_action"])
        return result

    @staticmethod
    def _signature(paths, relative: str) -> dict:
        path=paths.artifact_path(relative)
        if not path.is_file(): return {"path":relative,"present":False}
        stat=path.stat()
        return {"path":relative,"present":True,"bytes":stat.st_size,"mtime_ns":stat.st_mtime_ns}

    def record_run(self, project_id: str, run_id: str, status: str) -> None:
        """Persist only the current bounded run marker; evidence remains canonical."""
        from story_auto.core.project import load_project
        paths, config = load_project(self.runtime, project_id)
        state = self.reconciler.reconcile(paths, config).to_dict()
        state["run"] = {"run_id": run_id, "status": status}
        atomic_write_json(self.reconciler.state_path(paths), state)

    def project_list_item(self, project_id: str) -> dict:
        """Return a compact card without opening any generation manifest."""
        from story_auto.core.project import load_project
        from story_auto.core.artifacts import read_json
        paths, config = load_project(self.runtime, project_id)
        state_path = paths.artifact_path("output/production_state.json")
        try:
            state = read_json(state_path)
        except Exception:
            # Legacy projects are reconciled only when opened/commanded; cards remain cheap.
            state = {"pipeline_status": "RECONCILE_REQUIRED", "active_stage": "SOURCE", "next_action": {"action": "run_to_final", "label": "Continue production"}, "final_output": {"present": (paths.root / "output" / "final.mp4").is_file()}}
        content = paths.content_file.read_text(encoding="utf-8") if paths.content_file.is_file() else ""
        title = next((line[2:].strip() for line in content.splitlines() if line.startswith("# ") and line[2:].strip()), project_id)
        updated = max((path.stat().st_mtime for path in (paths.project_file, paths.content_file, state_path) if path.is_file()), default=paths.root.stat().st_mtime)
        next_action = state.get("next_action", {"action": "run_to_final", "label": "Continue production"})
        stage_positions = {"SOURCE": 8, "TIMING": 24, "PLAN": 42, "VISUALS": 62, "QUALITY": 82, "RENDER": 94}
        return {"project_id": project_id, "title": title, "render_mode": config.render_mode, "production": state,
                "user_status": "Complete" if state.get("final_output", {}).get("present") else state.get("pipeline_status", "RECONCILE_REQUIRED").replace("_", " ").title(),
                "primary_action": {"action": next_action.get("label", "Continue production"), "action_id": next_action.get("action", "run_to_final")},
                "final_path": state.get("final_output", {}).get("path"), "current_activity": next_action.get("label", "Continue production"),
                "progress": 100 if state.get("final_output", {}).get("present") else stage_positions.get(state.get("active_stage"), 0),
                "updated_at": datetime.fromtimestamp(updated, tz=timezone.utc).isoformat().replace("+00:00", "Z")}

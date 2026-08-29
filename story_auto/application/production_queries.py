"""Read-only application queries over compact production state."""
from __future__ import annotations

from datetime import datetime, timezone

from story_auto.core.project.production_state import ProductionStateReconciler
from story_auto.core.artifacts import atomic_write_json


class ProductionQueries:
    def __init__(self, runtime):
        self.runtime = runtime
        self.reconciler = ProductionStateReconciler()

    def production_query(self, project_id: str) -> dict:
        from story_auto.core.project import load_project
        paths, config = load_project(self.runtime, project_id)
        return self.reconciler.reconcile(paths, config).to_dict()

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

"""Reusable non-UI production commands for UI, CLI, API, and workers."""
from __future__ import annotations

from story_auto.application.production_coordinator import ProductionCoordinator


class ProductionCommands:
    def __init__(self, query, operations, record_run=None, record_failure=None):
        self.coordinator = ProductionCoordinator(query, operations, record_run, record_failure)

    def run_to_final(self, project_id: str) -> dict:
        return self.coordinator.run_until(project_id, "FINAL_VIDEO")

    def continue_production(self, project_id: str) -> dict:
        return self.coordinator.run_until(project_id, "FINAL_VIDEO")

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_auto.application.production_coordinator import ProductionCoordinator
from story_auto.application.production_queries import ProductionQueries
from story_auto.core.artifacts import atomic_write_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project, load_project
from story_auto.core.project.production_state import ProductionStateReconciler


def _project(root: str, project_id: str = "prj_phasea"):
    runtime = RuntimeLayout.from_root(root)
    return create_project(runtime, ProjectConfig(project_id, render_mode="full_image", settings={"execution": {"mode": "RENDER_ONLY"}}), "# Phase A\n\n## Narration\n\nA reusable narration."), runtime


def _complete(paths):
    output = paths.root / "output"
    output.mkdir(exist_ok=True)
    for name in ("content_manifest.json", "alignment.json", "story_timeline.json", "continuity_bible.json", "shot_plan.json", "media_plan.json", "render_plan.json"):
        atomic_write_json(output / name, {"fixture": name})
    atomic_write_json(output / "review_state.json", {"plan_approval": {"status": "APPROVED"}})
    atomic_write_json(output / "generation_requests.json", {"requests": [{"request_id": "shot_1", "purpose": "SHOT"}]})
    atomic_write_json(output / "generation_manifest.json", {"requests": [{"request_id": "shot_1", "status": "SUCCEEDED", "selected_asset": {"path": "assets/shot.png"}}]})
    (output / "final.mp4").write_bytes(b"fixture-final")


def _state(stage: str = "SOURCE", status: str = "READY") -> dict:
    return {"pipeline_status": status, "active_stage": stage, "stages": {"VISUALS": {"status": "READY"}}}


class ProductionStateTests(unittest.TestCase):
    def test_serialization_and_missing_state_reconstruction(self):
        with tempfile.TemporaryDirectory() as root:
            paths, _ = _project(root)
            state = ProductionStateReconciler().reconcile(paths, load_project(RuntimeLayout.from_root(root), paths.project_id)[1]).to_dict()
            self.assertEqual(state["project_id"], paths.project_id)
            self.assertEqual(state["schema_version"], "story-auto-production-state/1.0.8")
            self.assertTrue((paths.root / "output" / "production_state.json").is_file())
            self.assertNotIn("generation_manifest", str(state["stages"]))

    def test_stale_and_completed_state_rebuild_from_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            paths, runtime = _project(root)
            _complete(paths)
            reconciler = ProductionStateReconciler()
            first = reconciler.reconcile(paths, load_project(runtime, paths.project_id)[1]).to_dict()
            self.assertEqual(first["pipeline_status"], "COMPLETE")
            self.assertTrue(first["final_output"]["present"])
            atomic_write_json(paths.root / "output" / "production_state.json", {"schema_version": "old", "pipeline_status": "NOT_STARTED"})
            rebuilt = reconciler.reconcile(paths, load_project(runtime, paths.project_id)[1]).to_dict()
            self.assertEqual(rebuilt["pipeline_status"], "COMPLETE")
            self.assertEqual(rebuilt["stages"]["RENDER"]["status"], "COMPLETE")

    def test_project_list_never_opens_large_generation_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            paths, runtime = _project(root)
            # An invalid large-looking manifest proves list cards do not parse it.
            (paths.root / "output").mkdir(exist_ok=True)
            (paths.root / "output" / "generation_manifest.json").write_bytes(b"{" + b"x" * 2_000_000)
            card = ProductionQueries(runtime).project_list_item(paths.project_id)
            self.assertEqual(card["project_id"], paths.project_id)
            self.assertEqual(card["production"]["pipeline_status"], "RECONCILE_REQUIRED")


class ProductionCoordinatorTests(unittest.TestCase):
    def test_automatically_advances_to_final(self):
        stages = iter([_state("SOURCE"), _state("PLAN"), _state("VISUALS"), _state("RENDER"), _state("RENDER", "COMPLETE")])
        calls: list[str] = []
        coordinator = ProductionCoordinator(lambda _: next(stages), {name: lambda _project, name=name: calls.append(name) for name in ("prepare", "plan", "visuals", "render")})
        result = coordinator.run_until("prj_phasea")
        self.assertEqual(result["outcome"], "FINAL_VIDEO_COMPLETE")
        self.assertEqual(calls, ["prepare", "plan", "visuals", "render"])

    def test_owner_pause_and_resume(self):
        blocked = _state("QUALITY", "OWNER_DECISION_REQUIRED")
        coordinator = ProductionCoordinator(lambda _: blocked, {"prepare": lambda _: self.fail("must not run"), "plan": lambda _: self.fail("must not run"), "visuals": lambda _: self.fail("must not run"), "render": lambda _: self.fail("must not run")})
        self.assertEqual(coordinator.run_until("prj_phasea")["outcome"], "OWNER_DECISION_REQUIRED")
        states = iter([_state("RENDER"), _state("RENDER", "COMPLETE")])
        calls: list[str] = []
        resumed = ProductionCoordinator(lambda _: next(states), {"prepare": lambda _: None, "plan": lambda _: None, "visuals": lambda _: None, "render": lambda _: calls.append("render")})
        self.assertEqual(resumed.run_until("prj_phasea")["outcome"], "FINAL_VIDEO_COMPLETE")
        self.assertEqual(calls, ["render"])

    def test_provider_is_just_in_time_and_completed_replay_is_idempotent(self):
        complete = _state("RENDER", "COMPLETE")
        calls: list[str] = []
        coordinator = ProductionCoordinator(lambda _: complete, {name: lambda _project, name=name: calls.append(name) for name in ("prepare", "plan", "visuals", "render")})
        self.assertEqual(coordinator.run_until("prj_phasea")["outcome"], "FINAL_VIDEO_COMPLETE")
        self.assertEqual(calls, [])
        states = iter([_state("RENDER"), complete])
        coordinator = ProductionCoordinator(lambda _: next(states), {"prepare": lambda _: self.fail("TTS/Flow preflight must not run"), "plan": lambda _: self.fail("Gemini preflight must not run"), "visuals": lambda _: self.fail("Flow must not run for render-only"), "render": lambda _: calls.append("render")})
        self.assertEqual(coordinator.run_until("prj_phasea")["outcome"], "FINAL_VIDEO_COMPLETE")
        self.assertEqual(calls, ["render"])

    def test_stage_without_meaningful_state_change_stops_after_one_operation(self):
        state = _state("VISUALS")
        calls: list[str] = []
        coordinator = ProductionCoordinator(
            lambda _: state,
            {"visuals": lambda _: calls.append("visuals")},
        )
        result = coordinator.run_until("prj_no_progress")
        self.assertEqual((result["outcome"], result["reason_code"], result["stage"], result["operation"], calls),
                         ("SAFETY_BLOCKED", "STAGE_NO_PROGRESS", "VISUALS", "visuals", ["visuals"]))


if __name__ == "__main__":
    unittest.main()

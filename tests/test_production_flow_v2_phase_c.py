from __future__ import annotations

import tempfile
import unittest

from story_auto.application import OperatorService
from story_auto.core.artifacts import atomic_write_json, read_json


def _project(app: OperatorService, project_id: str, *, policy: str = "AUTO_ACCEPT", mode: str = "FULL"):
    app.create_project(project_id=project_id, render_mode="full_image", settings={"qc_policy": policy, "execution": {"mode": mode}},
                       content="# Phase C\n\n## Narration\n\nA provider-free fixture.")
    paths, _ = app._project(project_id)
    output = paths.root / "output"
    for name in ("content_manifest.json", "alignment.json", "story_timeline.json", "continuity_bible.json", "shot_plan.json", "media_plan.json"):
        atomic_write_json(output / name, {"fixture": name})
    atomic_write_json(output / "review_state.json", {"plan_approval": {"status": "APPROVED"}})
    atomic_write_json(output / "generation_requests.json", {"requests": [{"request_id": "scene_01", "purpose": "SHOT", "shot_id": "sh_0001"}]})
    return paths


class PhaseCDefaultsAndWorkspaceTests(unittest.TestCase):
    def test_runtime_defaults_are_durable_and_each_project_snapshots_them(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            app.update_runtime_defaults({"render_mode": "full_image", "visual_style": "documentary", "narrator": {"voice_id": "am_michael"},
                                         "project_settings": {"qc_policy": "MANUAL_REVIEW", "full_image": {"audio_visualizer": False}}})
            first = app.create_project(project_id="prj_defaults_first", content="# First\n\n## Narration\n\nText.")
            _, first_config = app._project(first["project_id"])
            self.assertEqual((first_config.render_mode, first_config.settings["qc_policy"], first_config.settings["ui"]["production_style"], first_config.settings["full_image"]["audio_visualizer"]),
                             ("full_image", "MANUAL_REVIEW", "documentary", False))
            self.assertTrue((app.runtime.config / "runtime_defaults.json").is_file())
            app.update_runtime_defaults({"visual_style": "natural", "project_settings": {"qc_policy": "AUTO_ACCEPT", "full_image": {"audio_visualizer": True}}})
            _, unchanged = app._project(first["project_id"])
            second = app.create_project(project_id="prj_defaults_second", content="# Second\n\n## Narration\n\nText.")
            _, second_config = app._project(second["project_id"])
            self.assertEqual((unchanged.settings["qc_policy"], unchanged.settings["ui"]["production_style"], unchanged.settings["full_image"]["audio_visualizer"]),
                             ("MANUAL_REVIEW", "documentary", False))
            self.assertEqual((second_config.settings["qc_policy"], second_config.settings["ui"]["production_style"], second_config.settings["full_image"]["audio_visualizer"]),
                             ("AUTO_ACCEPT", "natural", True))

    def test_workspace_uses_canonical_actions_for_manual_auth_and_complete_states(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            manual = _project(app, "prj_manual_state", policy="MANUAL_REVIEW")
            atomic_write_json(manual.artifact_path("output/generation_manifest.json"), {"requests": [{"request_id": "scene_01", "status": "QC_PENDING", "selected_asset": {"path": "assets/scene.png"}}]})
            manual_view = app.project_workspace("prj_manual_state")
            self.assertEqual((manual_view["production"]["next_action"]["action"], manual_view["production"]["next_action"]["label"]), ("review_visuals", "Review visuals"))

            auth = _project(app, "prj_auth_state")
            atomic_write_json(auth.artifact_path("output/generation_manifest.json"), {"requests": [{"request_id": "scene_01", "status": "AUTH_REQUIRED"}]})
            auth_view = app.project_workspace("prj_auth_state")
            self.assertEqual((auth_view["production"]["next_action"]["action"], auth_view["production"]["next_action"]["label"]), ("open_flow_sign_in", "Open Flow sign-in"))

            complete = _project(app, "prj_complete_state")
            (complete.artifact_path("output/final.mp4")).write_bytes(b"provider-free final")
            complete_view = app.project_workspace("prj_complete_state")
            self.assertEqual((complete_view["status"], complete_view["production"]["next_action"]["action"], complete_view["final_path"]),
                             ("Complete", "open_final", "output/final.mp4"))

    def test_workspace_uses_cached_compact_state_without_opening_large_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            paths = _project(app, "prj_compact")
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"requests": []})
            app.project_workspace("prj_compact")  # materializes compact state once
            before = read_json(paths.artifact_path("output/production_state.json"))
            app.production_queries.reconciler.reconcile = lambda *_: self.fail("ordinary workspace must use current compact state")
            after = app.project_workspace("prj_compact")
            self.assertEqual(after["production"]["evidence_fingerprint"], before["evidence_fingerprint"])


if __name__ == "__main__":
    unittest.main()

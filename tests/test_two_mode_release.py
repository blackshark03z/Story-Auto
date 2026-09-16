from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_auto.application import OperatorService, OperatorServiceError
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project


class ReleaseModeTests(unittest.TestCase):
    def test_wizard_exposes_full_image_hybrid_and_full_video(self):
        script = (Path(__file__).parents[1] / "story_auto" / "ui" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('value="full_image"', script)
        self.assertIn('name="format" value="hybrid_hook"', script)
        self.assertNotIn('name="format" value="hybrid_hook" disabled', script)
        self.assertIn('HYBRID VISUAL', script)
        self.assertIn('name="format" value="full_video_ai"', script)
        self.assertIn('BytePlus async API', script)
        self.assertNotIn('name="format" value="full_video_ai" disabled', script)

    def test_new_project_default_is_full_image(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            created = app.create_project(project_id="prj_full_image_default")
            self.assertEqual(created["render_mode"], "full_image")

    def test_hybrid_creation_is_rejected_before_a_project_is_created(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            with self.assertRaisesRegex(OperatorServiceError, "not available in the current release"):
                app.create_project(project_id="prj_hybrid_new", render_mode="hybrid_hook")
            self.assertFalse((RuntimeLayout.from_root(root).projects / "prj_hybrid_new").exists())

    def test_hybrid_creation_with_explicit_cuj_activation_is_available(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            created = app.create_project(project_id="prj_hybrid_cuj_new", render_mode="hybrid_hook",
                                         settings={"hybrid_visual": {"cuj_enabled": True, "audio_visualizer": True}})
            self.assertEqual(created["render_mode"], "hybrid_hook")
            paths, config = app._project("prj_hybrid_cuj_new")
            self.assertTrue(config.settings["hybrid_visual"]["cuj_enabled"])
            self.assertTrue(paths.root.exists())

    def test_full_video_creation_is_available_and_forces_manual_video_review(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            created = app.create_project(project_id="prj_full_video_new", render_mode="full_video_ai")
            self.assertEqual(created["render_mode"], "full_video_ai")
            paths, config = app._project("prj_full_video_new")
            self.assertEqual(config.settings["qc_policy"], "MANUAL_REVIEW")
            self.assertNotIn("flow_binding", config.settings)
            self.assertNotIn("flow_project_binding", config.settings)
            self.assertTrue(paths.root.exists())

    def test_full_video_snapshot_depends_on_byteplus_not_flow(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = RuntimeLayout.from_root(root)
            paths = create_project(runtime, ProjectConfig("prj_full_video_status", render_mode="full_video_ai"),
                                   "# Full Video Status\n\n## Narration\n\nProvider boundary fixture.\n")
            from story_auto.core.artifacts import atomic_write_json
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": [{
                "request_id": "req_video_status", "purpose": "SHOT", "shot_id": "sh_0001",
                "media_type": "VIDEO", "provider": "byteplus_seedance", "status": "PENDING"
            }]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"requests": [{
                "request_id": "req_video_status", "status": "PENDING", "provider": "byteplus_seedance", "attempts": []
            }]})
            app = OperatorService(root)
            with patch("story_auto.application.operator.seedance_readiness", return_value={
                "status": "NOT_CONFIGURED", "reason_code": "CREDENTIAL_MISSING", "model": "fixture"
            }):
                snapshot = app.snapshot("prj_full_video_status")
            self.assertIn("CREDENTIAL_MISSING", snapshot["blocked"])
            self.assertNotIn("FLOW_NOT_CONFIGURED", snapshot["blocked"])

    def test_full_video_generation_fails_closed_without_byteplus_credential(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = RuntimeLayout.from_root(root)
            create_project(runtime, ProjectConfig("prj_full_video_existing", render_mode="full_video_ai"),
                           "# Historical Full Video\n\n## Narration\n\nKeep this project unchanged.\n")
            app = OperatorService(root)
            with self.assertRaisesRegex(RuntimeError, "CREDENTIAL_MISSING"):
                app.generate("prj_full_video_existing")

    def test_historical_hybrid_run_is_provider_free_and_offers_no_retry(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = RuntimeLayout.from_root(root)
            paths = create_project(runtime, ProjectConfig("prj_hybrid_existing", render_mode="hybrid_hook"),
                                   "# Historical Hybrid\n\n## Narration\n\nKeep this project unchanged.\n")
            before = sorted(path.relative_to(paths.root).as_posix() for path in paths.root.rglob("*"))
            app = OperatorService(root)
            result = app.run_to_final("prj_hybrid_existing")
            self.assertEqual(result["outcome"], "FEATURE_NOT_AVAILABLE")
            self.assertEqual(result["provider_dispatches"], 0)
            self.assertFalse(result["retryable"])
            self.assertIsNone(result["next_action"])
            workspace = app.project_workspace("prj_hybrid_existing")
            self.assertEqual(workspace["production"]["pipeline_status"], "FEATURE_NOT_AVAILABLE")
            self.assertFalse(workspace["can_render_again"])
            after = sorted(path.relative_to(paths.root).as_posix() for path in paths.root.rglob("*"))
            self.assertEqual(after, before)
            with self.assertRaisesRegex(OperatorServiceError, "not available in the current release"):
                app.generate("prj_hybrid_existing", executor=object())


if __name__ == "__main__":
    unittest.main()

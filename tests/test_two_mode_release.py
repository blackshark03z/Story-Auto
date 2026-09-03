from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_auto.application import OperatorService, OperatorServiceError
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project


class FullImageOnlyReleaseTests(unittest.TestCase):
    def test_wizard_exposes_only_full_image_and_defers_video_modes(self):
        script = (Path(__file__).parents[1] / "story_auto" / "ui" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('value="full_image"', script)
        self.assertIn('value="hybrid_hook" disabled', script)
        self.assertIn('Intro Video + Images — Coming soon', script)
        self.assertIn('value="full_video_ai" disabled', script)
        self.assertIn('Full Video — Coming soon', script)
        self.assertIn('Only Full Image is available in this release.', script)

    def test_new_project_default_is_full_image(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            created = app.create_project(project_id="prj_full_image_default")
            self.assertEqual(created["render_mode"], "full_image")

    def test_hybrid_creation_is_rejected_before_a_project_is_created(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            with self.assertRaisesRegex(OperatorServiceError, "Only Full Image is available"):
                app.create_project(project_id="prj_hybrid_new", render_mode="hybrid_hook")
            self.assertFalse((RuntimeLayout.from_root(root).projects / "prj_hybrid_new").exists())

    def test_full_video_creation_is_rejected_before_a_project_is_created(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            with self.assertRaisesRegex(OperatorServiceError, "Only Full Image is available"):
                app.create_project(project_id="prj_full_video_new", render_mode="full_video_ai")
            self.assertFalse((RuntimeLayout.from_root(root).projects / "prj_full_video_new").exists())

    def test_historical_full_video_run_is_provider_free_and_offers_no_retry(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = RuntimeLayout.from_root(root)
            paths = create_project(runtime, ProjectConfig("prj_full_video_existing", render_mode="full_video_ai"),
                                   "# Historical Full Video\n\n## Narration\n\nKeep this project unchanged.\n")
            before = sorted(path.relative_to(paths.root).as_posix() for path in paths.root.rglob("*"))
            app = OperatorService(root)
            result = app.run_to_final("prj_full_video_existing")
            self.assertEqual(result["outcome"], "FEATURE_NOT_AVAILABLE")
            self.assertEqual(result["human_message"], "Only Full Image is available in this release.")
            self.assertEqual(result["provider_dispatches"], 0)
            self.assertFalse(result["retryable"])
            self.assertIsNone(result["next_action"])
            card = app.list_projects()[0]
            self.assertEqual(card["primary_action"], {"action": "Full Video unavailable", "action_id": "review_project"})
            workspace = app.project_workspace("prj_full_video_existing")
            self.assertEqual(workspace["production"]["pipeline_status"], "FEATURE_NOT_AVAILABLE")
            self.assertFalse(workspace["can_render_again"])
            after = sorted(path.relative_to(paths.root).as_posix() for path in paths.root.rglob("*"))
            self.assertEqual(after, before)
            with self.assertRaisesRegex(OperatorServiceError, "Only Full Image is available"):
                app.generate("prj_full_video_existing", executor=object())
            with self.assertRaisesRegex(OperatorServiceError, "Only Full Image is available"):
                app.publishing("prj_full_video_existing", "metadata", provider=object())

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
            with self.assertRaisesRegex(OperatorServiceError, "Only Full Image is available"):
                app.generate("prj_hybrid_existing", executor=object())


if __name__ == "__main__":
    unittest.main()

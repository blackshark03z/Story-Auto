from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_auto.application import OperatorService, OperatorServiceError
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project


class TwoModeReleaseTests(unittest.TestCase):
    def test_wizard_exposes_two_selectable_modes_and_defers_full_video(self):
        script = (Path(__file__).parents[1] / "story_auto" / "ui" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('value="full_image"', script)
        self.assertIn('value="hybrid_hook"', script)
        self.assertIn('Intro Video + Images', script)
        self.assertIn('value="full_video_ai" disabled', script)
        self.assertIn('Full Video — Coming soon', script)
        self.assertIn('Full Video is not available in this release.', script)

    def test_full_video_creation_is_rejected_before_a_project_is_created(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            with self.assertRaisesRegex(OperatorServiceError, "Full Video is not available"):
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
            self.assertEqual(result["human_message"], "Full Video is not available in this release.")
            self.assertEqual(result["provider_dispatches"], 0)
            self.assertFalse(result["retryable"])
            self.assertIsNone(result["next_action"])
            card = app.list_projects()[0]
            self.assertEqual(card["primary_action"], {"action": "Full Video unavailable", "action_id": "review_project"})
            after = sorted(path.relative_to(paths.root).as_posix() for path in paths.root.rglob("*"))
            self.assertEqual(after, before)
            with self.assertRaisesRegex(OperatorServiceError, "Full Video is not available"):
                app.generate("prj_full_video_existing", executor=object())


if __name__ == "__main__":
    unittest.main()

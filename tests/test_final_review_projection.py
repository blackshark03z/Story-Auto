"""Detailed review must not revive a final rejected by canonical production state."""
import tempfile
import unittest
from unittest.mock import patch

from story_auto.application.operator import OperatorService


class FinalReviewProjectionTests(unittest.TestCase):
    def test_stale_final_is_not_exposed_by_snapshot_or_review(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            app.create_project(project_id="prj_stale_review", render_mode="full_image",
                               content="# Review\n\n## Narration\n\nSaved story.")
            paths, _ = app._project("prj_stale_review")
            state = app.production_query(paths.project_id)
            paths.artifact_path("output/final.mp4").write_bytes(b"old output remains for recovery")
            # Exercise the detailed compatibility projection with an authoritative
            # incomplete state; validation of that state is covered separately.
            with patch.object(app, "production_query", return_value=state):
                snapshot = app.snapshot(paths.project_id)
                review = app.review_overview(paths.project_id)
            self.assertIsNone(snapshot["final_path"])
            self.assertNotEqual(snapshot["user_status"], "Complete")
            self.assertNotEqual(snapshot["render_status"], "COMPLETE")
            self.assertLess(snapshot["progress"], 100)
            self.assertTrue(snapshot["render_stale"])
            self.assertIsNone(review["final_path"])
            self.assertEqual(review["quality"][-1], {"label":"Final render", "status":"Waiting"})
            self.assertTrue(paths.artifact_path("output/final.mp4").is_file())

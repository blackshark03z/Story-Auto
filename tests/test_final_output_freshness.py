"""Final means the current approved inputs, not simply a file named final.mp4."""
import tempfile
import unittest

from story_auto.application import OperatorService
from story_auto.core.artifacts import atomic_write_json, read_json
from tests.final_output_fixture import complete_final


class FinalFreshnessTests(unittest.TestCase):
    def test_current_render_is_complete_and_input_changes_revoke_completion(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            app.create_project(project_id="prj_fresh_final", render_mode="full_image",
                               content="# Final\n\n## Narration\n\nA current final.")
            paths, _ = app._project("prj_fresh_final")
            complete_final(paths)
            self.assertEqual(app.production_query(paths.project_id)["pipeline_status"], "COMPLETE")
            self.assertEqual(app.production_queries.project_list_item(paths.project_id)["user_status"], "Complete")
            final = paths.artifact_path("output/final.mp4")
            original_final = final.read_bytes()
            for relative in ("output/final.mp4", "assets/image/fixture.png", "assets/audio/narration.wav",
                             "output/subtitles.srt", "output/subtitles.ass", "output/alignment.json",
                             "output/final_manifest.json", "content.md", "project.json"):
                with self.subTest(relative=relative):
                    target = paths.artifact_path(relative)
                    before = target.read_bytes()
                    try:
                        if relative == "project.json":
                            project = read_json(target)
                            project["settings"]["render"]["fps"] = 20
                            atomic_write_json(target, project)
                        else:
                            target.write_bytes(before + b" changed")
                        card = app.production_queries.project_list_item(paths.project_id)
                        self.assertNotEqual(card["user_status"], "Complete")
                        state = app.production_query(paths.project_id)
                        self.assertNotEqual(state["pipeline_status"], "COMPLETE")
                        self.assertFalse(state["final_output"]["present"])
                        self.assertIsNone(app.review_overview(paths.project_id).get("final_path"))
                    finally:
                        target.write_bytes(before)
                    self.assertEqual(app.production_query(paths.project_id)["pipeline_status"], "COMPLETE")
            self.assertEqual(final.read_bytes(), original_final)

    def test_unbound_final_is_preserved_but_not_offered_as_complete(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            app.create_project(project_id="prj_unbound", render_mode="full_image", content="# Old\n\n## Narration\n\nText.")
            paths, _ = app._project("prj_unbound")
            final = paths.artifact_path("output/final.mp4")
            final.write_bytes(b"old-output")
            self.assertIsNone(app.project_workspace(paths.project_id)["final_path"])
            self.assertEqual(final.read_bytes(), b"old-output")

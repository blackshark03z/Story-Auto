from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_auto.application import OperatorService, OperatorServiceError
from story_auto.core.artifacts import atomic_write_json, read_json


class OperatorApplicationTests(unittest.TestCase):
    def test_project_content_status_and_shared_state(self):
        with tempfile.TemporaryDirectory() as root:
            app=OperatorService(root)
            created=app.create_project(project_id="prj_operator01",content="# Story\n\n## Narration\n\nA quiet story begins.\n")
            self.assertEqual((created["content_status"],created["render_mode"]),("VALID","hybrid_hook"))
            app.save_content("prj_operator01","# Story\n\n## Narration\n\nThe story changes.\n")
            self.assertIn("The story changes",app.get_content("prj_operator01")["narration"])
            with self.assertRaises(Exception): app.save_content("prj_operator01","# Missing narration")
            self.assertEqual(app.start_or_resume("prj_operator01")["content"],"RUN")
            self.assertEqual(app.start_or_resume("prj_operator01")["content"],"SKIP")

    def test_prompt_edit_creates_new_identity_and_preserves_attempt_provenance(self):
        with tempfile.TemporaryDirectory() as root:
            app=OperatorService(root); app.create_project(project_id="prj_operator02",content="# Story\n\n## Narration\n\nTest.\n")
            paths,_=app._project("prj_operator02")
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),{"requests":[
                {"request_id":"ref_old","fingerprint":"a","purpose":"REFERENCE","media_type":"IMAGE","prompt":"old reference","depends_on":[]},
                {"request_id":"shot_old","fingerprint":"b","purpose":"SHOT","shot_id":"sh_0001","media_type":"VIDEO","prompt":"motion","depends_on":["ref_old"]}]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"schema_version":"story-auto-generation-manifest/1.0.0","project_id":"prj_operator02","requests":[{"request_id":"ref_old","status":"SUCCEEDED","attempts":[{"attempt":1}]}]})
            atomic_write_json(paths.artifact_path("output/media_plan.json"),{"shots":[{"shot_id":"sh_0001","selected_request_id":"shot_old"}]})
            result=app.edit_prompt("prj_operator02","ref_old","new natural reference")
            requests=read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
            self.assertNotEqual(requests[0]["request_id"],"ref_old")
            self.assertEqual(requests[1]["depends_on"],[requests[0]["request_id"]])
            self.assertNotEqual(requests[1]["request_id"],"shot_old")
            self.assertEqual(read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]["attempts"],[{"attempt":1}])
            self.assertEqual(len(result["references"]),1)

    def test_full_video_image_override_is_rejected_before_state_change(self):
        with tempfile.TemporaryDirectory() as root:
            app=OperatorService(root); app.create_project(project_id="prj_operator03",render_mode="full_video_ai",content="# Story\n\n## Narration\n\nTest.\n")
            with self.assertRaises(OperatorServiceError): app.set_media_override("prj_operator03","sh_0001","IMAGE")
            paths,_=app._project("prj_operator03")
            self.assertNotIn("media",read_json(paths.project_file)["settings"])


if __name__ == "__main__": unittest.main()

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

    def test_user_facing_projection_translates_attention_and_progress(self):
        with tempfile.TemporaryDirectory() as root:
            app=OperatorService(root)
            app.create_project(project_id="prj_creator_story",content="# The Lantern Room\n\n## Narration\n\nA quiet story begins here.\n")
            paths,_=app._project("prj_creator_story")
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),{"requests":[
                {"request_id":"req_hidden_01","purpose":"SHOT","shot_id":"sh_0001","media_type":"VIDEO","prompt":"quiet room"},
                {"request_id":"req_hidden_02","purpose":"SHOT","shot_id":"sh_0002","media_type":"IMAGE","prompt":"old piano"}]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"requests":[
                {"request_id":"req_hidden_01","status":"SUCCEEDED","attempts":[]},
                {"request_id":"req_hidden_02","status":"AUTH_REQUIRED","attempts":[]}]})
            value=app.snapshot("prj_creator_story")
            self.assertEqual(value["title"],"The Lantern Room")
            self.assertEqual(value["user_status"],"Needs your attention")
            self.assertEqual(value["attention"][0]["title"],"Google sign-in required")
            self.assertEqual(value["attention"][0]["action"],"Open Flow sign-in")
            self.assertEqual(value["current_activity"],"Visual creation is waiting for Google sign-in.")
            self.assertLess(value["progress"],100)
            self.assertNotIn("req_hidden_01",value["current_activity"])

    def test_complete_and_review_projection_uses_plain_quality_language(self):
        with tempfile.TemporaryDirectory() as root:
            app=OperatorService(root)
            app.create_project(project_id="prj_finished_story",content="# A Promise Kept\n\n## Narration\n\nThe promise was kept.\n")
            paths,_=app._project("prj_finished_story")
            paths.artifact_path("output/final.mp4").write_bytes(b"fixture")
            atomic_write_json(paths.artifact_path("output/alignment.json"),{"duration_seconds":72.4})
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),{"requests":[]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"requests":[]})
            snapshot=app.snapshot("prj_finished_story")
            review=app.review_overview("prj_finished_story")
            self.assertEqual((snapshot["user_status"],snapshot["progress"]),("Complete",100))
            self.assertEqual(snapshot["primary_action"]["action"],"Open final video")
            self.assertEqual(review["quality"][-1],{"label":"Final render","status":"Passed"})
            self.assertEqual(review["issues"],[])

    def test_user_projection_ignores_superseded_manifest_attempts(self):
        with tempfile.TemporaryDirectory() as root:
            app=OperatorService(root)
            app.create_project(project_id="prj_superseded",content="# Current Cut\n\n## Narration\n\nThe current cut is complete.\n")
            paths,_=app._project("prj_superseded")
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),{"requests":[
                {"request_id":"req_current","purpose":"SHOT","shot_id":"sh_0001","media_type":"VIDEO","prompt":"current"}]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"requests":[
                {"request_id":"req_old","status":"QC_PENDING","attempts":[]},
                {"request_id":"req_current","status":"SUCCEEDED","attempts":[]}]})
            snapshot=app.snapshot("prj_superseded")
            self.assertEqual(snapshot["generation_status"],{"SUCCEEDED":1})
            self.assertNotIn("MEDIA_QC_REQUIRED",snapshot["blocked"])
            self.assertEqual(app.review_overview("prj_superseded")["issues"],[])

    def test_new_video_defaults_are_voice_oriented_and_secret_free(self):
        with tempfile.TemporaryDirectory() as root:
            app=OperatorService(root)
            settings=app.settings_overview()
            self.assertEqual(settings["defaults"]["voice_name"],"George")
            self.assertEqual(settings["creation_defaults"]["tts"]["provider"],"kokoro_local")
            self.assertEqual(settings["creation_defaults"]["tts"]["kokoro_local"]["voice_id"],"bm_george")
            self.assertNotIn("api_key",str(settings).lower())


if __name__ == "__main__": unittest.main()

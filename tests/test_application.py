from __future__ import annotations

import tempfile
import unittest
import hashlib
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from story_auto.application import OperatorService, OperatorServiceError
from story_auto.core.audio import AudioPipelineError
from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.tts.kokoro_local import KokoroReadiness


class OperatorApplicationTests(unittest.TestCase):
    def _owner_acceptance_fixture(self, app, project_id, count=1):
        app.create_project(project_id=project_id,render_mode="full_image",settings={"qc_policy":"MANUAL_REVIEW"},content="# Owner acceptance\n\n## Narration\n\nUse existing visuals.\n")
        paths,_=app._project(project_id)
        asset=paths.artifact_path("assets/selected.png"); asset.parent.mkdir(parents=True,exist_ok=True)
        Image.new("RGB",(1280,720),"navy").save(asset,"PNG")
        digest=hashlib.sha256(asset.read_bytes()).hexdigest()
        requests=[]; entries=[]
        for number in range(count):
            request_id=f"req_owner_{number:03d}"; fingerprint=hashlib.sha256(request_id.encode()).hexdigest()
            request={"request_id":request_id,"fingerprint":fingerprint,"purpose":"SHOT","shot_id":f"sh_{number:04d}",
                     "media_type":"IMAGE","provider":"google_flow","prompt":"fixture"}
            requests.append(request)
            entries.append({"request_id":request_id,"request_identity_sha256":fingerprint,"related_identity":request["shot_id"],
                            "media_type":"IMAGE","provider":"google_flow","status":"QC_PENDING","failure_class":None,
                            "attempts":[{"attempt":1,"status":"SUCCEEDED","attribution_state":"CONFIRMED","asset_path":"assets/selected.png","asset_sha256":digest}],
                            "selected_asset":{"path":"assets/selected.png","sha256":digest,"attempt":1,"source_provider_attempt":1,"production_qc":"PENDING"}})
        atomic_write_json(paths.artifact_path("output/generation_requests.json"),{"requests":requests})
        atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"schema_version":"story-auto-generation-manifest/1.0.0","project_id":project_id,"requests":entries})
        return paths

    def test_owner_batch_accepts_exactly_42_persisted_pending_images_without_dispatch_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            app=OperatorService(root); paths=self._owner_acceptance_fixture(app,"prj_owner_42",count=42)
            first=app.accept_pending_visuals_by_owner("prj_owner_42","Owner explicitly skipped manual visual review for this run.")
            manifest=read_json(paths.artifact_path("output/generation_manifest.json"))
            self.assertEqual((first["accepted_images"],first["new_image_requests"],first["video_requests"]),(42,0,0))
            self.assertTrue(all(item["status"]=="SUCCEEDED" and item["selected_asset"]["production_qc"]=="OWNER_ACCEPTED" for item in manifest["requests"]))
            self.assertTrue(all(item["quality_reviews"][-1]["disposition"]=="MANUAL_REVIEW_SKIPPED" for item in manifest["requests"]))
            second=app.accept_pending_visuals_by_owner("prj_owner_42","Owner explicitly skipped manual visual review for this run.")
            replay=read_json(paths.artifact_path("output/generation_manifest.json"))
            self.assertEqual((second["accepted_images"],second["already_owner_accepted_images"],replay),(0,42,manifest))

    def test_owner_batch_does_not_accept_failed_or_ambiguous_assets(self):
        with tempfile.TemporaryDirectory() as root:
            app=OperatorService(root); paths=self._owner_acceptance_fixture(app,"prj_owner_safety",count=3)
            manifest=read_json(paths.artifact_path("output/generation_manifest.json"))
            manifest["requests"][1].update({"status":"FAILED_RETRYABLE","failure_class":"FLOW_TIMEOUT"})
            manifest["requests"][2].update({"status":"AMBIGUOUS","failure_class":"OUTPUT_ATTRIBUTION_AMBIGUOUS"})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),manifest)
            result=app.accept_pending_visuals_by_owner("prj_owner_safety","Owner explicitly skipped manual visual review for eligible assets only.")
            saved=read_json(paths.artifact_path("output/generation_manifest.json"))["requests"]
            self.assertEqual(result["accepted_images"],1)
            self.assertEqual((saved[0]["status"],saved[1]["status"],saved[2]["status"]),("SUCCEEDED","FAILED_RETRYABLE","AMBIGUOUS"))
            self.assertEqual([len(item["attempts"]) for item in saved],[1,1,1])

    def test_goal37_reopen_is_available_through_operator_surface(self):
        with tempfile.TemporaryDirectory() as root:
            app=OperatorService(root); app.create_project(project_id="prj_goal37",content="# Appeal\n\n## Narration\n\nTest.\n")
            paths,_=app._project("prj_goal37")
            asset=paths.artifact_path("assets/selected.png"); asset.parent.mkdir(parents=True,exist_ok=True); Image.new("RGB",(1280,720),"navy").save(asset,"PNG")
            digest=hashlib.sha256(asset.read_bytes()).hexdigest(); request_id="req_2ed7c6b9c1ce863d8e9d"
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),{"requests":[{"request_id":request_id,"purpose":"REFERENCE","media_type":"IMAGE","prompt":"fixture"}]})
            rejection={"reviewed_at":"2026-08-21T00:00:00Z","status":"REJECTED","failure_class":"NATURALNESS_QC_REJECTED",
                       "report":{"reviewer":"operator"},"selected_asset_path":"assets/selected.png","selected_asset_sha256":digest}
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"schema_version":"story-auto-generation-manifest/1.0.0","project_id":"prj_goal37","requests":[
                {"request_id":request_id,"media_type":"IMAGE","status":"FAILED_RETRYABLE","failure_class":"NATURALNESS_QC_REJECTED",
                 "attempts":[{"attempt":1,"status":"SUCCEEDED","attribution_state":"CONFIRMED",
                              "asset_path":"assets/selected.png","asset_sha256":digest}],
                 "selected_asset":{"path":"assets/selected.png","sha256":digest,"attempt":1,"production_qc":"REJECTED"},
                 "quality_reviews":[rejection]}]})
            media=app.reopen_false_positive_production_qc("prj_goal37",request_id,expected_asset_sha256=digest,
                                                           reviewer="tech-lead",reason="bounded appeal")
            item=next(value for value in media["references"] if value["request"]["request_id"]==request_id)
            self.assertEqual((item["status"],item["selected_asset"]["production_qc"],len(item["quality_reviews"])),("QC_PENDING","PENDING",1))
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
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"schema_version":"story-auto-generation-manifest/1.0.0","project_id":"prj_creator_story","requests":[
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

    def test_new_project_with_installed_default_is_ready_without_narration_generation(self):
        with tempfile.TemporaryDirectory() as root:
            app=OperatorService(root)
            settings={"tts":{"provider":"kokoro_local","allow_cross_provider_fallback":False,
                              "kokoro_local":{"runtime_path":"D:/kokoro","voice_id":"bm_george"}}}
            ready=KokoroReadiness("READY","Kokoro is ready",None)
            with patch("story_auto.application.operator.KokoroLocalProvider.readiness",return_value=ready):
                created=app.create_project(project_id="prj_installed_default",content="# Default\n\n## Narration\n\nA ready narrator.\n",settings=settings)
        self.assertEqual((created["user_status"],created["narrator"]),
                         ("Create video",{"provider":"kokoro_local","voice_id":"bm_george","name":"George","status":"Ready","technical_code":None}))

    def test_missing_default_is_exposed_and_rejected_at_new_project_boundary(self):
        with tempfile.TemporaryDirectory() as root:
            app=OperatorService(root)
            settings={"tts":{"provider":"kokoro_local","allow_cross_provider_fallback":False,
                              "kokoro_local":{"runtime_path":"D:/kokoro","voice_id":"am_michael"}}}
            missing=KokoroReadiness("VOICE_NOT_FOUND","The selected Kokoro voice is missing","KOKORO_VOICE_NOT_FOUND")
            with patch("story_auto.application.operator.available_voices",return_value=("bm_george",)), \
                 patch("story_auto.application.operator.KokoroLocalProvider.readiness",return_value=missing):
                create_project(RuntimeLayout.from_root(root),ProjectConfig("prj_stale_default",settings=settings),"# Old\n\n## Narration\n\nA stale narrator.\n")
                overview=app.settings_overview()
                self.assertFalse(overview["defaults"]["narrator_available"])
                self.assertEqual(overview["voice_options"],[{"voice_id":"bm_george","name":"George"}])
                self.assertIn("not installed",overview["defaults"]["narrator_message"])
                with self.assertRaises(AudioPipelineError) as caught:
                    app.create_project(project_id="prj_rejected_default",content="# Missing\n\n## Narration\n\nNo silent inheritance.\n",settings=settings)
            self.assertEqual(caught.exception.failure_class,"KOKORO_VOICE_NOT_FOUND")
            self.assertFalse((Path(root)/"projects"/"prj_rejected_default").exists())

    def test_existing_project_with_missing_custom_voice_remains_truthfully_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=RuntimeLayout.from_root(root)
            settings={"tts":{"provider":"kokoro_local","allow_cross_provider_fallback":False,
                              "kokoro_local":{"runtime_path":"D:/kokoro","voice_id":"custom_removed"}}}
            paths=create_project(runtime,ProjectConfig("prj_legacy_voice",settings=settings),"# Legacy\n\n## Narration\n\nKeep this binding.\n")
            missing=KokoroReadiness("VOICE_NOT_FOUND","The selected Kokoro voice is missing","KOKORO_VOICE_NOT_FOUND")
            with patch("story_auto.application.operator.KokoroLocalProvider.readiness",return_value=missing):
                snapshot=OperatorService(root).snapshot("prj_legacy_voice")
            self.assertEqual(snapshot["narrator"]["voice_id"],"custom_removed")
            self.assertEqual(snapshot["narrator"]["status"],"Needs attention")
            self.assertEqual(snapshot["blocked"],["KOKORO_VOICE_NOT_FOUND"])
            self.assertEqual(snapshot["attention"][0]["title"],"Selected narrator is unavailable")
            self.assertEqual(read_json(paths.project_file)["settings"]["tts"]["kokoro_local"]["voice_id"],"custom_removed")

    def test_new_video_defaults_allowlist_excludes_project_specific_and_token_like_values(self):
        with tempfile.TemporaryDirectory() as root:
            app=OperatorService(root)
            app.create_project(project_id="prj_defaults",content="# Defaults\n\n## Narration\n\nA safe default.\n")
            paths,_=app._project("prj_defaults")
            project=read_json(paths.project_file)
            project["settings"]={
                "llm":{"provider":"gemini","model":"gemini-3.6-flash","max_attempts":3},
                "flow":{"cdp_url":"http://127.0.0.1:9222","project_identity":"studio","access_token":"nested-secret"},
                "tts":{"provider":"kokoro_local","allow_cross_provider_fallback":False,"kokoro_local":{"runtime_path":"D:/kokoro","voice_id":"am_michael"}},
                "media":{"overrides":{"sh_0001":{"media_type":"IMAGE"}}},
                "audio":{"bgm_path":"D:/music/from-another-project.mp3"},
                "custom":{"access_token":"nested-secret"},
            }
            atomic_write_json(paths.project_file,project)
            defaults=app.settings_overview()["creation_defaults"]
            self.assertEqual(set(defaults),{"llm","tts"})
            self.assertNotIn("flow",defaults)
            self.assertNotIn("token",str(defaults).lower())
            self.assertNotIn("overrides",str(defaults).lower())
            self.assertNotIn("bgm_path",str(defaults).lower())

    def test_paid_provider_settings_readiness_is_unchanged(self):
        for provider in ("elevenlabs","typecast"):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as root:
                app=OperatorService(root)
                app.create_project(project_id=f"prj_{provider}",content="# Provider\n\n## Narration\n\nA safe provider check.\n",
                                   settings={"tts":{"provider":provider,"allow_cross_provider_fallback":False,
                                                    provider:{"voice_id":"voice_fixture"}}})
                with patch("story_auto.application.operator.KokoroLocalProvider.readiness",
                           side_effect=AssertionError("Kokoro probe must not run")):
                    voice=app.settings_overview()["providers"][0]
                self.assertEqual(voice["status"],"Ready")

    def test_scene_progress_and_review_keep_request_purposes_distinct(self):
        with tempfile.TemporaryDirectory() as root:
            app=OperatorService(root)
            app.create_project(project_id="prj_purposes",content="# Purpose Test\n\n## Narration\n\nA visual test.\n")
            paths,_=app._project("prj_purposes")
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),{"requests":[
                {"request_id":"ref_1","purpose":"REFERENCE","media_type":"IMAGE","prompt":"reference"},
                {"request_id":"shot_1","purpose":"SHOT","shot_id":"sh_0001","media_type":"VIDEO","prompt":"scene"},
                {"request_id":"thumb_1","purpose":"THUMBNAIL","media_type":"IMAGE","prompt":"thumbnail"}]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"requests":[
                {"request_id":"ref_1","status":"QC_PENDING","attempts":[]},
                {"request_id":"shot_1","status":"SUCCEEDED","attempts":[]},
                {"request_id":"thumb_1","status":"FAILED_PERMANENT","attempts":[]}]})
            snapshot=app.snapshot("prj_purposes")
            review=app.review_overview("prj_purposes")
            self.assertEqual((snapshot["completed_visuals"],snapshot["total_visuals"]),(1,1))
            self.assertEqual([issue["label"] for issue in review["issues"]],["Reference 1","Thumbnail"])
            self.assertTrue(all(issue["retryable"] for issue in review["issues"]))
            self.assertIn("Create again",review["issues"][1]["message"])
            self.assertEqual(len(app.media_items("prj_purposes")["thumbnails"]),1)
            self.assertEqual(snapshot["primary_action"]["action"],"Review recovery steps")
            self.assertNotEqual(snapshot["primary_action"]["action"],"Resume")

    def test_auth_and_ambiguous_recovery_match_provider_safety(self):
        with tempfile.TemporaryDirectory() as root:
            app=OperatorService(root)
            app.create_project(project_id="prj_recovery",content="# Recovery Test\n\n## Narration\n\nA recovery test.\n")
            paths,_=app._project("prj_recovery")
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),{"requests":[
                {"request_id":"shot_auth","purpose":"SHOT","shot_id":"sh_0001","media_type":"IMAGE","prompt":"auth"},
                {"request_id":"shot_ambiguous","purpose":"SHOT","shot_id":"sh_0002","media_type":"IMAGE","prompt":"ambiguous"}]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"schema_version":"story-auto-generation-manifest/1.0.0","project_id":"prj_recovery","requests":[
                {"request_id":"shot_auth","status":"AUTH_REQUIRED","attempts":[]},
                {"request_id":"shot_ambiguous","status":"AMBIGUOUS","media_type":"IMAGE","attempts":[{"failure_class":"FLOW_TIMEOUT","dispatch_confirmed":True}]}]})
            snapshot=app.snapshot("prj_recovery")
            issues={issue["status"]:issue for issue in app.review_overview("prj_recovery")["issues"]}
            self.assertEqual(snapshot["primary_action"]["action"],"Open Flow sign-in")
            self.assertTrue(issues["AUTH_REQUIRED"]["retryable"])
            self.assertEqual(issues["AUTH_REQUIRED"]["recovery_action"],"flow_sign_in_then_requeue")
            self.assertFalse(issues["AMBIGUOUS"]["retryable"])
            self.assertEqual(issues["AMBIGUOUS"]["recovery_action"],"manual_asset")
            app.regenerate("prj_recovery","shot_auth",reason="signed in; create again")
            self.assertEqual(app.snapshot("prj_recovery")["primary_action"]["action"],"Review recovery")
            recovered=Path(root)/"recovered.png"; Image.new("RGB",(32,32),"navy").save(recovered,"PNG")
            with self.assertRaises(OperatorServiceError) as caught:
                app.replace_asset("prj_recovery","shot_ambiguous",recovered)
            self.assertEqual(str(caught.exception),"MANUAL_LOCAL_OVERRIDE_AMBIGUOUS_BLOCKED")
            manifest=read_json(paths.artifact_path("output/generation_manifest.json"))
            adopted=next(item for item in manifest["requests"] if item["request_id"]=="shot_ambiguous")
            self.assertEqual(adopted["status"],"AMBIGUOUS")
            self.assertEqual(adopted["attempts"][0]["failure_class"],"FLOW_TIMEOUT")
            self.assertEqual(len(adopted["attempts"]),1)


if __name__ == "__main__": unittest.main()

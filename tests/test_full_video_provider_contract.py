from __future__ import annotations

import unittest

from story_auto.core.full_video_provider import (DEFAULT_FULL_VIDEO_PROVIDER,
    FullVideoProviderError, full_video_provider_snapshot, require_production_full_video_provider)
from story_auto.core.planning.service import PlanningError, compile_generation_requests, compile_media_plan
from story_auto.core.project.model import ProjectConfig, ProjectValidationError


class FullVideoProviderContractTests(unittest.TestCase):
    def _fixture(self):
        shot_plan={"shots":[{"shot_id":"sh_0001","start":0.0,"end":2.0,"character_ids":[],"prop_ids":[],"location_id":None,"subject":"woman","action":"stands still","camera_intent":"locked","composition_intent":"medium","visual_emotional_purpose":"calm"}]}
        continuity={"characters":[],"locations":[],"props":[]}
        settings={"hook_seconds":55.0,"motion_spike_threshold":8,"overrides":{},"max_attempts":2,"aspect_ratio":"16:9","large_batch_request_threshold":20,"provider_video_clip_seconds":4.0}
        media=compile_media_plan("prj_provider",shot_plan,"full_video_ai",settings)
        return shot_plan, continuity, settings, media

    def test_default_is_byteplus_and_snapshot_is_capability_aware(self):
        snapshot=full_video_provider_snapshot({})
        self.assertEqual(snapshot["provider_id"],DEFAULT_FULL_VIDEO_PROVIDER)
        self.assertEqual(snapshot["generation_mode"],"t2v")
        self.assertTrue(snapshot["production_enabled"])
        self.assertEqual(snapshot["reference_image_policy"],"NOT_REQUIRED")
        self.assertEqual(snapshot["continuity_reference_policy"],"NONE")
        self.assertEqual(snapshot["initial_anchor_policy"],"NONE")

    def test_elyum_is_known_but_fail_closed_until_continuity_lifecycle_lands(self):
        snapshot=full_video_provider_snapshot({"full_video_provider":"elyum_seedance"})
        self.assertEqual(snapshot["generation_mode"],"i2v")
        self.assertEqual(snapshot["reference_image_policy"],"REQUIRED")
        self.assertEqual(snapshot["continuity_reference_policy"],"SHOT_TO_SHOT_ACCEPTED_FRAME")
        self.assertEqual(snapshot["initial_anchor_policy"],"EXPLICIT_CANONICAL_ANCHOR")
        self.assertFalse(snapshot["production_enabled"])
        with self.assertRaises(FullVideoProviderError) as caught:
            require_production_full_video_provider({"full_video_provider":"elyum_seedance"})
        self.assertEqual(caught.exception.failure_class,"FULL_VIDEO_PROVIDER_NOT_PRODUCTION_ENABLED")

    def test_unknown_provider_is_invalid_and_setting_is_full_video_only(self):
        with self.assertRaises(ProjectValidationError):
            ProjectConfig("prj_bad",render_mode="full_video_ai",settings={"full_video_provider":"unknown"})
        with self.assertRaises(ProjectValidationError):
            ProjectConfig("prj_bad2",render_mode="full_image",settings={"full_video_provider":"byteplus_seedance"})

    def test_generation_requests_snapshot_byteplus_without_changing_default_behavior(self):
        shot_plan,continuity,settings,media=self._fixture()
        requests=compile_generation_requests("prj_provider",shot_plan,media,continuity,settings)
        self.assertEqual(requests["full_video_provider_snapshot"]["provider_id"],"byteplus_seedance")
        self.assertTrue(all(item["provider"]=="byteplus_seedance" for item in requests["requests"] if item["media_type"]=="VIDEO"))

    def test_unenabled_elyum_fails_before_provider_dispatch(self):
        shot_plan,continuity,settings,media=self._fixture()
        settings["full_video_provider"]="elyum_seedance"
        with self.assertRaises(PlanningError) as caught:
            compile_generation_requests("prj_provider",shot_plan,media,continuity,settings)
        self.assertEqual(caught.exception.failure_class,"FULL_VIDEO_PROVIDER_NOT_PRODUCTION_ENABLED")


if __name__ == "__main__":
    unittest.main()

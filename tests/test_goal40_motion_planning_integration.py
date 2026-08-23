from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.audio import TimedSpan, build_alignment
from story_auto.core.content import narration_hash
from story_auto.core.gemini_qc import MOTION_PLAN_VERSION
from story_auto.core.planning import run_visual_planning_stages, validate_generation_requests
from story_auto.core.planning.service import (PlanningError, apply_motion_plans,
                                              compile_generation_requests,
                                              compile_media_plan)
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.llm import LLMResponse, ReasoningResult, RouterError


FIXTURE = Path(__file__).parent / "fixtures" / "goal40_trial_b_pre_fix_generation_requests.json"


class OfflineMotionPlanner:
    name = "gemini"

    def __init__(self, *, decompose_first: bool = False, fail_motion: bool = False) -> None:
        self.shot_calls = 0
        self.motion_calls = 0
        self.external_provider_calls = 0
        self.decompose_first = decompose_first
        self.fail_motion = fail_motion

    def generate_structured(self, request):
        self.shot_calls += 1
        shots = []
        for index in range(16):
            action = "observes the quiet corridor"
            if index == 0 and self.decompose_first:
                action = "reaches for the door and opens it"
            shots.append({
                "scene_id": "scn_0001", "start": 0, "end": 1,
                "subject": "A fictional caretaker", "action": action,
                "character_ids": [], "location_id": None, "prop_ids": [],
                "camera_intent": "locked observational frame",
                "composition_intent": "restrained medium-wide composition",
                "visual_emotional_purpose": f"story beat {index + 1}",
                "motion_value": 0,
            })
        return LLMResponse({"shots": shots}, request.model, request.request_id, 1, 1, {})

    def reason(self, **kwargs):
        self.motion_calls += 1
        if self.fail_motion:
            raise RouterError("GEMINI_ROUTING_EXHAUSTED")
        intent = json.loads(kwargs["prompt"].split("Intent:\n", 1)[1])
        action = intent["action"]
        high_risk = "door" in action
        clips = [{
            "start_state": "standing still", "action": action,
            "end_state": "action complete", "natural_stillness": "brief pause",
        }]
        meaningful_actions = [action]
        if high_risk:
            meaningful_actions = ["reaches for the door", "opens the door"]
            clips = [
                {"start_state":"hand lowered", "action":"hand reaches the door handle",
                 "end_state":"hand rests on handle", "natural_stillness":"brief contact pause",
                 "direction_sensitive":True, "action_family":"CONTACT", "ordered_action_steps":["APPROACH", "CONTACT"],
                 "progression_checkpoints":["AWAY", "CONTACT"], "movement_direction":"CONTACT_THEN_OBJECT_MOTION",
                 "forbidden_motion":["OBJECT_BEFORE_CONTACT", "REVERSE_DIRECTION"]},
                {"start_state":"hand rests on handle", "action":"door opens once",
                 "end_state":"door remains open", "natural_stillness":"settles without looping",
                 "direction_sensitive":True, "action_family":"OPEN", "ordered_action_steps":["CONTACT", "OPEN"],
                 "progression_checkpoints":["CLOSED", "OPEN"], "movement_direction":"OPENING",
                 "forbidden_motion":["OBJECT_BEFORE_CONTACT", "REVERSE_DIRECTION"]},
            ]
        value = {
            "start_state": clips[0]["start_state"], "end_state": clips[-1]["end_state"],
            "meaningful_actions": meaningful_actions, "interaction_objects": ["door"] if high_risk else [],
            "hand_object_contact": "hand contacts handle before movement" if high_risk else "none",
            "action_dependencies": ["contact before opening"] if high_risk else [],
            "physical_complexity": "HIGH" if high_risk else "LOW",
            "anatomy_risk": "MEDIUM" if high_risk else "LOW", "looping_risk": "LOW",
            "atomic_clips": clips,
        }
        return ReasoningResult(value, "offline-fixture", "fixture-key", "fixture-project",
                               False, 0, 0, f"motion-input-{self.motion_calls:02d}")


class Goal40MotionPlanningIntegrationTests(unittest.TestCase):
    def _project(self, directory: str, *, render_mode: str = "hybrid_hook"):
        runtime = RuntimeLayout.from_root(directory)
        project_id = "prj_goal40_trial_b_sanitized"
        config = ProjectConfig(
            project_id=project_id, render_mode=render_mode,
            settings={
                "llm": {"provider":"gemini", "model":"gemini-3.5-flash", "max_attempts":1},
                "media": {"hook_seconds":8, "motion_spike_threshold":8,
                          "provider_video_clip_seconds":8, "max_attempts":2},
            },
        )
        narration = "A caretaker observes a quiet corridor."
        paths = create_project(runtime, config, f"## Narration\n\n{narration}\n")
        alignment = build_alignment(
            project_id=project_id, audio_path="output/voice.wav", audio_sha256="offline-audio",
            narration_sha256=narration_hash(narration), duration_seconds=16.0,
            source="goal40-offline-fixture", spans=[TimedSpan(narration, 0, 16)],
        )
        atomic_write_json(paths.artifact_path("output/alignment.json"), alignment)
        atomic_write_json(paths.artifact_path("output/story_timeline.json"), {
            "schema_version":"story-auto-story-timeline/1.0.0", "project_id":project_id,
            "alignment_sha256":sha256_file(paths.artifact_path("output/alignment.json")),
            "scenes":[{
                "scene_id":"scn_0001", "start":0.0, "end":16.0,
                "narration_segment_ids":["seg_0001"], "narration_text":narration,
                "story_role":"setup", "summary":"A quiet observation.", "entity_ids":[],
            }],
            "provenance":{"provider":"offline-fixture"}, "review_status":"VALIDATED",
        })
        atomic_write_json(paths.artifact_path("output/continuity_bible.json"), {
            "schema_version":"story-auto-continuity-bible/1.0.0", "project_id":project_id,
            "style":{}, "characters":[], "locations":[], "props":[],
            "provenance":{"provider":"offline-fixture"}, "review_status":"VALIDATED",
        })
        return runtime, paths, project_id

    def test_exact_trial_b_pre_fix_checkpoint_reenters_normal_pipeline(self):
        fixture = read_json(FIXTURE)
        self.assertEqual((fixture["render_mode"], fixture["logical_visuals"],
                          fixture["video_requests"], fixture["provider_submissions"]),
                         ("hybrid_hook", 16, 8, 0))
        broken = fixture["generation_requests"]
        self.assertEqual(sum(item["media_type"] == "VIDEO" for item in broken["requests"]), 8)
        self.assertEqual(sum("motion_risk_analysis" not in item for item in broken["requests"]
                             if item["media_type"] == "VIDEO"), 8)

        with tempfile.TemporaryDirectory() as directory:
            runtime, paths, project_id = self._project(directory)
            planner = OfflineMotionPlanner()
            self.assertEqual(run_visual_planning_stages(runtime.root, project_id, provider=planner),
                             ("RUN", "RUN", "RUN"))
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), broken)
            atomic_write_json(paths.root / "output" / ".checkpoints" / "generation_requests.json",
                              fixture["generation_request_checkpoint"])
            planner.motion_calls = 0

            self.assertEqual(run_visual_planning_stages(runtime.root, project_id, provider=planner),
                             ("SKIP", "SKIP", "RUN"))
            upgraded = read_json(paths.artifact_path("output/generation_requests.json"))
            videos = [item for item in upgraded["requests"] if item["media_type"] == "VIDEO"]
            self.assertEqual(len(videos), 8)
            self.assertEqual(sum(not isinstance(item.get("motion_risk_analysis"), dict)
                                 for item in videos), 0)
            self.assertEqual(sum(item["motion_risk_analysis"].get("schema_version") != MOTION_PLAN_VERSION
                                 for item in videos), 0)
            self.assertTrue(all(item["execution_tier"] == "STANDARD_PRODUCTION" for item in videos))
            self.assertEqual(planner.motion_calls, 8)
            self.assertEqual(planner.external_provider_calls, 0)
            self.assertFalse(paths.artifact_path("output/generation_manifest.json").exists())
            validate_generation_requests(
                upgraded, read_json(paths.artifact_path("output/media_plan.json")),
                read_json(paths.artifact_path("output/continuity_bible.json")),
            )

    def test_full_video_and_high_risk_decomposition_preserve_timing_and_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, paths, project_id = self._project(directory, render_mode="full_video_ai")
            planner = OfflineMotionPlanner(decompose_first=True)
            run_visual_planning_stages(runtime.root, project_id, provider=planner)
            requests = read_json(paths.artifact_path("output/generation_requests.json"))
            videos = [item for item in requests["requests"] if item["media_type"] == "VIDEO"]
            self.assertEqual(len(videos), 17)
            self.assertTrue(all(item.get("motion_risk_analysis") for item in videos))
            first = sorted((item for item in videos if item["shot_id"] == "sh_0001"),
                           key=lambda item: item["part_index"])
            self.assertEqual([item["part_index"] for item in first], [1, 2])
            self.assertAlmostEqual(first[0]["target_start"], 0.0)
            self.assertAlmostEqual(first[0]["target_end"], first[1]["target_start"])
            self.assertAlmostEqual(first[1]["target_end"], 1.0)
            ids = {item["request_id"] for item in requests["requests"]}
            self.assertEqual(len(ids), len(requests["requests"]))
            self.assertTrue(all(set(item["depends_on"]).issubset(ids) for item in requests["requests"]))
            self.assertEqual(planner.external_provider_calls, 0)

    def test_simple_motion_stays_atomic_and_images_are_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, paths, project_id = self._project(directory)
            planner = OfflineMotionPlanner()
            run_visual_planning_stages(runtime.root, project_id, provider=planner)
            requests = read_json(paths.artifact_path("output/generation_requests.json"))
            images = [item for item in requests["requests"] if item["media_type"] == "IMAGE"]
            videos = [item for item in requests["requests"] if item["media_type"] == "VIDEO"]
            self.assertEqual((len(images), len(videos)), (8, 8))
            self.assertTrue(all(item["part_count"] == 1 for item in videos))
            self.assertTrue(all("motion_risk_analysis" not in item for item in images))
            self.assertNotIn("motion_plan_version", images[0])

    def test_apply_motion_plans_preserves_hybrid_image_objects_exactly(self):
        shot_plan = {"shots":[
            {"shot_id":"sh_0001", "start":0.0, "end":1.0, "character_ids":[],
             "prop_ids":[], "location_id":None, "subject":"Caretaker",
             "action":"walks through the corridor", "camera_intent":"locked",
             "composition_intent":"medium frame", "visual_emotional_purpose":"arrival",
             "motion_value":0},
            {"shot_id":"sh_0002", "start":1.0, "end":2.0, "character_ids":[],
             "prop_ids":[], "location_id":None, "subject":"Empty corridor",
             "action":"remains still", "camera_intent":"locked",
             "composition_intent":"wide frame", "visual_emotional_purpose":"quiet aftermath",
             "motion_value":0},
        ]}
        continuity = {"characters":[], "locations":[], "props":[]}
        settings = {"hook_seconds":0.5, "motion_spike_threshold":8, "overrides":{},
                    "max_attempts":2, "aspect_ratio":"16:9",
                    "large_batch_request_threshold":20, "provider_video_clip_seconds":8.0}
        media = compile_media_plan("prj_goal40_mixed", shot_plan, "hybrid_hook", settings)
        before = compile_generation_requests(
            "prj_goal40_mixed", shot_plan, media, continuity, settings,
        )
        image_before = copy.deepcopy(next(
            item for item in before["requests"] if item["media_type"] == "IMAGE"
        ))
        video_before = next(item for item in before["requests"] if item["media_type"] == "VIDEO")
        analysis = {
            "physical_complexity":"LOW", "anatomy_risk":"LOW", "looping_risk":"LOW",
            "interaction_objects":[], "hand_object_contact":"none",
            "atomic_clips":[{
                "start_state":"standing", "action":"walks through the corridor",
                "end_state":"across the corridor", "natural_stillness":"brief pause",
            }],
        }

        after = apply_motion_plans(before, shot_plan, {
            "records":[{"request_id":video_before["request_id"], "analysis":analysis}],
        })
        image_after = next(item for item in after["requests"] if item["media_type"] == "IMAGE")
        videos_after = [item for item in after["requests"] if item["media_type"] == "VIDEO"]

        self.assertEqual(image_after, image_before)
        self.assertEqual(image_after["request_id"], image_before["request_id"])
        self.assertEqual(image_after["fingerprint"], image_before["fingerprint"])
        self.assertTrue(all(item.get("motion_risk_analysis") for item in videos_after))
        self.assertEqual(len({item["request_id"] for item in videos_after}), len(videos_after))
        validate_generation_requests(after, media, continuity)

    def test_motion_planner_failure_publishes_no_executable_requests_or_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, paths, project_id = self._project(directory)
            planner = OfflineMotionPlanner(fail_motion=True)
            with self.assertRaises(PlanningError) as caught:
                run_visual_planning_stages(runtime.root, project_id, provider=planner)
            self.assertEqual(caught.exception.failure_class, "MOTION_PLANNING_FAILED")
            self.assertFalse(paths.artifact_path("output/generation_requests.json").exists())
            self.assertFalse(paths.artifact_path("output/generation_manifest.json").exists())
            checkpoint = read_json(paths.root / "output" / ".checkpoints" / "generation_requests.json")
            self.assertEqual(checkpoint["status"], "FAILED")
            self.assertEqual(planner.external_provider_calls, 0)

    def test_missing_or_fabricated_motion_defaults_fail_planning_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, paths, project_id = self._project(directory)
            planner = OfflineMotionPlanner()
            run_visual_planning_stages(runtime.root, project_id, provider=planner)
            requests = read_json(paths.artifact_path("output/generation_requests.json"))
            media = read_json(paths.artifact_path("output/media_plan.json"))
            continuity = read_json(paths.artifact_path("output/continuity_bible.json"))
            video = next(item for item in requests["requests"] if item["media_type"] == "VIDEO")
            video["motion_risk_analysis"] = {"physical_complexity":"LOW"}
            with self.assertRaises(PlanningError) as caught:
                validate_generation_requests(requests, media, continuity)
            self.assertEqual(caught.exception.failure_class, "MOTION_PLAN_INVALID")


if __name__ == "__main__":
    unittest.main()

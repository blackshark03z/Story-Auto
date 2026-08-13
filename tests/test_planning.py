from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.audio import TimedSpan, build_alignment
from story_auto.core.content import narration_hash
from story_auto.core.planning import (approve_plan, approve_shot_plan, run_planning_stages,
                                      run_visual_planning_stages, validate_continuity,
                                      validate_generation_requests, validate_timeline)
from story_auto.core.planning.service import PlanningError, compile_generation_requests, compile_media_plan
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.llm import GeminiProvider, GeminiProviderError, LLMResponse


class FakeGemini:
    name = "gemini"
    def __init__(self): self.calls = []
    def generate_structured(self, request):
        self.calls.append(request)
        if request.stage == "story_timeline":
            value = {"groups": [{"segment_ids": ["seg_0001"], "story_role": "setup", "summary": "Daniel arrives.", "entity_ids": ["char_daniel", "loc_school"]}, {"segment_ids": ["seg_0002"], "story_role": "turn", "summary": "He finds a key.", "entity_ids": ["char_daniel", "prop_key"]}]}
        else:
            value = {"style": {"id": "cinematic", "negative_constraints": ["no text overlays"]}, "characters": [{"entity_id": "char_daniel", "name": "Daniel", "facts": {"age": 62}, "visual_design": {"eye_color": "brown"}}], "locations": [{"entity_id": "loc_school", "name": "School", "facts": {"narration_support": "academy"}}], "props": [{"entity_id": "prop_key", "name": "Brass key", "visual_design": {"material": "brass"}}]}
        return LLMResponse(value, request.model, request.request_id, 1, 3, {"promptTokenCount": 10, "candidatesTokenCount": 5})


class FakeVisualGemini(FakeGemini):
    def generate_structured(self, request):
        if request.stage == "shot_plan":
            self.calls.append(request)
            return LLMResponse({"shots": [
                {"scene_id":"scn_0001","start":0,"end":1,"subject":"Daniel","action":"arrives at the academy","character_ids":["char_daniel"],"location_id":"loc_school","prop_ids":[],"camera_intent":"slow tracking","composition_intent":"wide establishing frame","visual_emotional_purpose":"establish anticipation","motion_value":2},
                {"scene_id":"scn_0002","start":1,"end":2,"subject":"Daniel","action":"finds the brass key","character_ids":["char_daniel"],"location_id":"loc_school","prop_ids":["prop_key"],"camera_intent":"slow push in","composition_intent":"close detail","visual_emotional_purpose":"reveal discovery","motion_value":9}]}, request.model, request.request_id, 1, 3, {"promptTokenCount": 10})
        return super().generate_structured(request)


class PlanningTests(unittest.TestCase):
    def _project(self, directory: str):
        runtime = RuntimeLayout.from_root(directory)
        config = ProjectConfig(project_id="prj_plan001", settings={"llm": {"provider": "gemini", "model": "gemini-3.5-flash", "max_attempts": 2}})
        paths = create_project(runtime, config, "## Narration\n\nDaniel arrives at the academy. He finds a brass key.\n")
        narration = "Daniel arrives at the academy. He finds a brass key."
        alignment = build_alignment(project_id=config.project_id, audio_path="output/voice.wav", audio_sha256="audio", narration_sha256=narration_hash(narration), duration_seconds=2.0, source="fixture", spans=[TimedSpan("Daniel arrives at the academy. ", 0, 1), TimedSpan("He finds a brass key.", 1, 2)])
        atomic_write_json(paths.artifact_path("output/alignment.json"), alignment)
        return runtime, config, paths, alignment

    def test_planning_resume_approval_and_invalidation(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, config, paths, _ = self._project(directory); fake = FakeGemini()
            self.assertEqual(run_planning_stages(runtime.root, config.project_id, provider=fake), ("RUN", "RUN"))
            timeline, continuity = read_json(paths.artifact_path("output/story_timeline.json")), read_json(paths.artifact_path("output/continuity_bible.json"))
            self.assertEqual(timeline["scenes"][0]["start"], 0)
            self.assertEqual(timeline["review_status"], "VALIDATED")
            self.assertEqual(continuity["characters"][0]["facts"]["age"], 62)
            self.assertIn("eye_color", continuity["characters"][0]["visual_design"])
            self.assertEqual(run_planning_stages(runtime.root, config.project_id, provider=fake), ("SKIP", "SKIP"))
            paths.artifact_path("output/continuity_bible.json").unlink()
            self.assertEqual(run_planning_stages(runtime.root, config.project_id, provider=fake), ("SKIP", "RUN"))
            approve_plan(runtime.root, config.project_id)
            self.assertEqual(read_json(paths.artifact_path("output/review_state.json"))["plan_approval"]["status"], "APPROVED")
            project = read_json(paths.project_file); project["settings"]["llm"]["model"] = "gemini-3.6-flash"; atomic_write_json(paths.project_file, project)
            self.assertEqual(run_planning_stages(runtime.root, config.project_id, provider=fake), ("RUN", "RUN"))

    def test_timeline_and_continuity_semantic_rejections(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, _, alignment = self._project(directory)
            bad = {"schema_version": "story-auto-story-timeline/1.0.0", "scenes": [{"scene_id":"scn_0001", "start":0, "end":1, "narration_segment_ids":["seg_0001", "seg_0001"]}]}
            with self.assertRaises(PlanningError): validate_timeline(bad, alignment)
            timeline = {"scenes": [{"entity_ids": ["char_missing"]}]}
            continuity = {"schema_version":"story-auto-continuity-bible/1.0.0", "characters": [], "locations": [], "props": []}
            with self.assertRaises(PlanningError) as error: validate_continuity(continuity, timeline)
            self.assertEqual(error.exception.failure_class, "CONTINUITY_REFERENCE_INVALID")

    def test_gemini_structured_path_and_safe_failures(self):
        payload = {"candidates": [{"content": {"parts": [{"text": "{\"ok\": true}"}]}}], "usageMetadata": {"promptTokenCount": 2}}
        provider = GeminiProvider(transport=lambda url, body, key, timeout: payload)
        with patch("story_auto.providers.llm.gemini.provider_keys", return_value=["super-secret"]):
            response = provider.generate_structured(__import__("story_auto.providers.llm", fromlist=["LLMRequest"]).LLMRequest("gemini-3.5-flash", "x", {"type":"object"}, {"max_attempts":1}, "request", "test"))
        self.assertTrue(response.value["ok"])
        self.assertIn(":generateContent", provider.api_base + "/models/gemini-3.5-flash:generateContent")
        with patch("story_auto.providers.llm.gemini.provider_keys", side_effect=RuntimeError("super-secret")):
            with self.assertRaises(GeminiProviderError) as caught: provider.capability_probe("gemini-3.5-flash")
        self.assertEqual(caught.exception.failure_class, "GEMINI_CREDENTIAL_MISSING")
        self.assertNotIn("super-secret", str(caught.exception))

    def test_gemini_retries_rate_limit_then_rejects_invalid_output(self):
        calls = []
        def transport(*_):
            calls.append(1)
            if len(calls) == 1: raise GeminiProviderError("GEMINI_RATE_LIMIT")
            return {"candidates": [{"content": {"parts": [{"text": "not-json"}]}}]}
        provider = GeminiProvider(transport=transport)
        request = __import__("story_auto.providers.llm", fromlist=["LLMRequest"]).LLMRequest("gemini-3.5-flash", "x", {"type":"object"}, {"max_attempts":2}, "request", "test")
        with patch("story_auto.providers.llm.gemini.provider_keys", return_value=["key"]), self.assertRaises(GeminiProviderError) as caught:
            provider.generate_structured(request)
        self.assertEqual(len(calls), 2); self.assertEqual(caught.exception.failure_class, "GEMINI_STRUCTURED_OUTPUT_INVALID")

    def test_llm_credentials_cannot_enter_project_configuration(self):
        from story_auto.core.project import ProjectValidationError
        with self.assertRaises(ProjectValidationError):
            ProjectConfig(project_id="prj_plan001", settings={"llm": {"provider": "gemini", "api_key": "not-allowed"}})

    def test_visual_planning_media_requests_resume_and_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, config, paths, _ = self._project(directory); fake = FakeVisualGemini()
            run_planning_stages(runtime.root, config.project_id, provider=fake)
            project = read_json(paths.project_file); project["settings"]["media"] = {"hook_seconds": .5, "large_batch_request_threshold": 1}; atomic_write_json(paths.project_file, project)
            self.assertEqual(run_visual_planning_stages(runtime.root, config.project_id, provider=fake), ("RUN", "RUN", "RUN"))
            requests = read_json(paths.artifact_path("output/generation_requests.json"))
            self.assertEqual(requests["guardrail_estimate"]["reference_image_requests"], 3)
            self.assertEqual(requests["guardrail_estimate"]["required_video_requests"], 1)
            self.assertEqual(requests["guardrail_estimate"]["preferred_video_requests"], 1)
            self.assertTrue(requests["guardrail_estimate"]["requires_later_execution_confirmation"])
            self.assertTrue(all(request["request_id"].startswith("req_") for request in requests["requests"]))
            self.assertTrue(all(request["visual_policy"]["realism_style"] == "NATURAL_SOFT_REALISM" for request in requests["requests"]))
            self.assertTrue(all(request.get("output_count") == 1 for request in requests["requests"] if request["media_type"] == "IMAGE"))
            video_prompts=[request["prompt"] for request in requests["requests"] if request["media_type"] == "VIDEO"]
            self.assertTrue(all("Subject motion:" in prompt and "Preserve the supplied reference image" in prompt for prompt in video_prompts))
            self.assertTrue(all("masterpiece" not in request["prompt"].lower() and "8k" not in request["prompt"].lower() for request in requests["requests"]))
            validate_generation_requests(requests, read_json(paths.artifact_path("output/media_plan.json")), read_json(paths.artifact_path("output/continuity_bible.json")))
            self.assertEqual(run_visual_planning_stages(runtime.root, config.project_id, provider=fake), ("SKIP", "SKIP", "SKIP"))
            approve_shot_plan(runtime.root, config.project_id)
            self.assertEqual(read_json(paths.artifact_path("output/review_state.json"))["plan_approval"]["status"], "APPROVED")

    def test_full_video_override_rejected_and_hook_boundary_is_shot_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, config, paths, _ = self._project(directory); fake = FakeVisualGemini()
            run_planning_stages(runtime.root, config.project_id, provider=fake)
            project = read_json(paths.project_file); project["settings"]["media"] = {"hook_seconds": .5}; atomic_write_json(paths.project_file, project)
            run_visual_planning_stages(runtime.root, config.project_id, provider=fake)
            self.assertEqual(read_json(paths.artifact_path("output/media_plan.json"))["resolved_hook_end"], 1.0)
            project["render_mode"] = "full_video_ai"; project["settings"]["media"]["overrides"] = {"sh_0001": {"media_type":"IMAGE"}}; atomic_write_json(paths.project_file, project)
            with self.assertRaises(PlanningError) as caught: run_visual_planning_stages(runtime.root, config.project_id, provider=fake)
            self.assertEqual(caught.exception.failure_class, "MEDIA_OVERRIDE_REJECTED")

    def test_full_video_long_shot_partitions_into_deterministic_video_requests(self):
        shot_plan={"shots":[{"shot_id":"sh_0001","start":0.0,"end":2.0,"character_ids":["char_daniel"],"prop_ids":[],"location_id":"loc_school","subject":"Daniel","action":"walks through the hall","camera_intent":"slow observational push","composition_intent":"medium environmental frame","visual_emotional_purpose":"sustained unease"}]}
        continuity={"characters":[{"entity_id":"char_daniel","name":"Daniel","visual_design":{}}],"locations":[{"entity_id":"loc_school","name":"School","visual_design":{}}],"props":[]}
        settings={"hook_seconds":55.0,"motion_spike_threshold":8,"overrides":{},"max_attempts":2,"aspect_ratio":"16:9","large_batch_request_threshold":20,"provider_video_clip_seconds":.75}
        media=compile_media_plan("prj_fullvideo",shot_plan,"full_video_ai",settings)
        requests=compile_generation_requests("prj_fullvideo",shot_plan,media,continuity,settings)
        parts=[item for item in requests["requests"] if item.get("purpose")=="SHOT"]
        self.assertEqual(([item["part_index"] for item in parts],[round(item["target_duration"],2) for item in parts]),([1,2,3],[.75,.75,.5]))
        self.assertTrue(all(item["media_type"]=="VIDEO" and item["requirement"]=="REQUIRED" for item in parts))
        validate_generation_requests(requests,media,continuity)


if __name__ == "__main__": unittest.main()

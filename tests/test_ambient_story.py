from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from story_auto.application import OperatorService
from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.planning import compile_generation_requests, compile_media_plan, run_visual_planning_stages
from story_auto.core.planning.service import PlanningError
from story_auto.core.project import ProjectConfig, ProjectValidationError, RuntimeLayout, create_project, load_project
from story_auto.core.render import MediaTarget, compile_image, resolve_render_plan, resolve_render_settings, validate_video
from story_auto.core.visual import (
    AMBIENT_MOTIONS,
    AMBIENT_PRESENTATION_VERSION,
    compile_ambient_presentation,
    temporal_video_qc_applicability,
)


FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def planning_fixture(project_id: str) -> tuple[dict, dict, dict]:
    roles = ["incident", "power imbalance", "escalation", "point of no return", "reveal", "consequence", "closure"]
    summaries = [
        "The supervisor confronts Mara.", "The institution controls the room.", "The pressure rises.",
        "An irreversible accusation is made.", "Mara's hidden mastery is revealed.",
        "The institution responds with consequences.", "A restrained closure follows.",
    ]
    segments = []
    scenes = []
    for index, (role, summary) in enumerate(zip(roles, summaries), 1):
        start, end = float((index - 1) * 10), float(index * 10)
        segment_id = f"seg_{index:04d}"
        segments.append({"segment_id": segment_id, "start": start, "end": end, "text": summary + " "})
        entities = ["char_mara", "char_supervisor", "loc_office", "prop_blueprint"]
        if index >= 5: entities = ["char_mara", "char_supervisor", "loc_workshop", "prop_blueprint"]
        scenes.append({"scene_id":f"scn_{index:04d}","start":start,"end":end,
            "narration_segment_ids":[segment_id],"narration_text":summary,"story_role":role,
            "summary":summary,"entity_ids":entities})
    alignment = {"schema_version":"story-auto-alignment/1.0.0","project_id":project_id,
        "audio_path":"output/voice.wav","audio_sha256":"a" * 64,"narration_sha256":"n" * 64,
        "duration_seconds":70.0,"segments":segments}
    timeline = {"schema_version":"story-auto-story-timeline/1.0.0","project_id":project_id,
        "alignment_sha256":"f" * 64,"scenes":scenes,"review_status":"VALIDATED"}
    continuity = {"schema_version":"story-auto-continuity-bible/1.0.0","project_id":project_id,
        "style":{},"characters":[
            {"entity_id":"char_mara","name":"Mara","facts":{"age":52},"visual_design":{"hair":"dark bob"},"constraints":["same face and wardrobe"]},
            {"entity_id":"char_supervisor","name":"Supervisor","facts":{},"visual_design":{},"constraints":[]},
        ],"locations":[
            {"entity_id":"loc_office","name":"Institutional office","facts":{},"visual_design":{},"constraints":[]},
            {"entity_id":"loc_workshop","name":"Tactile workshop","facts":{},"visual_design":{},"constraints":[]},
        ],"props":[{"entity_id":"prop_blueprint","name":"Blueprint","facts":{},"visual_design":{"material":"worn paper"},"constraints":["same folded blueprint"]}],
        "review_status":"VALIDATED"}
    return alignment, timeline, continuity


class NoVisualProvider:
    def __init__(self): self.calls = 0
    def generate_structured(self, _request):
        self.calls += 1
        raise AssertionError("Ambient visual planning must not call a planning provider")


class AmbientProjectAndPlanningTests(unittest.TestCase):
    def test_durable_mode_style_validation_and_legacy_loading(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = RuntimeLayout.from_root(root)
            ambient = ProjectConfig("prj_ambient01", render_mode="ambient_story", settings={"ambient_style":"quiet_verdict"})
            create_project(runtime, ambient)
            self.assertEqual(load_project(runtime, ambient.project_id)[1].settings["ambient_style"], "quiet_verdict")
            create_project(runtime, ProjectConfig("prj_legacy01", render_mode="hybrid_hook"))
            self.assertNotIn("ambient_style", load_project(runtime, "prj_legacy01")[1].settings)
            with self.assertRaises(ProjectValidationError): ProjectConfig("prj_missing01", render_mode="ambient_story")
            with self.assertRaises(ProjectValidationError): ProjectConfig("prj_invalid01", render_mode="ambient_story", settings={"ambient_style":"viper_protocol"})

    def _ambient_project(self, root: str, style: str = "quiet_verdict"):
        runtime = RuntimeLayout.from_root(root)
        config = ProjectConfig("prj_ambientplan", render_mode="ambient_story", settings={
            "ambient_style":style,"llm":{"provider":"gemini","model":"gemini-3.5-flash"},
            "media":{"max_attempts":2,"large_batch_request_threshold":20},
        })
        paths = create_project(runtime, config, "# Ambient\n\n## Narration\n\nA complete approved story.\n")
        alignment, timeline, continuity = planning_fixture(config.project_id)
        for name, value in (("alignment",alignment),("story_timeline",timeline),("continuity_bible",continuity)):
            atomic_write_json(paths.artifact_path(f"output/{name}.json"), value)
        return runtime, config, paths

    def test_visual_chapters_budgets_image_only_resume_and_narrow_invalidation(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._ambient_project(root)
            provider = NoVisualProvider()
            self.assertEqual(run_visual_planning_stages(runtime.root, config.project_id, provider=provider), ("RUN","RUN","RUN"))
            quiet_shots = read_json(paths.artifact_path("output/shot_plan.json"))
            media = read_json(paths.artifact_path("output/media_plan.json"))
            requests = read_json(paths.artifact_path("output/generation_requests.json"))
            self.assertEqual(len(quiet_shots["shots"]), 6)
            self.assertEqual(quiet_shots["asset_budget"], {"preferred_min":2,"preferred_max":5,"hard_max":8,"planned_images":6,"budget_exception_reason":"SEMANTIC_STATE_INCOMPATIBILITY"})
            self.assertTrue(all(shot["source_scene_ids"] and shot["change_reason"] for shot in quiet_shots["shots"]))
            self.assertTrue(all((item["media_type"],item["requirement"]) == ("IMAGE","REQUIRED") for item in media["shots"]))
            self.assertFalse(any(item["media_type"] == "VIDEO" for item in requests["requests"]))
            self.assertEqual((requests["temporal_video_qc"], temporal_video_qc_applicability("ambient_story")), ("NOT_APPLICABLE","NOT_APPLICABLE"))
            self.assertEqual(provider.calls, 0)
            self.assertEqual(run_visual_planning_stages(runtime.root, config.project_id, provider=provider), ("SKIP","SKIP","SKIP"))
            request_hash = sha256_file(paths.artifact_path("output/generation_requests.json"))
            project = read_json(paths.project_file)
            project["settings"]["render"] = {"ambient_presentation":{"motion_enabled":False,"overlay_enabled":False}}
            atomic_write_json(paths.project_file, project)
            self.assertEqual(run_visual_planning_stages(runtime.root, config.project_id, provider=provider), ("SKIP","SKIP","SKIP"))
            self.assertEqual(sha256_file(paths.artifact_path("output/generation_requests.json")), request_hash)
            old_request_ids = [item["request_id"] for item in requests["requests"]]
            project["settings"]["ambient_style"] = "hidden_mastery"
            atomic_write_json(paths.project_file, project)
            self.assertEqual(run_visual_planning_stages(runtime.root, config.project_id, provider=provider), ("RUN","RUN","RUN"))
            hidden_shots = read_json(paths.artifact_path("output/shot_plan.json"))
            hidden_requests = read_json(paths.artifact_path("output/generation_requests.json"))
            self.assertEqual(len(hidden_shots["shots"]), 6)
            self.assertEqual(hidden_shots["asset_budget"], {"preferred_min":4,"preferred_max":7,"hard_max":10,"planned_images":6,"budget_exception_reason":None})
            self.assertNotEqual([item["request_id"] for item in hidden_requests["requests"]], old_request_ids)
            self.assertEqual(provider.calls, 0)

    def test_existing_mode_media_policies_remain_separate(self):
        shots = {"shots":[
            {"shot_id":"sh_0001","start":0.0,"end":1.0,"motion_value":0},
            {"shot_id":"sh_0002","start":1.0,"end":2.0,"motion_value":0},
        ]}
        settings = {"hook_seconds":.5,"motion_spike_threshold":8,"overrides":{},"max_attempts":2,
                    "aspect_ratio":"16:9","large_batch_request_threshold":20,"provider_video_clip_seconds":8.0,"ambient_style":None}
        hybrid = compile_media_plan("prj_hybrid", shots, "hybrid_hook", settings)
        full = compile_media_plan("prj_full", shots, "full_video_ai", settings)
        self.assertEqual([(item["media_type"],item["requirement"]) for item in hybrid["shots"]], [("VIDEO","REQUIRED"),("IMAGE","REQUIRED")])
        self.assertTrue(all((item["media_type"],item["requirement"]) == ("VIDEO","REQUIRED") for item in full["shots"]))
        self.assertTrue(all("ambient_presentation" not in item for item in hybrid["shots"] + full["shots"]))

    def test_operator_reports_temporal_qc_not_applicable(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            created = app.create_project(project_id="prj_ambientui", render_mode="ambient_story",
                ambient_style="hidden_mastery", content="# Story\n\n## Narration\n\nApproved narration.\n")
            self.assertEqual((created["render_mode"],created["ambient_style_label"]),("ambient_story","Hidden Mastery"))
            review = app.review_overview(created["project_id"])
            self.assertEqual(review["temporal_video_qc"], "NOT_APPLICABLE")
            self.assertEqual(next(item["status"] for item in review["quality"] if item["label"] == "Motion quality"), "Not applicable")


class AmbientRenderPlanTests(unittest.TestCase):
    def test_clean_derivative_exact_mapping_and_deterministic_presentation(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            raw = base / "raw.png"; clean = base / "clean.png"
            Image.new("RGB", (320,180), (150,120,90)).save(raw)
            Image.new("RGB", (320,180), (145,118,88)).save(clean)
            shot = {"shot_id":"sh_0001","start":0.0,"end":20.0,"story_state":"REVEAL"}
            presentation = compile_ambient_presentation("prj_map", shot, "quiet_verdict")
            media = {"shots":[{"shot_id":"sh_0001","media_type":"IMAGE","requirement":"REQUIRED","fallback_policy":"BLOCK",
                "image_motion_policy":presentation["motion"],"ambient_presentation":presentation}]}
            requests = {"requests":[{"request_id":"req_exact","purpose":"SHOT","shot_id":"sh_0001","media_type":"IMAGE","provider":"google_flow"}]}
            manifest = {"requests":[{"request_id":"req_exact","status":"SUCCEEDED","selected_asset":{
                "path":"clean.png","sha256":sha256_file(clean),"attempt":1,"raw_path":"raw.png","raw_sha256":sha256_file(raw),
                "postprocess":{"profile":"1376x768-v1","visible_provider_mark":"PASS_CLEAN"}}}]}
            alignment = {"duration_seconds":20.0}
            plan = resolve_render_plan(project_id="prj_map",project_root=base,render_mode="ambient_story",alignment=alignment,
                shot_plan={"shots":[shot]},media_plan=media,generation_requests=requests,generation_manifest=manifest,
                settings={"transition":{"type":"CUT","duration":0.0},"ambient_presentation":{"motion_enabled":True,"overlay_enabled":True}})
            self.assertEqual((plan["segments"][0]["source_asset"],plan["segments"][0]["source_hash"]),("clean.png",sha256_file(clean)))
            self.assertNotEqual(plan["segments"][0]["source_hash"], sha256_file(raw))
            self.assertEqual(plan["segments"][0]["ambient_presentation"], presentation)
            self.assertEqual(compile_ambient_presentation("prj_map", shot, "quiet_verdict"), presentation)
            self.assertTrue(presentation["motion"] == "STATIC" or .01 <= presentation["total_scale_change"] <= .03)


@unittest.skipUnless(FFMPEG, "FFmpeg integration requires ffmpeg and ffprobe")
class AmbientCompilerTests(unittest.TestCase):
    def test_all_motion_primitives_compile_with_safe_long_image_path(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root); source = base / "source.png"
            Image.new("RGB", (320,180), (92,118,142)).save(source)
            for index, motion in enumerate(sorted(AMBIENT_MOTIONS), 1):
                static = motion == "STATIC"
                presentation = {"schema_version":AMBIENT_PRESENTATION_VERSION,"style_id":"quiet_verdict","motion":motion,
                    "total_scale_change":0.0 if static else .02,
                    "translation_fraction":.008 if motion == "MICRO_DRIFT" else .02 if motion.startswith("SUBTLE_PAN") else 0.0,
                    "overlay":"FINE_GRAIN","overlay_strength":.55,"seed":100 + index}
                output = base / f"{motion.lower()}.mp4"
                metadata = compile_image(source,output,duration=3.0,motion=motion,
                    target=MediaTarget(160,90,6,"yuv420p"),presentation=presentation)
                validate_video(output,target=MediaTarget(160,90,6,"yuv420p"),silent=True,expected_duration=3.0)
                self.assertAlmostEqual(metadata["duration_seconds"], 3.0, places=1)

    def test_long_image_segment_streams_to_exact_duration(self):
        with tempfile.TemporaryDirectory() as root:
            base=Path(root); source=base/"long.png"; output=base/"long.mp4"
            Image.new("RGB",(320,180),(74,96,118)).save(source)
            presentation={"schema_version":AMBIENT_PRESENTATION_VERSION,"style_id":"quiet_verdict","motion":"SUBTLE_PUSH",
                "total_scale_change":.015,"translation_fraction":0.0,"overlay":"FINE_GRAIN","overlay_strength":.55,"seed":413}
            compile_image(source,output,duration=15.0,motion="SUBTLE_PUSH",target=MediaTarget(160,90,6,"yuv420p"),presentation=presentation)
            metadata=validate_video(output,target=MediaTarget(160,90,6,"yuv420p"),silent=True,expected_duration=15.0)
            self.assertAlmostEqual(metadata["duration_seconds"],15.0,places=1)


if __name__ == "__main__":
    unittest.main()

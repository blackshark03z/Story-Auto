from __future__ import annotations

import tempfile
import unittest
import shutil
import subprocess
from pathlib import Path

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.audio import TimedSpan, build_alignment
from story_auto.core.content import narration_hash
from story_auto.core.planning.service import (PlanningError, compile_full_image_shot_plan,
                                              compile_generation_requests, compile_media_plan,
                                              validate_generation_requests, validate_shot_plan)
from story_auto.core.planning import run_planning_stages, run_visual_planning_stages
from story_auto.core.project import ProjectConfig, ProjectValidationError, RuntimeLayout, create_project
from story_auto.core.render.compiler import compile_image
from story_auto.core.render.compositor import compose
from story_auto.core.render.service import run_render_stages
from story_auto.core.render.media import MediaTarget, probe_media
from story_auto.core.render.waveform import derive_amplitude_envelope, visualizer_spec
from story_auto.core.project.model import full_image_motion_spec
from story_auto.providers.llm import LLMResponse


class _TimelineContinuityFake:
    def __init__(self): self.calls = []
    def generate_structured(self, request):
        self.calls.append(request.stage)
        if request.stage == "story_timeline":
            value = {"groups":[{"segment_ids":["seg_0001"],"story_role":"setup","summary":"A beginning","entity_ids":[]}, {"segment_ids":["seg_0002"],"story_role":"turn","summary":"A resolution","entity_ids":[]}]}
        else:
            value = {"style":{},"characters":[],"locations":[],"props":[]}
        return LLMResponse(value, request.model, request.request_id, 1, 1, {})


class FullImagePlanningTests(unittest.TestCase):
    def setUp(self):
        self.timeline = {"scenes": [
            {"scene_id":"scn_0001","start":0.0,"end":12.0,"narration_segment_ids":["seg_1"],"summary":"A cautious arrival.","entity_ids":["char_a"]},
            {"scene_id":"scn_0002","start":12.0,"end":24.0,"narration_segment_ids":["seg_2"],"summary":"A clue appears.","entity_ids":["char_a","prop_key"]},
            {"scene_id":"scn_0003","start":24.0,"end":36.0,"narration_segment_ids":["seg_3"],"summary":"The evidence changes everything.","entity_ids":["char_a"]},
            {"scene_id":"scn_0004","start":36.0,"end":43.0,"narration_segment_ids":["seg_4"],"summary":"A final reaction.","entity_ids":["char_a"]},
        ]}
        self.continuity = {"characters":[{"entity_id":"char_a","name":"A","visual_design":{}}], "locations":[], "props":[{"entity_id":"prop_key","name":"key","visual_design":{}}]}
        self.alignment = {"duration_seconds":43.0,"segments":[
            {"segment_id":"seg_1","start":0.0,"end":12.0,"text":"A cautious arrival. "},
            {"segment_id":"seg_2","start":12.0,"end":24.0,"text":"A clue appears. "},
            {"segment_id":"seg_3","start":24.0,"end":36.0,"text":"The evidence changes everything. "},
            {"segment_id":"seg_4","start":36.0,"end":43.0,"text":"A final reaction."},
        ]}
        self.settings = {"hook_seconds":55.0,"motion_spike_threshold":8,"overrides":{},"max_attempts":2,"aspect_ratio":"16:9","large_batch_request_threshold":20,"provider_video_clip_seconds":8.0,
                         "full_image":{"image_duration_seconds":30.0,"cadence":"SEMANTIC_ADAPTIVE","motion":"AUTO_CONTINUOUS_ZOOM","audio_visualizer":True}}

    def test_config_serializes_defaults_and_rejects_invalid_duration(self):
        config = ProjectConfig("prj_full", render_mode="full_image", settings={"full_image": {}})
        self.assertEqual(config.to_dict()["settings"]["full_image"]["image_duration_seconds"], 30.0)
        for duration in (0, -1, "30", float("inf")):
            with self.assertRaises(ProjectValidationError):
                ProjectConfig("prj_bad", render_mode="full_image", settings={"full_image":{"image_duration_seconds":duration}})

    def test_semantic_windows_cover_once_are_deterministic_and_image_only(self):
        first = compile_full_image_shot_plan("prj_full", self.timeline, self.alignment, self.continuity, self.settings["full_image"], timeline_sha256="t", continuity_sha256="c")
        second = compile_full_image_shot_plan("prj_full", self.timeline, self.alignment, self.continuity, self.settings["full_image"], timeline_sha256="t", continuity_sha256="c")
        self.assertEqual(first, second)
        validate_shot_plan(first, self.timeline, self.continuity)
        self.assertEqual((first["shots"][0]["start"], first["shots"][-1]["end"]), (0.0, 43.0))
        self.assertEqual([shot["narration_segment_ids"] for shot in first["shots"]], [["seg_1", "seg_2"], ["seg_3", "seg_4"]])
        self.assertLess(first["shots"][-1]["end"] - first["shots"][-1]["start"], self.settings["full_image"]["image_duration_seconds"])
        media = compile_media_plan("prj_full", first, "full_image", self.settings)
        self.assertEqual([item["image_motion_policy"] for item in media["shots"]], ["AUTO_CONTINUOUS_ZOOM_IN", "AUTO_CONTINUOUS_ZOOM_OUT"])
        self.assertEqual([item["motion_spec"] for item in media["shots"]], [
            full_image_motion_spec("ZOOM_IN"), full_image_motion_spec("ZOOM_OUT")])
        self.assertEqual(media["shots"][0]["motion_spec"]["end_scale"], 1.16)
        requests = compile_generation_requests("prj_full", first, media, self.continuity, self.settings)
        validate_generation_requests(requests, media, self.continuity)
        self.assertTrue(all(item["media_type"] == "IMAGE" for item in requests["requests"]))
        self.assertEqual(requests["guardrail_estimate"]["required_video_requests"], 0)

    def test_effect_settings_do_not_change_image_request_identity(self):
        shots = compile_full_image_shot_plan("prj_full", self.timeline, self.alignment, self.continuity, self.settings["full_image"], timeline_sha256="t", continuity_sha256="c")
        media = compile_media_plan("prj_full", shots, "full_image", self.settings)
        requests = compile_generation_requests("prj_full", shots, media, self.continuity, self.settings)
        changed = {**self.settings, "full_image": {**self.settings["full_image"], "audio_visualizer":False}}
        changed_media = compile_media_plan("prj_full", shots, "full_image", changed)
        changed_requests = compile_generation_requests("prj_full", shots, changed_media, self.continuity, changed)
        self.assertEqual([item["request_id"] for item in requests["requests"]], [item["request_id"] for item in changed_requests["requests"]])

    def test_waveform_envelope_is_deterministic_and_reacts_to_amplitude(self):
        quiet_loud = derive_amplitude_envelope([.05] * 4 + [.8] * 4, window_size=4)
        self.assertEqual(quiet_loud, derive_amplitude_envelope([.05] * 4 + [.8] * 4, window_size=4))
        self.assertLess(quiet_loud[0], quiet_loud[1])
        spec = visualizer_spec(enabled=True)
        self.assertTrue(spec["deterministic"])
        self.assertEqual((spec["size"], spec["position"], spec["position_pixels"]), ([1344, 270], "CENTER_FRAME", [288, 405]))
        self.assertEqual((spec["amplitude_gain"], spec["amplitude_scale"], spec["color"]), (4.0, "sqrt", "white@0.92"))
        self.assertFalse(visualizer_spec(enabled=False)["enabled"])

    def test_full_image_visual_stage_uses_no_video_or_motion_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = RuntimeLayout.from_root(directory)
            config = ProjectConfig("prj_full_stage", render_mode="full_image", settings={
                "llm":{"provider":"gemini","model":"gemini-3.5-flash"},
                "full_image":{"image_duration_seconds":30,"cadence":"SEMANTIC_ADAPTIVE","motion":"AUTO_CONTINUOUS_ZOOM","audio_visualizer":True},
            })
            paths = create_project(runtime, config, "## Narration\n\nThe beginning. The resolution.\n")
            alignment = build_alignment(project_id=config.project_id, audio_path="output/voice.wav", audio_sha256="a", narration_sha256=narration_hash("The beginning. The resolution."), duration_seconds=36.0, source="fixture", spans=[TimedSpan("The beginning. ", 0, 18), TimedSpan("The resolution.", 18, 36)])
            atomic_write_json(paths.artifact_path("output/alignment.json"), alignment)
            provider = _TimelineContinuityFake()
            run_planning_stages(runtime.root, config.project_id, provider=provider)
            self.assertEqual(run_visual_planning_stages(runtime.root, config.project_id), ("RUN", "RUN", "RUN"))
            requests = read_json(paths.artifact_path("output/generation_requests.json"))
            self.assertEqual(provider.calls, ["story_timeline", "continuity"])
            self.assertTrue(all(item["media_type"] == "IMAGE" for item in requests["requests"]))

    def test_continuous_zoom_outputs_safe_16_by_9_video(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable")
        with tempfile.TemporaryDirectory() as directory:
            source = __import__("pathlib").Path(directory) / "still.png"
            Image.new("RGB", (800, 600), "navy").save(source)
            for motion in ("AUTO_CONTINUOUS_ZOOM_IN", "AUTO_CONTINUOUS_ZOOM_OUT"):
                output = __import__("pathlib").Path(directory) / f"{motion}.mp4"
                compile_image(source, output, duration=.4, motion=motion, target=MediaTarget(320, 180, 10))
                meta = probe_media(output)
                self.assertEqual((meta["video"]["width"], meta["video"]["height"]), (320, 180))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg unavailable")
    def test_full_image_final_format_contract_is_hash_bound_and_master_audio_owned(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            runtime = RuntimeLayout.from_root(directory)
            config = ProjectConfig("prj_full_format", render_mode="full_image", settings={
                "render": {"width": 320, "height": 180, "fps": 10},
                "full_image": {"image_duration_seconds": 5, "cadence": "FIXED",
                               "motion": "AUTO_CONTINUOUS_ZOOM", "audio_visualizer": True},
            })
            paths = create_project(runtime, config)
            narration_rel = "assets/audio/narration.wav"
            narration = paths.artifact_path(narration_rel); narration.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            "sine=frequency=440:sample_rate=48000:duration=1", "-c:a", "pcm_s16le", str(narration)], check=True)
            image_rel = "assets/image/req_full/attempt_001.png"
            image = paths.artifact_path(image_rel); image.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (640, 360), "navy").save(image)
            atomic_write_json(paths.artifact_path("output/alignment.json"), {
                "audio_path": narration_rel, "duration_seconds": 1.0,
                "segments": [{"segment_id": "seg_1", "start": 0.0, "end": 1.0, "text": "One image beat."}],
            })
            atomic_write_json(paths.artifact_path("output/shot_plan.json"), {
                "shots": [{"shot_id": "sh_0001", "start": 0.0, "end": 1.0}]})
            atomic_write_json(paths.artifact_path("output/media_plan.json"), {"render_mode": "full_image", "shots": [{
                "shot_id": "sh_0001", "media_type": "IMAGE", "requirement": "REQUIRED", "fallback_policy": "BLOCK",
                "image_motion_policy": "AUTO_CONTINUOUS_ZOOM_IN", "motion_spec": full_image_motion_spec("ZOOM_IN"),
            }]})
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": [{
                "request_id": "req_full", "purpose": "SHOT", "shot_id": "sh_0001", "media_type": "IMAGE", "provider": "google_flow",
            }]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"requests": [{
                "request_id": "req_full", "status": "SUCCEEDED",
                "selected_asset": {"path": image_rel, "sha256": sha256_file(image), "attempt": 1},
            }]})
            result = run_render_stages(runtime.root, config.project_id)
            manifest = result["final_manifest"]
            render_plan_path = paths.artifact_path("output/render_plan.json")
            self.assertEqual(read_json(render_plan_path)["render_mode"], "full_image")
            self.assertEqual(manifest["render_plan_sha256"], sha256_file(render_plan_path))
            self.assertEqual(read_json(paths.artifact_path("output/audio_plan.json"))["source_video_audio"], "MUTE")
            self.assertTrue(manifest["audio_visualizer"]["enabled"])
            self.assertEqual((manifest["width"], manifest["height"], len(manifest["streams"]["audio"])), (320, 180, 1))
            self.assertAlmostEqual(manifest["duration_seconds"], 1.0, delta=.12)
            self.assertEqual(manifest["final_sha256"], sha256_file(paths.artifact_path("output/final.mp4")))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg unavailable")
    def test_waveform_on_and_off_render_valid_audio_video(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "still.png"; clip = root / "clip.mp4"; narration = root / "voice.wav"
            Image.new("RGB", (800, 600), "navy").save(source)
            compile_image(source, clip, duration=.5, motion="AUTO_CONTINUOUS_ZOOM_IN", target=MediaTarget(320, 180, 10))
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.5", "-c:a", "pcm_s16le", str(narration)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            segment = {"target_duration":.5, "transition":{"type":"CUT", "duration":0}}
            for enabled in (False, True):
                output = root / f"final_{enabled}.mp4"
                compose(clips=[clip], segments=[segment], narration=narration, output=output, master_duration=.5,
                        target=MediaTarget(320, 180, 10), audio_visualizer=enabled)
                meta = probe_media(output)
                self.assertEqual((meta["video"]["width"], meta["video"]["height"], len(meta["audio"])), (320, 180, 1))


if __name__ == "__main__":
    unittest.main()

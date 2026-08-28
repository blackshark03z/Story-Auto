from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import wave

from story_auto.application.operator import OperatorService, OperatorServiceError
from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.audio import SrtError, parse_srt_bytes
from story_auto.core.planning.service import (compile_full_image_shot_plan, compile_generation_requests,
                                              compile_media_plan, validate_shot_plan)
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.pipeline import adopt_existing_audio, adopt_existing_srt, run_audio_stages


def _wav(seconds: int = 12) -> bytes:
    value = BytesIO()
    with wave.open(value, "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000 * seconds)
    return value.getvalue()


SRT = b"""1\n00:00:00,000 --> 00:00:02,000\nA sentence starts\n\n2\n00:00:02,000 --> 00:00:02,010\n\n3\n00:00:02,010 --> 00:00:04,000\nand continues here.\n\n4\n00:00:04,000 --> 00:00:06,000\nAnother action happens.\n\n5\n00:00:06,000 --> 00:00:08,000\nThen the final thought\n\n6\n00:00:08,000 --> 00:00:11,800\nresolves safely.\n"""


class _NoTts:
    def generate(self, *_args, **_kwargs):
        raise AssertionError("TTS must not be called for Audio+SRT")


class Goal50AudioSrtDirectComposeTests(unittest.TestCase):
    def _project(self, root: str):
        runtime = RuntimeLayout.from_root(root)
        paths = create_project(runtime, ProjectConfig("prj_goal50", render_mode="full_image", settings={
            "execution": {"mode": "EXISTING_VOICE"},
            "full_image": {"image_duration_seconds": 5, "cadence": "SEMANTIC_ADAPTIVE"},
        }), "# Story\n\n## Narration\n\nA sentence starts and continues here. Another action happens. Then the final thought resolves safely.\n")
        return runtime, paths

    def test_parser_normalizes_empty_ten_millisecond_cues_deterministically(self):
        first = parse_srt_bytes(SRT)
        second = parse_srt_bytes(SRT)
        cues, encoding, stats = first
        self.assertEqual(first, second)
        self.assertEqual(encoding, "utf-8-sig")
        self.assertEqual(stats, {"raw_cue_count": 6, "text_cue_count": 5, "ignored_empty_cues": 1,
                                 "first_timestamp": 0.0, "last_timestamp": 11.8})
        self.assertEqual([cue.cue_id for cue in cues], ["cue_0001", "cue_0003", "cue_0004", "cue_0005", "cue_0006"])

    def test_malformed_or_non_monotonic_srt_fails_closed(self):
        with self.assertRaisesRegex(SrtError, "SRT_TIMESTAMP_INVALID"):
            parse_srt_bytes(b"1\n00:99:00,000 --> 00:00:02,000\nBad\n")
        with self.assertRaisesRegex(SrtError, "SRT_TIMELINE_NON_MONOTONIC"):
            parse_srt_bytes(b"1\n00:00:02,000 --> 00:00:03,000\nOne\n\n2\n00:00:01,000 --> 00:00:04,000\nTwo\n")

    def test_import_binds_srt_to_audio_and_skips_tts_and_alignment_replacement(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths = self._project(root)
            audio, srt = Path(root) / "narration.wav", Path(root) / "timing.srt"
            audio.write_bytes(_wav()); srt.write_bytes(SRT)
            adopt_existing_audio(runtime.root, paths.project_id, audio)
            manifest = adopt_existing_srt(runtime.root, paths.project_id, srt)
            alignment = read_json(paths.artifact_path("output/alignment.json"))
            self.assertEqual(manifest["validation_result"], "PASS")
            self.assertEqual(manifest["normalization"]["IGNORED_EMPTY_CUES"], 1)
            self.assertEqual(alignment["timing_source"], "SRT")
            self.assertEqual(run_audio_stages(runtime.root, paths.project_id, adapter=_NoTts()), ("REUSE", "REUSE"))
            self.assertEqual(read_json(paths.artifact_path("output/alignment.json"))["source"], "SRT")

    def test_material_audio_srt_duration_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths = self._project(root)
            audio, srt = Path(root) / "narration.wav", Path(root) / "timing.srt"
            audio.write_bytes(_wav(2)); srt.write_bytes(SRT)
            adopt_existing_audio(runtime.root, paths.project_id, audio)
            with self.assertRaisesRegex(ValueError, "AUDIO_SRT_DURATION_MISMATCH"):
                adopt_existing_srt(runtime.root, paths.project_id, srt)

    def test_full_image_windows_group_cues_without_gaps_or_overlaps(self):
        cues, _, _ = parse_srt_bytes(SRT)
        alignment = {"duration_seconds": 12.0, "segments": [
            {"segment_id": cue.cue_id, "start": cue.start, "end": cue.end, "text": cue.text} for cue in cues]}
        scenes = [{"scene_id": f"scn_{index:04d}", "start": 0.0 if index == 1 else cues[index - 1].start,
                   "end": 12.0 if index == len(cues) else cue.end, "narration_segment_ids": [cue.cue_id],
                   "summary": cue.text, "entity_ids": []} for index, cue in enumerate(cues, 1)]
        timeline = {"scenes": scenes}
        continuity = {"characters": [], "locations": [], "props": []}
        plan = compile_full_image_shot_plan("prj_goal50", timeline, alignment, continuity,
            {"image_duration_seconds": 5.0, "cadence": "SEMANTIC_ADAPTIVE", "motion": "AUTO_CONTINUOUS_ZOOM", "audio_visualizer": True},
            timeline_sha256="a", continuity_sha256="b")
        self.assertLess(len(plan["shots"]), len(cues))
        self.assertTrue(all(shot["source_cue_ids"] == shot["narration_segment_ids"] for shot in plan["shots"]))
        self.assertTrue(all(shot["window_id"].startswith("win_") for shot in plan["shots"]))
        self.assertEqual(plan["shots"][0]["start"], 0.0)
        self.assertEqual(plan["shots"][-1]["end"], 12.0)
        self.assertTrue(all(a["end"] == b["start"] for a, b in zip(plan["shots"], plan["shots"][1:])))
        validate_shot_plan(plan, timeline, continuity)

    def test_fixed_windows_and_srt_change_create_new_exact_window_request_identities(self):
        def plan_for(source: bytes, cadence: str):
            cues, _, _ = parse_srt_bytes(source)
            alignment = {"duration_seconds": 12.0, "segments": [
                {"segment_id": cue.cue_id, "start": cue.start, "end": cue.end, "text": cue.text} for cue in cues]}
            timeline = {"scenes": [{"scene_id": f"scn_{index:04d}", "start": 0.0 if index == 1 else cues[index - 1].start,
                         "end": 12.0 if index == len(cues) else cue.end, "narration_segment_ids": [cue.cue_id],
                         "summary": cue.text, "entity_ids": []} for index, cue in enumerate(cues, 1)]}
            continuity = {"characters": [], "locations": [], "props": []}
            full_image = {"image_duration_seconds": 5.0, "cadence": cadence, "motion": "AUTO_CONTINUOUS_ZOOM", "audio_visualizer": True}
            plan = compile_full_image_shot_plan("prj_goal50", timeline, alignment, continuity, full_image,
                timeline_sha256="timeline", continuity_sha256="continuity")
            settings = {"full_image": full_image, "hook_seconds": 0.0, "motion_spike_threshold": 8,
                        "overrides": {}, "max_attempts": 2, "aspect_ratio": "16:9",
                        "large_batch_request_threshold": 20, "provider_video_clip_seconds": 8.0}
            return plan, compile_generation_requests("prj_goal50", plan,
                compile_media_plan("prj_goal50", plan, "full_image", settings), continuity, settings)

        fixed, fixed_requests = plan_for(SRT, "FIXED")
        changed, changed_requests = plan_for(SRT.replace(b"Another action happens.", b"A different action happens."), "FIXED")
        self.assertLess(len(fixed["shots"]), 5)
        self.assertEqual(fixed["shots"][-1]["end"], 12.0)  # final partial window covers audio master
        self.assertNotEqual([shot["window_id"] for shot in fixed["shots"]], [shot["window_id"] for shot in changed["shots"]])
        self.assertNotEqual([item["request_id"] for item in fixed_requests["requests"]],
                            [item["request_id"] for item in changed_requests["requests"]])

    def test_direct_compose_requires_current_exact_window_request_identity_and_never_calls_provider(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths = self._project(root)
            audio, srt = Path(root) / "narration.wav", Path(root) / "timing.srt"
            audio.write_bytes(_wav()); srt.write_bytes(SRT)
            original = adopt_existing_audio(runtime.root, paths.project_id, audio)
            adopt_existing_srt(runtime.root, paths.project_id, srt)
            current = {"request_id": "req_current_window", "purpose": "SHOT", "shot_id": "sh_0001", "media_type": "IMAGE"}
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": [current]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"requests": [{
                "request_id": "req_stale_window", "status": "SUCCEEDED", "selected_asset": {"sha256": "old"}}]})
            project = read_json(paths.project_file); project["settings"]["execution"]["mode"] = "RENDER_ONLY"; atomic_write_json(paths.project_file, project)
            app = OperatorService(root)
            with self.assertRaisesRegex(OperatorServiceError, "No accepted visual assets"):
                app.start_or_resume(paths.project_id, audio_adapter=_NoTts())
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"requests": [{
                "request_id": "req_current_window", "status": "SUCCEEDED", "selected_asset": {"sha256": "accepted"}}]})
            result = app.start_or_resume(paths.project_id, audio_adapter=_NoTts())
            self.assertEqual((result["tts"], result["alignment"]), ("REUSE", "REUSE"))
            self.assertEqual(read_json(paths.artifact_path("output/audio_manifest.json"))["audio_sha256"], original["audio_sha256"])
            self.assertTrue(app.snapshot(paths.project_id)["accepted_visuals"])

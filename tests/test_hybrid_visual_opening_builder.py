from __future__ import annotations

from pathlib import Path
import base64
import shutil
import subprocess
import tempfile
import unittest

from story_auto.core.artifacts import atomic_write_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.visual.opening_builder import (OpeningBuilderError, configure_opening_builder,
    import_opening_clip, opening_builder_view, prepare_opening_builder_from_plan)


FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


class HybridVisualOpeningBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = RuntimeLayout.from_root(self.temp.name).ensure()
        self.project_id = "prj_hybrid_opening"
        self.paths = create_project(
            self.runtime,
            ProjectConfig(self.project_id, render_mode="hybrid_hook", settings={
                "render": {"width": 320, "height": 180, "fps": 24, "pixel_format": "yuv420p"},
            }),
            "# Hybrid opening test\n\n## Narration\n\nA short opening narration for the manual builder.\n",
        )
        self.shared = "Same adult protagonist, same wardrobe, same dawn mountain setting, restrained cinematic style."
        self.slots = [
            {"duration_seconds": 6, "purpose": "Hook establishing beat", "prompt": "Wide dawn reveal; protagonist enters frame."},
            {"duration_seconds": 6, "purpose": "Character action beat", "prompt": "Medium shot; protagonist notices a distant signal and reacts."},
            {"duration_seconds": 6, "purpose": "Transition beat", "prompt": "Closer reaction resolving toward the first still-image scene."},
        ]

    def tearDown(self):
        self.temp.cleanup()

    def _configure(self):
        return configure_opening_builder(self.runtime.root, self.project_id,
                                         shared_context=self.shared, slot_specs=self.slots)

    def _video(self, name: str, *, duration: float = 7.0, color: str = "navy", audio: bool = True) -> Path:
        path = Path(self.temp.name) / name
        command = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                   f"color=c={color}:s=640x360:r=30:d={duration}"]
        if audio:
            command += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={duration}",
                        "-shortest"]
        command += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        if audio:
            command += ["-c:a", "aac"]
        else:
            command += ["-an"]
        command.append(str(path))
        subprocess.run(command, check=True)
        return path

    def test_configure_creates_stable_exact_slot_contract_and_copy_pack(self):
        value = self._configure()
        self.assertEqual(value["status"], "NOT_READY")
        self.assertEqual(value["opening_duration_seconds"], 18.0)
        self.assertEqual([item["slot_id"] for item in value["slots"]], ["OPENING_O1", "OPENING_O2", "OPENING_O3"])
        self.assertEqual([(item["start"], item["end"]) for item in value["slots"]], [(0.0, 6.0), (6.0, 12.0), (12.0, 18.0)])
        self.assertEqual(value["slots"][1]["prompt"], self.slots[1]["prompt"])
        self.assertEqual(len(value["slots"][1]["prompt_sha256"]), 64)
        self.assertIn("OPENING SHARED CONTEXT", value["copy_all_prompts"])
        self.assertIn("OPENING_O2 — 6.0 sec", value["copy_all_prompts"])
        same = self._configure()
        self.assertEqual(same["plan_sha256"], value["plan_sha256"])

    def test_prepare_from_canonical_generation_requests_preserves_exact_prompts_and_request_identity(self):
        atomic_write_json(self.paths.artifact_path("output/continuity_bible.json"), {
            "characters": [{"entity_id": "char_1", "name": "Lan", "visual_design": "white and pale-blue hanfu", "constraints": ["same face"]}],
            "locations": [{"entity_id": "loc_1", "name": "Mountain pavilion", "facts": ["dawn mist"]}],
            "props": [],
        })
        atomic_write_json(self.paths.artifact_path("output/generation_requests.json"), {
            "schema_version": "story-auto-generation-requests/1.0.0",
            "project_id": self.project_id,
            "requests": [
                {"request_id": "req_o1", "purpose": "SHOT", "shot_id": "sh_0001", "media_type": "VIDEO",
                 "requirement": "REQUIRED", "part_index": 1, "target_start": 0.0, "target_end": 8.0,
                 "target_duration": 8.0, "prompt": "Exact provider-ready opening prompt one."},
                {"request_id": "req_o2", "purpose": "SHOT", "shot_id": "sh_0002", "media_type": "VIDEO",
                 "requirement": "REQUIRED", "part_index": 1, "target_start": 8.0, "target_end": 16.0,
                 "target_duration": 8.0, "prompt": "Exact provider-ready opening prompt two."},
                {"request_id": "req_body", "purpose": "SHOT", "shot_id": "sh_0003", "media_type": "IMAGE",
                 "requirement": "REQUIRED", "part_index": 1, "target_start": 16.0, "target_end": 24.0,
                 "target_duration": 8.0, "prompt": "Body image prompt."},
            ],
        })
        value = prepare_opening_builder_from_plan(self.runtime.root, self.project_id)
        self.assertEqual(value["opening_duration_seconds"], 16.0)
        self.assertEqual([item["source_request_id"] for item in value["slots"]], ["req_o1", "req_o2"])
        self.assertEqual(value["slots"][0]["prompt"], "Exact provider-ready opening prompt one.")
        self.assertIn("Lan", value["shared_context"])
        self.assertIn("Mountain pavilion", value["shared_context"])
        self.assertIn("Exact provider-ready opening prompt two.", value["copy_all_prompts"])

    def test_invalid_opening_duration_and_slot_duration_fail_closed(self):
        with self.assertRaises(OpeningBuilderError) as caught:
            configure_opening_builder(self.runtime.root, self.project_id, shared_context=self.shared,
                                      slot_specs=[{"duration_seconds": 5, "purpose": "a", "prompt": "a"},
                                                  {"duration_seconds": 5, "purpose": "b", "prompt": "b"}])
        self.assertEqual(caught.exception.failure_class, "OPENING_DURATION_INVALID")
        invalid = list(self.slots)
        invalid[0] = {"duration_seconds": 4, "purpose": "bad", "prompt": "bad"}
        with self.assertRaises(OpeningBuilderError) as caught:
            configure_opening_builder(self.runtime.root, self.project_id, shared_context=self.shared, slot_specs=invalid)
        self.assertEqual(caught.exception.failure_class, "OPENING_SLOT_DURATION_INVALID")

    @unittest.skipUnless(FFMPEG, "Opening Builder integration requires ffmpeg and ffprobe")
    def test_manual_import_binds_exact_slot_normalizes_and_strips_audio(self):
        self._configure()
        source = self._video("o1_with_audio.mp4", duration=7.0, audio=True)
        value = import_opening_clip(self.runtime.root, self.project_id, "OPENING_O1", source,
                                    original_filename="manual_o1.mp4")
        slot = value["slots"][0]
        self.assertEqual((slot["slot_id"], slot["status"], slot["revision"]), ("OPENING_O1", "READY", 1))
        self.assertTrue(slot["source_asset"]["had_audio"])
        self.assertTrue(slot["normalized_asset"]["audio_stripped"])
        self.assertEqual((slot["normalized_asset"]["width"], slot["normalized_asset"]["height"]), (320, 180))
        self.assertAlmostEqual(slot["normalized_asset"]["duration_seconds"], 6.0, delta=.08)
        normalized = self.paths.artifact_path(slot["normalized_asset"]["path"])
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                                "stream=codec_type", "-of", "csv=p=0", str(normalized)],
                               capture_output=True, text=True, check=True)
        self.assertEqual(probe.stdout.strip(), "")
        self.assertFalse(value["ready"])
        self.assertFalse(value["slots"][1]["asset_ready"])

    @unittest.skipUnless(FFMPEG, "Opening Builder integration requires ffmpeg and ffprobe")
    def test_all_slots_ready_replacement_history_and_plan_lock(self):
        self._configure()
        for index, color in enumerate(("navy", "teal", "maroon"), start=1):
            import_opening_clip(self.runtime.root, self.project_id, f"OPENING_O{index}",
                                self._video(f"o{index}.mp4", color=color))
        value = opening_builder_view(self.runtime.root, self.project_id)
        self.assertTrue(value["ready"])
        self.assertEqual(value["status"], "READY")
        before = value["slots"][0]["normalized_asset"]["sha256"]
        replaced = import_opening_clip(self.runtime.root, self.project_id, "OPENING_O1",
                                       self._video("o1_replacement.mp4", color="gold"))
        first = replaced["slots"][0]
        self.assertEqual(first["revision"], 2)
        self.assertEqual(len(first["replacement_history"]), 1)
        self.assertEqual(first["replacement_history"][0]["normalized_asset"]["sha256"], before)
        changed = [dict(item) for item in self.slots]
        changed[0]["prompt"] = "A materially changed opening prompt."
        with self.assertRaises(OpeningBuilderError) as caught:
            configure_opening_builder(self.runtime.root, self.project_id, shared_context=self.shared, slot_specs=changed)
        self.assertEqual(caught.exception.failure_class, "OPENING_PLAN_LOCKED")

    @unittest.skipUnless(FFMPEG, "Opening Builder integration requires ffmpeg and ffprobe")
    def test_large_shortage_is_rejected_but_small_mismatch_is_handled(self):
        self._configure()
        too_short = self._video("too_short.mp4", duration=4.5, audio=False)
        with self.assertRaises(OpeningBuilderError) as caught:
            import_opening_clip(self.runtime.root, self.project_id, "OPENING_O1", too_short)
        self.assertEqual(caught.exception.failure_class, "OPENING_IMPORT_TOO_SHORT")
        small_short = self._video("small_short.mp4", duration=5.4, audio=False)
        value = import_opening_clip(self.runtime.root, self.project_id, "OPENING_O1", small_short)
        self.assertEqual(value["slots"][0]["status"], "READY")
        self.assertAlmostEqual(value["slots"][0]["normalized_asset"]["duration_seconds"], 6.0, delta=.08)

    @unittest.skipUnless(FFMPEG, "Opening Builder integration requires ffmpeg and ffprobe")
    def test_operator_workspace_and_browser_payload_round_trip(self):
        try:
            from story_auto.application import OperatorService
        except ModuleNotFoundError as error:
            self.skipTest(f"operator dependency unavailable in this interpreter: {error}")
        self._configure()
        source = self._video("browser_o1.mp4", duration=6.5, audio=True)
        service = OperatorService(self.runtime.root)
        payload = {"filename": "external_generator_o1.mp4",
                   "base64": base64.b64encode(source.read_bytes()).decode("ascii")}
        imported = service.import_opening_clip(self.project_id, slot_id="OPENING_O1", imported_video=payload)
        self.assertEqual(imported["slots"][0]["source_asset"]["original_filename"], "external_generator_o1.mp4")
        workspace = service.project_workspace(self.project_id)
        self.assertEqual(workspace["production"]["pipeline_status"], "FEATURE_NOT_AVAILABLE")
        self.assertEqual(workspace["opening_builder"]["slots"][0]["status"], "READY")


if __name__ == "__main__":
    unittest.main()

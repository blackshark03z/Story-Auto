from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import wave

from story_auto.application.operator import OperatorService, OperatorServiceError
from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, ProjectValidationError, RuntimeLayout, create_project
from story_auto.core.render import resolve_render_settings
from story_auto.pipeline import adopt_existing_audio, run_audio_stages


class _NoTts:
    def generate(self, *_args, **_kwargs):
        raise AssertionError("TTS must not be submitted for a reused narration")


def _wav(seconds: int = 2) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000 * seconds)
    return buffer.getvalue()


class Goal49PipelineReuseTests(unittest.TestCase):
    def _project(self, root: str, mode: str = "EXISTING_VOICE"):
        runtime = RuntimeLayout.from_root(root)
        config = ProjectConfig("prj_goal49", settings={"execution": {"mode": mode}})
        paths = create_project(runtime, config, "# Reuse\n\n## Narration\n\nFirst sentence. Second sentence.\n")
        source = Path(root) / "narration.wav"; source.write_bytes(_wav())
        return runtime, paths, source

    def test_execution_mode_serialization_and_full_default(self):
        self.assertEqual(ProjectConfig("prj_full").settings, {})
        value = ProjectConfig("prj_reuse", settings={"execution":{"mode":"VISUALS_ONLY"}})
        self.assertEqual(ProjectConfig.from_dict(value.to_dict()).settings["execution"]["mode"], "VISUALS_ONLY")
        with self.assertRaises(ProjectValidationError): ProjectConfig("prj_bad", settings={"execution":{"mode":"SKIP"}})

    def test_imported_audio_is_canonical_validated_and_never_calls_tts(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths, source = self._project(root)
            manifest = adopt_existing_audio(runtime.root, paths.project_id, source)
            self.assertEqual(manifest["source_type"], "IMPORTED")
            self.assertEqual(manifest["canonical_path"], manifest["audio_path"])
            self.assertEqual(manifest["provenance"]["validation"], "READABLE_AUDIO_STREAM")
            self.assertTrue(paths.artifact_path(manifest["audio_path"]).is_file())
            self.assertEqual(run_audio_stages(runtime.root, paths.project_id, adapter=_NoTts()), ("REUSE", "REUSE"))
            alignment = read_json(paths.artifact_path("output/alignment.json"))
            self.assertEqual(alignment["source"], "deterministic_text_proportional_no_asr")

    def test_invalid_or_missing_import_is_rejected_without_canonical_binding(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths, source = self._project(root)
            source.write_bytes(b"not media")
            with self.assertRaises(Exception): adopt_existing_audio(runtime.root, paths.project_id, source)
            self.assertFalse(paths.artifact_path("output/audio_manifest.json").exists())
            with self.assertRaisesRegex(ValueError, "No narration audio has been selected"):
                run_audio_stages(runtime.root, paths.project_id, adapter=_NoTts())

    def test_visuals_only_reuses_audio_and_render_only_blocks_without_accepted_assets(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths, source = self._project(root, "VISUALS_ONLY")
            adopt_existing_audio(runtime.root, paths.project_id, source)
            self.assertEqual(run_audio_stages(runtime.root, paths.project_id, adapter=_NoTts())[0], "REUSE")
            app = OperatorService(root)
            project = read_json(paths.project_file); project["settings"]["execution"]["mode"] = "RENDER_ONLY"; atomic_write_json(paths.project_file, project)
            with self.assertRaisesRegex(OperatorServiceError, "No accepted visual assets"):
                app.start_or_resume(paths.project_id, audio_adapter=_NoTts())
            with self.assertRaisesRegex(OperatorServiceError, "RENDER_ONLY"):
                app.generate(paths.project_id, executor=object())

    def test_render_only_uses_accepted_asset_identity_without_provider_submission(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths, source = self._project(root, "RENDER_ONLY")
            adopt_existing_audio(runtime.root, paths.project_id, source)
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests":[{"request_id":"req_1","purpose":"SHOT","shot_id":"sh_1"}]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"requests":[{"request_id":"req_1","status":"SUCCEEDED","selected_asset":{"sha256":"accepted"}}]})
            app = OperatorService(root)
            result = app.start_or_resume(paths.project_id, audio_adapter=_NoTts())
            self.assertEqual(result["tts"], "REUSE")
            self.assertEqual(result["alignment"], "REUSE")
            self.assertTrue(app.snapshot(paths.project_id)["accepted_visuals"])

    def test_render_only_blocks_qc_pending_visuals(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths, source = self._project(root, "RENDER_ONLY")
            adopt_existing_audio(runtime.root, paths.project_id, source)
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), {
                "requests": [{"request_id": "req_pending", "purpose": "SHOT", "shot_id": "sh_pending"}],
            })
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
                "requests": [{"request_id": "req_pending", "status": "QC_PENDING",
                              "selected_asset": {"sha256": "unreviewed"}}],
            })
            with self.assertRaisesRegex(OperatorServiceError, "No accepted visual assets"):
                OperatorService(root).start_or_resume(paths.project_id, audio_adapter=_NoTts())

    def test_full_image_scene_duration_is_seconds_and_preserves_imported_narration(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = RuntimeLayout.from_root(root)
            config = ProjectConfig("prj_duration", render_mode="full_image", settings={
                "execution":{"mode":"EXISTING_VOICE"},
                "full_image":{"image_duration_seconds":30,"cadence":"SEMANTIC_ADAPTIVE"},
            })
            paths=create_project(runtime,config,"# Duration\n\n## Narration\n\nA full image narration.\n")
            source=Path(root)/"voice.wav"; source.write_bytes(_wav())
            original=adopt_existing_audio(runtime.root,paths.project_id,source)
            updated=OperatorService(root).set_full_image_duration(paths.project_id,15,"FIXED")
            self.assertEqual(read_json(paths.project_file)["settings"]["full_image"]["image_duration_seconds"],15.0)
            self.assertEqual(read_json(paths.project_file)["settings"]["full_image"]["cadence"],"FIXED")
            self.assertEqual(read_json(paths.artifact_path("output/audio_manifest.json"))["audio_sha256"],original["audio_sha256"])
            self.assertEqual(updated["duration_seconds"],2.0)

    def test_waveform_change_requires_only_final_render_and_preserves_visuals(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=RuntimeLayout.from_root(root)
            config=ProjectConfig("prj_waveform",render_mode="full_image",settings={
                "execution":{"mode":"EXISTING_VOICE"},
                "full_image":{"audio_visualizer":False},
            })
            paths=create_project(runtime,config,"# Waveform\n\n## Narration\n\nA reusable voice stays unchanged.\n")
            source=Path(root)/"voice.wav"; source.write_bytes(_wav())
            original=adopt_existing_audio(runtime.root,paths.project_id,source)
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests":[{"request_id":"req_1","purpose":"SHOT","shot_id":"sh_1"}]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"requests":[{"request_id":"req_1","status":"SUCCEEDED","selected_asset":{"sha256":"accepted"}}]})
            old_settings,_=resolve_render_settings(config)
            paths.artifact_path("output/final.mp4").write_bytes(b"old final")
            atomic_write_json(paths.artifact_path("output/final_manifest.json"), {"composer":{"settings":old_settings}})
            before_requests=paths.artifact_path("output/generation_requests.json").read_bytes()
            before_manifest=paths.artifact_path("output/generation_manifest.json").read_bytes()
            updated=OperatorService(root).set_full_image_audio_visualizer(paths.project_id,True)
            self.assertTrue(read_json(paths.project_file)["settings"]["full_image"]["audio_visualizer"])
            self.assertEqual(read_json(paths.artifact_path("output/audio_manifest.json"))["audio_sha256"],original["audio_sha256"])
            self.assertEqual(paths.artifact_path("output/generation_requests.json").read_bytes(),before_requests)
            self.assertEqual(paths.artifact_path("output/generation_manifest.json").read_bytes(),before_manifest)
            self.assertTrue(updated["render_stale"])
            self.assertEqual(updated["render_status"],"NEEDS_RENDER")
            self.assertIsNone(updated["final_path"])


if __name__ == "__main__":
    unittest.main()

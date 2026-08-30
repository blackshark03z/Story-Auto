from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import wave

from story_auto.application.operator import OperatorService, OperatorServiceError
from story_auto.core.artifacts import read_json


def _wav(seconds: int = 8) -> bytes:
    value = BytesIO()
    with wave.open(value, "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000 * seconds)
    return value.getvalue()


SRT = b"""1\n00:00:00,000 --> 00:00:03,000\nThe first visual cue.\n\n2\n00:00:03,000 --> 00:00:07,800\nThe final visual cue.\n"""


def _upload(filename: str, payload: bytes) -> dict[str, str]:
    return {"filename": filename, "base64": base64.b64encode(payload).decode("ascii")}


class Goal51NewVideoUxTests(unittest.TestCase):
    def test_audio_srt_creates_without_operator_content_and_serializes_source(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            snapshot = app.create_project(
                project_id="prj_goal51_audio_srt", render_mode="full_image",
                settings={"execution": {"mode": "EXISTING_VOICE"},
                          "ui": {"input_source": "AUDIO_SRT"},
                          "full_image": {"image_duration_seconds": 15, "cadence": "FIXED", "audio_visualizer": False}},
                imported_audio=_upload("voice.wav", _wav()), imported_srt=_upload("timing.srt", SRT),
            )
            self.assertEqual((snapshot["input_source"], snapshot["narration_audio"], snapshot["subtitle_timing"], snapshot["timing_source"]),
                             ("AUDIO_SRT", "IMPORTED", "IMPORTED", "SRT"))
            self.assertEqual(snapshot["full_image"]["image_duration_seconds"], 15.0)
            content = Path(snapshot["project_path"], "content.md").read_text(encoding="utf-8")
            self.assertIn("The first visual cue.", content)
            self.assertEqual(read_json(Path(snapshot["project_path"], "output", "alignment.json"))["timing_source"], "SRT")

    def test_existing_audio_requires_canonical_text_but_never_tts(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root); upload = _upload("voice.wav", _wav())
            with self.assertRaisesRegex(OperatorServiceError, "EXISTING_AUDIO_TEXT_REQUIRED"):
                app.create_project(project_id="prj_goal51_missing_text", settings={"execution": {"mode": "EXISTING_VOICE"}, "ui": {"input_source": "EXISTING_AUDIO"}}, imported_audio=upload)
            snapshot = app.create_project(project_id="prj_goal51_audio", settings={"execution": {"mode": "EXISTING_VOICE"}, "ui": {"input_source": "EXISTING_AUDIO"}}, imported_audio=upload,
                                          content="# Imported\n\n## Narration\n\nThe spoken source is canonical.\n")
            self.assertEqual((snapshot["input_source"], snapshot["narration_audio"], snapshot["tts_provider"]),
                             ("EXISTING_AUDIO", "IMPORTED", "NOT_CONFIGURED"))

    def test_audio_srt_validation_fails_closed_for_missing_invalid_and_mismatched_inputs(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root); audio = _upload("voice.wav", _wav())
            missing=app.inspect_imports(source_mode="AUDIO_SRT", imported_audio=audio, imported_srt=None)
            malformed=app.inspect_imports(source_mode="AUDIO_SRT", imported_audio=audio, imported_srt=_upload("bad.srt", b"1\n00:99:00,000 --> 00:00:02,000\nBad\n"))
            mismatch=app.inspect_imports(source_mode="AUDIO_SRT", imported_audio=_upload("short.wav", _wav(2)), imported_srt=_upload("timing.srt", SRT))
            self.assertEqual((missing["status"],missing["code"]),("BLOCKED","SRT_INVALID"))
            self.assertEqual((malformed["status"],malformed["srt"]["code"]),("BLOCKED","SRT_TIMESTAMP_INVALID"))
            self.assertEqual((mismatch["status"],mismatch["timeline"]["code"]),("BLOCKED","TIMELINE_MISMATCH"))

    def test_source_first_markup_has_required_choices_and_execution_summary(self):
        script = (Path(__file__).parents[1] / "story_auto/ui/static/app.js").read_text(encoding="utf-8")
        for value in ("STORY_CONTENT", "EXISTING_AUDIO", "AUDIO_SRT", "INPUT SOURCE", "Execution summary", "TTS: SKIP", "Timing: ${wizard.source === 'AUDIO_SRT'", "Render Again"):
            self.assertIn(value, script)
        self.assertIn("const labels = ['Source','Input','Output & quality','Review']", script)

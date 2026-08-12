from __future__ import annotations

import tempfile
import unittest
import wave
from io import BytesIO
from unittest.mock import patch
from pathlib import Path

from story_auto.core.artifacts import atomic_write_json, atomic_write_text, read_json
from story_auto.core.audio import AlignmentError, TTSRequest, TTSResult, TimedSpan, build_alignment, validate_alignment
from story_auto.core.content import narration_hash
from story_auto.core.project import ProjectConfig, ProjectValidationError, RuntimeLayout, create_project
from story_auto.pipeline import run_audio_stages
from story_auto.providers.tts.elevenlabs import ElevenLabsProvider, classify_http, merge_offset_spans
from story_auto.providers.tts.typecast import _concatenate_wav, normalize_timestamps, split_text_chunks
from story_auto.providers.credentials import provider_keys
from story_auto.core.audio.errors import AudioPipelineError
from story_auto.core.audio.media import audio_duration_seconds


class _FakeTypecast:
    name = "typecast"
    def __init__(self): self.calls = 0
    def generate(self, request: TTSRequest, output: Path) -> TTSResult:
        self.calls += 1
        buffer = BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000); audio.writeframes(b"\0\0" * 16000)
        output.write_bytes(buffer.getvalue())
        characters = [{"text": c, "text_index": i, "start": i * .1, "end": (i + 1) * .1} for i, c in enumerate(request.narration)]
        return TTSResult(output, "typecast", request.voice_id, 2.0, request.narration_sha256, {"characters": characters}, "typecast_timestamps")
    def align(self, request: TTSRequest, result: TTSResult):
        return normalize_timestamps(request.narration, result.metadata["characters"])


class AudioContractTests(unittest.TestCase):
    @staticmethod
    def _wav(seconds: int = 1) -> bytes:
        buffer = BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000); audio.writeframes(b"\0\0" * 8000 * seconds)
        return buffer.getvalue()

    def test_provider_contract_and_elevenlabs_helpers(self) -> None:
        request = TTSRequest("Hello.", narration_hash("Hello."), "elevenlabs", "voice", {"model": "m"})
        self.assertEqual(request.provider, "elevenlabs")
        self.assertEqual(ElevenLabsProvider().chunk_plan("abc", 2), ("ab", "c"))
        self.assertEqual(classify_http(429), "RATE_LIMITED")
        self.assertEqual(merge_offset_spans([[{"text":"a", "start":0, "end":1}], [{"text":"b", "start":0, "end":1}]], [1, 1])[1]["start"], 1)

    def test_typecast_normalization_and_canonical_validation(self) -> None:
        text = "One. Two."
        chars = [{"text": c, "text_index": i, "start": i / 10, "end": (i + 1) / 10} for i, c in enumerate(text)]
        spans = [TimedSpan(**span) for span in normalize_timestamps(text, chars)]
        value = build_alignment(project_id="prj_audio001", audio_path="output/voice.wav", audio_sha256="audio", narration_sha256=narration_hash(text), duration_seconds=2, source="typecast_timestamps", spans=spans)
        validate_alignment(value, narration=text, narration_sha256=narration_hash(text), audio_sha256="audio", duration_seconds=2)
        value["segments"][0]["start"] = -1
        with self.assertRaises(AlignmentError): validate_alignment(value, narration=text, narration_sha256=narration_hash(text), audio_sha256="audio", duration_seconds=2)

    def test_typecast_chunking_and_wav_concatenation_are_deterministic(self) -> None:
        text = "First sentence. Second sentence."
        chunks = split_text_chunks(text, 16)
        self.assertEqual("".join(chunks), text)
        audio, duration = _concatenate_wav([self._wav(), self._wav()])
        self.assertEqual(duration, 2.0)
        with wave.open(BytesIO(audio), "rb") as merged: self.assertEqual(merged.getnframes(), 16000)

    def test_invalid_audio_is_not_checkpoint_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "voice.wav"; path.write_bytes(b"not audio")
            with self.assertRaises(AudioPipelineError) as captured: audio_duration_seconds(path, provider="typecast")
            self.assertEqual(captured.exception.failure_class, "AUDIO_ARTIFACT_INVALID")

    def test_resume_keeps_audio_when_alignment_is_missing_and_invalidates_on_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = RuntimeLayout.from_root(directory)
            config = ProjectConfig(project_id="prj_audio001", settings={"tts": {"provider":"typecast", "allow_cross_provider_fallback":False, "typecast":{"voice_id":"tc_fake", "model":"ssfm-v30"}}})
            paths = create_project(runtime, config, "## Narration\n\nFirst. Second.\n")
            fake = _FakeTypecast()
            self.assertEqual(run_audio_stages(runtime.root, config.project_id, adapter=fake), ("RUN", "RUN"))
            self.assertEqual(run_audio_stages(runtime.root, config.project_id, adapter=fake), ("SKIP", "SKIP"))
            paths.artifact_path("output/alignment.json").unlink()
            self.assertEqual(run_audio_stages(runtime.root, config.project_id, adapter=fake), ("SKIP", "RUN"))
            paths.artifact_path("output/alignment.json").write_text("corrupt", encoding="utf-8")
            self.assertEqual(run_audio_stages(runtime.root, config.project_id, adapter=fake), ("SKIP", "RUN"))
            paths.artifact_path("output/voice.wav").unlink()
            self.assertEqual(run_audio_stages(runtime.root, config.project_id, adapter=fake), ("RUN", "RUN"))
            paths.artifact_path("output/voice.wav").write_bytes(b"corrupt")
            self.assertEqual(run_audio_stages(runtime.root, config.project_id, adapter=fake), ("RUN", "RUN"))
            payload = read_json(paths.project_file); payload["settings"]["tts"]["typecast"]["voice_id"] = "tc_changed"; atomic_write_json(paths.project_file, payload)
            self.assertEqual(run_audio_stages(runtime.root, config.project_id, adapter=fake), ("RUN", "RUN"))
            atomic_write_text(paths.content_file, "## Narration\n\nChanged narration.\n")
            self.assertEqual(run_audio_stages(runtime.root, config.project_id, adapter=fake), ("RUN", "RUN"))

    def test_invalid_provider_is_rejected(self) -> None:
        with self.assertRaises(ValueError): TTSRequest("x", narration_hash("x"), "other", "voice")
        with self.assertRaises(ProjectValidationError):
            ProjectConfig(project_id="prj_audio001", settings={"tts":{"provider":"other"}})
        with self.assertRaises(ProjectValidationError):
            ProjectConfig(project_id="prj_audio001", settings={"tts":{"provider":"typecast", "allow_cross_provider_fallback":True, "typecast":{"voice_id":"tc_x"}}})

    def test_missing_credentials_are_sanitized(self) -> None:
        with patch("story_auto.providers.credentials._read_pool", return_value=[]), patch.dict("os.environ", {"TYPECAST_API_KEY": ""}, clear=False), self.assertRaises(AudioPipelineError) as captured:
            provider_keys("typecast")
        self.assertEqual(captured.exception.failure_class, "CREDENTIAL_MISSING")
        self.assertNotIn("TYPECAST_API_KEY", str(captured.exception))


if __name__ == "__main__": unittest.main()

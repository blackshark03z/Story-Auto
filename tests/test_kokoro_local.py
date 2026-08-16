from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from story_auto.application import OperatorService
from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.audio import AudioPipelineError, TTSRequest
from story_auto.core.content import narration_hash
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.pipeline import run_audio_stages
from story_auto.providers.tts import provider_for
from story_auto.providers.tts.kokoro_local import (KokoroLocalProvider, available_voices,
                                                    discover_runtime, plan_kokoro_chunks,
                                                    probe_kokoro_readiness)
from story_auto.providers.tts.kokoro_worker import _map_tokens


SNAPSHOT = "1" * 40


class FakeKokoroWorker:
    def __init__(self, *, invalid_audio: bool = False, fail_after_first: bool = False) -> None:
        self.invalid_audio = invalid_audio
        self.fail_after_first = fail_after_first
        self.calls = 0

    @staticmethod
    def _wav(path: Path, seconds: float = 1.0) -> None:
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(24_000)
            output.writeframes(b"\0\0" * int(24_000 * seconds))

    def __call__(self, command, **kwargs):
        self.calls += 1
        request_path = Path(command[command.index("--request") + 1])
        result_path = Path(command[command.index("--result") + 1])
        request = read_json(request_path); cache = Path(request["cache_dir"])
        values, reused = [], 0
        for position, chunk in enumerate(request["chunks"]):
            stem = f"chunk_{int(chunk['index']):04d}_{chunk['identity_sha256'][:12]}"
            wav_path, json_path = cache / f"{stem}.wav", cache / f"{stem}.json"
            if json_path.is_file() and wav_path.is_file():
                values.append(read_json(json_path)); reused += 1; continue
            if self.invalid_audio:
                wav_path.write_bytes(b"invalid")
                frame_count = 24_000
            else:
                self._wav(wav_path); frame_count = 24_000
            tokens=[]; words=list(re.finditer(r"[A-Za-z0-9]+", chunk["text"]))
            for index, match in enumerate(words):
                start = .05 + index * (.85 / max(1, len(words)))
                tokens.append({"text":match.group(), "source_start":match.start(), "source_end":match.end(),
                               "start":start, "end":min(.95, start + .08)})
            value={"schema_version":"story-auto-kokoro-chunk/1.0.0", "index":chunk["index"],
                   "identity_sha256":chunk["identity_sha256"], "text_sha256":hashlib.sha256(chunk["text"].encode()).hexdigest(),
                   "audio_path":str(wav_path.resolve()), "audio_sha256":sha256_file(wav_path), "sample_rate":24_000,
                   "channels":1, "sample_width_bytes":2, "frame_count":frame_count, "duration_seconds":1.0,
                   "tokens":tokens}
            atomic_write_json(json_path,value); values.append(value)
            if self.fail_after_first and self.calls == 1 and position == 0:
                atomic_write_json(result_path,{"schema_version":"story-auto-kokoro-worker-result/1.0.0",
                    "status":"FAILED","failure_class":"KOKORO_TIMEOUT"})
                return subprocess.CompletedProcess(command,1,"","")
        atomic_write_json(result_path,{"schema_version":"story-auto-kokoro-worker-result/1.0.0",
            "status":"SUCCESS","chunks":values,"reused_chunk_count":reused,
            "generated_chunk_count":len(values)-reused})
        return subprocess.CompletedProcess(command,0,"","")


class FakeKokoroProbe:
    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.calls = 0

    def __call__(self, command, **kwargs):
        self.calls += 1
        result_path = Path(command[command.index("--result") + 1])
        atomic_write_json(result_path, {"schema_version":"story-auto-kokoro-probe-result/1.0.0",
                                        "status":"READY" if self.ready else "RUNTIME_LOAD_FAILED"})
        return subprocess.CompletedProcess(command,0 if self.ready else 1,"","")


class KokoroLocalTests(unittest.TestCase):
    def _runtime(self, directory: str, *, voice: str = "am_michael") -> dict:
        root=Path(directory)/"kokoro"; python=root/".venv"/"Scripts"/"python.exe"
        python.parent.mkdir(parents=True); python.write_bytes(b"python")
        (root/"kokoro").mkdir(); (root/"kokoro"/"pipeline.py").write_text("# installed",encoding="utf-8")
        (root/"pyproject.toml").write_text('[project]\nversion = "0.9.4"\n',encoding="utf-8")
        cache=Path(directory)/"hf"/"models--hexgrad--Kokoro-82M"; (cache/"refs").mkdir(parents=True)
        (cache/"refs"/"main").write_text(SNAPSHOT,encoding="utf-8")
        snapshot=cache/"snapshots"/SNAPSHOT; (snapshot/"voices").mkdir(parents=True)
        (snapshot/"config.json").write_text('{"vocab":{}}',encoding="utf-8")
        (snapshot/"kokoro-v1_0.pth").write_bytes(b"model")
        (snapshot/"voices"/f"{voice}.pt").write_bytes(b"voice")
        return {"runtime_path":str(root),"model_cache":str(cache),"voice_id":voice,
                "language":"a","speed":1.0,"device":"cpu","chunk_characters":30}

    def test_registration_and_explicit_project_selection(self) -> None:
        self.assertIsInstance(provider_for("kokoro_local"), KokoroLocalProvider)
        config=ProjectConfig("prj_kokoro",settings={"tts":{"provider":"kokoro_local",
            "allow_cross_provider_fallback":False,"kokoro_local":{"voice_id":"am_michael"}}})
        self.assertEqual(config.settings["tts"]["provider"],"kokoro_local")
        self.assertFalse(config.settings["tts"]["allow_cross_provider_fallback"])

    def test_runtime_and_voice_missing_are_classified(self) -> None:
        with self.assertRaises(AudioPipelineError) as missing:
            discover_runtime({"runtime_path":"Z:\\missing"})
        self.assertEqual(missing.exception.failure_class,"KOKORO_RUNTIME_NOT_FOUND")
        with tempfile.TemporaryDirectory() as directory:
            settings=self._runtime(directory)
            (Path(settings["model_cache"])/"snapshots"/SNAPSHOT/"voices"/"am_michael.pt").unlink()
            with self.assertRaises(AudioPipelineError) as voice:
                KokoroLocalProvider().fingerprint_settings(settings)
            self.assertEqual(voice.exception.failure_class,"KOKORO_VOICE_NOT_FOUND")

    def test_readiness_distinguishes_model_voice_load_and_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings=self._runtime(directory)
            ready=probe_kokoro_readiness(settings,runner=FakeKokoroProbe())
            self.assertEqual((ready.ready,ready.state,ready.technical_code),(True,"READY",None))
            load_failed=probe_kokoro_readiness(settings,runner=FakeKokoroProbe(ready=False))
            self.assertEqual(load_failed.state,"RUNTIME_LOAD_FAILED")
            (Path(settings["model_cache"])/"snapshots"/SNAPSHOT/"voices"/"am_michael.pt").unlink()
            self.assertEqual(probe_kokoro_readiness(settings).state,"VOICE_NOT_FOUND")
            (Path(settings["model_cache"])/"snapshots"/SNAPSHOT/"kokoro-v1_0.pth").unlink()
            self.assertEqual(probe_kokoro_readiness(settings).state,"MODEL_NOT_FOUND")
            self.assertEqual(probe_kokoro_readiness({"runtime_path":""}).state,"CONFIGURATION_INVALID")

    def test_settings_and_production_share_missing_model_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings=self._runtime(directory)
            (Path(settings["model_cache"])/"snapshots"/SNAPSHOT/"kokoro-v1_0.pth").unlink()
            runtime=RuntimeLayout.from_root(Path(directory)/"runtime")
            config=ProjectConfig("prj_kokoro_missing",settings={
                "tts":{"provider":"kokoro_local","allow_cross_provider_fallback":False,"kokoro_local":settings},
                "llm":{"provider":"gemini","model":"gemini-3.5-flash"},
                "flow":{"project_identity":"must-not-run"},
            })
            paths=create_project(runtime,config,"## Narration\n\nA short local check.\n")
            app=OperatorService(runtime.root)
            voice_row=app.settings_overview()["providers"][0]
            self.assertEqual((voice_row["status"],voice_row["detail"],voice_row["technical_code"]),
                             ("Needs attention","Kokoro model files are missing","KOKORO_MODEL_NOT_FOUND"))
            runner_calls=[]
            def never_run(*args,**kwargs):
                runner_calls.append(args)
                raise AssertionError("synthesis or downstream provider invoked")
            content_hash=sha256_file(paths.content_file)
            adapter=KokoroLocalProvider(runner=never_run,readiness_runner=never_run)
            with self.assertRaises(AudioPipelineError) as captured:
                app.start_or_resume(config.project_id,planning_provider=never_run,audio_adapter=adapter)
            self.assertEqual(captured.exception.failure_class,"KOKORO_MODEL_NOT_FOUND")
            self.assertEqual(runner_calls,[])
            self.assertEqual(sha256_file(paths.content_file),content_hash)
            self.assertFalse(paths.artifact_path("output/voice.wav").exists())
            self.assertFalse(paths.artifact_path("output/story_timeline.json").exists())

    def test_successful_fake_synthesis_alignment_and_canonical_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings=self._runtime(directory); runtime=RuntimeLayout.from_root(Path(directory)/"runtime")
            config=ProjectConfig("prj_kokoro",settings={"tts":{"provider":"kokoro_local",
                "allow_cross_provider_fallback":False,"kokoro_local":settings}})
            paths=create_project(runtime,config,"## Narration\n\nFirst sentence. Second sentence.\n")
            adapter=KokoroLocalProvider(runner=FakeKokoroWorker(),readiness_runner=FakeKokoroProbe())
            with patch("story_auto.providers.credentials.provider_keys",side_effect=AssertionError("paid credential access")):
                self.assertEqual(run_audio_stages(runtime.root,config.project_id,adapter=adapter),("RUN","RUN"))
            manifest=read_json(paths.artifact_path("output/audio_manifest.json"))
            alignment=read_json(paths.artifact_path("output/alignment.json"))
            self.assertEqual(manifest["provider"],"kokoro_local")
            self.assertEqual(manifest["metadata"]["sample_rate"],24_000)
            self.assertEqual("".join(item["text"] for item in alignment["segments"]),"First sentence. Second sentence.")
            self.assertEqual(run_audio_stages(runtime.root,config.project_id,adapter=adapter),("SKIP","SKIP"))

    def test_invalid_worker_audio_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings=self._runtime(directory); request=TTSRequest("Hello.",narration_hash("Hello."),
                "kokoro_local","am_michael",settings)
            with self.assertRaises(AudioPipelineError) as captured:
                KokoroLocalProvider(runner=FakeKokoroWorker(invalid_audio=True),readiness_runner=FakeKokoroProbe()).generate(request,Path(directory)/"voice.wav")
            self.assertEqual(captured.exception.failure_class,"KOKORO_AUDIO_INVALID")

    def test_chunk_resume_and_fingerprint_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings=self._runtime(directory); runner=FakeKokoroWorker(fail_after_first=True)
            provider=KokoroLocalProvider(runner=runner,readiness_runner=FakeKokoroProbe()); narration="First sentence. Second sentence. Third sentence."
            request=TTSRequest(narration,narration_hash(narration),"kokoro_local","am_michael",settings)
            first=provider.fingerprint_settings(settings); second=provider.fingerprint_settings(dict(settings))
            self.assertEqual(first,second)
            with self.assertRaises(AudioPipelineError) as captured:
                provider.generate(request,Path(directory)/"voice.wav")
            self.assertEqual(captured.exception.failure_class,"KOKORO_TIMEOUT")
            result=provider.generate(request,Path(directory)/"voice.wav")
            self.assertGreaterEqual(result.metadata["reused_chunk_count"],1)
            self.assertEqual(runner.calls,2)

    def test_chunk_plan_is_exact_and_never_splits_a_word(self) -> None:
        narration="alpha beta gamma delta epsilon zeta eta theta"
        chunks=plan_kokoro_chunks(narration,12)
        self.assertEqual("".join(chunks),narration)
        for left,right in zip(chunks,chunks[1:]):
            self.assertTrue(left[-1].isspace() or right[0].isspace())

    def test_voice_enumeration_uses_only_local_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings=self._runtime(directory)
            self.assertEqual(available_voices(settings),("am_michael",))

    def test_worker_maps_kokoro_whitespace_outside_display_graphemes(self) -> None:
        class Token:
            def __init__(self,text,start,end):
                self.text=text; self.start_ts=start; self.end_ts=end
        class Result:
            graphemes="Martin brushed dust."
            tokens=[Token("\n\nMartin",.1,.3),Token("brushed",.3,.5),Token("dust",.5,.7),Token(".",.7,.75),Token("\n\n",None,None)]
        source="Prior.\n\nMartin brushed dust.\n\nNext."
        mapped,cursor=_map_tokens(source,Result(),1.0,len("Prior."))
        self.assertEqual(mapped[0]["text"],"\n\nMartin")
        self.assertEqual(mapped[0]["source_start"],len("Prior."))
        self.assertEqual(cursor,source.index("Next."))


if __name__ == "__main__":
    unittest.main()

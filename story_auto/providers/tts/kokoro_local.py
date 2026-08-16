"""Story Auto adapter for the installed direct-Python Kokoro runtime."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import wave
from typing import Any, Callable

from story_auto.core.artifacts import atomic_write_bytes, atomic_write_json, read_json, sha256_file
from story_auto.core.audio.contracts import TTSRequest, TTSResult
from story_auto.core.audio.errors import AudioPipelineError
from story_auto.core.content import plan_chunks, sentence_spans, validate_reconstruction


ADAPTER_VERSION = "story-auto-kokoro-local/1.0.0"
MODEL_REPO = "hexgrad/Kokoro-82M"
SAMPLE_RATE = 24_000


@dataclass(frozen=True)
class KokoroRuntime:
    root: Path
    python: Path
    version: str
    model_cache: Path
    model_snapshot: str
    config_path: Path
    model_path: Path
    voices_dir: Path
    device: str


@dataclass(frozen=True)
class KokoroReadiness:
    state: str
    user_message: str
    technical_code: str | None
    runtime: KokoroRuntime | None = None
    voice_path: Path | None = None

    @property
    def ready(self) -> bool:
        return self.state == "READY"

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "state": self.state,
            "user_message": self.user_message,
            "technical_code": self.technical_code,
        }


_READINESS_MESSAGES = {
    "READY": "Kokoro is ready",
    "RUNTIME_NOT_FOUND": "Kokoro runtime is not installed",
    "MODEL_NOT_FOUND": "Kokoro model files are missing",
    "VOICE_NOT_FOUND": "The selected Kokoro voice is missing",
    "RUNTIME_LOAD_FAILED": "Kokoro could not load its local model",
    "CONFIGURATION_INVALID": "Kokoro settings are invalid",
}
_READINESS_CODES = {
    "RUNTIME_NOT_FOUND": "KOKORO_RUNTIME_NOT_FOUND",
    "MODEL_NOT_FOUND": "KOKORO_MODEL_NOT_FOUND",
    "VOICE_NOT_FOUND": "KOKORO_VOICE_NOT_FOUND",
    "RUNTIME_LOAD_FAILED": "KOKORO_RUNTIME_LOAD_FAILED",
    "CONFIGURATION_INVALID": "KOKORO_CONFIGURATION_INVALID",
}
_READINESS_CACHE: dict[tuple[Any, ...], KokoroReadiness] = {}
_READINESS_LOCK = threading.Lock()


def plan_kokoro_chunks(narration: str, max_characters: int = 1_200) -> tuple[str, ...]:
    """Return exact, bounded source slices without cutting through a word."""
    initial = plan_chunks(narration, max_characters=max_characters)
    if all(not (left and right and not left[-1].isspace() and not right[0].isspace())
           for left, right in zip(initial, initial[1:])):
        return initial
    chunks, position = [], 0
    while position < len(narration):
        limit = min(len(narration), position + max_characters)
        if limit < len(narration):
            choices = [narration.rfind("\n\n", position + 1, limit + 1),
                       narration.rfind("\n", position + 1, limit + 1),
                       narration.rfind(" ", position + 1, limit + 1)]
            split = max(choices)
            if split <= position:
                raise AudioPipelineError("KOKORO_SYNTHESIS_FAILED", provider="kokoro_local", stage="tts",
                                         detail="no safe chunk boundary")
            limit = split + 1
        chunks.append(narration[position:limit])
        position = limit
    result = tuple(chunks)
    if not validate_reconstruction(narration, result):
        raise AudioPipelineError("KOKORO_SYNTHESIS_FAILED", provider="kokoro_local", stage="tts")
    return result


def _version(root: Path) -> str:
    try:
        match = re.search(r'^version\s*=\s*"([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"), re.MULTILINE)
        if match:
            return match.group(1)
    except OSError:
        pass
    raise AudioPipelineError("KOKORO_RUNTIME_NOT_FOUND", provider="kokoro_local", stage="preflight")


def _default_model_cache() -> Path:
    configured_hub = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    hub = Path(configured_hub) if configured_hub else Path(
        os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")
    ) / "hub"
    return hub / "models--hexgrad--Kokoro-82M"


def discover_runtime(settings: dict[str, Any]) -> KokoroRuntime:
    raw = settings.get("runtime_path")
    if not isinstance(raw, str) or not raw.strip():
        raise AudioPipelineError("KOKORO_CONFIGURATION_INVALID", provider="kokoro_local", stage="preflight")
    root = Path(raw).resolve()
    python = root / ".venv" / "Scripts" / "python.exe"
    if not root.is_dir() or not python.is_file() or not (root / "kokoro" / "pipeline.py").is_file():
        raise AudioPipelineError("KOKORO_RUNTIME_NOT_FOUND", provider="kokoro_local", stage="preflight")
    raw_cache = settings.get("model_cache", _default_model_cache())
    if not isinstance(raw_cache, (str, os.PathLike)) or not str(raw_cache).strip():
        raise AudioPipelineError("KOKORO_CONFIGURATION_INVALID", provider="kokoro_local", stage="preflight")
    model_cache = Path(raw_cache).resolve()
    try:
        snapshot = str(settings.get("model_snapshot") or (model_cache / "refs" / "main").read_text(encoding="utf-8")).strip()
    except OSError as error:
        raise AudioPipelineError("KOKORO_MODEL_NOT_FOUND", provider="kokoro_local", stage="preflight") from error
    if not re.fullmatch(r"[0-9a-f]{40}", snapshot):
        raise AudioPipelineError("KOKORO_CONFIGURATION_INVALID", provider="kokoro_local", stage="preflight")
    snapshot_root = model_cache / "snapshots" / snapshot
    config_path, model_path, voices_dir = snapshot_root / "config.json", snapshot_root / "kokoro-v1_0.pth", snapshot_root / "voices"
    if (not config_path.is_file() or config_path.stat().st_size <= 0
            or not model_path.is_file() or model_path.stat().st_size <= 0):
        raise AudioPipelineError("KOKORO_MODEL_NOT_FOUND", provider="kokoro_local", stage="preflight")
    requested_device = str(settings.get("device", "cpu")).lower()
    if requested_device not in {"cpu", "auto"}:
        raise AudioPipelineError("KOKORO_CONFIGURATION_INVALID", provider="kokoro_local", stage="preflight")
    return KokoroRuntime(root, python, _version(root), model_cache, snapshot, config_path, model_path, voices_dir, "cpu")


def _readiness(state: str, *, runtime: KokoroRuntime | None = None,
               voice_path: Path | None = None) -> KokoroReadiness:
    return KokoroReadiness(state, _READINESS_MESSAGES[state], _READINESS_CODES.get(state), runtime, voice_path)


def _state_for_failure(failure_class: str) -> str:
    return {
        "KOKORO_RUNTIME_NOT_FOUND": "RUNTIME_NOT_FOUND",
        "KOKORO_MODEL_NOT_FOUND": "MODEL_NOT_FOUND",
        "KOKORO_VOICE_NOT_FOUND": "VOICE_NOT_FOUND",
        "KOKORO_CONFIGURATION_INVALID": "CONFIGURATION_INVALID",
    }.get(failure_class, "RUNTIME_LOAD_FAILED")


def _selected_voice(runtime: KokoroRuntime, settings: dict[str, Any]) -> Path:
    voice = settings.get("voice_id")
    if not isinstance(voice, str) or not voice.strip() or Path(voice).name != voice:
        raise AudioPipelineError("KOKORO_CONFIGURATION_INVALID", provider="kokoro_local", stage="preflight")
    path = runtime.voices_dir / f"{voice}.pt"
    if not path.is_file() or path.stat().st_size <= 0:
        raise AudioPipelineError("KOKORO_VOICE_NOT_FOUND", provider="kokoro_local", stage="preflight")
    return path


def _probe_identity(runtime: KokoroRuntime, voice_path: Path, settings: dict[str, Any]) -> tuple[Any, ...]:
    def identity(path: Path) -> tuple[str, int, int]:
        stat = path.stat()
        return str(path), stat.st_size, stat.st_mtime_ns
    return (identity(runtime.python), runtime.version, identity(runtime.config_path), identity(runtime.model_path),
            identity(voice_path), runtime.device, str(settings.get("language", "b")))


def probe_kokoro_readiness(settings: dict[str, Any], *, runner: Callable[..., subprocess.CompletedProcess] | None = None,
                           use_cache: bool = True) -> KokoroReadiness:
    """Load the exact configured model and voice without generating narration."""
    try:
        runtime = discover_runtime(settings)
        voice_path = _selected_voice(runtime, settings)
        language = str(settings.get("language", "b")).lower()
        if language not in {"a", "b", "e", "f", "h", "i", "p", "j", "z"}:
            raise AudioPipelineError("KOKORO_CONFIGURATION_INVALID", provider="kokoro_local", stage="preflight")
        speed = float(settings.get("speed", 1.0))
        if not 0.5 <= speed <= 2.0:
            raise AudioPipelineError("KOKORO_CONFIGURATION_INVALID", provider="kokoro_local", stage="preflight")
        chunk_characters = int(settings.get("chunk_characters", 1_200))
        if chunk_characters < 1:
            raise AudioPipelineError("KOKORO_CONFIGURATION_INVALID", provider="kokoro_local", stage="preflight")
        key = _probe_identity(runtime, voice_path, settings)
    except (AudioPipelineError, TypeError, ValueError) as error:
        if not isinstance(error, AudioPipelineError):
            return _readiness("CONFIGURATION_INVALID")
        return _readiness(_state_for_failure(error.failure_class))

    active_runner = runner or subprocess.run
    if runner is None and use_cache:
        with _READINESS_LOCK:
            cached = _READINESS_CACHE.get(key)
        if cached is not None:
            return cached
    with tempfile.TemporaryDirectory(prefix="story_auto_kokoro_probe_") as directory:
        temporary = Path(directory)
        request_path, result_path = temporary / "request.json", temporary / "result.json"
        atomic_write_json(request_path, {
            "schema_version": "story-auto-kokoro-probe-request/1.0.0",
            "model_repo": MODEL_REPO,
            "config_path": str(runtime.config_path),
            "model_path": str(runtime.model_path),
            "voice_path": str(voice_path),
            "language": language,
            "device": runtime.device,
        })
        environment = dict(os.environ)
        environment.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                            "HF_HUB_CACHE": str(runtime.model_cache.parent)})
        command = [str(runtime.python), str(Path(__file__).with_name("kokoro_probe.py").resolve()),
                   "--request", str(request_path), "--result", str(result_path)]
        try:
            completed = active_runner(command, cwd=runtime.root, env=environment, capture_output=True,
                                      text=True, check=False, timeout=float(settings.get("readiness_timeout_seconds", 180)))
            result = read_json(result_path) if result_path.is_file() else {}
            ready = completed.returncode == 0 and result.get("status") == "READY"
        except (OSError, subprocess.TimeoutExpired, ValueError):
            ready = False
    value = (_readiness("READY", runtime=runtime, voice_path=voice_path) if ready
             else _readiness("RUNTIME_LOAD_FAILED", runtime=runtime, voice_path=voice_path))
    if runner is None and use_cache and value.ready:
        with _READINESS_LOCK:
            _READINESS_CACHE[key] = value
    return value


def require_kokoro_ready(settings: dict[str, Any], *, runner: Callable[..., subprocess.CompletedProcess] | None = None) -> KokoroReadiness:
    value = probe_kokoro_readiness(settings, runner=runner)
    if not value.ready:
        raise AudioPipelineError(value.technical_code or "KOKORO_RUNTIME_LOAD_FAILED",
                                 provider="kokoro_local", stage="preflight")
    return value


def available_voices(settings: dict[str, Any]) -> tuple[str, ...]:
    runtime = discover_runtime(settings)
    return tuple(sorted(path.stem for path in runtime.voices_dir.glob("*.pt") if path.is_file()))


def _wav_metadata(path: Path) -> tuple[int, int, int, int, float]:
    try:
        with wave.open(str(path), "rb") as audio:
            channels, width, rate, frames = audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()
    except (OSError, EOFError, wave.Error) as error:
        raise AudioPipelineError("KOKORO_AUDIO_INVALID", provider="kokoro_local", stage="tts") from error
    if (channels, width, rate) != (1, 2, SAMPLE_RATE) or frames <= 0:
        raise AudioPipelineError("KOKORO_AUDIO_INVALID", provider="kokoro_local", stage="tts")
    return channels, width, rate, frames, frames / float(rate)


def _concatenate(chunks: list[dict], output: Path) -> tuple[float, list[dict]]:
    frames, tokens, source_offset, audio_offset = [], [], 0, 0.0
    for chunk in chunks:
        path = Path(chunk["audio_path"])
        channels, width, rate, frame_count, duration = _wav_metadata(path)
        if chunk.get("audio_sha256") != sha256_file(path) or int(chunk.get("frame_count", -1)) != frame_count:
            raise AudioPipelineError("KOKORO_AUDIO_INVALID", provider="kokoro_local", stage="tts")
        with wave.open(str(path), "rb") as audio:
            frames.append(audio.readframes(frame_count))
        for token in chunk.get("tokens", []):
            tokens.append({"text": token["text"], "source_start": source_offset + int(token["source_start"]),
                           "source_end": source_offset + int(token["source_end"]),
                           "start": audio_offset + float(token["start"]), "end": audio_offset + float(token["end"])})
        source_offset += int(chunk["source_length"])
        audio_offset += duration
    buffer = bytearray()
    import io
    stream = io.BytesIO()
    with wave.open(stream, "wb") as merged:
        merged.setnchannels(1); merged.setsampwidth(2); merged.setframerate(SAMPLE_RATE)
        for payload in frames:
            merged.writeframes(payload)
    atomic_write_bytes(output, stream.getvalue())
    return audio_offset, tokens


class KokoroLocalProvider:
    name = "kokoro_local"
    provenance = "Local Kokoro direct-Python runtime; no cloud API or credential boundary."

    def __init__(self, runner: Callable[..., subprocess.CompletedProcess] | None = None,
                 readiness_runner: Callable[..., subprocess.CompletedProcess] | None = None) -> None:
        self.runner = runner or subprocess.run
        self.readiness_runner = readiness_runner

    def readiness(self, settings: dict[str, Any]) -> KokoroReadiness:
        return probe_kokoro_readiness(settings, runner=self.readiness_runner)

    def fingerprint_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        readiness = require_kokoro_ready(settings, runner=self.readiness_runner)
        runtime, voice_path = readiness.runtime, readiness.voice_path
        assert runtime is not None and voice_path is not None
        return {"adapter_version": ADAPTER_VERSION, "runtime_version": runtime.version,
                "model_snapshot": runtime.model_snapshot, "model_bytes": runtime.model_path.stat().st_size,
                "voice_sha256": sha256_file(voice_path), "device": runtime.device}

    def _invoke(self, request: TTSRequest, output: Path, *, chunks: tuple[str, ...]) -> dict[str, Any]:
        runtime = discover_runtime(request.settings)
        voices = available_voices(request.settings)
        if request.voice_id not in voices:
            raise AudioPipelineError("KOKORO_VOICE_NOT_FOUND", provider=self.name, stage="preflight")
        try:
            speed = float(request.settings.get("speed", 1.0))
        except (TypeError, ValueError) as error:
            raise AudioPipelineError("KOKORO_START_FAILED", provider=self.name, stage="preflight") from error
        if not 0.5 <= speed <= 2.0:
            raise AudioPipelineError("KOKORO_START_FAILED", provider=self.name, stage="preflight")
        language = str(request.settings.get("language", request.voice_id[:1]))
        identity = self.fingerprint_settings(request.settings)
        chunk_values = []
        for index, text in enumerate(chunks, 1):
            seed = {"adapter_version": ADAPTER_VERSION, "runtime_version": runtime.version,
                    "model_snapshot": runtime.model_snapshot, "voice": request.voice_id, "language": language,
                    "speed": speed, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
            chunk_values.append({"index": index, "text": text, "source_length": len(text),
                                 "identity_sha256": hashlib.sha256(json.dumps(seed, sort_keys=True, separators=(",", ":")).encode()).hexdigest()})
        cache_dir = output.parent / "kokoro_chunks"
        cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="story_auto_kokoro_", dir=output.parent) as directory:
            temporary = Path(directory); request_path, result_path = temporary / "request.json", temporary / "result.json"
            atomic_write_json(request_path, {"schema_version":"story-auto-kokoro-worker-request/1.0.0",
                "model_repo":MODEL_REPO, "model_snapshot":runtime.model_snapshot, "language":language,
                "voice":request.voice_id, "speed":speed, "device":runtime.device,
                "config_path":str(runtime.config_path), "model_path":str(runtime.model_path),
                "voice_path":str(runtime.voices_dir / f"{request.voice_id}.pt"),
                "cache_dir":str(cache_dir.resolve()), "chunks":chunk_values})
            environment = dict(os.environ)
            environment.update({"HF_HUB_OFFLINE":"1", "TRANSFORMERS_OFFLINE":"1",
                                "HF_HUB_CACHE":str(runtime.model_cache.parent)})
            command = [str(runtime.python), str(Path(__file__).with_name("kokoro_worker.py").resolve()),
                       "--request", str(request_path), "--result", str(result_path)]
            try:
                completed = self.runner(command, cwd=runtime.root, env=environment, capture_output=True,
                                        text=True, check=False, timeout=float(request.settings.get("timeout_seconds", 1800)))
            except subprocess.TimeoutExpired as error:
                raise AudioPipelineError("KOKORO_TIMEOUT", provider=self.name, stage="tts") from error
            except OSError as error:
                raise AudioPipelineError("KOKORO_START_FAILED", provider=self.name, stage="tts") from error
            result = read_json(result_path) if result_path.is_file() else {}
            if completed.returncode != 0 or result.get("status") != "SUCCESS":
                failure = result.get("failure_class", "KOKORO_SYNTHESIS_FAILED")
                allowed = {"KOKORO_MODEL_NOT_FOUND", "KOKORO_VOICE_NOT_FOUND", "KOKORO_START_FAILED",
                           "KOKORO_RUNTIME_LOAD_FAILED", "KOKORO_CONFIGURATION_INVALID",
                           "KOKORO_SYNTHESIS_FAILED", "KOKORO_TIMEOUT", "KOKORO_AUDIO_INVALID", "KOKORO_ALIGNMENT_FAILED"}
                raise AudioPipelineError(failure if failure in allowed else "KOKORO_SYNTHESIS_FAILED",
                                         provider=self.name, stage="tts")
        by_index = {int(item["index"]): item for item in result["chunks"]}
        resolved = []
        for chunk in chunk_values:
            item = by_index.get(chunk["index"])
            if not item or item.get("identity_sha256") != chunk["identity_sha256"]:
                raise AudioPipelineError("KOKORO_AUDIO_INVALID", provider=self.name, stage="tts")
            item = dict(item); item["source_length"] = chunk["source_length"]; resolved.append(item)
        duration, tokens = _concatenate(resolved, output)
        return {"runtime":runtime, "speed":speed, "language":language, "identity":identity,
                "chunks":resolved, "tokens":tokens, "duration":duration,
                "reused_chunk_count":int(result.get("reused_chunk_count", 0)),
                "generated_chunk_count":int(result.get("generated_chunk_count", len(resolved)))}

    def generate(self, request: TTSRequest, output: Path) -> TTSResult:
        chunks = plan_kokoro_chunks(request.narration, int(request.settings.get("chunk_characters", 1_200)))
        value = self._invoke(request, output, chunks=chunks)
        _wav_metadata(output)
        runtime: KokoroRuntime = value["runtime"]
        metadata = {"adapter_version":ADAPTER_VERSION, "runtime_version":runtime.version,
                    "model_repo":MODEL_REPO, "model_snapshot":runtime.model_snapshot,
                    "voice":request.voice_id, "language":value["language"], "speed":value["speed"],
                    "device":runtime.device, "sample_rate":SAMPLE_RATE, "channels":1, "sample_width_bytes":2,
                    "chunk_count":len(value["chunks"]), "reused_chunk_count":value["reused_chunk_count"],
                    "generated_chunk_count":value["generated_chunk_count"],
                    "chunk_identities":[item["identity_sha256"] for item in value["chunks"]],
                    "tokens":value["tokens"]}
        return TTSResult(output, self.name, request.voice_id, value["duration"], request.narration_sha256,
                         metadata, "kokoro_model_token_timestamps")

    def align(self, request: TTSRequest, result: TTSResult) -> list[dict[str, Any]]:
        tokens = result.metadata.get("tokens")
        if not isinstance(tokens, list) or not tokens:
            raise AudioPipelineError("KOKORO_ALIGNMENT_FAILED", provider=self.name, stage="alignment")
        spans, previous_end = [], 0.0
        for start_index, end_index in sentence_spans(request.narration):
            timed = [token for token in tokens if int(token.get("source_end", -1)) > start_index
                     and int(token.get("source_start", -1)) < end_index]
            if not timed:
                raise AudioPipelineError("KOKORO_ALIGNMENT_FAILED", provider=self.name, stage="alignment")
            start, end = float(timed[0]["start"]), float(timed[-1]["end"])
            if start < previous_end:
                start = previous_end
            if end <= start:
                raise AudioPipelineError("KOKORO_ALIGNMENT_FAILED", provider=self.name, stage="alignment")
            spans.append({"text":request.narration[start_index:end_index], "start":start, "end":end})
            previous_end = end
        return spans

    def preflight(self, *, text: str, voice_id: str, settings: dict[str, Any], output: Path) -> TTSResult:
        request = TTSRequest(text, hashlib.sha256(text.encode("utf-8")).hexdigest(), self.name, voice_id, settings)
        result = self.generate(request, output)
        self.align(request, result)
        return result

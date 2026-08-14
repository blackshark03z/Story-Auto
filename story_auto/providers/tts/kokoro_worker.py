"""Isolated direct-Python worker for the installed Kokoro runtime.

This file is executed by Kokoro's own virtual-environment interpreter.  It
uses only the installed direct Python API and publishes resumable WAV chunks
plus model-predicted token timings.  Network access is disabled by the parent
adapter so a missing local model or voice fails closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import wave
from pathlib import Path


SAMPLE_RATE = 24_000


class WorkerFailure(RuntimeError):
    def __init__(self, failure_class: str) -> None:
        self.failure_class = failure_class
        super().__init__(failure_class)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _write_wav(path: Path, samples) -> None:
    import numpy as np

    array = np.asarray(samples, dtype=np.float32).reshape(-1)
    if not len(array) or not np.isfinite(array).all() or float(np.max(np.abs(array))) > 1.25:
        raise WorkerFailure("KOKORO_AUDIO_INVALID")
    pcm = (np.clip(array, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".wav", dir=path.parent)
    os.close(descriptor)
    try:
        with wave.open(temporary, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)
            output.writeframes(pcm)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _cached(wav_path: Path, sidecar_path: Path, identity: str) -> bool:
    try:
        value = json.loads(sidecar_path.read_text(encoding="utf-8"))
        if value.get("identity_sha256") != identity or value.get("audio_sha256") != _sha256(wav_path):
            return False
        with wave.open(str(wav_path), "rb") as audio:
            return (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()) == (
                1, 2, SAMPLE_RATE, int(value["frame_count"])
            ) and audio.getnframes() > 0
    except Exception:
        return False


def _map_tokens(text: str, result, audio_offset: float, source_cursor: int) -> tuple[list[dict], int]:
    graphemes = str(result.graphemes)
    result_start = text.find(graphemes, source_cursor)
    if result_start < 0:
        raise WorkerFailure("KOKORO_ALIGNMENT_FAILED")
    result_end = result_start + len(graphemes)
    # Kokoro's token slice can retain leading/trailing whitespace that its
    # ``graphemes`` display value strips.  Map tokens from the prior consumed
    # source cursor, while still using graphemes as the contiguous-segment
    # anchor.  This preserves exact paragraph breaks without inventing timing.
    cursor = source_cursor
    mapped: list[dict] = []
    for token in result.tokens or []:
        token_text = str(token.text or "")
        if not token_text:
            continue
        token_start = text.find(token_text, cursor)
        if token_start < 0:
            raise WorkerFailure("KOKORO_ALIGNMENT_FAILED")
        token_end = token_start + len(token_text)
        cursor = token_end
        if token.start_ts is None or token.end_ts is None:
            continue
        start = audio_offset + float(token.start_ts)
        end = audio_offset + float(token.end_ts)
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise WorkerFailure("KOKORO_ALIGNMENT_FAILED")
        mapped.append({"text": token_text, "source_start": token_start, "source_end": token_end,
                       "start": round(start, 6), "end": round(end, 6)})
    return mapped, max(result_end, cursor)


def _synthesize(pipeline, chunk: dict, *, voice: str, speed: float, cache: Path) -> tuple[dict, bool]:
    import numpy as np

    index = int(chunk["index"])
    identity = str(chunk["identity_sha256"])
    stem = f"chunk_{index:04d}_{identity[:12]}"
    wav_path, sidecar_path = cache / f"{stem}.wav", cache / f"{stem}.json"
    if _cached(wav_path, sidecar_path, identity):
        return json.loads(sidecar_path.read_text(encoding="utf-8")), True

    text = str(chunk["text"])
    arrays, tokens, audio_offset, source_cursor = [], [], 0.0, 0
    try:
        results = pipeline(text, voice=voice, speed=speed, split_pattern=None)
        for result in results:
            if result.audio is None:
                continue
            array = result.audio.detach().cpu().numpy().astype(np.float32).reshape(-1)
            if not len(array):
                continue
            mapped, source_cursor = _map_tokens(text, result, audio_offset, source_cursor)
            tokens.extend(mapped)
            arrays.append(array)
            audio_offset += len(array) / SAMPLE_RATE
    except WorkerFailure:
        raise
    except Exception as error:
        raise WorkerFailure("KOKORO_SYNTHESIS_FAILED") from error
    if not arrays or not tokens:
        raise WorkerFailure("KOKORO_SYNTHESIS_FAILED")
    audio = np.concatenate(arrays)
    if tokens[-1]["end"] > len(audio) / SAMPLE_RATE + 0.2:
        raise WorkerFailure("KOKORO_ALIGNMENT_FAILED")
    _write_wav(wav_path, audio)
    value = {
        "schema_version": "story-auto-kokoro-chunk/1.0.0",
        "index": index,
        "identity_sha256": identity,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "audio_path": str(wav_path.resolve()),
        "audio_sha256": _sha256(wav_path),
        "sample_rate": SAMPLE_RATE,
        "channels": 1,
        "sample_width_bytes": 2,
        "frame_count": len(audio),
        "duration_seconds": round(len(audio) / SAMPLE_RATE, 6),
        "tokens": tokens,
    }
    _atomic_json(sidecar_path, value)
    return value, False


def run(request_path: Path, result_path: Path) -> None:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    cache = Path(request["cache_dir"])
    cache.mkdir(parents=True, exist_ok=True)
    try:
        from kokoro import KPipeline
        pipeline = KPipeline(lang_code=request["language"], repo_id=request["model_repo"], device=request["device"])
        try:
            pipeline.load_voice(request["voice"])
        except Exception as error:
            raise WorkerFailure("KOKORO_VOICE_NOT_FOUND") from error
        chunks, reused = [], 0
        for chunk in request["chunks"]:
            value, was_reused = _synthesize(pipeline, chunk, voice=request["voice"],
                                             speed=float(request["speed"]), cache=cache)
            chunks.append(value)
            reused += int(was_reused)
        _atomic_json(result_path, {
            "schema_version": "story-auto-kokoro-worker-result/1.0.0",
            "status": "SUCCESS",
            "chunks": chunks,
            "reused_chunk_count": reused,
            "generated_chunk_count": len(chunks) - reused,
        })
    except WorkerFailure as error:
        _atomic_json(result_path, {"schema_version": "story-auto-kokoro-worker-result/1.0.0",
                                   "status": "FAILED", "failure_class": error.failure_class})
        raise
    except Exception as error:
        _atomic_json(result_path, {"schema_version": "story-auto-kokoro-worker-result/1.0.0",
                                   "status": "FAILED", "failure_class": "KOKORO_START_FAILED"})
        raise WorkerFailure("KOKORO_START_FAILED") from error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    run(args.request, args.result)


if __name__ == "__main__":
    main()

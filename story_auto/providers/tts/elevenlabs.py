from __future__ import annotations

import json, socket, urllib.error, urllib.parse, urllib.request, re, shutil, subprocess, tempfile, os
from pathlib import Path
from typing import Any

from story_auto.core.artifacts import atomic_write_bytes
from story_auto.core.audio.contracts import TTSRequest, TTSResult
from story_auto.core.audio.errors import AmbiguousDispatchError, AudioPipelineError
from story_auto.core.content import plan_chunks, sentence_spans, validate_reconstruction
from story_auto.providers.credentials import provider_keys


def classify_http(status: int) -> str:
    return {401: "CREDENTIAL_INVALID", 402: "QUOTA_EXHAUSTED", 403: "CREDENTIAL_INVALID", 429: "RATE_LIMITED",
            502: "PROVIDER_UNAVAILABLE", 503: "PROVIDER_UNAVAILABLE", 504: "PROVIDER_UNAVAILABLE"}.get(status, "PROVIDER_GENERATION_FAILED")


def merge_offset_spans(parts: list[list[dict[str, Any]]], durations: list[float]) -> list[dict[str, Any]]:
    offset, merged = 0.0, []
    for spans, duration in zip(parts, durations):
        for item in spans: merged.append({"text": item["text"], "start": float(item["start"]) + offset, "end": float(item["end"]) + offset})
        offset += duration
    return merged


def concatenate_mp3_parts(parts: list[bytes], output: Path) -> None:
    """Losslessly concatenate independently generated MP3 chunks into a staged artifact."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg: raise AudioPipelineError("AUDIO_ARTIFACT_INVALID", provider="elevenlabs", stage="tts", detail="ffmpeg unavailable")
    with tempfile.TemporaryDirectory(prefix="story_auto_elevenlabs_", dir=output.parent) as directory:
        root = Path(directory); paths=[]
        for index, payload in enumerate(parts, 1):
            path=root / f"part_{index:04d}.mp3"; atomic_write_bytes(path, payload); paths.append(path)
        listing=root / "concat.txt"
        listing.write_text("".join(f"file '{path.as_posix()}'\n" for path in paths), encoding="utf-8")
        staged=root / "voice.mp3"
        result=subprocess.run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(staged)], capture_output=True, text=True, check=False)
        if result.returncode != 0 or not staged.is_file() or staged.stat().st_size == 0:
            raise AudioPipelineError("AUDIO_ARTIFACT_INVALID", provider="elevenlabs", stage="tts")
        os.replace(staged, output)


class ElevenLabsProvider:
    name = "elevenlabs"
    provenance = "YouTube Auto snapshot d0c86c8e: chunk planning/error ambiguity concepts adapted; no imports retained."

    def __init__(self, transport=None) -> None: self.transport = transport or self._request
    def chunk_plan(self, narration: str, limit: int = 4500) -> list[str]:
        chunks = plan_chunks(narration, max_characters=limit)
        if not validate_reconstruction(narration, chunks): raise ValueError("chunk reconstruction failed")
        return chunks
    def _request(self, url: str, payload: dict[str, Any], key: str, accept: str) -> bytes:
        request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json", "Accept":accept, "xi-api-key":key}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=180) as response: return response.read()
        except urllib.error.HTTPError as error: raise AudioPipelineError(classify_http(error.code), provider=self.name, stage="tts") from error
        except (urllib.error.URLError, TimeoutError, socket.timeout) as error: raise AmbiguousDispatchError(self.name) from error
    def generate(self, request: TTSRequest, output: Path) -> TTSResult:
        keys, chunks = provider_keys(self.name), self.chunk_plan(request.narration, int(request.settings.get("chunk_characters", 4500)))
        parts=[]
        for chunk in chunks:
            audio=b""
            for key in keys:
                try:
                    audio = self.transport(f"https://api.elevenlabs.io/v1/text-to-speech/{request.voice_id}?{urllib.parse.urlencode({'output_format':'mp3_44100_128'})}", {"text":chunk, "model_id":request.settings.get("model", "eleven_multilingual_v2")}, key, "audio/mpeg"); break
                except AudioPipelineError as error:
                    if error.failure_class in {"CREDENTIAL_INVALID", "QUOTA_EXHAUSTED", "RATE_LIMITED"}: continue
                    raise
            if not audio: raise AudioPipelineError("PROVIDER_GENERATION_FAILED", provider=self.name, stage="tts")
            parts.append(audio)
        if len(parts) == 1: atomic_write_bytes(output, parts[0])
        else: concatenate_mp3_parts(parts, output)
        return TTSResult(output, self.name, request.voice_id, 0.0, request.narration_sha256, {"model":request.settings.get("model", "eleven_multilingual_v2"), "part_count":len(parts)}, "elevenlabs_forced_alignment")
    def align(self, request: TTSRequest, result: TTSResult) -> list[dict[str, Any]]:
        """Call the documented forced-alignment boundary; never retry ambiguous dispatch."""
        key = provider_keys(self.name)[0]
        boundary = "StoryAutoBoundary"
        audio = result.audio_path.read_bytes()
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"text\"\r\n\r\n{request.narration}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"voice.mp3\"\r\nContent-Type: audio/mpeg\r\n\r\n").encode() + audio + f"\r\n--{boundary}--\r\n".encode()
        http = urllib.request.Request("https://api.elevenlabs.io/v1/forced-alignment", data=body, headers={"xi-api-key":key, "Accept":"application/json", "Content-Type":f"multipart/form-data; boundary={boundary}"}, method="POST")
        try:
            with urllib.request.urlopen(http, timeout=180) as response: payload=json.loads(response.read().decode())
        except urllib.error.HTTPError as error: raise AudioPipelineError(classify_http(error.code), provider=self.name, stage="alignment") from error
        except (urllib.error.URLError, TimeoutError, socket.timeout) as error: raise AmbiguousDispatchError(self.name) from error
        words = payload.get("words") if isinstance(payload, dict) else None
        if not isinstance(words, list): raise AudioPipelineError("FORCED_ALIGNMENT_FAILED", provider=self.name, stage="alignment")
        timed = []
        for word in words:
            if not isinstance(word, dict) or not str(word.get("text", word.get("word", ""))).strip(): continue
            try: timed.append((float(word["start"]), float(word["end"])))
            except (KeyError, TypeError, ValueError): raise AudioPipelineError("FORCED_ALIGNMENT_FAILED", provider=self.name, stage="alignment")
        transcript = [(index, match) for index, match in enumerate(re.finditer(r"\S+", request.narration))]
        if len(timed) < len(transcript): raise AudioPipelineError("NARRATION_ALIGNMENT_MISMATCH", provider=self.name, stage="alignment")
        word_to_time = {index: timed[index] for index, _ in transcript}
        spans=[]
        for start_index, end_index in sentence_spans(request.narration):
            sentence=request.narration[start_index:end_index]
            positions=[index for index, match in transcript if start_index <= match.start() < end_index]
            if not positions: raise AudioPipelineError("FORCED_ALIGNMENT_FAILED", provider=self.name, stage="alignment")
            start, end = word_to_time[positions[0]][0], word_to_time[positions[-1]][1]
            if end <= start: raise AudioPipelineError("FORCED_ALIGNMENT_FAILED", provider=self.name, stage="alignment")
            spans.append({"text":sentence, "start":start, "end":end})
        return spans

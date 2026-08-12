from __future__ import annotations

import base64, json, socket, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from typing import Any

from story_auto.core.audio.contracts import TTSRequest, TTSResult
from story_auto.core.audio.errors import AmbiguousDispatchError, AudioPipelineError
from story_auto.core.content import sentence_spans
from story_auto.core.artifacts import atomic_write_bytes
from story_auto.providers.credentials import provider_keys


def normalize_timestamps(text: str, characters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spans=[]
    for start_index, end_index in sentence_spans(text):
        timed=[c for c in characters if start_index <= int(c.get("text_index", -1)) < end_index and str(c.get("text", "")).strip()]
        if not timed: raise AudioPipelineError("TIMESTAMP_NORMALIZATION_FAILED", provider="typecast", stage="alignment")
        start=float(timed[0].get("start", timed[0].get("start_time"))); end=float(timed[-1].get("end", timed[-1].get("end_time")))
        if end <= start: raise AudioPipelineError("TIMESTAMP_NORMALIZATION_FAILED", provider="typecast", stage="alignment")
        spans.append({"text":text[start_index:end_index], "start":start, "end":end})
    return spans


class TypecastProvider:
    name="typecast"
    provenance="YouTube Auto snapshot d0c86c8e: timestamp-to-sentence normalization adapted; no imports retained."
    def __init__(self, transport=None) -> None: self.transport=transport or self._request
    def _request(self, payload: dict[str, Any], key: str) -> dict[str, Any]:
        request=urllib.request.Request("https://api.typecast.ai/v1/text-to-speech/with-timestamps?granularity=char", data=json.dumps(payload).encode(), headers={"Content-Type":"application/json", "Accept":"application/json", "X-API-KEY":key}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=180) as response: return json.loads(response.read().decode())
        except urllib.error.HTTPError as error: raise AudioPipelineError("RATE_LIMITED" if error.code==429 else "PROVIDER_GENERATION_FAILED", provider=self.name, stage="tts") from error
        except (urllib.error.URLError, TimeoutError, socket.timeout) as error: raise AmbiguousDispatchError(self.name) from error
    def generate(self, request: TTSRequest, output: Path) -> TTSResult:
        key=provider_keys(self.name)[0]
        response=self.transport({"voice_id":request.voice_id, "text":request.narration, "model":request.settings.get("model", "ssfm-v30"), "prompt":{"emotion_type":"smart"}, "output":{"audio_format":"wav"}}, key)
        try: audio=base64.b64decode(response["audio"], validate=True); characters=response["characters"]
        except Exception as error: raise AudioPipelineError("PROVIDER_GENERATION_FAILED", provider=self.name, stage="tts") from error
        returned="".join(str(item.get("text", "")) for item in characters)
        if returned != request.narration: raise AudioPipelineError("NARRATION_ALIGNMENT_MISMATCH", provider=self.name, stage="tts")
        atomic_write_bytes(output, audio)
        return TTSResult(output, self.name, request.voice_id, float(request.settings.get("duration_seconds", 0)), request.narration_sha256, {"model":request.settings.get("model", "ssfm-v30"), "characters":characters}, "typecast_timestamps")
    def align(self, request: TTSRequest, result: TTSResult) -> list[dict[str, Any]]:
        return normalize_timestamps(request.narration, result.metadata["characters"])

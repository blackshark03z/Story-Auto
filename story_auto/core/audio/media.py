"""Media validation owned by the Story Auto audio boundary."""

from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

from .errors import AudioPipelineError


SUPPORTED_AUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"})


def inspect_audio(path: Path, *, provider: str) -> dict[str, Any]:
    """Verify a readable audio stream and return only media facts we observed."""
    if path.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
        raise AudioPipelineError("AUDIO_FORMAT_UNSUPPORTED", provider=provider, stage="tts")
    try:
        with wave.open(str(path), "rb") as audio:
            rate = audio.getframerate()
            duration = audio.getnframes() / float(rate) if rate else 0.0
            codec = "pcm"
    except (wave.Error, EOFError, OSError):
        duration = 0.0
        codec = None
    if duration <= 0:
        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            result = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name,codec_type:format=duration", "-of", "json", str(path)], capture_output=True, text=True, check=False)
            try: duration = float(result.stdout.strip()) if result.returncode == 0 else 0.0
            except ValueError:
                try:
                    import json
                    probe = json.loads(result.stdout) if result.returncode == 0 else {}
                    streams = probe.get("streams", [])
                    codec = streams[0].get("codec_name") if streams and streams[0].get("codec_type") == "audio" else None
                    duration = float(probe.get("format", {}).get("duration", 0)) if codec else 0.0
                except (ValueError, TypeError, json.JSONDecodeError): duration = 0.0
    if duration <= 0:
        raise AudioPipelineError("AUDIO_ARTIFACT_INVALID", provider=provider, stage="tts")
    return {"duration_seconds": round(float(duration), 6), "container": path.suffix.lower().removeprefix("."), "codec": codec or "unknown", "has_audio_stream": True}


def audio_duration_seconds(path: Path, *, provider: str) -> float:
    """Compatibility duration view over strict audio stream validation."""
    return float(inspect_audio(path, provider=provider)["duration_seconds"])

"""Media validation owned by the Story Auto audio boundary."""

from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

from .errors import AudioPipelineError


def audio_duration_seconds(path: Path, *, provider: str) -> float:
    """Return a verified duration without accepting arbitrary non-empty bytes."""
    try:
        with wave.open(str(path), "rb") as audio:
            rate = audio.getframerate()
            duration = audio.getnframes() / float(rate) if rate else 0.0
    except (wave.Error, EOFError, OSError):
        duration = 0.0
    if duration <= 0:
        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)], capture_output=True, text=True, check=False)
            try: duration = float(result.stdout.strip()) if result.returncode == 0 else 0.0
            except ValueError: duration = 0.0
    if duration <= 0:
        raise AudioPipelineError("AUDIO_ARTIFACT_INVALID", provider=provider, stage="tts")
    return duration

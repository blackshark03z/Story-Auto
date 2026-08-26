"""Small deterministic helpers shared by FULL_IMAGE waveform evidence/tests."""

from __future__ import annotations

import math
from collections.abc import Sequence


def derive_amplitude_envelope(samples: Sequence[float], *, window_size: int) -> list[float]:
    """Return normalized RMS buckets without retaining raw audio in artifacts."""
    if not isinstance(window_size, int) or window_size <= 0:
        raise ValueError("window_size must be positive")
    if not samples:
        return []
    result: list[float] = []
    for start in range(0, len(samples), window_size):
        window = samples[start:start + window_size]
        result.append(round(math.sqrt(sum(float(value) ** 2 for value in window) / len(window)), 8))
    return result


def visualizer_spec(*, enabled: bool) -> dict[str, object]:
    return {"enabled": bool(enabled), "source": "canonical_narration_audio",
            "renderer": "ffmpeg_showwaves", "size": [420, 72], "position": "TOP_LEFT_SAFE_MARGIN",
            "deterministic": True}

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


def visualizer_spec(*, enabled: bool, target_width: int = 1920, target_height: int = 1080) -> dict[str, object]:
    """Describe the centered, renderer-owned FULL_IMAGE waveform geometry."""
    if target_width <= 0 or target_height <= 0:
        raise ValueError("target dimensions must be positive")
    width = round(target_width * .70)
    height = round(target_height * .25)
    return {"enabled": bool(enabled), "source": "canonical_narration_audio",
            "renderer": "ffmpeg_showwaves", "size": [width, height], "position": "CENTER_FRAME",
            "position_pixels": [(target_width - width) // 2, (target_height - height) // 2],
            "amplitude_gain": 4.0, "amplitude_scale": "sqrt", "color": "white@0.92",
            "deterministic": True}

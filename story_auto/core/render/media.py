"""Small FFmpeg/FFprobe primitives owned by Story Auto's render boundary."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import subprocess
from typing import Any, Callable, Iterable

from story_auto.core.artifacts import sha256_file


class MediaError(RuntimeError):
    """Stable product-facing media failure."""

    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(failure_class + (f": {detail}" if detail else ""))


@dataclass(frozen=True)
class MediaTarget:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    pixel_format: str = "yuv420p"

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0 or self.fps <= 0:
            raise MediaError("RENDER_SETTINGS_INVALID")


def format_duration(value: float) -> str:
    if not math.isfinite(value) or value <= 0:
        raise MediaError("RENDER_DURATION_INVALID")
    return f"{value:.6f}".rstrip("0").rstrip(".")


def run_command(command: list[str], *, runner: Callable[..., Any] = subprocess.run) -> None:
    try:
        runner(command, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        raise MediaError("FFMPEG_FAILED", detail[-1000:]) from error


def probe_media(path: Path | str, *, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    target = Path(path)
    try:
        result = runner(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(target)],
            capture_output=True, text=True, check=True,
        )
        raw = json.loads(result.stdout)
        streams = raw.get("streams", [])
        video = next((item for item in streams if item.get("codec_type") == "video"), None)
        audio = [item for item in streams if item.get("codec_type") == "audio"]
        duration = float((video or {}).get("duration") or raw.get("format", {}).get("duration") or 0)
        if duration <= 0:
            raise ValueError("non-positive duration")
        return {
            "path": str(target),
            "duration_seconds": duration,
            "container": raw.get("format", {}).get("format_name"),
            "video": None if video is None else {
                "codec": video.get("codec_name"),
                "width": int(video.get("width", 0)),
                "height": int(video.get("height", 0)),
                "pixel_format": video.get("pix_fmt"),
                "frame_rate": video.get("avg_frame_rate") or video.get("r_frame_rate"),
            },
            "audio": [{"codec": item.get("codec_name"), "channels": item.get("channels"),
                       "sample_rate": item.get("sample_rate")} for item in audio],
            "sha256": sha256_file(target),
        }
    except Exception as error:
        if isinstance(error, MediaError):
            raise
        raise MediaError("MEDIA_PROBE_FAILED", str(target)) from error


def validate_video(
    path: Path | str, *, target: MediaTarget | None = None, silent: bool | None = None,
    expected_duration: float | None = None, tolerance: float = 0.08,
) -> dict[str, Any]:
    metadata = probe_media(path)
    video = metadata["video"]
    if video is None or video["width"] <= 0 or video["height"] <= 0:
        raise MediaError("FINAL_MEDIA_INVALID", "missing video stream")
    if target and (video["width"], video["height"], video["pixel_format"]) != (
        target.width, target.height, target.pixel_format,
    ):
        raise MediaError("FINAL_MEDIA_INVALID", "video does not match target format")
    if silent is True and metadata["audio"]:
        raise MediaError("FINAL_MEDIA_INVALID", "silent clip contains audio")
    if silent is False and not metadata["audio"]:
        raise MediaError("FINAL_MEDIA_INVALID", "final output lacks audio")
    if expected_duration is not None and abs(metadata["duration_seconds"] - expected_duration) > tolerance:
        raise MediaError("FINAL_DURATION_INVALID", f"expected {expected_duration}, got {metadata['duration_seconds']}")
    return metadata


def concat_escape(path: Path | str) -> str:
    """Return one safe ffconcat file line for an absolute path."""

    value = str(Path(path).resolve()).replace("\\", "/").replace("'", "'\\''")
    return f"file '{value}'"


def transition_output_durations(segments: Iterable[dict[str, Any]]) -> tuple[list[float], float]:
    """Return compile durations and final duration for overlap transitions.

    Each source clip carries its outgoing overlap. Crossfading that overlap out
    restores the exact sum of canonical target intervals.
    """

    values = list(segments)
    compiled: list[float] = []
    final = 0.0
    for index, segment in enumerate(values):
        duration = float(segment["target_duration"])
        transition = segment.get("transition", {})
        overlap = float(transition.get("duration", 0)) if transition.get("type", "CUT") == "CROSSFADE" else 0.0
        if index == len(values) - 1:
            overlap = 0.0
        if duration <= 0 or overlap < 0 or overlap >= duration:
            raise MediaError("TRANSITION_TIMING_INVALID")
        compiled.append(duration + overlap)
        final += duration
    return compiled, final

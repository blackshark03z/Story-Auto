"""Deterministic subtitles derived only from canonical alignment timing."""

from __future__ import annotations

from pathlib import Path
import textwrap
from typing import Any

from story_auto.core.artifacts import atomic_write_text


SUBTITLE_VERSION = "story-auto-subtitles/1.0.0"


class SubtitleError(RuntimeError):
    failure_class = "SUBTITLE_FAILED"


def _srt_time(value: float) -> str:
    milliseconds = max(0, round(value * 1000))
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _ass_time(value: float) -> str:
    centiseconds = max(0, round(value * 100))
    hours, rest = divmod(centiseconds, 360_000)
    minutes, rest = divmod(rest, 6000)
    seconds, centis = divmod(rest, 100)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}.{centis:02d}"


def _wrapped(text: str, width: int) -> list[str]:
    clean = " ".join(str(text).split())
    return textwrap.wrap(clean, width=width, break_long_words=False, break_on_hyphens=False) or [""]


def validate_subtitle_timing(alignment: dict[str, Any]) -> None:
    duration = float(alignment.get("duration_seconds", 0))
    previous = 0.0
    segments = alignment.get("segments")
    if duration <= 0 or not isinstance(segments, list) or not segments:
        raise SubtitleError("invalid canonical alignment")
    for item in segments:
        try:
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError) as error:
            raise SubtitleError("invalid subtitle timing") from error
        if start < previous - .001 or end <= start or end > duration + .05 or not str(item.get("text", "")).strip():
            raise SubtitleError("invalid subtitle timing")
        previous = end


def build_subtitles(alignment: dict[str, Any], srt_path: Path, ass_path: Path, *, width: int = 44,
                    font_name: str = "Arial", font_size: int = 48) -> None:
    validate_subtitle_timing(alignment)
    srt: list[str] = []
    dialogues: list[str] = []
    for index, item in enumerate(alignment["segments"], 1):
        lines = _wrapped(item["text"], width)
        srt.extend([str(index), f"{_srt_time(float(item['start']))} --> {_srt_time(float(item['end']))}", "\n".join(lines), ""])
        ass_text = r"\N".join(line.replace("{", r"\{").replace("}", r"\}") for line in lines)
        dialogues.append(f"Dialogue: 0,{_ass_time(float(item['start']))},{_ass_time(float(item['end']))},Default,,0,0,0,,{ass_text}")
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,90,90,54,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    atomic_write_text(srt_path, "\n".join(srt))
    atomic_write_text(ass_path, header + "\n".join(dialogues) + "\n")

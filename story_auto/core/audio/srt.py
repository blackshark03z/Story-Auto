"""Strict, deterministic import of operator-supplied SRT timing."""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path


SRT_ENCODINGS = ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be")
_TIMING = re.compile(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2}),(\d{3})$")


class SrtError(ValueError):
    failure_class = "SRT_INVALID"


@dataclass(frozen=True)
class SrtCue:
    cue_id: str
    start: float
    end: float
    text: str
    raw_index: int


def _decode(payload: bytes) -> tuple[str, str]:
    for encoding in SRT_ENCODINGS:
        try:
            return payload.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise SrtError("SRT_ENCODING_UNSUPPORTED")


def _seconds(parts: tuple[str, ...]) -> float:
    hours, minutes, seconds, milliseconds = (int(item) for item in parts)
    if minutes > 59 or seconds > 59:
        raise SrtError("SRT_TIMESTAMP_INVALID")
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def parse_srt_bytes(payload: bytes) -> tuple[list[SrtCue], str, dict[str, int | float]]:
    if not isinstance(payload, bytes) or not payload:
        raise SrtError("SRT_SOURCE_INVALID")
    text, encoding = _decode(payload)
    if "\x00" in text:
        raise SrtError("SRT_ENCODING_UNSUPPORTED")
    blocks = re.split(r"\r?\n[\t ]*\r?\n", text.strip())
    if not blocks:
        raise SrtError("SRT_CUES_MISSING")
    raw, non_empty, previous_end, prior_number = [], [], 0.0, None
    for raw_index, block in enumerate(blocks, 1):
        lines = block.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if len(lines) < 2:
            raise SrtError("SRT_CUE_MALFORMED")
        number = None
        timing_line = lines[0].strip()
        text_lines = lines[1:]
        if not _TIMING.fullmatch(timing_line):
            if not timing_line.isdigit() or len(lines) < 2:
                raise SrtError("SRT_CUE_MALFORMED")
            number, timing_line, text_lines = int(timing_line), lines[1].strip(), lines[2:]
            if number <= 0 or (prior_number is not None and number <= prior_number):
                raise SrtError("SRT_CUE_NUMBERING_INVALID")
            prior_number = number
        match = _TIMING.fullmatch(timing_line)
        if match is None:
            raise SrtError("SRT_TIMESTAMP_INVALID")
        start, end = _seconds(match.groups()[:4]), _seconds(match.groups()[4:])
        if start < 0 or end <= start or start < previous_end:
            raise SrtError("SRT_TIMELINE_NON_MONOTONIC")
        cue = SrtCue(f"cue_{raw_index:04d}", start, end, "\n".join(text_lines).strip(), raw_index)
        raw.append(cue)
        if cue.text:
            non_empty.append(cue)
        previous_end = end
    if not non_empty:
        raise SrtError("SRT_TEXT_CUES_MISSING")
    return non_empty, encoding, {"raw_cue_count": len(raw), "text_cue_count": len(non_empty),
                                  "ignored_empty_cues": len(raw) - len(non_empty),
                                  "first_timestamp": non_empty[0].start, "last_timestamp": non_empty[-1].end}


def parse_srt_file(path: Path | str) -> tuple[list[SrtCue], str, dict[str, int | float]]:
    source = Path(path)
    if source.suffix.lower() != ".srt" or not source.is_file():
        raise SrtError("SRT_SOURCE_INVALID")
    try:
        return parse_srt_bytes(source.read_bytes())
    except OSError as error:
        raise SrtError("SRT_SOURCE_UNREADABLE") from error

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from story_auto.core.content import narrations_equivalent

ALIGNMENT_SCHEMA_VERSION = "story-auto-alignment/1.0.0"


class AlignmentError(ValueError):
    failure_class = "ALIGNMENT_INVALID"


@dataclass(frozen=True)
class TimedSpan:
    text: str
    start: float
    end: float


def build_alignment(*, project_id: str, audio_path: str, audio_sha256: str, narration_sha256: str,
                    duration_seconds: float, source: str, spans: list[TimedSpan]) -> dict[str, Any]:
    value = {"schema_version": ALIGNMENT_SCHEMA_VERSION, "project_id": project_id, "audio_path": audio_path,
             "audio_sha256": audio_sha256, "narration_sha256": narration_sha256,
             "duration_seconds": round(float(duration_seconds), 6), "source": source,
             "segments": [{"segment_id": f"seg_{index:04d}", "start": round(span.start, 6),
                           "end": round(span.end, 6), "text": span.text} for index, span in enumerate(spans, 1)]}
    return value


def deterministic_text_alignment(*, project_id: str, audio_path: str, audio_sha256: str,
                                 narration_sha256: str, narration: str,
                                 duration_seconds: float) -> dict[str, Any]:
    """A truthful non-ASR fallback: deterministic sentence windows proportional to text length."""
    import re
    # Keep separators in their preceding segment so concatenating canonical text
    # remains byte-for-byte equivalent to the narration contract.
    pieces, cursor = [], 0
    for boundary in re.finditer(r"(?<=[.!?])\s+|\n{2,}", narration):
        pieces.append(narration[cursor:boundary.end()])
        cursor = boundary.end()
    if cursor < len(narration):
        pieces.append(narration[cursor:])
    pieces = [item for item in pieces if item]
    if not pieces:
        raise AlignmentError("alignment needs narration text")
    weights = [max(1, len(re.sub(r"\s+", "", item))) for item in pieces]
    total = sum(weights)
    cursor = 0.0
    spans: list[TimedSpan] = []
    for index, (piece, weight) in enumerate(zip(pieces, weights)):
        end = float(duration_seconds) if index == len(pieces) - 1 else round(cursor + duration_seconds * weight / total, 6)
        if end <= cursor:
            end = cursor + .001
        spans.append(TimedSpan(piece, cursor, end))
        cursor = end
    return build_alignment(project_id=project_id, audio_path=audio_path, audio_sha256=audio_sha256,
                           narration_sha256=narration_sha256, duration_seconds=duration_seconds,
                           source="deterministic_text_proportional_no_asr", spans=spans)


def validate_alignment(value: Any, *, narration: str, narration_sha256: str, audio_sha256: str,
                       duration_seconds: float, tolerance_seconds: float = 0.15) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != ALIGNMENT_SCHEMA_VERSION:
        raise AlignmentError("unsupported alignment schema")
    if value.get("narration_sha256") != narration_sha256 or value.get("audio_sha256") != audio_sha256:
        raise AlignmentError("narration or audio identity mismatch")
    segments = value.get("segments")
    if not isinstance(segments, list) or not segments:
        raise AlignmentError("alignment needs at least one segment")
    reconstructed, previous_end = [], 0.0
    for segment in segments:
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
            raise AlignmentError("invalid segment")
        try: start, end = float(segment["start"]), float(segment["end"])
        except (KeyError, TypeError, ValueError) as error: raise AlignmentError("invalid segment timing") from error
        if start < 0 or end <= start or start < previous_end:
            raise AlignmentError("segments must be ordered non-overlapping positive intervals")
        previous_end, reconstructed = end, reconstructed + [segment["text"]]
    if previous_end > duration_seconds + tolerance_seconds:
        raise AlignmentError("alignment exceeds validated audio duration")
    if value.get("timing_source") == "SRT":
        if value.get("source") != "SRT" or not all(str(item.get("segment_id", "")).startswith("cue_") for item in segments):
            raise AlignmentError("SRT alignment provenance is invalid")
        return
    if not narrations_equivalent("".join(reconstructed), narration):
        raise AlignmentError("alignment text does not reconstruct narration")

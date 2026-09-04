"""Canonical, serializable readiness for operator-supplied narration imports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from story_auto.core.audio import (SRT_TIMELINE_TOLERANCE_SECONDS, SrtCue,
                                   SrtError, parse_srt_bytes)
from story_auto.core.audio.errors import AudioPipelineError
from story_auto.core.audio.media import inspect_audio


def _component(status: str, code: str | None, message: str, **facts: Any) -> dict[str, Any]:
    return {"status": status, "code": code, "message": message, **facts}


def _not_required(message: str = "Not required for this input source.") -> dict[str, Any]:
    return _component("NOT_REQUIRED", None, message)


def _import_semantics(source_mode: str) -> tuple[str, str]:
    """Keep the declared import execution semantics stable in every readiness state."""
    return "SKIPPED", "SRT" if source_mode == "AUDIO_SRT" else "ALIGNMENT"


def _blocked(*, source_mode: str, code: str, message: str, audio: dict[str, Any], srt: dict[str, Any],
             timeline: dict[str, Any]) -> dict[str, Any]:
    tts, timing = _import_semantics(source_mode)
    return {"status": "BLOCKED", "code": code, "message": message,
            "audio": audio, "srt": srt, "timeline": timeline,
            "tts": tts, "timing": timing}


def not_required_readiness() -> dict[str, Any]:
    """A uniform result for source modes that do not import media."""
    return {"status": "READY", "code": "READY", "message": "No imported narration validation is required.",
            "audio": _not_required(), "srt": _not_required(), "timeline": _not_required(),
            "tts": "RUN", "timing": "AUTO"}


def inspect_import_readiness(*, source_mode: str, audio_path: Path | None = None,
                             audio_filename: str | None = None, srt_payload: bytes | None = None,
                             srt_filename: str | None = None, audio_error: str | None = None,
                             srt_error: str | None = None) -> tuple[dict[str, Any], list[SrtCue]]:
    """Return the one import-readiness truth and parsed cues when they are valid.

    This is deliberately a result model rather than an exception transport: normal
    validation failures stay actionable at the API, wizard, and create boundaries.
    """
    if source_mode not in {"EXISTING_AUDIO", "AUDIO_SRT"}:
        return not_required_readiness(), []
    if audio_error or audio_path is None:
        code = audio_error or "NARRATION_AUDIO_REQUIRED"
        audio = _component("BLOCKED", code, "Choose a readable narration audio file.")
        return _blocked(source_mode=source_mode, code="AUDIO_INVALID", message=audio["message"], audio=audio,
                        srt=_not_required() if source_mode == "EXISTING_AUDIO" else _component("NOT_EVALUATED", None, "Select narration audio first."),
                        timeline=_not_required("Existing audio uses alignment timing.") if source_mode == "EXISTING_AUDIO" else _component("NOT_EVALUATED", None, "Timeline is checked after valid imports.")), []
    try:
        observed = inspect_audio(audio_path, provider="existing_audio")
    except AudioPipelineError as error:
        code = getattr(error, "failure_class", None) or str(error) or "AUDIO_STREAM_INVALID"
        audio = _component("BLOCKED", code, "Narration audio could not be read.")
        return _blocked(source_mode=source_mode, code="AUDIO_INVALID", message=audio["message"], audio=audio,
                        srt=_not_required() if source_mode == "EXISTING_AUDIO" else _component("NOT_EVALUATED", None, "Select valid narration audio first."),
                        timeline=_not_required("Existing audio uses alignment timing.") if source_mode == "EXISTING_AUDIO" else _component("NOT_EVALUATED", None, "Timeline is checked after valid imports.")), []
    duration_ms = float(observed["duration_seconds"]) * 1000.0
    audio = _component("READY", "READY", "Narration audio is ready.", filename=audio_filename or audio_path.name,
                       duration_ms=duration_ms, format=observed["container"], codec=observed["codec"])
    if source_mode == "EXISTING_AUDIO":
        return {"status": "READY", "code": "READY", "message": "Narration audio is ready.", "audio": audio,
                "srt": _not_required(), "timeline": _not_required(), "tts": "SKIPPED", "timing": "ALIGNMENT"}, []
    if srt_error or srt_payload is None:
        code = srt_error or "SRT_REQUIRED"
        srt = _component("BLOCKED", code, "Choose a matching SRT subtitle file.")
        return _blocked(source_mode=source_mode, code="SRT_INVALID", message=srt["message"], audio=audio, srt=srt,
                        timeline=_component("NOT_EVALUATED", None, "Timeline is checked after valid subtitles.")), []
    try:
        cues, encoding, stats = parse_srt_bytes(srt_payload)
    except SrtError as error:
        code = str(error) or "SRT_INVALID"
        message = "Subtitle timestamps are invalid." if code == "SRT_TIMESTAMP_INVALID" else "Subtitle file is malformed."
        srt = _component("BLOCKED", code, message)
        return _blocked(source_mode=source_mode, code="SRT_INVALID", message=message, audio=audio, srt=srt,
                        timeline=_component("NOT_EVALUATED", None, "Timeline is checked after valid subtitles.")), []
    srt_end_ms = float(stats["last_timestamp"]) * 1000.0
    srt = _component("READY", "READY", "Matching SRT timing is ready.", filename=srt_filename or "timing.srt",
                     encoding=encoding, raw_cue_count=stats["raw_cue_count"], text_cue_count=stats["text_cue_count"],
                     ignored_empty_cues=stats["ignored_empty_cues"], first_timestamp_ms=float(stats["first_timestamp"]) * 1000.0,
                     last_timestamp_ms=srt_end_ms)
    tolerance_ms = SRT_TIMELINE_TOLERANCE_SECONDS * 1000.0
    signed_offset_ms = srt_end_ms - duration_ms
    delta_ms = abs(signed_offset_ms)
    if delta_ms > tolerance_ms:
        direction = "SRT_AFTER_AUDIO" if signed_offset_ms > 0 else "SRT_BEFORE_AUDIO"
        relation = "after" if signed_offset_ms > 0 else "before"
        message = (f"Subtitle timing ends {delta_ms / 1000.0:.3f} s {relation} the narration audio. "
                   f"Allowed difference is {tolerance_ms / 1000.0:.3f} s.")
        timeline = _component("BLOCKED", "TIMELINE_MISMATCH", message, audio_duration_ms=duration_ms,
                              srt_end_ms=srt_end_ms, signed_offset_ms=signed_offset_ms, direction=direction,
                              delta_ms=delta_ms, tolerance_ms=tolerance_ms)
        return _blocked(source_mode=source_mode, code="TIMELINE_MISMATCH", message=message, audio=audio, srt=srt, timeline=timeline), cues
    timeline = _component("READY", "READY", "Subtitle timing matches the narration audio.", audio_duration_ms=duration_ms,
                          srt_end_ms=srt_end_ms, delta_ms=delta_ms, tolerance_ms=tolerance_ms)
    return {"status": "READY", "code": "READY", "message": "Audio and subtitle timing are ready.",
            "audio": audio, "srt": srt, "timeline": timeline, "tts": "SKIPPED", "timing": "SRT"}, cues

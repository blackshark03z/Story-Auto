"""Provider-neutral narration audio and alignment contracts."""

from .alignment import AlignmentError, TimedSpan, build_alignment, deterministic_text_alignment, validate_alignment
from .contracts import TTSRequest, TTSResult
from .errors import AudioPipelineError
from .media import audio_duration_seconds
from .srt import SrtCue, SrtError, parse_srt_bytes, parse_srt_file

__all__ = ["AlignmentError", "AudioPipelineError", "SrtCue", "SrtError", "TimedSpan", "TTSRequest", "TTSResult", "audio_duration_seconds", "build_alignment", "parse_srt_bytes", "parse_srt_file", "validate_alignment"]

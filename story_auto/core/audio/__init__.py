"""Provider-neutral narration audio and alignment contracts."""

from .alignment import AlignmentError, TimedSpan, build_alignment, validate_alignment
from .contracts import TTSRequest, TTSResult
from .errors import AudioPipelineError
from .media import audio_duration_seconds

__all__ = ["AlignmentError", "AudioPipelineError", "TimedSpan", "TTSRequest", "TTSResult", "audio_duration_seconds", "build_alignment", "validate_alignment"]

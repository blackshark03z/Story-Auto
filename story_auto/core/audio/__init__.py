"""Provider-neutral narration audio and alignment contracts."""

from .alignment import AlignmentError, TimedSpan, build_alignment, validate_alignment
from .contracts import TTSRequest, TTSResult
from .errors import AudioPipelineError

__all__ = ["AlignmentError", "AudioPipelineError", "TimedSpan", "TTSRequest", "TTSResult", "build_alignment", "validate_alignment"]

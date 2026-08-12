from __future__ import annotations


class AudioPipelineError(RuntimeError):
    """Sanitized, contextual TTS pipeline failure; never includes secrets."""

    def __init__(self, failure_class: str, *, provider: str, stage: str, detail: str = "") -> None:
        self.failure_class, self.provider, self.stage = failure_class, provider, stage
        super().__init__(f"{provider}:{stage}:{failure_class}" + (f" ({detail})" if detail else ""))


class AmbiguousDispatchError(AudioPipelineError):
    def __init__(self, provider: str) -> None:
        super().__init__("AMBIGUOUS_POST_DISPATCH", provider=provider, stage="tts")

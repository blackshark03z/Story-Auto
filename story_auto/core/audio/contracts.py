from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TTSRequest:
    narration: str
    narration_sha256: str
    provider: str
    voice_id: str
    settings: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.provider not in {"elevenlabs", "typecast"}:
            raise ValueError("unsupported TTS provider")
        if not self.narration.strip() or not self.voice_id.strip():
            raise ValueError("narration and voice_id are required")


@dataclass(frozen=True)
class TTSResult:
    audio_path: Path
    provider: str
    voice_id: str
    duration_seconds: float
    narration_sha256: str
    metadata: dict[str, Any] = field(default_factory=dict)
    alignment_method: str = ""

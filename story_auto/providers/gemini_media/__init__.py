"""Official Gemini API media execution at Story Auto's provider boundary."""

from .client import (
    GeminiMediaClient,
    GeminiMediaError,
    MediaResult,
    ModelCapability,
)
from .service import execute_media_request

__all__ = ["GeminiMediaClient", "GeminiMediaError", "MediaResult", "ModelCapability", "execute_media_request"]

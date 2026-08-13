"""Gemini Web browser provider boundary for Story Auto."""

from .capabilities import GeminiWebCapabilities, inspect_capabilities
from .session import GeminiWebError, GeminiWebRuntime, launch_dedicated_session
from .live import LiveGeminiWebGenerator
from .service import execute_web_request

__all__ = [
    "GeminiWebCapabilities",
    "GeminiWebError",
    "GeminiWebRuntime",
    "LiveGeminiWebGenerator",
    "execute_web_request",
    "inspect_capabilities",
    "launch_dedicated_session",
]

"""Isolated, operator-owned Chrome runtime for Gemini Web."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
from urllib.parse import urlparse
from urllib.request import urlopen
import json


class GeminiWebError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "", *, dispatch_confirmed: bool = False) -> None:
        self.failure_class = failure_class
        self.detail = detail
        self.dispatch_confirmed = dispatch_confirmed
        super().__init__(failure_class + (f": {detail}" if detail else ""))


@dataclass(frozen=True)
class GeminiWebRuntime:
    profile: Path
    cdp_url: str = "http://127.0.0.1:9223"
    app_url: str = "https://gemini.google.com/app"
    expected_account_hint: str = "STORY_AUTO_DEDICATED_SESSION"

    @classmethod
    def from_root(cls, root: Path | str) -> "GeminiWebRuntime":
        resolved = Path(root).resolve()
        return cls(profile=resolved / "browser" / "gemini-profile")


def cdp_health(runtime: GeminiWebRuntime) -> dict:
    try:
        with urlopen(runtime.cdp_url.rstrip("/") + "/json/version", timeout=3) as response:
            value = json.loads(response.read().decode("utf-8"))
        if not isinstance(value, dict) or "Browser" not in value:
            raise ValueError("invalid CDP metadata")
        return value
    except Exception as error:
        raise GeminiWebError("GEMINI_WEB_CDP_UNAVAILABLE", "launch the dedicated Gemini Web runtime") from error


def _chrome_path() -> Path:
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    chrome = next((path for path in candidates if path.is_file()), None)
    if chrome is None:
        raise GeminiWebError("GEMINI_WEB_CDP_UNAVAILABLE", "Google Chrome was not found")
    return chrome


def launch_dedicated_session(runtime: GeminiWebRuntime, *, launcher=subprocess.Popen) -> None:
    """Launch only the Story Auto Gemini profile; never copies or reads another profile."""
    port = urlparse(runtime.cdp_url).port
    if not port:
        raise GeminiWebError("GEMINI_WEB_CDP_UNAVAILABLE", "CDP URL needs an explicit port")
    runtime.profile.mkdir(parents=True, exist_ok=True)
    launcher(
        [
            str(_chrome_path()),
            f"--remote-debugging-port={port}",
            f"--remote-allow-origins={runtime.cdp_url}",
            f"--user-data-dir={runtime.profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling",
            runtime.app_url,
        ],
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )

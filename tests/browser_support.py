from __future__ import annotations

import os
from pathlib import Path


def system_chrome_path() -> Path | None:
    """Return an installed system Chrome without assuming 32-bit placement."""
    roots = (
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("LOCALAPPDATA"),
    )
    candidates = [
        Path(root) / "Google/Chrome/Application/chrome.exe"
        for root in roots
        if root
    ]
    return next((path for path in candidates if path.is_file()), None)

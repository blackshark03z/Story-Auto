"""Bounded local resource preflights for provider acquisition and rendering."""
from __future__ import annotations

from pathlib import Path
import shutil
from typing import Callable, Any


class ResourceError(RuntimeError):
    def __init__(self, failure_class: str, detail: str="") -> None:
        self.failure_class=failure_class; super().__init__(failure_class+(f": {detail}" if detail else ""))


def ensure_free_space(path: Path | str, *, minimum_free_bytes: int,
                      disk_usage: Callable[[Path | str], Any]=shutil.disk_usage) -> int:
    if not isinstance(minimum_free_bytes,int) or minimum_free_bytes<0: raise ResourceError("STORAGE_SETTINGS_INVALID")
    target=Path(path); target.mkdir(parents=True,exist_ok=True)
    try: free=int(disk_usage(target).free)
    except OSError as error: raise ResourceError("STORAGE_STATE_UNAVAILABLE") from error
    if free<minimum_free_bytes: raise ResourceError("INSUFFICIENT_DISK_SPACE",f"required={minimum_free_bytes} free={free}")
    return free

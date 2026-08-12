"""Atomic UTF-8 writes for durable Story Auto artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any


class ArtifactWriteError(OSError):
    """Raised when an artifact cannot be atomically published."""


def atomic_write_text(path: Path | str, content: str) -> None:
    """Atomically replace *path* with UTF-8 *content*.

    Data is fully written and flushed to a sibling temporary file before the
    replace step.  If replacement fails, the already-published file remains
    intact and the temporary file is removed.
    """

    if not isinstance(content, str):
        raise TypeError("artifact text must be a string")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", delete=False,
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
        ) as temporary:
            temp_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temp_path, target)
        temp_path = None
    except OSError as error:
        raise ArtifactWriteError(f"could not atomically write {target}") from error
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def atomic_write_json(path: Path | str, value: Any) -> None:
    """Serialize JSON deterministically, then atomically publish it as UTF-8."""

    serialized = json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ) + "\n"
    atomic_write_text(path, serialized)

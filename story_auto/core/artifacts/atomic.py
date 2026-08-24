"""Atomic UTF-8 writes for durable Story Auto artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any
import hashlib


class ArtifactWriteError(OSError):
    """Raised when an artifact cannot be atomically published."""


_TRANSIENT_REPLACE_ERRNOS = {getattr(os, "EACCES", 13), getattr(os, "EBUSY", 16)}
_TRANSIENT_REPLACE_WINERRORS = {5, 32, 33}
_REPLACE_DELAYS_SECONDS = (0.05, 0.1, 0.2, 0.4, 0.8)


def _replace_with_retry(source: Path, target: Path) -> None:
    """Publish a completed sibling file, tolerating brief Windows share locks.

    The temporary file has already been flushed.  Retrying only the replace
    operation neither rewrites it nor crosses any provider boundary, and a
    final failure still leaves the prior published artifact intact.
    """

    for delay in (*_REPLACE_DELAYS_SECONDS, None):
        try:
            os.replace(source, target)
            return
        except OSError as error:
            transient = (
                error.errno in _TRANSIENT_REPLACE_ERRNOS
                or getattr(error, "winerror", None) in _TRANSIENT_REPLACE_WINERRORS
            )
            if not transient or delay is None:
                raise
            time.sleep(delay)


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
        _replace_with_retry(temp_path, target)
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


def atomic_write_bytes(path: Path | str, content: bytes) -> None:
    if not isinstance(content, bytes):
        raise TypeError("artifact bytes must be bytes")
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, dir=target.parent, prefix=f".{target.name}.", suffix=".tmp") as temporary:
            temp_path = Path(temporary.name); temporary.write(content); temporary.flush(); os.fsync(temporary.fileno())
        _replace_with_retry(temp_path, target); temp_path = None
    except OSError as error:
        raise ArtifactWriteError(f"could not atomically write {target}") from error
    finally:
        if temp_path is not None: temp_path.unlink(missing_ok=True)


def read_json(path: Path | str) -> Any:
    """Read UTF-8 JSON, retaining the filesystem boundary in the error."""

    target = Path(path)
    try:
        with target.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactWriteError(f"could not read JSON artifact {target}") from error


def sha256_file(path: Path | str) -> str:
    """Return the SHA-256 of a file without loading it all into memory."""

    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise ArtifactWriteError(f"could not hash file {path}") from error
    return digest.hexdigest()

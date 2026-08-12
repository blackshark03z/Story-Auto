"""One-writer project lock with conservative stale-lock recovery."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import time
from typing import Any

from story_auto.core.artifacts import atomic_write_json, read_json
from .paths import RuntimeLayout


class ProjectLockedError(RuntimeError):
    failure_class = "PROJECT_LOCKED"


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class ProjectLock:
    def __init__(self, runtime: RuntimeLayout, project_id: str, *, stale_after_seconds: float = 300.0, clock=time.time) -> None:
        self.runtime, self.project_id, self.stale_after_seconds, self.clock = runtime.ensure(), project_id, stale_after_seconds, clock
        self.path = self.runtime.locks / f"{project_id}.lock"
        self.metadata: dict[str, Any] | None = None

    def _stale(self) -> bool:
        try:
            metadata = read_json(self.path)
        except Exception:
            return False
        if not isinstance(metadata, dict) or metadata.get("hostname") != socket.gethostname():
            return False
        age = self.clock() - metadata.get("created_at", self.clock())
        return age >= self.stale_after_seconds and not _process_is_alive(metadata.get("pid", -1))

    def acquire(self) -> "ProjectLock":
        metadata = {"project_id": self.project_id, "pid": os.getpid(), "hostname": socket.gethostname(), "created_at": self.clock()}
        encoded = json.dumps(metadata, sort_keys=True).encode("utf-8")
        for attempt in range(2):
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(encoded); handle.flush(); os.fsync(handle.fileno())
                self.metadata = metadata
                return self
            except FileExistsError:
                if attempt == 0 and self._stale():
                    stale_path = self.path.with_suffix(self.path.suffix + ".stale")
                    try:
                        os.replace(self.path, stale_path)
                    except FileNotFoundError:
                        pass
                    else:
                        stale_path.unlink(missing_ok=True)
                    continue
                raise ProjectLockedError(f"project {self.project_id} is already locked: {self.path}")
        raise AssertionError("unreachable")

    def release(self) -> None:
        if self.metadata is None:
            return
        try:
            current = read_json(self.path)
            if current == self.metadata:
                self.path.unlink(missing_ok=True)
        finally:
            self.metadata = None

    def __enter__(self) -> "ProjectLock": return self.acquire()
    def __exit__(self, *_: object) -> None: self.release()

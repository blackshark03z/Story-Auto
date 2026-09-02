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


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5
_ERROR_INVALID_PARAMETER = 87
_STILL_ACTIVE = 259


class ProjectLockedError(RuntimeError):
    failure_class = "PROJECT_LOCKED"


class _WindowsProcessProbe:
    """Read-only Win32 owner-liveness probe used only on Windows."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._open_process = kernel32.OpenProcess
        self._open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._open_process.restype = wintypes.HANDLE
        self._get_exit_code = kernel32.GetExitCodeProcess
        self._get_exit_code.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self._get_exit_code.restype = wintypes.BOOL
        self._close_handle = kernel32.CloseHandle
        self._close_handle.argtypes = [wintypes.HANDLE]
        self._close_handle.restype = wintypes.BOOL

    def open_process(self, pid: int):
        return self._open_process(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)

    def last_error(self) -> int:
        return int(self._ctypes.get_last_error())

    def exit_code(self, handle) -> int | None:
        code = self._wintypes.DWORD()
        if not self._get_exit_code(handle, self._ctypes.byref(code)):
            return None
        return int(code.value)

    def close_handle(self, handle) -> None:
        self._close_handle(handle)


def _windows_process_is_alive(pid: int, *, probe=None) -> bool:
    """Return False only when Win32 proves a Windows process is dead.

    Windows does not support POSIX ``kill(pid, 0)`` probe semantics.  Unknown
    results deliberately remain alive so a possibly-live project lock cannot
    be stolen.
    """
    if pid <= 0:
        return False
    try:
        native = probe or _WindowsProcessProbe()
        handle = native.open_process(pid)
        if not handle:
            error = native.last_error()
            if error == _ERROR_INVALID_PARAMETER:
                return False
            if error == _ERROR_ACCESS_DENIED:
                return True
            return True
        try:
            code = native.exit_code(handle)
            if code is None:
                return True
            return code == _STILL_ACTIVE
        finally:
            native.close_handle(handle)
    except Exception:
        return True


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_process_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_process_liveness(pid: int, *, probe=None) -> bool | None:
    """Return True only for a provably live owner; None is intentionally unknown."""
    if pid <= 0:
        return False
    try:
        native = probe or _WindowsProcessProbe()
        handle = native.open_process(pid)
        if not handle:
            error = native.last_error()
            return False if error == _ERROR_INVALID_PARAMETER else None
        try:
            code = native.exit_code(handle)
            return None if code is None else code == _STILL_ACTIVE
        finally:
            native.close_handle(handle)
    except Exception:
        return None


def _process_liveness(pid: int) -> bool | None:
    """Read-only activity proof, stricter than stale-lock acquisition safety."""
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_process_liveness(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return None
    except OSError:
        return None
    return True


def project_lock_owned_by_live_process(runtime: RuntimeLayout, project_id: str) -> bool:
    """Prove a local project lock is owned by a live process without mutating it.

    Unknown ownership or liveness is not operational activity evidence.  This
    deliberately differs from lock acquisition, where uncertainty protects a
    potentially live owner from being stolen.
    """
    path = runtime.locks / f"{project_id}.lock"
    try:
        metadata = read_json(path)
    except Exception:
        return False
    if (not isinstance(metadata, dict) or metadata.get("project_id") != project_id
            or metadata.get("hostname") != socket.gethostname()
            or not isinstance(metadata.get("pid"), int)):
        return False
    return _process_liveness(metadata["pid"]) is True


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

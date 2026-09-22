"""Encrypted, named Dola cookie accounts.

This store deliberately has its own file and schema: Dola sessions must never
share or overwrite the API-key credential pools.
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from story_auto.core.artifacts import atomic_write_json
from story_auto.providers.credentials import _OWN_ENTROPY, _protect, _unprotect

_SCHEMA = "story-auto-dola-cookie-accounts"
_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_SESSION = re.compile(r"(?:^|;)\s*sessionid=([^;\s]+)", re.IGNORECASE)
_LOCK_GUARD = threading.RLock()


class DolaAccountError(ValueError):
    """A safe, non-secret configuration error."""


def _default_path() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return local / "StoryAuto" / "dola-cookie-accounts.v1.json"


@contextmanager
def _file_lock(path: Path):
    """OS-owned lock: process exit also releases ownership."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 5
    with _LOCK_GUARD:
        with lock_path.open("a+b") as handle:
            if handle.seek(0, 2) == 0:
                handle.write(b"0")
                handle.flush()
            while True:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise DolaAccountError("Dola account settings are busy. Try saving again.")
                    time.sleep(0.05)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class DolaAccountStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else _default_path()

    @staticmethod
    def _parse(raw: Any) -> list[dict[str, str]]:
        if isinstance(raw, str):
            text = raw.strip()
            if text.startswith("["):
                try:
                    raw = json.loads(text)
                except json.JSONDecodeError as error:
                    raise DolaAccountError("Dola account JSON is invalid.") from error
            else:
                raw = [line.split("\t", 1) for line in text.splitlines() if line.strip()]
        if not isinstance(raw, list):
            raise DolaAccountError("Paste named Dola accounts as tab-separated lines or a JSON list.")
        parsed: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in raw:
            if isinstance(item, dict):
                account_id = str(item.get("account_id", "")).strip()
                cookie = str(item.get("cookie", "")).strip()
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                account_id, cookie = str(item[0]).strip(), str(item[1]).strip()
            else:
                raise DolaAccountError("Each Dola account needs a name and a full cookie header.")
            if not _ALIAS.fullmatch(account_id):
                raise DolaAccountError("Account names use letters, numbers, dots, underscores, or dashes.")
            if "\r" in cookie or "\n" in cookie or not _SESSION.search(cookie):
                raise DolaAccountError("Each cookie header must include sessionid and contain one line.")
            if account_id in seen:
                raise DolaAccountError("Each Dola account name may appear only once per save.")
            seen.add(account_id)
            parsed.append({"account_id": account_id, "cookie": cookie})
        if not parsed:
            raise DolaAccountError("Add at least one named Dola account.")
        return parsed

    def _read_locked(self) -> dict[str, str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema_name") != _SCHEMA:
                raise DolaAccountError("Saved Dola account format is unsupported.")
            result: dict[str, str] = {}
            for item in payload.get("accounts", []):
                account_id = str(item.get("account_id", ""))
                blob = base64.b64decode(str(item.get("blob", "")), validate=True)
                if _ALIAS.fullmatch(account_id):
                    result[account_id] = _unprotect(blob, _OWN_ENTROPY)
            return result
        except FileNotFoundError:
            return {}
        except Exception:
            raise DolaAccountError("Saved Dola accounts could not be read. Paste fresh cookies to replace them.")

    def _write_locked(self, accounts: dict[str, str]) -> None:
        payload = {"schema_name": _SCHEMA, "schema_version": "1.0.0",
                   "protection": "WINDOWS_DPAPI_CURRENT_USER",
                   "accounts": [{"account_id": account_id, "protection": "WINDOWS_DPAPI_CURRENT_USER",
                                 "blob": _protect(cookie, _OWN_ENTROPY)}
                                for account_id, cookie in sorted(accounts.items())]}
        atomic_write_json(self.path, payload)

    def list_accounts(self) -> list[dict[str, object]]:
        with _file_lock(self.path):
            accounts = self._read_locked()
        return [{"account_id": account_id, "configured": True} for account_id in sorted(accounts)]

    def preview_accounts(self, raw: Any) -> dict[str, object]:
        incoming = self._parse(raw)
        with _file_lock(self.path):
            existing = self._read_locked()
        aliases = {item["account_id"] for item in incoming}
        return {"incoming_count": len(incoming), "new_count": len(aliases - set(existing)),
                "updated_count": len(aliases & set(existing)), "account_ids": sorted(aliases)}

    def save_accounts(self, raw: Any) -> dict[str, object]:
        incoming = self._parse(raw)
        with _file_lock(self.path):
            accounts = self._read_locked()
            aliases = {item["account_id"] for item in incoming}
            result = {"incoming_count": len(incoming), "new_count": len(aliases - set(accounts)),
                      "updated_count": len(aliases & set(accounts))}
            accounts.update({item["account_id"]: item["cookie"] for item in incoming})
            self._write_locked(accounts)
            result["saved_count"] = len(accounts)
        return result

    def get_cookie(self, account_id: str) -> str:
        if not _ALIAS.fullmatch(str(account_id)):
            raise DolaAccountError("Dola account is not configured.")
        with _file_lock(self.path):
            cookie = self._read_locked().get(str(account_id))
        if not cookie:
            raise DolaAccountError("Dola account is not configured.")
        return cookie

    def remove_account(self, account_id: str) -> dict[str, object]:
        if not _ALIAS.fullmatch(str(account_id)):
            raise DolaAccountError("Dola account is not configured.")
        with _file_lock(self.path):
            accounts = self._read_locked()
            removed = accounts.pop(str(account_id), None) is not None
            if removed:
                self._write_locked(accounts)
            return {"removed": removed, "saved_count": len(accounts)}

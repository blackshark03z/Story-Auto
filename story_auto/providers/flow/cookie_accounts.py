"""Encrypted named Flow cookie exports.

This is deliberately separate from API-key and Dola cookie stores.  The only
plaintext lifetime is the caller's in-memory value and the DPAPI operation.
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
from story_auto.providers.credentials import _protect, _unprotect

from .cookie_session import normalize_cookie_export

_SCHEMA = "story-auto-flow-cookie-accounts"
_ENTROPY = b"story-auto.flow-cookie-accounts.v1"
_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_LOCK_GUARD = threading.RLock()


class FlowCookieAccountError(ValueError):
    """Safe account-store error; values from cookie exports are never echoed."""


def _default_path() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return local / "StoryAuto" / "flow-cookie-accounts.v1.json"


@contextmanager
def _file_lock(path: Path):
    """Serialize read-modify-write across processes; stale lock files are harmless."""
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
                        raise FlowCookieAccountError("Flow cookie settings are busy. Try saving again.") from None
                    time.sleep(0.05)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _account_id(value: Any) -> str:
    if not isinstance(value, str) or not _ALIAS.fullmatch(value):
        raise FlowCookieAccountError("Flow cookie account name is invalid.")
    return value


class FlowCookieAccountStore:
    """DPAPI-backed, alias-scoped Flow browser-cookie export store."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else _default_path()

    @staticmethod
    def _normalize(raw: Any, *, allow_expired: bool = False) -> list[dict]:
        try:
            # Store reads must preserve a previously valid, now-expired export
            # long enough for its alias to be refreshed.  Actual use and every
            # incoming save keep the ordinary current-time expiry gate.
            return normalize_cookie_export(raw, now=float("-inf") if allow_expired else None)
        except Exception:
            raise FlowCookieAccountError("Flow cookie export is invalid or expired.") from None

    def _read_locked(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schema_name") != _SCHEMA or payload.get("schema_version") not in {"1.0.0", "1.1.0"}:
                raise ValueError()
            entries = payload.get("accounts")
            if not isinstance(entries, list):
                raise ValueError()
            accounts: dict[str, dict[str, Any]] = {}
            for item in entries:
                if not isinstance(item, dict):
                    raise ValueError()
                account_id = _account_id(item.get("account_id"))
                revision = item.get("revision")
                if (not isinstance(revision, int) or isinstance(revision, bool) or revision < 1
                        or account_id in accounts):
                    raise ValueError()
                if 'removed' in item:
                    if (payload['schema_version'] != '1.1.0' or item['removed'] is not True
                            or set(item) != {'account_id', 'revision', 'removed'}):
                        raise ValueError()
                    accounts[account_id] = {'revision': revision, 'removed': True}
                    continue
                blob = item.get("blob")
                if not isinstance(blob, str):
                    raise ValueError()
                decoded = _unprotect(base64.b64decode(blob, validate=True), _ENTROPY)
                cookies = self._normalize(json.loads(decoded), allow_expired=True)
                accounts[account_id] = {"revision": revision, "cookies": cookies}
            return accounts
        except FileNotFoundError:
            return {}
        except Exception:
            raise FlowCookieAccountError("Saved Flow cookie accounts could not be read safely.") from None

    def _write_locked(self, accounts: dict[str, dict[str, Any]]) -> None:
        entries = []
        for account_id, account in sorted(accounts.items()):
            if account.get('removed') is True:
                entries.append({'account_id':account_id,'revision':account['revision'],'removed':True})
                continue
            plain = json.dumps(account["cookies"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            entries.append({
                "account_id": account_id,
                "revision": account["revision"],
                "protection": "WINDOWS_DPAPI_CURRENT_USER",
                "blob": _protect(plain, _ENTROPY),
            })
        atomic_write_json(self.path, {
            "schema_name": _SCHEMA,
            "schema_version": "1.1.0",
            "protection": "WINDOWS_DPAPI_CURRENT_USER",
            "accounts": entries,
        })

    def list_accounts(self) -> list[dict[str, object]]:
        with _file_lock(self.path):
            accounts = self._read_locked()
        return [{"account_id": account_id, "configured": True, "revision": account["revision"]}
                for account_id, account in sorted(accounts.items()) if not account.get('removed')]

    def preview_account(self, account_id: str, raw: Any) -> dict[str, object]:
        account_id = _account_id(account_id)
        cookies = self._normalize(raw)
        with _file_lock(self.path):
            existing = self._read_locked().get(account_id)
        return {
            "account_id": account_id,
            "cookie_count": len(cookies),
            "configured": existing is not None and not existing.get('removed'),
            "replacing": existing is not None and not existing.get('removed'),
            "current_revision": existing["revision"] if existing is not None else None,
        }

    def save_account(self, account_id: str, raw: Any) -> dict[str, object]:
        account_id = _account_id(account_id)
        cookies = self._normalize(raw)
        with _file_lock(self.path):
            accounts = self._read_locked()
            previous = accounts.get(account_id)
            revision = (previous["revision"] + 1) if previous is not None else 1
            accounts[account_id] = {"revision": revision, "cookies": cookies}
            self._write_locked(accounts)
        return {"account_id": account_id, "revision": revision}

    def remove_account(self, account_id: str, *, expected_revision: int) -> dict[str, object]:
        """Remove stored secret, retaining a non-secret monotonic revision tombstone.

        This is local removal, not Google logout or cancellation of in-flight work.
        """
        account_id = _account_id(account_id)
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 1:
            raise FlowCookieAccountError('Flow cookie account revision is invalid.')
        with _file_lock(self.path):
            accounts = self._read_locked()
            account = accounts.get(account_id)
            if account is None or account.get('removed'):
                raise FlowCookieAccountError('Flow cookie account is not configured.')
            if account['revision'] != expected_revision:
                raise FlowCookieAccountError('Flow cookie account changed. Reload Settings before removing it.')
            accounts[account_id] = {'revision':account['revision'] + 1, 'removed':True}
            self._write_locked(accounts)
        return {'account_id':account_id, 'removed':True}

    def get_account(self, account_id: str) -> dict[str, object]:
        account_id = _account_id(account_id)
        with _file_lock(self.path):
            account = self._read_locked().get(account_id)
        if account is None or account.get('removed'):
            raise FlowCookieAccountError("Flow cookie account is not configured.")
        # A saved export may age out between Settings and execution.  Do not
        # return it to a caller, but retain it so an alias-scoped refresh is
        # still possible.
        cookies = self._normalize(account["cookies"])
        # Return a detached value so a caller cannot mutate the next read.
        return {"account_id": account_id, "revision": account["revision"], "cookies": [dict(row) for row in cookies]}

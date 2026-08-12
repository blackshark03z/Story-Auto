"""Story Auto's isolated provider credential boundary.

Environment variables win.  On Windows, an existing YouTube Auto DPAPI pool is
read once and migrated into a separately encrypted Story Auto store; the source
product is never imported, changed, or logged.
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
from pathlib import Path

from story_auto.core.artifacts import atomic_write_json
from story_auto.core.audio.errors import AudioPipelineError

_LEGACY_ENTROPY = b"youtube-auto.credentials.v1"
_OWN_ENTROPY = b"story-auto.credentials.v1"
_POOL = {"elevenlabs": "elevenlabs_api_keys", "typecast": "typecast_api_keys", "gemini": "gemini_api_keys"}
_ENV = {"elevenlabs": "ELEVENLABS_API_KEY", "typecast": "TYPECAST_API_KEY", "gemini": "GEMINI_API_KEY"}


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _store_path(product: str) -> Path:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return local / product / "credentials.v1.json"


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _unprotect(data: bytes, entropy: bytes) -> str:
    if os.name != "nt": raise OSError("Windows DPAPI unavailable")
    input_blob, input_buffer = _blob(data); entropy_blob, entropy_buffer = _blob(entropy); output_blob = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(input_blob), None, ctypes.byref(entropy_blob), None, None, 0, ctypes.byref(output_blob)):
        raise OSError("DPAPI decrypt failed")
    try: return ctypes.string_at(output_blob.pbData, output_blob.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData); _ = (input_buffer, entropy_buffer)


def _protect(value: str, entropy: bytes) -> str:
    if os.name != "nt": raise OSError("Windows DPAPI unavailable")
    input_blob, input_buffer = _blob(value.encode("utf-8")); entropy_blob, entropy_buffer = _blob(entropy); output_blob = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(input_blob), None, ctypes.byref(entropy_blob), None, None, 0, ctypes.byref(output_blob)):
        raise OSError("DPAPI encrypt failed")
    try: return base64.b64encode(ctypes.string_at(output_blob.pbData, output_blob.cbData)).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData); _ = (input_buffer, entropy_buffer)


def _read_pool(path: Path, pool: str, entropy: bytes) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8")); entries = payload.get("pools", {}).get(pool, [])
        values = [_unprotect(base64.b64decode(str(entry["blob"]), validate=True), entropy).strip() for entry in entries]
        return [value for value in values if value]
    except Exception:
        return []


def _write_own_pool(pool: str, values: list[str]) -> None:
    path = _store_path("StoryAuto")
    try: payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception: payload = {"schema_name": "story-auto-credentials", "schema_version": "1.0.0", "protection": "WINDOWS_DPAPI_CURRENT_USER", "pools": {}}
    payload["pools"][pool] = [{"protection": "WINDOWS_DPAPI_CURRENT_USER", "blob": _protect(value, _OWN_ENTROPY)} for value in values]
    atomic_write_json(path, payload)


def provider_keys(provider: str) -> list[str]:
    """Return a key pool without ever exposing a key in an exception or log."""
    if provider not in _POOL: raise ValueError("unsupported provider")
    environment = [value.strip() for value in os.getenv(_ENV[provider], "").split(",") if value.strip()]
    if environment: return environment
    pool = _POOL[provider]
    own = _read_pool(_store_path("StoryAuto"), pool, _OWN_ENTROPY)
    if own: return own
    legacy = _read_pool(_store_path("YouTubeAuto"), pool, _LEGACY_ENTROPY)
    if legacy:
        try: _write_own_pool(pool, legacy)
        except Exception: pass  # In-memory use remains safe if migration cannot persist.
        return legacy
    # This established boundary predates LLM planning.  Keep its sanitized,
    # provider-neutral behavior; provider adapters translate this to their
    # public failure class at their own boundary.
    raise AudioPipelineError("CREDENTIAL_MISSING", provider=provider, stage="credentials")

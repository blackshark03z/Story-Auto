"""Elyum MCP transport shared by bounded Goal 54 research and gated production code.

The provider contract is task based:

- `elyum_upload` imports local/public reference media and is documented free;
- `elyum_estimate` quotes held Credits without generation;
- `elyum_make_video` creates one job and accepts an idempotent `clientRef`;
- `elyum_wait`/`elyum_job_status` observe the same durable `jobId`;
- `elyum_keep` is the only action documented to spend Credits;
- `elyum_kill` releases a hold and consumes kill allowance.

No browser/session automation exists in this boundary.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path

from story_auto.providers.credentials import provider_keys
from typing import Any, Protocol
import urllib.error
import urllib.request
from urllib.parse import urljoin


DEFAULT_ENDPOINT = "https://elyum.ai/mcp"
DEFAULT_FAST_I2V_MODEL = "seedance-2-fast-i2v"
DEFAULT_REFERENCE_MODEL = "seedance-2.5-reference"
PROTOCOL_VERSION = "2025-06-18"
VIDEO_MODES = frozenset({"ugc", "i2v", "t2v", "clone", "captions", "edit", "extend"})
SUPPORTED_RESOLUTIONS = frozenset({"480p", "720p", "1080p"})


class ElyumSeedanceError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "", *, dispatch_state: str = "NOT_DISPATCHED") -> None:
        self.failure_class = failure_class
        self.detail = detail
        self.dispatch_state = dispatch_state
        super().__init__(failure_class + (f": {detail}" if detail else ""))


class ToolSession(Protocol):
    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any: ...


def _decode_rpc(body: bytes, content_type: str) -> dict[str, Any] | None:
    if not body:
        return None
    text = body.decode("utf-8", errors="replace")
    if "text/event-stream" in (content_type or "").lower():
        payloads: list[dict[str, Any]] = []
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                payloads.append(value)
        return payloads[-1] if payloads else None
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise ElyumSeedanceError("MCP_RESPONSE_INVALID") from error
    return value if isinstance(value, dict) else None


def _extract_tool_payload(result: dict[str, Any]) -> Any:
    structured = result.get("structuredContent")
    if structured is not None:
        return structured
    content = result.get("content")
    if isinstance(content, list):
        texts = [item.get("text") for item in content
                 if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)]
        for text in texts:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
        if texts:
            return {"message": texts[0][:400]}
    return {}


class McpToolSession:
    def __init__(self, endpoint: str, key: str, *, timeout: float = 30.0) -> None:
        self.endpoint = endpoint
        self.key = key
        self.timeout = timeout
        self.session_id: str | None = None
        self._next_id = 1
        self._initialized = False

    def _post(self, message: dict[str, Any]) -> dict[str, Any] | None:
        headers = {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "User-Agent": "StoryAuto-ElyumGoal54/1",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(message, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                session = response.headers.get("Mcp-Session-Id")
                if session:
                    self.session_id = session
                return _decode_rpc(response.read(), response.headers.get("Content-Type", ""))
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                failure = "CREDENTIAL_OR_ACCESS_DENIED"
            elif error.code == 429:
                failure = "RATE_LIMITED"
            elif error.code in {400, 404, 409, 422}:
                failure = "CAPABILITY_OR_REQUEST_INVALID"
            elif error.code in {408, 425} or error.code >= 500:
                failure = "PROVIDER_TRANSIENT"
            else:
                failure = "PROVIDER_REQUEST_FAILED"
            raise ElyumSeedanceError(failure) from error
        except ElyumSeedanceError:
            raise
        except (TimeoutError, urllib.error.URLError, OSError) as error:
            raise ElyumSeedanceError("PROVIDER_TRANSIENT", type(error).__name__) from error

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        value = self._post({"jsonrpc": "2.0", "id": request_id, "method": method,
                            **({"params": params} if params is not None else {})})
        if not isinstance(value, dict):
            raise ElyumSeedanceError("MCP_RESPONSE_MISSING")
        if value.get("id") not in {request_id, str(request_id)}:
            raise ElyumSeedanceError("MCP_RESPONSE_ID_MISMATCH")
        provider_error = value.get("error")
        if isinstance(provider_error, dict):
            code = provider_error.get("code")
            raise ElyumSeedanceError(f"MCP_ERROR_{code}")
        result = value.get("result")
        if not isinstance(result, dict):
            raise ElyumSeedanceError("MCP_RESULT_INVALID")
        return result

    def _notify(self, method: str) -> None:
        self._post({"jsonrpc": "2.0", "method": method})

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "story-auto-elyum-goal54", "version": "1.0"},
        })
        self._notify("notifications/initialized")
        self._initialized = True

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self._ensure_initialized()
        result = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        return _extract_tool_payload(result)


def _api_key() -> str:
    environment = os.getenv("ELYUM_API_KEY", "").strip()
    if environment:
        return environment
    try:
        values = provider_keys("elyum")
    except Exception:
        return ""
    return values[0].strip() if values else ""


def _find_first(node: Any, keys: set[str]) -> Any:
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in keys and value not in (None, ""):
                return value
        for value in node.values():
            found = _find_first(value, keys)
            if found not in (None, ""):
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_first(value, keys)
            if found not in (None, ""):
                return found
    return None


def _collect_urls(node: Any, *, key_hints: tuple[str, ...] = ()) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            lower = str(key).lower()
            if isinstance(value, str) and (value.startswith("https://") or value.startswith("/media")):
                if not key_hints or any(hint in lower for hint in key_hints):
                    found.append(value)
            else:
                found.extend(_collect_urls(value, key_hints=key_hints))
    elif isinstance(node, list):
        for value in node:
            found.extend(_collect_urls(value, key_hints=key_hints))
    return list(dict.fromkeys(found))


class ElyumSeedanceClient:
    provider = "elyum_seedance"

    def __init__(self, *, key: str | None = None, endpoint: str | None = None,
                 session: ToolSession | None = None, timeout: float = 30.0) -> None:
        self.key = (key if key is not None else _api_key()).strip()
        self.endpoint = (endpoint or os.getenv("ELYUM_MCP_ENDPOINT") or DEFAULT_ENDPOINT).strip()
        self.timeout = timeout
        self.session = session if session is not None else (McpToolSession(self.endpoint, self.key, timeout=timeout) if self.key else None)

    def readiness(self) -> dict[str, Any]:
        return {
            "status": "READY" if self.session is not None else "NOT_CONFIGURED",
            "provider": "Elyum",
            "provider_id": self.provider,
            "transport": "MCP_STREAMABLE_HTTP",
            "browser_required": False,
            "reason_code": None if self.session is not None else "CREDENTIAL_MISSING",
        }

    def _call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if self.session is None:
            raise ElyumSeedanceError("CREDENTIAL_MISSING")
        return self.session.call_tool(name, arguments or {})

    def account_balance(self) -> int:
        payload = self._call("elyum_account", {})
        balance = _find_first(payload, {"balance", "credits", "creditbalance", "credit_balance"})
        if isinstance(balance, bool) or not isinstance(balance, (int, float)):
            raise ElyumSeedanceError("ACCOUNT_BALANCE_INVALID")
        return int(balance)

    def model_catalog(self) -> Any:
        """Read the provider model catalog without creating or spending anything."""
        return self._call("elyum_models", {})

    def seedance_model_ids(self) -> list[str]:
        """Extract candidate Seedance model ids/slugs from Elyum's live catalog."""
        payload = self.model_catalog()
        found: list[str] = []

        def add(value: Any) -> None:
            if not isinstance(value, str):
                return
            candidate = value.strip()
            if candidate and "seedance" in candidate.lower() and candidate not in found:
                found.append(candidate)

        def visit(node: Any) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    lower = str(key).lower()
                    if lower in {"id", "slug", "model", "modelid", "model_id"}:
                        add(value)
                    if isinstance(key, str) and "seedance" in key.lower() and isinstance(value, (dict, list)):
                        add(key)
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)
            elif isinstance(node, str) and ("-" in node or "_" in node):
                add(node)

        visit(payload)
        return found

    def estimate_video(self, *, model: str, duration: int, mode: str, resolution: str | None = None) -> int:
        if mode not in {"t2v", "i2v", "ugc", "clone"}:
            raise ElyumSeedanceError("MODE_UNSUPPORTED", mode)
        if not 2 <= int(duration) <= 30:
            raise ElyumSeedanceError("DURATION_UNSUPPORTED", str(duration))
        arguments: dict[str, Any] = {"kind": "video", "mode": mode, "model": model, "duration": int(duration)}
        if resolution is not None:
            if resolution not in SUPPORTED_RESOLUTIONS:
                raise ElyumSeedanceError("RESOLUTION_UNSUPPORTED", resolution)
            arguments["resolution"] = resolution
        payload = self._call("elyum_estimate", arguments)
        credits = _find_first(payload, {"credits", "credit", "cost", "heldcredits", "held_credits"})
        if isinstance(credits, bool) or not isinstance(credits, (int, float)):
            raise ElyumSeedanceError("ESTIMATE_INVALID")
        return int(credits)

    def upload_file(self, path: Path | str) -> str:
        source = Path(path)
        if not source.is_file():
            raise ElyumSeedanceError("REFERENCE_FILE_MISSING")
        payload = source.read_bytes()
        if not payload:
            raise ElyumSeedanceError("REFERENCE_FILE_EMPTY")
        if len(payload) > 60 * 1024 * 1024:
            raise ElyumSeedanceError("REFERENCE_FILE_TOO_LARGE")
        mime, _encoding = mimetypes.guess_type(source.name)
        if mime not in {"image/png", "image/jpeg", "image/webp", "video/mp4", "video/quicktime", "video/webm"}:
            raise ElyumSeedanceError("REFERENCE_MIME_UNSUPPORTED", str(mime or ""))
        result = self._call("elyum_upload", {
            "base64": base64.b64encode(payload).decode("ascii"),
            "filename": source.name,
            "mimeType": mime,
        })
        urls = _collect_urls(result)
        if not urls:
            raise ElyumSeedanceError("UPLOAD_URL_MISSING")
        url = urls[0]
        return urljoin(self.endpoint, url)

    def make_video(self, *, client_ref: str, model: str, prompt: str, duration: int = 4,
                   mode: str = "i2v", aspect_ratio: str = "16:9", resolution: str = "480p",
                   image_url: str | None = None, image_urls: list[str] | None = None,
                   audio: bool = False) -> tuple[str, Any]:
        client_ref = str(client_ref or "").strip()
        prompt = str(prompt or "").strip()
        if not client_ref or len(client_ref) > 120:
            raise ElyumSeedanceError("CLIENT_REF_INVALID")
        if not prompt:
            raise ElyumSeedanceError("PROMPT_INVALID")
        if mode not in VIDEO_MODES:
            raise ElyumSeedanceError("MODE_UNSUPPORTED", mode)
        if not 2 <= int(duration) <= 30:
            raise ElyumSeedanceError("DURATION_UNSUPPORTED", str(duration))
        if resolution not in SUPPORTED_RESOLUTIONS:
            raise ElyumSeedanceError("RESOLUTION_UNSUPPORTED", resolution)
        references = [str(url).strip() for url in (image_urls or []) if str(url).strip()]
        if mode == "i2v" and not (image_url or references):
            raise ElyumSeedanceError("REFERENCE_REQUIRED")
        arguments: dict[str, Any] = {
            "clientRef": client_ref,
            "mode": mode,
            "model": model,
            "prompt": prompt,
            "duration": int(duration),
            "aspectRatio": aspect_ratio,
            "resolution": resolution,
            "audio": bool(audio),
        }
        if image_url:
            arguments["imageUrl"] = str(image_url)
        if references:
            if len(references) > 6:
                raise ElyumSeedanceError("TOO_MANY_REFERENCES")
            arguments["imageUrls"] = references
        try:
            result = self._call("elyum_make_video", arguments)
        except ElyumSeedanceError as error:
            if error.failure_class in {"PROVIDER_TRANSIENT", "RATE_LIMITED"}:
                raise ElyumSeedanceError("IDEMPOTENT_REPLAY_REQUIRED", error.failure_class,
                                         dispatch_state="RECONCILE_BY_CLIENT_REF") from error
            raise
        job_id = _find_first(result, {"jobid", "job_id"})
        if not isinstance(job_id, str) or not job_id.strip():
            raise ElyumSeedanceError("PROVIDER_JOB_ID_MISSING", dispatch_state="RECONCILE_BY_CLIENT_REF")
        return job_id.strip(), result

    def wait(self, job_id: str, *, timeout_seconds: int = 50, thumbnails: bool = True) -> Any:
        if not str(job_id or "").strip():
            raise ElyumSeedanceError("PROVIDER_JOB_ID_INVALID")
        timeout_seconds = max(0, min(55, int(timeout_seconds)))
        return self._call("elyum_wait", {"jobId": str(job_id), "timeoutSeconds": timeout_seconds,
                                         "thumbnails": bool(thumbnails)})

    def job_status(self, job_id: str, *, thumbnails: bool = True) -> Any:
        if not str(job_id or "").strip():
            raise ElyumSeedanceError("PROVIDER_JOB_ID_INVALID")
        return self._call("elyum_job_status", {"jobId": str(job_id), "thumbnails": bool(thumbnails)})

    @staticmethod
    def gen_id(result: Any) -> str | None:
        value = _find_first(result, {"genid", "gen_id"})
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def execution_state(result: Any) -> str | None:
        value = _find_first(result, {"status", "state"})
        return str(value).strip().lower() if value not in (None, "") else None

    @staticmethod
    def preview_urls(result: Any) -> list[str]:
        # Elyum locked-preview runtime currently returns the preview as generic `url`.
        # This method is only used on pre-keep observation results, where that URL is
        # the locked preview rather than the unlocked/original asset.
        return _collect_urls(result, key_hints=("thumb", "poster", "preview", "url"))

    @staticmethod
    def unlock_credits(result: Any) -> int | None:
        value = _find_first(result, {"unlockcredits", "unlock_credits"})
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(value)

    @staticmethod
    def downloadable_urls(result: Any) -> list[str]:
        return _collect_urls(result, key_hints=("url", "download", "file", "video"))

    def keep(self, gen_id: str, *, index: int = 0) -> Any:
        if not str(gen_id or "").strip():
            raise ElyumSeedanceError("GEN_ID_INVALID")
        return self._call("elyum_keep", {"genId": str(gen_id), "index": int(index)})

    def kill(self, gen_id: str, *, index: int = 0, reason: str | None = None) -> Any:
        if not str(gen_id or "").strip():
            raise ElyumSeedanceError("GEN_ID_INVALID")
        arguments: dict[str, Any] = {"genId": str(gen_id), "index": int(index)}
        if reason:
            arguments["reason"] = reason
        return self._call("elyum_kill", arguments)

"""Stable API-first BytePlus Seedance 2.5 client.

Only the documented asynchronous task API is used. Browser/session state is not
part of this provider boundary. A POST network failure is treated as ambiguous
because the provider may have accepted the task even when no response reached
Story Auto.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Callable
import urllib.error
import urllib.request
from urllib.parse import urlparse

from story_auto.core.resources import ensure_free_space
from story_auto.providers.credentials import provider_keys
from story_auto.providers.flow.validation import validate_video


DEFAULT_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3"
DEFAULT_MODEL = "dreamina-seedance-2-5-260628"
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "expired", "cancelled"})
NONTERMINAL_STATUSES = frozenset({"queued", "running"})
SUPPORTED_RESOLUTIONS = frozenset({"480p", "720p"})


class BytePlusSeedanceError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "", *, dispatch_state: str = "NOT_DISPATCHED") -> None:
        self.failure_class = failure_class
        self.detail = detail
        self.dispatch_state = dispatch_state
        super().__init__(failure_class + (f": {detail}" if detail else ""))


Transport = Callable[[str, str, dict[str, Any] | None, str, float], tuple[dict[str, Any], int]]
BinaryTransport = Callable[[str, float], bytes]


def _classify_http(status: int) -> str:
    if status in {401, 403}:
        return "CREDENTIAL_OR_ACCESS_DENIED"
    if status == 429:
        return "RATE_LIMITED"
    if status in {400, 404, 409, 422}:
        return "CAPABILITY_OR_REQUEST_INVALID"
    if status in {408, 425} or status >= 500:
        return "PROVIDER_TRANSIENT"
    return "PROVIDER_REQUEST_FAILED"


def _safe_detail(error: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8"))
        if isinstance(payload, dict):
            provider_error = payload.get("error") if isinstance(payload.get("error"), dict) else payload
            value = provider_error.get("message") or provider_error.get("code") or provider_error.get("type")
            return str(value or "")[:240]
    except Exception:
        pass
    return ""


def _default_transport(url: str, method: str, body: dict[str, Any] | None, key: str,
                       timeout: float) -> tuple[dict[str, Any], int]:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            if not isinstance(payload, dict):
                raise BytePlusSeedanceError("PROVIDER_RESPONSE_INVALID")
            return payload, int(response.status)
    except urllib.error.HTTPError as error:
        failure = _classify_http(error.code)
        dispatch_state = "AMBIGUOUS" if method == "POST" and failure == "PROVIDER_TRANSIENT" else "NOT_DISPATCHED"
        if dispatch_state == "AMBIGUOUS":
            failure = "AMBIGUOUS_POST_DISPATCH"
        raise BytePlusSeedanceError(failure, _safe_detail(error), dispatch_state=dispatch_state) from error
    except BytePlusSeedanceError:
        raise
    except (TimeoutError, urllib.error.URLError, OSError) as error:
        if method == "POST":
            raise BytePlusSeedanceError("AMBIGUOUS_POST_DISPATCH", type(error).__name__, dispatch_state="AMBIGUOUS") from error
        raise BytePlusSeedanceError("PROVIDER_TRANSIENT", type(error).__name__) from error


def _default_binary(url: str, timeout: float) -> bytes:
    if not isinstance(url, str) or not url.startswith("https://"):
        raise BytePlusSeedanceError("ASSET_URL_INVALID", dispatch_state="CONFIRMED")
    host = (urlparse(url).hostname or "").lower()
    if not any(host == suffix or host.endswith("." + suffix) for suffix in ("volces.com", "bytepluses.com", "byteplus.com")):
        raise BytePlusSeedanceError("ASSET_HOST_NOT_ALLOWED", dispatch_state="CONFIRMED")
    request = urllib.request.Request(url, headers={"User-Agent": "StoryAuto/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        raise BytePlusSeedanceError(_classify_http(error.code), dispatch_state="CONFIRMED") from error
    except (TimeoutError, urllib.error.URLError, OSError) as error:
        raise BytePlusSeedanceError("ASSET_ACQUISITION_FAILED", type(error).__name__, dispatch_state="CONFIRMED") from error


def _api_key() -> str:
    for name in ("BYTEPLUS_MODELARK_API_KEY", "BYTEPLUS_API_KEY", "ARK_API_KEY"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    try:
        values = provider_keys("byteplus_modelark")
    except Exception:
        values = []
    return values[0] if values else ""


class BytePlusSeedanceClient:
    provider = "byteplus_seedance"

    def __init__(self, *, key: str | None = None, base_url: str | None = None,
                 model: str | None = None, transport: Transport = _default_transport,
                 binary_transport: BinaryTransport = _default_binary,
                 timeout: float = 60.0, asset_timeout: float = 300.0) -> None:
        self.key = (key if key is not None else _api_key()).strip()
        self.base_url = (base_url or os.getenv("BYTEPLUS_MODELARK_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.model = (model or os.getenv("BYTEPLUS_SEEDANCE_MODEL") or DEFAULT_MODEL).strip()
        self.transport = transport
        self.binary_transport = binary_transport
        self.timeout = timeout
        self.asset_timeout = asset_timeout

    def readiness(self) -> dict[str, Any]:
        return {
            "status": "READY" if self.key else "NOT_CONFIGURED",
            "provider": "BytePlus ModelArk",
            "provider_id": self.provider,
            "model": self.model,
            "transport": "REST_ASYNC_TASK",
            "browser_required": False,
            "reason_code": None if self.key else "CREDENTIAL_MISSING",
        }

    def _request(self, path: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.key:
            raise BytePlusSeedanceError("CREDENTIAL_MISSING")
        payload, _status = self.transport(
            self.base_url + "/" + path.lstrip("/"), method, body, self.key, self.timeout)
        return payload

    def create_task(self, *, prompt: str, duration: float, aspect_ratio: str = "16:9",
                    resolution: str = "720p") -> str:
        prompt = str(prompt or "").strip()
        if not prompt:
            raise BytePlusSeedanceError("PROMPT_INVALID")
        seconds = int(math.ceil(float(duration)))
        if seconds < 4 or seconds > 30:
            raise BytePlusSeedanceError("DURATION_UNSUPPORTED", str(seconds))
        if resolution not in SUPPORTED_RESOLUTIONS:
            raise BytePlusSeedanceError("RESOLUTION_UNSUPPORTED", resolution)
        payload = self._request("contents/generations/tasks", method="POST", body={
            "model": self.model,
            "content": [{"type": "text", "text": prompt}],
            "ratio": aspect_ratio,
            "resolution": resolution,
            "duration": seconds,
            "generate_audio": False,
            "watermark": False,
        })
        task_id = payload.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise BytePlusSeedanceError("PROVIDER_TASK_ID_MISSING", dispatch_state="AMBIGUOUS")
        return task_id.strip()

    def list_tasks(self, *, page_size: int = 1) -> dict[str, Any]:
        if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 100:
            raise BytePlusSeedanceError("PAGE_SIZE_INVALID")
        payload = self._request(f"contents/generations/tasks?page_num=1&page_size={page_size}")
        if not isinstance(payload.get("items", []), list):
            raise BytePlusSeedanceError("PROVIDER_RESPONSE_INVALID")
        return payload

    def get_task(self, task_id: str) -> dict[str, Any]:
        task_id = str(task_id or "").strip()
        if not task_id or "/" in task_id or chr(92) in task_id:
            raise BytePlusSeedanceError("PROVIDER_TASK_ID_INVALID")
        payload = self._request(f"contents/generations/tasks/{task_id}")
        status = str(payload.get("status") or "").lower()
        if status not in TERMINAL_STATUSES | NONTERMINAL_STATUSES:
            raise BytePlusSeedanceError("PROVIDER_TASK_STATE_UNKNOWN", status, dispatch_state="CONFIRMED")
        return payload

    @staticmethod
    def video_url(task: dict[str, Any]) -> str:
        content = task.get("content") if isinstance(task, dict) else None
        url = content.get("video_url") if isinstance(content, dict) else None
        if not isinstance(url, str) or not url.startswith("https://"):
            raise BytePlusSeedanceError("PROVIDER_RESULT_MISSING", dispatch_state="CONFIRMED")
        return url

    def acquire_video(self, task: dict[str, Any], destination: Path) -> dict[str, Any]:
        url = self.video_url(task)
        payload = self.binary_transport(url, self.asset_timeout)
        if not payload:
            raise BytePlusSeedanceError("ASSET_ACQUISITION_FAILED", dispatch_state="CONFIRMED")
        ensure_free_space(destination.parent, minimum_free_bytes=max(256 * 1024 * 1024, len(payload) * 2))
        destination.parent.mkdir(parents=True, exist_ok=True)
        candidate = destination.with_name(destination.stem + ".candidate" + destination.suffix)
        try:
            candidate.write_bytes(payload)
            validate_video(candidate)
            os.replace(candidate, destination)
            return validate_video(destination) | {"download_bytes": len(payload)}
        finally:
            if candidate.exists():
                candidate.unlink()

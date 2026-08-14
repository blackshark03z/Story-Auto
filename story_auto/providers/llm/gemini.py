"""The sole Story Auto Gemini API boundary.

Planning code supplies prompt semantics and schemas; this module owns HTTP,
credentials, retry, and safe provider diagnostics.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from story_auto.core.retry import retry
from story_auto.providers.credentials import provider_keys


class GeminiProviderError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(f"gemini:planning:{failure_class}" + (f" ({detail})" if detail else ""))


@dataclass(frozen=True)
class LLMRequest:
    model: str
    prompt: str
    response_schema: dict[str, Any]
    settings: dict[str, Any]
    request_id: str
    stage: str
    media: tuple["LLMMedia", ...] = ()


@dataclass(frozen=True)
class LLMMedia:
    data: bytes
    mime_type: str
    label: str = "media"


@dataclass(frozen=True)
class LLMResponse:
    value: dict[str, Any]
    model: str
    request_id: str
    attempts: int
    latency_ms: int
    usage: dict[str, Any]


def _failure_for_status(status: int) -> str:
    return {400: "GEMINI_INVALID_REQUEST", 401: "GEMINI_CREDENTIAL_MISSING", 403: "GEMINI_MODEL_UNAVAILABLE", 404: "GEMINI_MODEL_UNAVAILABLE", 408: "GEMINI_TIMEOUT", 429: "GEMINI_RATE_LIMIT", 500: "GEMINI_PROVIDER_ERROR", 502: "GEMINI_PROVIDER_ERROR", 503: "GEMINI_PROVIDER_ERROR", 504: "GEMINI_TIMEOUT"}.get(status, "GEMINI_PROVIDER_ERROR")


class GeminiProvider:
    name = "gemini"
    api_base = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, transport: Callable[[str, dict[str, Any], str, float], dict[str, Any]] | None = None,
                 keys: list[str] | None = None) -> None:
        self.transport = transport or self._request
        self.keys = list(keys) if keys is not None else None

    def _request(self, url: str, body: dict[str, Any], key: str, timeout: float) -> dict[str, Any]:
        request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = ""
            try:
                payload = json.loads(error.read(4096).decode("utf-8", errors="replace"))
                detail = str(payload.get("error", {}).get("message", ""))
            except Exception:
                pass
            # Provider diagnostics may be useful for fixing a malformed
            # request, but must never expose credential-like tokens.
            detail = re.sub(r"[A-Za-z0-9_-]{24,}", "<redacted-token>", detail)[:240]
            failure = _failure_for_status(error.code)
            if "api key not valid" in detail.lower() or "invalid api key" in detail.lower():
                failure = "GEMINI_CREDENTIAL_MISSING"
            raise GeminiProviderError(failure, detail) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
            raise GeminiProviderError("GEMINI_TIMEOUT") from error
        if not isinstance(value, dict):
            raise GeminiProviderError("GEMINI_PROVIDER_ERROR")
        return value

    def _key(self) -> str:
        try:
            return provider_keys(self.name)[0]
        except Exception as error:
            raise GeminiProviderError("GEMINI_CREDENTIAL_MISSING") from error

    def generate_structured(self, request: LLMRequest) -> LLMResponse:
        if not request.model.strip():
            raise GeminiProviderError("GEMINI_MODEL_UNAVAILABLE")
        timeout = float(request.settings.get("timeout_seconds", 60))
        attempts_limit = int(request.settings.get("max_attempts", 2))
        if timeout <= 0 or attempts_limit < 1:
            raise ValueError("invalid Gemini request settings")
        parts: list[dict[str, Any]] = [{"text": request.prompt}]
        for media in request.media:
            parts.append({"text": f"Ordered evidence: {media.label}"})
            parts.append({"inlineData": {"mimeType": media.mime_type,
                                         "data": base64.b64encode(media.data).decode("ascii")}})
        body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": {"responseMimeType": "application/json", "responseSchema": request.response_schema}}
        for key in ("temperature", "maxOutputTokens", "topP"):
            if key in request.settings:
                body["generationConfig"][key] = request.settings[key]
        attempts = 0
        started = time.monotonic()
        keys = self.keys if self.keys is not None else provider_keys(self.name)
        if not keys:
            raise GeminiProviderError("GEMINI_CREDENTIAL_MISSING")
        key_index = 0
        def call() -> tuple[dict[str, Any], dict[str, Any]]:
            nonlocal attempts
            nonlocal key_index
            attempts += 1
            try:
                payload = self.transport(f"{self.api_base}/models/{urllib.parse.quote(request.model, safe='')}:generateContent", body, keys[key_index], timeout)
                finish = str(payload.get("candidates", [{}])[0].get("finishReason", "")) if isinstance(payload.get("candidates"), list) else ""
                if finish in {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"}:
                    raise GeminiProviderError("GEMINI_SAFETY_REFUSAL")
                try:
                    text = payload["candidates"][0]["content"]["parts"][0]["text"]
                    value = json.loads(text)
                except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
                    raise GeminiProviderError("GEMINI_STRUCTURED_OUTPUT_INVALID") from error
                if not isinstance(value, dict):
                    raise GeminiProviderError("GEMINI_STRUCTURED_OUTPUT_INVALID")
                return payload, value
            except GeminiProviderError as error:
                if error.failure_class in {"GEMINI_RATE_LIMIT", "GEMINI_STRUCTURED_OUTPUT_INVALID"} and key_index + 1 < len(keys):
                    key_index += 1
                raise
        payload, value = retry(call, attempts=attempts_limit, retryable=lambda e: isinstance(e, GeminiProviderError) and e.failure_class in {"GEMINI_RATE_LIMIT", "GEMINI_STRUCTURED_OUTPUT_INVALID", "GEMINI_TIMEOUT", "GEMINI_PROVIDER_ERROR"})
        usage = payload.get("usageMetadata") if isinstance(payload.get("usageMetadata"), dict) else {}
        return LLMResponse(value, request.model, request.request_id, attempts, round((time.monotonic() - started) * 1000), usage)

    def capability_probe(self, model: str, *, live: bool = False) -> dict[str, Any]:
        """Verify credentials/configuration without a normal-run smoke call."""
        self._key()
        result = {"provider": self.name, "model": model, "credential": "AVAILABLE", "structured_output": "SUPPORTED"}
        if live:
            # Current reasoning models may consume a few hundred internal
            # thought tokens even for a tiny structured probe.
            response = self.generate_structured(LLMRequest(model, "Return exactly an object with ok true.", {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}, {"max_attempts": 1, "timeout_seconds": 60, "maxOutputTokens": 512, "temperature": 0}, "capability_smoke", "capability"))
            if response.value.get("ok") is not True:
                raise GeminiProviderError("GEMINI_STRUCTURED_OUTPUT_INVALID")
            result["smoke"] = "PASS"
        return result

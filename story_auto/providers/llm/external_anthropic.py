"""Configurable Anthropic Messages-compatible LLM gateway boundary.

The configured model is a gateway alias, not proof of upstream model identity.
Secrets come only from Story Auto's DPAPI/environment credential boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from story_auto.providers.credentials import provider_keys
from .gemini import LLMMedia, LLMRequest, LLMResponse
from .router import ReasoningResult, RouterError, _validate


class ExternalLLMError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(failure_class + (f": {detail}" if detail else ""))


def normalize_base_url(value: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ExternalLLMError("EXTERNAL_LLM_BASE_URL_INVALID")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ExternalLLMError("EXTERNAL_LLM_HTTPS_REQUIRED")
    path = parsed.path.rstrip("/")
    if any(part in {".", ".."} for part in path.split("/") if part):
        raise ExternalLLMError("EXTERNAL_LLM_BASE_URL_PATH_UNSUPPORTED")
    root = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
    return root.rstrip("/")


def _messages_url(base_url: str) -> str:
    base = normalize_base_url(base_url)
    return base + ("/messages" if base.endswith("/v1") else "/v1/messages")


def _failure(status: int) -> str:
    return {400:"EXTERNAL_LLM_INVALID_REQUEST",401:"EXTERNAL_LLM_CREDENTIAL_MISSING",403:"EXTERNAL_LLM_CREDENTIAL_MISSING",404:"EXTERNAL_LLM_MODEL_UNAVAILABLE",408:"EXTERNAL_LLM_TIMEOUT",429:"EXTERNAL_LLM_RATE_LIMIT",500:"EXTERNAL_LLM_PROVIDER_ERROR",502:"EXTERNAL_LLM_PROVIDER_ERROR",503:"EXTERNAL_LLM_PROVIDER_ERROR",504:"EXTERNAL_LLM_TIMEOUT"}.get(status,"EXTERNAL_LLM_PROVIDER_ERROR")


def _json_text(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, flags=re.IGNORECASE | re.DOTALL)
    if fence:
        value = fence.group(1).strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise ExternalLLMError("EXTERNAL_LLM_STRUCTURED_OUTPUT_INVALID") from error
    if not isinstance(parsed, dict):
        raise ExternalLLMError("EXTERNAL_LLM_STRUCTURED_OUTPUT_INVALID")
    return parsed


class AnthropicCompatibleProvider:
    name = "external_anthropic"

    def __init__(self, *, base_url: str, model_alias: str, auth_mode: str = "x-api-key",
                 transport: Callable[[str, dict[str, Any], str, float], dict[str, Any]] | None = None,
                 keys: list[str] | None = None) -> None:
        self.base_url = normalize_base_url(base_url)
        self.model_alias = str(model_alias or "").strip()
        if not self.model_alias:
            raise ExternalLLMError("EXTERNAL_LLM_MODEL_ALIAS_REQUIRED")
        mode = str(auth_mode or "x-api-key").strip().lower()
        if mode == "x_api_key":
            mode = "x-api-key"
        self.auth_mode = mode
        if self.auth_mode not in {"x-api-key", "bearer"}:
            raise ExternalLLMError("EXTERNAL_LLM_AUTH_MODE_INVALID")
        self.transport = transport or self._request
        self.keys = list(keys) if keys is not None else None

    def _request(self, url: str, body: dict[str, Any], key: str, timeout: float) -> dict[str, Any]:
        headers = {"Content-Type":"application/json", "anthropic-version":"2023-06-01"}
        if self.auth_mode == "bearer":
            headers["Authorization"] = f"Bearer {key}"
        else:
            headers["x-api-key"] = key
        request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = ""
            try:
                payload = json.loads(error.read(4096).decode("utf-8", errors="replace"))
                detail = str(payload.get("error", {}).get("message", ""))
            except Exception:
                pass
            detail = re.sub(r"[A-Za-z0-9_-]{24,}", "<redacted-token>", detail)[:240]
            raise ExternalLLMError(_failure(error.code), detail) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
            raise ExternalLLMError("EXTERNAL_LLM_TIMEOUT") from error
        if not isinstance(payload, dict):
            raise ExternalLLMError("EXTERNAL_LLM_PROVIDER_ERROR")
        return payload

    def _keys(self) -> list[str]:
        if self.keys is not None:
            return self.keys
        try:
            return provider_keys("external_llm")
        except Exception as error:
            raise ExternalLLMError("EXTERNAL_LLM_CREDENTIAL_MISSING") from error

    def generate_structured(self, request: LLMRequest) -> LLMResponse:
        timeout = float(request.settings.get("timeout_seconds", 120))
        attempts_limit = max(1, int(request.settings.get("max_attempts", 2)))
        content: list[dict[str, Any]] = [{"type":"text","text":request.prompt + "\nReturn ONLY a JSON object matching this JSON Schema:\n" + json.dumps(request.response_schema, ensure_ascii=False, separators=(",", ":"))}]
        for media in request.media:
            if not media.mime_type.startswith("image/"):
                raise ExternalLLMError("EXTERNAL_LLM_MEDIA_UNSUPPORTED", media.mime_type)
            content.append({"type":"image","source":{"type":"base64","media_type":media.mime_type,"data":base64.b64encode(media.data).decode("ascii")}})
        body = {"model":self.model_alias,"max_tokens":int(request.settings.get("maxOutputTokens",4096)),"messages":[{"role":"user","content":content}]}
        keys = self._keys()
        if not keys:
            raise ExternalLLMError("EXTERNAL_LLM_CREDENTIAL_MISSING")
        started = time.monotonic(); attempts = 0; last_error: ExternalLLMError | None = None
        for key in keys:
            if attempts >= attempts_limit:
                break
            attempts += 1
            try:
                payload = self.transport(_messages_url(self.base_url), body, key, timeout)
                blocks = payload.get("content")
                text = "\n".join(str(item.get("text", "")) for item in blocks if isinstance(item, dict) and item.get("type") == "text") if isinstance(blocks, list) else ""
                value = _json_text(text)
                usage = dict(payload.get("usage") or {}) if isinstance(payload.get("usage"), dict) else {}
                usage.update({"provider":"external_anthropic","configured_model_alias":self.model_alias,"gateway_reported_model":payload.get("model")})
                return LLMResponse(value, self.model_alias, request.request_id, attempts, round((time.monotonic()-started)*1000), usage)
            except ExternalLLMError as error:
                last_error = error
                if error.failure_class not in {"EXTERNAL_LLM_RATE_LIMIT","EXTERNAL_LLM_CREDENTIAL_MISSING","EXTERNAL_LLM_TIMEOUT","EXTERNAL_LLM_PROVIDER_ERROR","EXTERNAL_LLM_STRUCTURED_OUTPUT_INVALID"}:
                    raise
        raise last_error or ExternalLLMError("EXTERNAL_LLM_ROUTING_EXHAUSTED")

    def reason(self, *, task: str, prompt: str, schema: dict[str, Any], tier: str,
               media: tuple[LLMMedia, ...] = (), prompt_version: str, schema_version: str,
               qc_policy_version: str = "NONE", confidence_field: str | None = None,
               settings: dict[str, Any] | None = None, acceptance_validator=None,
               acceptance_max_rejections: int | None = None) -> ReasoningResult:
        identity = {"provider":self.name,"base_url":self.base_url,"model_alias":self.model_alias,"auth_mode":self.auth_mode,"task":task,"prompt":prompt,"schema":schema,"tier":tier,"prompt_version":prompt_version,"schema_version":schema_version,"qc_policy_version":qc_policy_version}
        input_hash = hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()
        max_semantic = max(1, int(acceptance_max_rejections or 1)); corrective = ""; total_attempts = 0
        for semantic_attempt in range(max_semantic):
            response = self.generate_structured(LLMRequest(self.model_alias, prompt + ("\nCorrective feedback:\n" + corrective if corrective else ""), schema, settings or {"max_attempts":2}, input_hash[:24], task, media))
            total_attempts += response.attempts
            try:
                _validate(response.value, schema)
                if acceptance_validator is not None:
                    acceptance_validator(response.value)
                return ReasoningResult(response.value, self.model_alias, "external-key-pool", "external-gateway", False, semantic_attempt, total_attempts, input_hash)
            except Exception as error:
                failure_class = getattr(error, "failure_class", None)
                if semantic_attempt + 1 >= max_semantic or not failure_class:
                    if isinstance(error, RouterError):
                        raise
                    raise ExternalLLMError(str(failure_class or "EXTERNAL_LLM_ACCEPTANCE_REJECTED"), str(error)) from error
                corrective = str(error)
        raise ExternalLLMError("EXTERNAL_LLM_ACCEPTANCE_REJECTED")

    def capability_probe(self, *, live: bool = False) -> dict[str, Any]:
        keys = self._keys()
        if not keys:
            raise ExternalLLMError("EXTERNAL_LLM_CREDENTIAL_MISSING")
        result = {"provider":self.name,"protocol":"ANTHROPIC_MESSAGES","base_url":self.base_url,"model_alias":self.model_alias,"auth_mode":self.auth_mode,"credential_count":len(keys)}
        if live:
            response = self.generate_structured(LLMRequest(self.model_alias,"Return only JSON with ok true.",{"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"]},{"max_attempts":min(2,len(keys)),"timeout_seconds":60,"maxOutputTokens":64},"external_llm_probe","capability"))
            if response.value.get("ok") is not True:
                raise ExternalLLMError("EXTERNAL_LLM_STRUCTURED_OUTPUT_INVALID")
            result.update({"status":"CONNECTED","gateway_reported_model":response.usage.get("gateway_reported_model")})
        return result

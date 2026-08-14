"""Central, deterministic Gemini reasoning router with sanitized provenance."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Callable

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.providers.credentials import provider_keys
from .gemini import GeminiProvider, GeminiProviderError, LLMMedia, LLMRequest

ROUTER_VERSION = "story-auto-gemini-router/1.0.0"
HARD_MODELS = ("gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-pro", "gemini-2.5-flash")
BULK_MODELS = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite")


class RouterError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(failure_class + (f": {detail}" if detail else ""))


@dataclass(frozen=True)
class _Credential:
    key: str
    alias: str
    project_alias: str


@dataclass(frozen=True)
class ReasoningResult:
    value: dict[str, Any]
    model: str
    credential_alias: str
    project_alias: str
    cache_hit: bool
    fallback_count: int
    request_count: int
    input_hash: str


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _validate(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    expected = schema.get("type")
    checks = {"object": dict, "array": list, "string": str, "number": (int, float),
              "integer": int, "boolean": bool}
    if expected in checks and (not isinstance(value, checks[expected]) or
            expected in {"number", "integer"} and isinstance(value, bool)):
        raise RouterError("GEMINI_SCHEMA_INVALID", path)
    if "enum" in schema and value not in schema["enum"]:
        raise RouterError("GEMINI_SCHEMA_INVALID", path)
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value: raise RouterError("GEMINI_SCHEMA_INVALID", f"{path}.{name}")
        props = schema.get("properties", {})
        for name, item in value.items():
            if name in props: _validate(item, props[name], f"{path}.{name}")
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            raise RouterError("GEMINI_SCHEMA_INVALID", path)
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value): _validate(item, item_schema, f"{path}[{index}]")


class GeminiReasoningRouter:
    """Route structured reasoning while keeping canonical state deterministic."""
    def __init__(self, *, cache_dir: Path, ledger_path: Path,
                 provider_factory: Callable[[list[str]], GeminiProvider] | None = None,
                 credentials: list[tuple[str, str, str]] | None = None,
                 now: Callable[[], float] = time.time) -> None:
        if credentials is None:
            keys = provider_keys("gemini")
            aliases = [x.strip() for x in os.getenv("STORY_AUTO_GEMINI_PROJECT_ALIASES", "").split(",")]
            credentials = [(key, f"key-{index:02d}", aliases[index - 1] if index <= len(aliases) and aliases[index - 1] else f"project-unknown-key-{index:02d}")
                           for index, key in enumerate(keys, 1)]
        self.credentials = [_Credential(*item) for item in credentials]
        if not self.credentials: raise RouterError("GEMINI_CREDENTIAL_MISSING")
        self.cache_dir, self.ledger_path = cache_dir, ledger_path
        self.provider_factory = provider_factory or (lambda keys: GeminiProvider(keys=keys))
        self.now = now
        self.health: dict[tuple[str, str], float] = {}

    def _ledger(self) -> dict[str, Any]:
        if self.ledger_path.is_file(): return read_json(self.ledger_path)
        return {"schema_version": "story-auto-gemini-reasoning-ledger/1.0.0", "router_version": ROUTER_VERSION, "requests": []}

    def _record(self, item: dict[str, Any]) -> None:
        ledger = self._ledger(); ledger["requests"].append(item); atomic_write_json(self.ledger_path, ledger)

    def reason(self, *, task: str, prompt: str, schema: dict[str, Any], tier: str,
               media: tuple[LLMMedia, ...] = (), prompt_version: str,
               schema_version: str, qc_policy_version: str = "NONE",
               confidence_field: str | None = None, settings: dict[str, Any] | None = None) -> ReasoningResult:
        if tier not in {"HARD", "BULK"}: raise ValueError("tier must be HARD or BULK")
        media_hashes = [{"label": m.label, "mime_type": m.mime_type,
                         "sha256": hashlib.sha256(m.data).hexdigest()} for m in media]
        identity = {"task": task, "prompt": prompt, "schema": schema, "tier": tier,
                    "media": media_hashes, "prompt_version": prompt_version,
                    "schema_version": schema_version, "qc_policy_version": qc_policy_version,
                    "router_version": ROUTER_VERSION}
        input_hash = hashlib.sha256(_canonical(identity)).hexdigest()
        cache = self.cache_dir / f"{input_hash}.json"
        if cache.is_file():
            saved = read_json(cache); _validate(saved["value"], schema)
            return ReasoningResult(saved["value"], saved["model"], saved["credential_alias"],
                                   saved["project_alias"], True, saved.get("fallback_count", 0), 0, input_hash)
        models = list(HARD_MODELS if tier == "HARD" else BULK_MODELS)
        attempted: list[dict[str, str]] = []; request_count = 0
        fatal = {"GEMINI_INVALID_REQUEST", "GEMINI_SAFETY_REFUSAL"}
        for model in models:
            tried_projects: set[str] = set()
            unknown_project_attempts = 0
            credential_calls = 0
            for credential in self.credentials:
                if credential.project_alias in tried_projects: continue
                if credential_calls >= 6: continue
                if credential.project_alias.startswith("project-unknown-key-"):
                    if unknown_project_attempts >= 2: continue
                    unknown_project_attempts += 1
                tried_projects.add(credential.project_alias)
                if self.health.get((credential.project_alias, model), 0) > self.now(): continue
                credential_calls += 1
                request_count += 1
                try:
                    response = self.provider_factory([credential.key]).generate_structured(LLMRequest(
                        model, prompt, schema, settings or {"max_attempts": 2, "timeout_seconds": 180,
                        "temperature": .1, "maxOutputTokens": 4096}, input_hash[:24], task, media))
                    _validate(response.value, schema)
                    if tier == "BULK" and confidence_field and str(response.value.get(confidence_field, "")).upper() in {"LOW", "UNCERTAIN"}:
                        hard = self.reason(task=task, prompt=prompt, schema=schema, tier="HARD", media=media,
                            prompt_version=prompt_version, schema_version=schema_version,
                            qc_policy_version=qc_policy_version, confidence_field=None, settings=settings)
                        return ReasoningResult(hard.value, hard.model, hard.credential_alias, hard.project_alias,
                                               hard.cache_hit, len(attempted) + hard.fallback_count, request_count + hard.request_count, input_hash)
                    saved = {"value": response.value, "model": response.model,
                             "credential_alias": credential.alias, "project_alias": credential.project_alias,
                             "fallback_count": len(attempted), "identity": identity}
                    self.cache_dir.mkdir(parents=True, exist_ok=True); atomic_write_json(cache, saved)
                    self._record({"input_hash": input_hash, "task": task, "tier": tier, "model": response.model,
                                  "credential_alias": credential.alias, "project_alias": credential.project_alias,
                                  "status": "SUCCEEDED", "fallback_count": len(attempted),
                                  "media_hashes": media_hashes, "prompt_version": prompt_version,
                                  "schema_version": schema_version, "qc_policy_version": qc_policy_version})
                    return ReasoningResult(response.value, response.model, credential.alias, credential.project_alias,
                                           False, len(attempted), request_count, input_hash)
                except RouterError as error:
                    failure = error.failure_class
                except GeminiProviderError as error:
                    failure = error.failure_class
                attempted.append({"model": model, "project_alias": credential.project_alias, "failure_class": failure})
                if failure == "GEMINI_CREDENTIAL_MISSING" and credential.project_alias.startswith("project-unknown-key-"):
                    unknown_project_attempts = max(0, unknown_project_attempts - 1)
                if failure in fatal:
                    self._record({"input_hash": input_hash, "task": task, "tier": tier, "model": model,
                                  "credential_alias": credential.alias, "project_alias": credential.project_alias,
                                  "status": "FAILED", "failure_class": failure})
                    raise RouterError(failure)
                if failure == "GEMINI_RATE_LIMIT":
                    self.health[(credential.project_alias, model)] = self.now() + 300
                if failure == "GEMINI_INVALID_REQUEST": raise RouterError(failure)
        self._record({"input_hash": input_hash, "task": task, "tier": tier, "status": "FAILED",
                      "failure_class": "GEMINI_ROUTING_EXHAUSTED", "attempts": attempted})
        raise RouterError("GEMINI_ROUTING_EXHAUSTED")

    def probe_models(self, *, tier: str = "HARD") -> list[dict[str, Any]]:
        models = HARD_MODELS if tier == "HARD" else BULK_MODELS
        results = []
        for model in models:
            credential = self.credentials[0]
            try:
                evidence = self.provider_factory([credential.key]).capability_probe(model, live=True)
                results.append({"model": model, "available": True, "project_alias": credential.project_alias,
                                "credential_alias": credential.alias, "evidence": evidence})
            except GeminiProviderError as error:
                results.append({"model": model, "available": False, "project_alias": credential.project_alias,
                                "credential_alias": credential.alias, "failure_class": error.failure_class})
        return results

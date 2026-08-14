from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from story_auto.providers.llm.gemini import GeminiProviderError, LLMRequest, LLMResponse
from story_auto.providers.llm.router import GeminiReasoningRouter, RoutedGeminiProvider, RouterError


SCHEMA = {"type": "object", "required": ["ok", "confidence"], "properties": {
    "ok": {"type": "boolean"}, "confidence": {"type": "string"}}}


class FakeProvider:
    def __init__(self, key, behavior, calls): self.key, self.behavior, self.calls = key, behavior, calls
    def generate_structured(self, request):
        self.calls.append((self.key, request.model, request.stage))
        action = self.behavior(self.key, request.model)
        if isinstance(action, Exception): raise action
        return LLMResponse(action, request.model, request.request_id, 1, 1, {})
    def capability_probe(self, model, live=False):
        action = self.behavior(self.key, model)
        if isinstance(action, Exception): raise action
        return {"model": model, "smoke": "PASS"}


def router(tmp, behavior, credentials=None):
    calls = []
    value = GeminiReasoningRouter(cache_dir=Path(tmp) / "cache", ledger_path=Path(tmp) / "ledger.json",
        credentials=credentials or [("secret-a", "key-01", "project-a")],
        provider_factory=lambda keys: FakeProvider(keys[0], behavior, calls), now=lambda: 1000)
    return value, calls


def invoke(value, tier="HARD", confidence=True):
    return value.reason(task="test", prompt="structured", schema=SCHEMA, tier=tier,
        prompt_version="p1", schema_version="s1", confidence_field="confidence" if confidence else None)


def test_hard_and_bulk_router_model_order():
    with tempfile.TemporaryDirectory() as tmp:
        hard, calls = router(tmp, lambda *_: {"ok": True, "confidence": "HIGH"})
        assert invoke(hard).model == "gemini-3.6-flash"
        assert calls[0][1] == "gemini-3.6-flash"
    with tempfile.TemporaryDirectory() as tmp:
        bulk, calls = router(tmp, lambda *_: {"ok": True, "confidence": "HIGH"})
        assert invoke(bulk, "BULK").model == "gemini-3.5-flash-lite"
        assert calls[0][1] == "gemini-3.5-flash-lite"


def test_unknown_project_credentials_get_bounded_key_fallback():
    with tempfile.TemporaryDirectory() as tmp:
        credentials = [("secret-a", "key-01", "project-unknown-key-01"),
                       ("secret-b", "key-02", "project-unknown-key-02"),
                       ("secret-c", "key-03", "project-unknown-key-03")]
        def behavior(key, _model):
            if key == "secret-a": return GeminiProviderError("GEMINI_RATE_LIMIT")
            return {"ok": True, "confidence": "HIGH"}
        value, calls = router(tmp, behavior, credentials)
        result = invoke(value)
        assert (result.credential_alias, len(calls)) == ("key-02", 2)


def test_unknown_project_pool_is_bounded_at_six_distinct_keys_per_model():
    with tempfile.TemporaryDirectory() as tmp:
        credentials=[(f"key-{i}",f"alias-{i}",f"project-unknown-key-{i:02d}") for i in range(1,8)]
        def behavior(key, _model):
            return {"ok":True,"confidence":"HIGH"} if key == "key-6" else GeminiProviderError("GEMINI_RATE_LIMIT")
        value,calls=router(tmp,behavior,credentials)
        result=invoke(value)
        assert result.credential_alias == "alias-6"
        assert len(calls) == 6


def test_invalid_unknown_key_does_not_consume_project_probe_limit():
    with tempfile.TemporaryDirectory() as tmp:
        credentials = [("quota-key", "key-01", "project-unknown-key-01"),
                       ("invalid-key", "key-02", "project-unknown-key-02"),
                       ("healthy-key", "key-03", "project-unknown-key-03")]
        def behavior(key, _model):
            if key == "quota-key": return GeminiProviderError("GEMINI_RATE_LIMIT")
            if key == "invalid-key": return GeminiProviderError("GEMINI_CREDENTIAL_MISSING")
            return {"ok": True, "confidence": "HIGH"}
        value, calls = router(tmp, behavior, credentials)
        result = invoke(value)
        assert (result.credential_alias, len(calls)) == ("key-03", 3)


def test_low_confidence_bulk_escalates_to_hard():
    with tempfile.TemporaryDirectory() as tmp:
        value, calls = router(tmp, lambda _key, model: {"ok": True, "confidence": "LOW"} if "lite" in model else {"ok": True, "confidence": "HIGH"})
        result = invoke(value, "BULK")
        assert result.model == "gemini-3.6-flash"
        assert [x[1] for x in calls] == ["gemini-3.5-flash-lite", "gemini-3.6-flash"]


def test_429_routes_to_another_project_without_hammering_same_project():
    with tempfile.TemporaryDirectory() as tmp:
        credentials = [("a1", "key-01", "project-a"), ("a2", "key-02", "project-a"), ("b1", "key-03", "project-b")]
        value, calls = router(tmp, lambda key, _model: GeminiProviderError("GEMINI_RATE_LIMIT") if key == "a1" else {"ok": True, "confidence": "HIGH"}, credentials)
        result = invoke(value)
        assert result.project_alias == "project-b"
        assert [x[0] for x in calls] == ["a1", "b1"]


def test_model_fallback_and_project_model_health():
    with tempfile.TemporaryDirectory() as tmp:
        value, calls = router(tmp, lambda _key, model: GeminiProviderError("GEMINI_MODEL_UNAVAILABLE") if model == "gemini-3.6-flash" else {"ok": True, "confidence": "HIGH"})
        assert invoke(value).model == "gemini-3.5-flash"
        assert [x[1] for x in calls] == ["gemini-3.6-flash", "gemini-3.5-flash"]


@pytest.mark.parametrize("failure", ["GEMINI_INVALID_REQUEST", "GEMINI_SAFETY_REFUSAL"])
def test_invalid_request_and_safety_refusal_do_not_rotate_or_model_hop(failure):
    with tempfile.TemporaryDirectory() as tmp:
        credentials = [("a", "key-01", "project-a"), ("b", "key-02", "project-b")]
        value, calls = router(tmp, lambda *_: GeminiProviderError(failure), credentials)
        with pytest.raises(RouterError, match=failure): invoke(value)
        assert len(calls) == 1


def test_structured_schema_validation_and_cache_reuse_and_secret_redaction():
    with tempfile.TemporaryDirectory() as tmp:
        count = {"n": 0}
        def behavior(_key, model):
            count["n"] += 1
            return {"broken": True} if model == "gemini-3.6-flash" else {"ok": True, "confidence": "HIGH"}
        value, calls = router(tmp, behavior)
        first = invoke(value); second = invoke(value)
        assert first.model == "gemini-3.5-flash" and second.cache_hit and second.request_count == 0
        ledger = (Path(tmp) / "ledger.json").read_text(encoding="utf-8")
        assert "secret-a" not in ledger and "key-01" in ledger and count["n"] == 2


def test_credential_health_is_scoped_by_project_and_model():
    with tempfile.TemporaryDirectory() as tmp:
        value, _ = router(tmp, lambda *_: {"ok": True, "confidence": "HIGH"})
        value.health[("project-a", "gemini-3.6-flash")] = 1300
        assert invoke(value).model == "gemini-3.5-flash"


def test_routed_provider_preserves_planning_contract_and_records_actual_model():
    with tempfile.TemporaryDirectory() as tmp:
        value, calls = router(tmp, lambda _key, model: {"ok": True, "confidence": "HIGH"})
        provider = RoutedGeminiProvider(value)
        response = provider.generate_structured(LLMRequest("gemini-3.5-flash", "structured", SCHEMA,
            {"max_attempts": 1}, "request-1", "story_timeline"))
        assert response.request_id == "request-1"
        assert response.model == "gemini-3.6-flash"
        assert response.usage["credential_alias"] == "key-01"
        assert calls[0][1] == "gemini-3.6-flash"

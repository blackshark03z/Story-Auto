from __future__ import annotations

import unittest

from story_auto.providers.llm.gemini import GeminiProvider, LLMRequest
from story_auto.providers.llm.router import HARD_MODELS


class Gemini38UpgradeTests(unittest.TestCase):
    def test_hard_router_prefers_current_stable_flash_generation(self):
        self.assertEqual(HARD_MODELS[:4], (
            "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"
        ))

    def test_gemini38_omits_deprecated_sampling_parameters(self):
        observed = {}
        def transport(url, body, key, timeout):
            observed.update({"url": url, "body": body, "key": key, "timeout": timeout})
            return {"candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]}}], "usageMetadata": {}}
        provider = GeminiProvider(transport=transport, keys=["fixture-key"])
        response = provider.generate_structured(LLMRequest(
            "gemini-3.8-flash", "Return JSON.",
            {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
            {"max_attempts": 1, "temperature": 0.2, "topP": 0.9, "maxOutputTokens": 512},
            "req-38", "test"))
        config = observed["body"]["generationConfig"]
        self.assertEqual(response.value, {"ok": True})
        self.assertNotIn("temperature", config)
        self.assertNotIn("topP", config)
        self.assertEqual(config["maxOutputTokens"], 512)
        self.assertIn("gemini-3.8-flash", observed["url"])

    def test_legacy_gemini35_request_shape_remains_compatible(self):
        observed = {}
        def transport(url, body, key, timeout):
            observed["body"] = body
            return {"candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]}}]}
        GeminiProvider(transport=transport, keys=["fixture-key"]).generate_structured(LLMRequest(
            "gemini-3.5-flash", "Return JSON.",
            {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
            {"max_attempts": 1, "temperature": 0.2, "topP": 0.9}, "req-35", "test"))
        config = observed["body"]["generationConfig"]
        self.assertEqual(config["temperature"], 0.2)
        self.assertEqual(config["topP"], 0.9)


if __name__ == "__main__":
    unittest.main()

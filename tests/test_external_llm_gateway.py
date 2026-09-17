from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from story_auto.application.operator import OperatorService
from story_auto.providers.credentials import provider_keys
from story_auto.providers.llm import AnthropicCompatibleProvider, ExternalLLMError, LLMRequest, normalize_base_url
from story_auto.ui.server import create_server


class ExternalLlmGatewayTests(unittest.TestCase):
    def test_path_prefix_and_structured_messages_contract(self):
        calls = []
        def transport(url, body, key, timeout):
            calls.append((url, body, key, timeout))
            return {"content":[{"type":"text","text":"{\"ok\":true}"}],"model":"gateway-reported-model","usage":{"input_tokens":10}}
        provider = AnthropicCompatibleProvider(base_url="https://gateway.example.com/team/anthropic", model_alias="claude-route", auth_mode="bearer", transport=transport, keys=["fixture-external-key"])
        response = provider.generate_structured(LLMRequest("claude-route","Return ok",{"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"]},{"max_attempts":1,"timeout_seconds":5},"req-1","test"))
        self.assertEqual(response.value,{"ok":True})
        self.assertEqual(response.model,"claude-route")
        self.assertEqual(calls[0][0],"https://gateway.example.com/team/anthropic/v1/messages")
        self.assertEqual(calls[0][2],"fixture-external-key")
        self.assertEqual(response.usage["gateway_reported_model"],"gateway-reported-model")
        self.assertEqual(response.usage["provider"],"external_anthropic")

    def test_base_url_fails_closed_on_unsafe_shapes(self):
        self.assertEqual(normalize_base_url("https://gateway.example.com/anthropic/"),"https://gateway.example.com/anthropic")
        for value in ("http://gateway.example.com","https://user:pass@gateway.example.com","https://gateway.example.com/path?key=secret","https://gateway.example.com/a/../b"):
            with self.assertRaises(ExternalLLMError): normalize_base_url(value)
        self.assertEqual(normalize_base_url("http://127.0.0.1:8000/proxy"),"http://127.0.0.1:8000/proxy")

    @unittest.skipUnless(os.name == "nt", "Story Auto credential persistence uses Windows DPAPI")
    def test_settings_config_key_pool_test_and_gemini_switch_are_secret_free(self):
        class FakeGateway:
            def __init__(self, *, base_url, model_alias, auth_mode="x-api-key", **_kwargs):
                self.base_url=base_url; self.model_alias=model_alias; self.auth_mode=auth_mode
            def capability_probe(self, *, live=False):
                return {"status":"CONNECTED","gateway_reported_model":"claude-proxy-model"}
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as local:
            with patch.dict(os.environ,{"LOCALAPPDATA":local,"STORY_AUTO_EXTERNAL_LLM_API_KEY":""},clear=False), patch("story_auto.application.operator.AnthropicCompatibleProvider",FakeGateway):
                app=OperatorService(root)
                configured=app.configure_external_llm(base_url="https://gateway.example.com/anthropic",model_alias="claude-proxy",auth_mode="x-api-key")
                self.assertTrue(configured["selected_for_new_projects"])
                key1="fixture-external-key-one-not-real"; key2="fixture-external-key-two-not-real"
                saved=app.save_external_llm_keys([key1,key2,key1])
                self.assertEqual((saved["added_count"],saved["saved_credential_count"]),(2,2))
                self.assertEqual(provider_keys("external_llm"),[key1,key2])
                raw=(Path(local)/"StoryAuto"/"credentials.v1.json").read_text(encoding="utf-8")
                self.assertNotIn(key1,raw); self.assertNotIn(key2,raw)
                result=app.test_external_llm_connection()
                self.assertEqual(result["status"],"CONNECTED")
                self.assertEqual(result["gateway_reported_model"],"claude-proxy-model")
                self.assertNotIn(key1,json.dumps(result)); self.assertNotIn(key2,json.dumps(result))
                creation=app.creation_defaults()["creation_defaults"]["llm"]
                self.assertEqual(creation["provider"],"external_anthropic")
                self.assertNotIn("model",creation)
                self.assertEqual(creation["external_anthropic"]["auth_mode"],"x-api-key")
                app.use_gemini_brain()
                gemini=app.creation_defaults()["creation_defaults"]["llm"]
                self.assertEqual(gemini,{"provider":"gemini","model":"gemini-3.8-flash"})

    @unittest.skipUnless(os.name == "nt", "Browser credential journey requires Windows DPAPI")
    def test_browser_settings_configures_tests_and_switches_brain_without_exposing_key(self):
        from playwright.sync_api import sync_playwright
        class FakeGateway:
            def __init__(self, *, base_url, model_alias, auth_mode="x-api-key", **_kwargs):
                self.base_url=base_url; self.model_alias=model_alias; self.auth_mode=auth_mode
            def capability_probe(self, *, live=False):
                return {"status":"CONNECTED","gateway_reported_model":"etf-route-haiku"}
        with sync_playwright() as probe:
            chrome=Path(probe.chromium.executable_path)
        if not chrome.is_file(): self.skipTest("Playwright Chromium is not installed")
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as local:
            with patch.dict(os.environ,{"LOCALAPPDATA":local,"STORY_AUTO_EXTERNAL_LLM_API_KEY":""},clear=False), patch("story_auto.application.operator.AnthropicCompatibleProvider",FakeGateway):
                server=create_server(root,port=0); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
                try:
                    with sync_playwright() as playwright:
                        browser=playwright.chromium.launch(headless=True,executable_path=str(chrome)); page=browser.new_page(); page.goto(f"http://127.0.0.1:{server.server_address[1]}")
                        page.locator("#settingsNav").click(); page.get_by_text("Reasoning provider",exact=True).wait_for(timeout=5000)
                        page.locator("#externalLlmBaseUrl").fill("https://gateway.example.com/anthropic")
                        page.locator("#externalLlmModel").fill("claude-proxy")
                        page.locator("#externalLlmAuthMode").select_option("x-api-key")
                        page.locator("#saveExternalLlmConfig").click(); page.locator("#brainProviderStatus").get_by_text("External Anthropic-compatible gateway",exact=True).wait_for(timeout=5000)
                        key="fixture-browser-external-key-not-real"
                        page.locator("#externalLlmApiKey").fill(key); page.locator("#saveExternalLlmKeys").click()
                        page.locator("#testExternalLlm").wait_for(state="visible",timeout=5000)
                        self.assertNotIn(key,page.locator("body").inner_text())
                        page.locator("#testExternalLlm").click(); page.get_by_text("Connected · etf-route-haiku",exact=True).wait_for(timeout=5000)
                        page.locator("#useGeminiBrain").click(); page.locator("#brainProviderStatus").get_by_text("Gemini 3.8 Flash",exact=True).wait_for(timeout=5000)
                        browser.close()
                finally:
                    server.shutdown(); server.server_close(); thread.join(5)

    def test_invalid_auth_mode_is_rejected(self):
        with self.assertRaises(ExternalLLMError):
            AnthropicCompatibleProvider(base_url="https://gateway.example.com",model_alias="x",auth_mode="cookie",keys=["fixture-key"])


if __name__ == "__main__":
    unittest.main()

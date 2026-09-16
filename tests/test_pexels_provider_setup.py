from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from story_auto.application.operator import OperatorService
from story_auto.providers.credentials import (clear_provider_keys, provider_key_status,
                                               provider_keys, set_provider_keys)
from story_auto.ui.server import create_server


class PexelsProviderSetupTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Story Auto credential persistence uses Windows DPAPI")
    def test_pexels_key_round_trips_through_dpapi_store_without_plaintext(self):
        with tempfile.TemporaryDirectory() as local:
            with patch.dict(os.environ, {"LOCALAPPDATA": local, "PEXELS_API_KEY": ""}, clear=False):
                key = "fixture-pexels-key-not-a-real-secret"
                set_provider_keys("pexels", [key])
                status = provider_key_status("pexels")
                self.assertEqual(status, {"configured": True, "count": 1, "source": "DPAPI_STORE", "removable": True})
                self.assertEqual(provider_keys("pexels"), [key])
                store = Path(local) / "StoryAuto" / "credentials.v1.json"
                raw = store.read_text(encoding="utf-8")
                self.assertNotIn(key, raw)
                self.assertIn("WINDOWS_DPAPI_CURRENT_USER", raw)
                clear_provider_keys("pexels")
                self.assertFalse(provider_key_status("pexels")["configured"])

    def test_live_test_returns_only_non_secret_readiness(self):
        class FakePexelsClient:
            def __init__(self):
                self.key = "fixture-value-never-returned"

            def search_videos(self, *args, **kwargs):
                return {"videos": [{"provider_asset_id": "1"}],
                        "rate_limit": {"limit": 20000, "remaining": 19999, "reset": 1790000000}}

        with tempfile.TemporaryDirectory() as root:
            with patch("story_auto.application.operator.provider_key_status",
                       return_value={"configured": True, "count": 1, "source": "DPAPI_STORE", "removable": True}), \
                 patch("story_auto.application.operator.PexelsClient", FakePexelsClient):
                result = OperatorService(root).test_pexels_connection()
        self.assertEqual(result["status"], "CONNECTED")
        self.assertTrue(result["live_verified"])
        self.assertEqual(result["rate_limit"]["remaining"], 19999)
        self.assertNotIn("fixture-value-never-returned", json.dumps(result))

    @unittest.skipUnless(os.name == "nt", "Browser credential journey requires Windows DPAPI")
    def test_browser_settings_save_test_remove_and_hybrid_fallback_visibility(self):
        from playwright.sync_api import sync_playwright

        class FakePexelsClient:
            def __init__(self):
                try:
                    self.key = provider_keys("pexels")[0]
                except Exception:
                    self.key = ""

            def search_videos(self, *args, **kwargs):
                return {"videos": [{"provider_asset_id": "1"}],
                        "rate_limit": {"limit": 20000, "remaining": 19998, "reset": 1790000000}}

        with sync_playwright() as probe:
            chrome = Path(probe.chromium.executable_path)
        if not chrome.is_file():
            self.skipTest("Playwright Chromium is not installed")

        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as local:
            with patch.dict(os.environ, {"LOCALAPPDATA": local, "PEXELS_API_KEY": ""}, clear=False), \
                 patch("story_auto.application.operator.PexelsClient", FakePexelsClient):
                server = create_server(root, port=0)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True, executable_path=str(chrome))
                        page = browser.new_page()
                        page.goto(f"http://127.0.0.1:{server.server_address[1]}")
                        page.locator("#settingsNav").click()
                        page.get_by_text("Hybrid stock video", exact=False).first.wait_for(timeout=5000)
                        self.assertEqual(page.locator("#pexelsLiveStatus").inner_text(), "Not configured")

                        fixture_key = "fixture-pexels-key-not-a-real-secret"
                        page.locator("#pexelsApiKey").fill(fixture_key)
                        page.locator("#savePexelsKey").click()
                        page.locator("#pexelsLiveStatus").get_by_text("Configured", exact=True).wait_for(timeout=5000)
                        self.assertNotIn(fixture_key, page.locator("body").inner_text())

                        page.locator("#testPexelsKey").click()
                        page.locator("#pexelsLiveStatus").get_by_text("Connected", exact=False).wait_for(timeout=5000)
                        self.assertIn("19998", page.locator("#pexelsLiveStatus").inner_text())

                        page.locator("#clearPexelsKey").click()
                        page.locator("#pexelsLiveStatus").get_by_text("Not configured", exact=True).wait_for(timeout=5000)

                        page.locator("#homeNav").click()
                        page.locator("#newVideoTop").click()
                        page.get_by_role("button", name="Continue", exact=True).click()
                        page.locator("#contentInput").fill("# Hybrid Provider Setup\n\n## Narration\n\nA short provider setup story.")
                        page.get_by_role("button", name="Continue", exact=True).click()
                        page.locator('input[name="format"][value="hybrid_hook"]').check()
                        text = page.locator("#wizardContent").inner_text()
                        self.assertIn("HYBRID VISUAL PROVIDERS", text)
                        self.assertIn("Pexels not configured", text)
                        self.assertIn("fallback", text.lower())
                        browser.close()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(5)


if __name__ == "__main__":
    unittest.main()

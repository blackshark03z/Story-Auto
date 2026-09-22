from __future__ import annotations

import json
import unittest

from story_auto.providers.video_generation import (
    cross_provider_fallback_allowed,
    provider_descriptor,
    video_provider_catalog,
)


class VideoProviderRegistryTests(unittest.TestCase):
    def test_seedance_model_family_is_independent_from_provider(self):
        byteplus = provider_descriptor("byteplus_seedance")
        elyum = provider_descriptor("elyum_seedance")
        self.assertEqual(byteplus["model_family"], "seedance")
        self.assertEqual(elyum["model_family"], "seedance")
        self.assertNotEqual(byteplus["provider_id"], elyum["provider_id"])
        self.assertEqual(byteplus["lifecycle"], "ASYNC_TASK")
        self.assertEqual(elyum["lifecycle"], "LOCKED_PREVIEW_KEEP_KILL")

    def test_cross_provider_fallback_is_pre_dispatch_only(self):
        for state in ("NOT_CONFIGURED", "CAPABILITY_UNSUPPORTED", "PREFLIGHT_FAILED", "CONFIRMED_NOT_DISPATCHED"):
            self.assertTrue(cross_provider_fallback_allowed(state), state)
        for state in ("AMBIGUOUS", "SUBMITTED", "GENERATING", "PREVIEW_READY", "SUCCEEDED", "FAILED_TERMINAL"):
            self.assertFalse(cross_provider_fallback_allowed(state), state)

    def test_catalog_exposes_tiers_without_secret_material(self):
        catalog = video_provider_catalog()
        ids = [row["provider_id"] for row in catalog]
        self.assertEqual(ids, ["byteplus_seedance", "elyum_seedance", "dola_official", "dola_cookie", "manual_external"])
        by_id = {row["provider_id"]: row for row in catalog}
        self.assertTrue(by_id["byteplus_seedance"]["production_routed"])
        self.assertFalse(by_id["elyum_seedance"]["production_routed"])
        self.assertTrue(by_id["dola_official"]["experimental"])
        self.assertEqual(by_id["dola_cookie"]["modes"], ["T2V"])
        self.assertFalse(by_id["dola_cookie"]["production_routed"])
        self.assertEqual(by_id["dola_official"]["reason_code"], "OFFICIAL_API_CONTRACT_NOT_QUALIFIED")
        self.assertNotEqual(by_id["dola_official"]["transport"], "SESSION_BASED_EXPERIMENTAL")
        self.assertEqual(by_id["manual_external"]["status"], "READY")
        serialized = json.dumps(catalog).lower()
        self.assertNotIn("api_key", serialized)
        self.assertNotIn("cookie_value", serialized)


    def test_browser_settings_exposes_video_provider_registry(self):
        import tempfile
        import threading
        from pathlib import Path as LocalPath
        from story_auto.ui.server import create_server
        from playwright.sync_api import sync_playwright

        with sync_playwright() as probe:
            chrome = LocalPath(probe.chromium.executable_path)
        if not chrome.is_file():
            self.skipTest("Playwright Chromium is not installed")
        with tempfile.TemporaryDirectory() as root:
            server = create_server(root, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True, executable_path=str(chrome))
                    page = browser.new_page()
                    page.goto(f"http://127.0.0.1:{server.server_address[1]}")
                    page.locator("#settingsNav").click()
                    page.get_by_text("Video generation providers", exact=True).wait_for(timeout=5000)
                    surface = page.locator("#view").inner_text()
                    for label in ("BytePlus ModelArk", "Elyum", "Dola", "Manual external generation"):
                        self.assertIn(label, surface)
                    self.assertIn("Experimental", surface)
                    browser.close()
            finally:
                server.shutdown(); server.server_close(); thread.join(5)


if __name__ == "__main__":
    unittest.main()

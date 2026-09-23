"""Offline boundaries for opt-in Dola browser UI transport."""
from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, Mock, patch

from story_auto.providers.dola_cookie.browser_ui import (
    DolaBrowserUIClient, PatchrightDolaRunner, _CONVERSATION_URL, _bind_profile, _cookies_for_browser,
    _native_request_id, _send_once,
)
from story_auto.providers.dola_cookie.client import DolaCookieError


COOKIE = "sessionid=fixture-session; msToken=fixture-ms; store-idc=fixture-idc"


def _native_request(*, prompt="a river", ratio="16:9", duration=5, model="seedance_v2.0"):
    return Mock(post_data_json={
        "messages": [{"local_message_id": "native-1", "content_block": [{
            "block_type": 10000, "content": {"text_block": {"text": prompt}},
        }]}],
        "chat_ability": {"ability_type": 17, "ability_param": json.dumps({
            "ratio": ratio, "duration": duration, "model": model,
        })},
    })


class DolaBrowserUITests(unittest.TestCase):
    def test_conversation_url_allows_only_dola_apex_or_www(self):
        for url in ("https://www.dola.com/chat/12345", "https://dola.com/chat/12345"):
            self.assertEqual(_CONVERSATION_URL.fullmatch(url).group(1), "12345")
        for url in ("http://dola.com/chat/12345", "https://www.dola.com.evil/chat/12345"):
            self.assertIsNone(_CONVERSATION_URL.fullmatch(url))

    def test_cookie_seed_has_no_plaintext_logging_or_aliasing(self):
        rows = _cookies_for_browser(COOKIE)
        self.assertEqual([row["name"] for row in rows], ["sessionid", "msToken", "store-idc"])
        self.assertTrue(all(row["url"] == "https://www.dola.com/chat" for row in rows))
        for invalid in ("msToken=x", "sessionid=x; sessionid=y", "sessionid=x\nother=y",
                        "sessionid=x; bad=y\tdata"):
            with self.subTest(cookie=invalid):
                with self.assertRaises(DolaCookieError):
                    _cookies_for_browser(invalid)

    def test_native_request_requires_exact_prompt_ratio_duration_and_model(self):
        self.assertEqual(_native_request_id(_native_request(), "a river", "16:9", 5),
                         "native-1")
        for request in (
            _native_request(prompt="another prompt"),
            _native_request(prompt="please make a river video"),
            _native_request(ratio="9:16"),
            _native_request(duration=10),
            _native_request(model="unknown"),
        ):
            with self.subTest(body=request.post_data_json):
                with self.assertRaisesRegex(DolaCookieError, "NATIVE_REQUEST_UNVERIFIED"):
                    _native_request_id(request, "a river", "16:9", 5)

    def test_native_id_is_durable_before_post_send_contract_rejection(self):
        seen = []
        with self.assertRaisesRegex(DolaCookieError, "NATIVE_REQUEST_UNVERIFIED"):
            _native_request_id(_native_request(model="drifted"), "a river", "16:9", 5,
                               seen.append)
        self.assertEqual(seen, ["native-1"])

    def test_failed_send_click_does_not_fall_back_to_enter(self):
        page = Mock()
        button = Mock()
        button.is_visible.return_value = True
        button.click.side_effect = RuntimeError("uncertain click")
        locator = page.locator.return_value
        locator.count.return_value = 1
        locator.nth.return_value = button
        composer = Mock()
        with self.assertRaisesRegex(RuntimeError, "uncertain click"):
            _send_once(page, composer)
        button.click.assert_called_once()
        composer.press.assert_not_called()

    def test_profile_binding_refuses_unbound_or_different_account(self):
        with TemporaryDirectory() as directory:
            profile = Path(directory) / "profile"
            _bind_profile(profile, "daily", "a" * 64)
            _bind_profile(profile, "daily", "a" * 64)
            with self.assertRaisesRegex(DolaCookieError, "BINDING_MISMATCH"):
                _bind_profile(profile, "another", "b" * 64)
            unbound = Path(directory) / "unbound"
            unbound.mkdir()
            (unbound / "Default").mkdir()
            with self.assertRaisesRegex(DolaCookieError, "PROFILE_UNBOUND"):
                _bind_profile(unbound, "daily", "a" * 64)

    def test_opt_in_client_passes_one_call_to_runner(self):
        class Runner:
            def __init__(self): self.calls = []
            def run(self, **kwargs):
                self.calls.append(kwargs)
                kwargs["on_native_request"]("native-1")
                kwargs["on_receipt"]("conversation-1")
                return "conversation-1"
        runner = Runner()
        with TemporaryDirectory() as directory:
            client = DolaBrowserUIClient(COOKIE, account_id="daily",
                                         profile_dir=Path(directory) / "profile", runner=runner)
            native = []
            receipts = []
            result = client.submit("a river", "16:9", 5, receipts.append,
                                   client_request_id="attempt-1", on_native_request=native.append)
        self.assertEqual(result, "conversation-1")
        self.assertEqual((native, receipts), (["native-1"], ["conversation-1"]))
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0]["account_id"], "daily")

    def test_preflight_does_not_call_submit(self):
        class Runner:
            def __init__(self): self.calls = []
            def preflight(self, **kwargs):
                self.calls.append(kwargs)
                return {"status": "UI_READY_NO_SUBMIT", "generation_submits": 0}
            def run(self, **kwargs):
                raise AssertionError("preflight must never submit")
        runner = Runner()
        with TemporaryDirectory() as directory:
            client = DolaBrowserUIClient(COOKIE, account_id="daily",
                                         profile_dir=Path(directory) / "profile", runner=runner)
            self.assertEqual(client.preflight()["generation_submits"], 0)
            self.assertEqual((runner.calls[0]["duration"], runner.calls[0]["ratio"]), (5, "16:9"))
            with self.assertRaises(DolaCookieError):
                client.preflight(duration=15)
        self.assertEqual(len(runner.calls), 1)

    def test_cookie_rotation_uses_a_new_dedicated_profile(self):
        with TemporaryDirectory() as directory:
            base = Path(directory) / "profiles"
            first = DolaBrowserUIClient(COOKIE, account_id="daily", profile_dir=base)
            refreshed = DolaBrowserUIClient(COOKIE.replace("fixture-session", "refreshed-session"),
                                            account_id="daily", profile_dir=base)
        self.assertNotEqual(first._profile, refreshed._profile)
        self.assertNotEqual(first.profile_binding, refreshed.profile_binding)

    def test_runner_uses_one_click_and_persists_native_id_before_receipt(self):
        class Browser:
            def __init__(self, request):
                self.page = Mock(url="https://www.dola.com/chat/12345")
                self.context = Mock(pages=[self.page])
                self.playwright = Mock()
                self.playwright.chromium.launch_persistent_context.return_value = self.context
                self.manager = MagicMock()
                self.manager.__enter__.return_value = self.playwright
                self.send = Mock()
                self.send.is_visible.return_value = True
                locator = Mock()
                locator.count.return_value = 1
                locator.nth.return_value = self.send
                self.page.locator.return_value = locator
                self.page.get_by_text.return_value.count.return_value = 0
                self.page.on.side_effect = lambda event, callback: setattr(self, "observe", callback)
                self.send.click.side_effect = lambda **kwargs: self.observe(request)

        request = _native_request()
        request.method = "POST"
        request.url = "https://www.dola.com/chat/completion?source=web"
        browser = Browser(request)
        reader = Mock()
        reader.verify_input.return_value = True
        native, receipts = [], []
        with TemporaryDirectory() as directory, \
                patch("patchright.sync_api.sync_playwright", return_value=browser.manager), \
                patch("story_auto.providers.dola_cookie.browser_ui._profile_lease", return_value=nullcontext()), \
                patch("story_auto.providers.dola_cookie.browser_ui._bind_profile"), \
                patch("story_auto.providers.dola_cookie.browser_ui._prepare_video_ui", return_value=Mock()):
            result = PatchrightDolaRunner().run(
                cookie=COOKIE, profile=Path(directory) / "profile", account_id="daily",
                binding="a" * 64, prompt="a river", ratio="16:9", duration=5,
                on_native_request=native.append, on_receipt=receipts.append, reader=reader,
            )
        self.assertEqual(result, "12345")
        self.assertEqual((native, receipts), (["native-1"], ["12345"]))
        browser.send.click.assert_called_once()
        reader.verify_input.assert_called_once_with("12345", "native-1")
        browser.context.close.assert_called_once()

        drift = _native_request(model="drifted")
        drift.method = "POST"
        drift.url = request.url
        browser = Browser(drift)
        native, receipts = [], []
        with TemporaryDirectory() as directory, \
                patch("patchright.sync_api.sync_playwright", return_value=browser.manager), \
                patch("story_auto.providers.dola_cookie.browser_ui._profile_lease", return_value=nullcontext()), \
                patch("story_auto.providers.dola_cookie.browser_ui._bind_profile"), \
                patch("story_auto.providers.dola_cookie.browser_ui._prepare_video_ui", return_value=Mock()):
            with self.assertRaisesRegex(DolaCookieError, "NATIVE_REQUEST_UNVERIFIED"):
                PatchrightDolaRunner().run(
                    cookie=COOKIE, profile=Path(directory) / "profile", account_id="daily",
                    binding="a" * 64, prompt="a river", ratio="16:9", duration=5,
                    on_native_request=native.append, on_receipt=receipts.append, reader=Mock(),
                )
        self.assertEqual((native, receipts), (["native-1"], []))
        browser.send.click.assert_called_once()

        browser = Browser(request)
        native, receipts = [], []
        def persist_failure(identifier):
            raise RuntimeError("journal unavailable")
        with TemporaryDirectory() as directory, \
                patch("patchright.sync_api.sync_playwright", return_value=browser.manager), \
                patch("story_auto.providers.dola_cookie.browser_ui._profile_lease", return_value=nullcontext()), \
                patch("story_auto.providers.dola_cookie.browser_ui._bind_profile"), \
                patch("story_auto.providers.dola_cookie.browser_ui._prepare_video_ui", return_value=Mock()):
            with self.assertRaisesRegex(DolaCookieError, "PERSIST_FAILED"):
                PatchrightDolaRunner().run(
                    cookie=COOKIE, profile=Path(directory) / "profile", account_id="daily",
                    binding="a" * 64, prompt="a river", ratio="16:9", duration=5,
                    on_native_request=persist_failure, on_receipt=receipts.append, reader=Mock(),
                )
        self.assertEqual(receipts, [])
        browser.send.click.assert_called_once()


if __name__ == "__main__":
    unittest.main()

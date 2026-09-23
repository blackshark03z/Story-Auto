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
    _native_request_id, _send_once, _seed_profile_cookies, _type_prompt,
)
from story_auto.providers.dola_cookie.client import DolaCookieError


COOKIE = "sessionid=fixture-session; msToken=fixture-ms; store-idc=fixture-idc"


def _native_request(*, prompt="a river", ratio="16:9", duration=5, model="seedance_v2.0",
                    text=None):
    if text is None:
        text = f"Generated video: {prompt}, {ratio}"
    return Mock(post_data_json={
        "messages": [{"local_message_id": "native-1", "content_block": [{
            "block_type": 10000, "content": {"text_block": {"text": text}},
        }]}],
        "chat_ability": {"ability_type": 17, "ability_param": json.dumps({
            "ratio": ratio, "duration": duration, "model": model,
        })},
    })


class DolaBrowserUITests(unittest.TestCase):
    def test_surviving_draft_is_never_doubled_after_manual_challenge(self):
        page = Mock()
        composer = Mock()
        composer.evaluate.side_effect = ["", "a river", "partial a river"]
        _type_prompt(page, composer, "a river")
        _type_prompt(page, composer, "a river", after_challenge=True)
        page.keyboard.type.assert_called_once_with("a river", delay=20)
        composer.click.assert_called_once()
        with self.assertRaisesRegex(DolaCookieError, "DOLA_COMPOSER_NOT_EMPTY"):
            _type_prompt(page, composer, "a river", after_challenge=True)
        page.keyboard.type.assert_called_once()

    def test_initial_stale_draft_fails_before_any_type_or_send(self):
        page = Mock()
        composer = Mock()
        composer.evaluate.return_value = "old draft"
        with self.assertRaisesRegex(DolaCookieError, "DOLA_COMPOSER_NOT_EMPTY"):
            _type_prompt(page, composer, "a river")
        page.keyboard.type.assert_not_called()
        page.keyboard.press.assert_not_called()

    def test_pre_send_challenge_waits_in_same_window_then_rechecks_controls(self):
        runner = PatchrightDolaRunner(operator_visible=True)
        page = Mock()
        composer = Mock()
        with patch("story_auto.providers.dola_cookie.browser_ui._prepare_video_ui",
                   side_effect=[DolaCookieError("DOLA_NEEDS_OPERATOR", "NOT_DISPATCHED"), composer]) as prepare, \
                patch.object(runner, "_challenge_visible", side_effect=[True, True, True, False]), \
                patch("story_auto.providers.dola_cookie.browser_ui.time.monotonic", side_effect=[10, 11]):
            self.assertIs(runner._prepare_with_operator(page, duration=5, ratio="16:9"), composer)
        self.assertEqual(prepare.call_count, 2)
        page.bring_to_front.assert_called_once()
        page.wait_for_timeout.assert_called_once_with(500)
        page.context.close.assert_not_called()
        page.keyboard.press.assert_not_called()

    def test_manual_challenge_wait_preserves_browser_without_sending(self):
        runner = PatchrightDolaRunner(operator_visible=True)
        page = Mock()
        with patch.object(runner, "_challenge_visible", side_effect=[True, True, False]), \
                patch("story_auto.providers.dola_cookie.browser_ui.time.monotonic", side_effect=[10, 310]):
            elapsed = runner._wait_for_operator(page)
        self.assertEqual(elapsed, 300)
        page.wait_for_timeout.assert_called_once_with(500)
        page.bring_to_front.assert_called_once()
        page.keyboard.press.assert_not_called()
        page.context.close.assert_not_called()

    def test_profile_seed_preserves_existing_session_and_verification_cookies(self):
        context = Mock()
        context.cookies.return_value = [
            {"name": "sessionid", "value": "newer-session"},
            {"name": "msToken", "value": "newer-token"},
            {"name": "s_v_web_id", "value": "verification-fixture"},
        ]
        _seed_profile_cookies(context, _cookies_for_browser(COOKIE))
        context.add_cookies.assert_called_once_with([
            {"name": "store-idc", "value": "fixture-idc", "url": "https://www.dola.com/chat"}
        ])
        context.clear_cookies.assert_not_called()

    def test_empty_profile_is_seeded_once(self):
        context = Mock()
        seed = _cookies_for_browser(COOKIE)
        context.cookies.return_value = []
        _seed_profile_cookies(context, seed)
        context.cookies.return_value = seed
        _seed_profile_cookies(context, seed)
        context.add_cookies.assert_called_once_with(seed)
        context.clear_cookies.assert_not_called()

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

    def test_native_request_requires_exact_ui_prompt_ratio_duration_and_model(self):
        self.assertEqual(_native_request_id(_native_request(), "a river", "16:9", 5),
                         "native-1")
        for request in (
            _native_request(prompt="another prompt"),
            _native_request(text="a river"),
            _native_request(text="Generated video: a river, 9:16"),
            _native_request(text="Generated video: a river, 16:9 extra"),
            _native_request(text="Generated video: a river, 16:9, 16:9"),
            _native_request(ratio="9:16"),
            _native_request(ratio="9:16", text="Generated video: a river, 16:9"),
            _native_request(duration=10),
            _native_request(model="unknown"),
        ):
            with self.subTest(body=request.post_data_json):
                with self.assertRaisesRegex(DolaCookieError, "NATIVE_REQUEST_UNVERIFIED"):
                    _native_request_id(request, "a river", "16:9", 5)

    def test_native_id_is_durable_before_post_send_contract_rejection(self):
        for request in (_native_request(model="drifted"), _native_request(text="a river")):
            seen = []
            with self.subTest(body=request.post_data_json):
                with self.assertRaisesRegex(DolaCookieError, "NATIVE_REQUEST_UNVERIFIED"):
                    _native_request_id(request, "a river", "16:9", 5, seen.append)
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
                self.elapsed = 0.0
                self.page = Mock(url="https://www.dola.com/chat/12345")
                self.context = Mock(pages=[self.page])
                self.context.cookies.return_value = []
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
                self.page.on.side_effect = lambda event, callback: setattr(self, event, callback)
                self.page.wait_for_timeout.side_effect = self.advance
                self.send.click.side_effect = lambda **kwargs: self.request(request)

            def advance(self, milliseconds):
                self.elapsed += milliseconds / 1000

        request = _native_request()
        request.method = "POST"
        request.url = "https://www.dola.com/chat/completion?source=web"
        browser = Browser(request)
        reader = Mock()
        reader.verify_input.return_value = True
        reader.poll.return_value = {"status": "COMPLETED"}
        native, receipts = [], []
        with TemporaryDirectory() as directory, \
                patch("patchright.sync_api.sync_playwright", return_value=browser.manager), \
                patch("story_auto.providers.dola_cookie.browser_ui._profile_lease", return_value=nullcontext()), \
                patch("story_auto.providers.dola_cookie.browser_ui._bind_profile"), \
                patch("story_auto.providers.dola_cookie.browser_ui.time.monotonic", side_effect=lambda: browser.elapsed), \
                patch("story_auto.providers.dola_cookie.browser_ui._prepare_video_ui", return_value=Mock(evaluate=Mock(return_value=""))):
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
                patch("story_auto.providers.dola_cookie.browser_ui.time.monotonic", side_effect=lambda: browser.elapsed), \
                patch("story_auto.providers.dola_cookie.browser_ui._prepare_video_ui", return_value=Mock(evaluate=Mock(return_value=""))):
            with self.assertRaisesRegex(DolaCookieError, "NATIVE_REQUEST_UNVERIFIED"):
                PatchrightDolaRunner().run(
                    cookie=COOKIE, profile=Path(directory) / "profile", account_id="daily",
                    binding="a" * 64, prompt="a river", ratio="16:9", duration=5,
                    on_native_request=native.append, on_receipt=receipts.append, reader=Mock(),
                )
        self.assertEqual((native, receipts), (["native-1"], []))
        browser.send.click.assert_called_once()
        self.assertGreaterEqual(browser.elapsed, 180)

        browser = Browser(request)
        native, receipts = [], []
        def persist_failure(identifier):
            raise RuntimeError("journal unavailable")
        with TemporaryDirectory() as directory, \
                patch("patchright.sync_api.sync_playwright", return_value=browser.manager), \
                patch("story_auto.providers.dola_cookie.browser_ui._profile_lease", return_value=nullcontext()), \
                patch("story_auto.providers.dola_cookie.browser_ui._bind_profile"), \
                patch("story_auto.providers.dola_cookie.browser_ui.time.monotonic", side_effect=lambda: browser.elapsed), \
                patch("story_auto.providers.dola_cookie.browser_ui._prepare_video_ui", return_value=Mock(evaluate=Mock(return_value=""))):
            with self.assertRaisesRegex(DolaCookieError, "PERSIST_FAILED"):
                PatchrightDolaRunner().run(
                    cookie=COOKIE, profile=Path(directory) / "profile", account_id="daily",
                    binding="a" * 64, prompt="a river", ratio="16:9", duration=5,
                    on_native_request=persist_failure, on_receipt=receipts.append, reader=Mock(),
                )
        self.assertEqual(receipts, [])
        browser.send.click.assert_called_once()
        self.assertGreaterEqual(browser.elapsed, 180)

    def test_runner_waits_for_late_receipt_and_never_accepts_unlinked_media(self):
        class Browser:
            def __init__(self, *, numeric_at=None, media_at=None, click_error=False):
                self.elapsed = 0.0
                self.numeric_at = numeric_at
                self.media_at = media_at
                self.page = Mock(url="https://www.dola.com/chat/local_123")
                self.context = Mock(pages=[self.page])
                self.context.cookies.return_value = []
                playwright = Mock()
                playwright.chromium.launch_persistent_context.return_value = self.context
                self.manager = MagicMock()
                self.manager.__enter__.return_value = playwright
                self.send = Mock()
                self.send.is_visible.return_value = True
                self.page.locator.side_effect = self.locator
                self.page.get_by_text.return_value.count.return_value = 0
                self.page.on.side_effect = lambda event, callback: setattr(self, event, callback)
                self.page.wait_for_timeout.side_effect = self.advance
                self.send.click.side_effect = self.click
                self.click_error = click_error

            def locator(self, selector):
                result = Mock()
                if selector.startswith("button[type='submit']"):
                    result.count.return_value = 1
                    result.nth.return_value = self.send
                elif selector.startswith("video,"):
                    result.count.side_effect = lambda: int(
                        self.media_at is not None and self.elapsed >= self.media_at
                    )
                else:
                    result.evaluate_all.return_value = []
                return result

            def click(self, **kwargs):
                request = _native_request()
                request.method = "POST"
                request.url = "https://www.dola.com/chat/completion"
                self.request(request)
                unrelated = Mock(url="https://cdn.bytevcloud.com/other.mp4", status=200)
                self.response(unrelated)
                if self.click_error:
                    raise RuntimeError("click timed out after send")

            def advance(self, milliseconds):
                self.elapsed += milliseconds / 1000
                if self.numeric_at is not None and self.elapsed >= self.numeric_at:
                    self.page.url = "https://www.dola.com/chat/12345"

        def exercise(browser, *, verified, poll_status="COMPLETED"):
            reader = Mock()
            if isinstance(verified, Exception):
                reader.verify_input.side_effect = verified
            else:
                reader.verify_input.return_value = verified
            if isinstance(poll_status, list):
                reader.poll.side_effect = [{"status": status} for status in poll_status]
            else:
                reader.poll.return_value = {"status": poll_status}
            native, receipts = [], []
            with TemporaryDirectory() as directory, \
                    patch("patchright.sync_api.sync_playwright", return_value=browser.manager), \
                    patch("story_auto.providers.dola_cookie.browser_ui._profile_lease", return_value=nullcontext()), \
                    patch("story_auto.providers.dola_cookie.browser_ui._bind_profile"), \
                    patch("story_auto.providers.dola_cookie.browser_ui.time.monotonic", side_effect=lambda: browser.elapsed), \
                    patch("story_auto.providers.dola_cookie.browser_ui._prepare_video_ui", return_value=Mock(evaluate=Mock(return_value=""))):
                try:
                    result = PatchrightDolaRunner().run(
                        cookie=COOKIE, profile=Path(directory) / "profile", account_id="daily",
                        binding="a" * 64, prompt="a river", ratio="16:9", duration=5,
                        on_native_request=native.append, on_receipt=receipts.append, reader=reader,
                    )
                except DolaCookieError as error:
                    result = error.failure_class
                    browser.read_diagnostic = error.read_diagnostic
            return result, native, receipts, reader

        late = Browser(numeric_at=65, click_error=True)
        result, native, receipts, reader = exercise(
            late, verified=True, poll_status=["PENDING", "COMPLETED"]
        )
        self.assertEqual((result, native, receipts), ("12345", ["native-1"], ["12345"]))
        self.assertGreaterEqual(late.elapsed, 70)
        self.assertLess(late.elapsed, 180)
        late.send.click.assert_called_once()
        reader.verify_input.assert_called_with("12345", "native-1")
        late.context.close.assert_called_once()

        pending = Browser(numeric_at=5)
        result, native, receipts, reader = exercise(pending, verified=True,
                                                    poll_status="PENDING")
        self.assertEqual((result, native, receipts), ("12345", ["native-1"], ["12345"]))
        self.assertGreaterEqual(pending.elapsed, 180)
        pending.send.click.assert_called_once()
        self.assertGreater(reader.poll.call_count, 1)

        unverified = Browser(numeric_at=5)
        result, native, receipts, reader = exercise(unverified, verified=False)
        self.assertEqual((result, native, receipts),
                         ("DOLA_UI_RESULT_IDENTITY_UNVERIFIED", ["native-1"], []))
        self.assertGreaterEqual(unverified.elapsed, 180)
        unverified.send.click.assert_called_once()
        reader.poll.assert_not_called()

        read_failure = Browser(numeric_at=5)
        result, native, receipts, reader = exercise(
            read_failure, verified=DolaCookieError("PROVIDER_TRANSIENT", "AMBIGUOUS")
        )
        self.assertEqual((result, receipts), ("DOLA_UI_RESULT_IDENTITY_UNVERIFIED", []))
        self.assertEqual(read_failure.read_diagnostic,
                         "PROVIDER_TRANSIENT|PROVIDER_TRANSIENT")
        self.assertGreaterEqual(read_failure.elapsed, 180)

        contradictory = Browser(numeric_at=5)
        result, native, receipts, reader = exercise(
            contradictory,
            verified=DolaCookieError("DOLA_RESULT_IDENTITY_MISMATCH", "AMBIGUOUS"),
        )
        self.assertEqual((result, receipts), ("DOLA_RESULT_IDENTITY_MISMATCH", []))
        self.assertGreaterEqual(contradictory.elapsed, 180)
        reader.poll.assert_not_called()

        unrelated_media = Browser(media_at=10)
        result, native, receipts, reader = exercise(unrelated_media, verified=False)
        self.assertEqual((result, native, receipts),
                         ("DOLA_UI_MEDIA_UNATTRIBUTED", ["native-1"], []))
        self.assertGreaterEqual(unrelated_media.elapsed, 180)
        unrelated_media.send.click.assert_called_once()
        reader.poll.assert_not_called()


if __name__ == "__main__":
    unittest.main()

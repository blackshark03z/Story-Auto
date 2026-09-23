"""Opt-in Dola browser-UI submit; no automatic retry or CAPTCHA handling.

The browser performs only the first send action. Existing Dola read/download
code remains responsible for exact-result polling and cookie-free acquisition.
This module is not selected by the default provider routing.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Callable
from urllib.parse import urlsplit

from .accounts import _COOKIE_NAME
from .client import DolaCookieClient, DolaCookieError


CHAT_URL = "https://www.dola.com/chat"
_SESSION_NAMES = {"sessionid", "sessionid_ss"}
_LOGIN = re.compile(r"^(?:log\s?in|sign\s?in|đăng nhập|ログイン|登录|登入)$", re.I)
_VIDEO_ENTRIES = ("Create Videos", "Tạo video", "Create video", "動画生成", "生成视频")
_LOCAL_ID = re.compile(r"[A-Za-z0-9_-]{1,160}")
_CONVERSATION_URL = re.compile(r"^https://(?:www\.)?dola\.com/chat/([0-9]{3,40})(?:[/?#].*)?$")
_DOLA_HOSTS = {"dola.com", "www.dola.com"}


def _cookies_for_browser(header: str) -> list[dict[str, str]]:
    if not isinstance(header, str) or "\r" in header or "\n" in header:
        raise DolaCookieError("DOLA_COOKIE_HEADER_INVALID", "NOT_DISPATCHED")
    rows = []
    names = set()
    for part in header.split(";"):
        name, separator, value = part.strip().partition("=")
        if (not separator or not _COOKIE_NAME.fullmatch(name) or not value or name in names
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise DolaCookieError("DOLA_COOKIE_HEADER_INVALID", "NOT_DISPATCHED")
        names.add(name)
        rows.append({"name": name, "value": value, "url": CHAT_URL})
    if not (names & _SESSION_NAMES):
        raise DolaCookieError("CREDENTIAL_MISSING", "NOT_DISPATCHED")
    return rows


def _native_request_id(request, prompt: str, ratio: str, duration: int,
                       on_identified: Callable[[str], None] | None = None) -> str:
    """Check the app's own outgoing request, never construct or replay it."""
    try:
        body = request.post_data_json
        if not isinstance(body, dict):
            raise ValueError("BODY")
        messages = body.get("messages")
        if not isinstance(messages, list) or len(messages) != 1 or not isinstance(messages[0], dict):
            raise ValueError("MESSAGES")
        message = messages[0]
        identifier = message.get("local_message_id")
        if not isinstance(identifier, str) or not _LOCAL_ID.fullmatch(identifier):
            raise ValueError("LOCAL_ID")
        # Preserve the app-generated ID before checking the remaining wire
        # shape. A post-send contract mismatch still needs reconciliation.
        if on_identified is not None:
            on_identified(identifier)
        blocks = message.get("content_block")
        texts = [((block.get("content") or {}).get("text_block") or {}).get("text")
                 for block in blocks if isinstance(block, dict) and block.get("block_type") == 10000] if isinstance(blocks, list) else []
        if len(texts) != 1 or not isinstance(texts[0], str) or texts[0].strip() != prompt.strip():
            raise ValueError("PROMPT")
        ability = body.get("chat_ability") or {}
        params = json.loads(ability.get("ability_param", "{}"))
        if (ability.get("ability_type") != 17 or params.get("ratio") != ratio
                or params.get("duration") != duration or params.get("model") != "seedance_v2.0"):
            raise ValueError("SETTINGS")
        return identifier
    except (AttributeError, TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise DolaCookieError("DOLA_NATIVE_REQUEST_UNVERIFIED", "AMBIGUOUS") from error


@contextmanager
def _profile_lease(profile: Path):
    """Process-level lease independent of Story Auto's runtime-root locks."""
    profile.parent.mkdir(parents=True, exist_ok=True)
    lease_path = profile.parent / (profile.name + ".story-auto.lock")
    with lease_path.open("a+b") as handle:
        handle.seek(0)
        if handle.read(1) != b"1":
            handle.seek(0)
            handle.write(b"1")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise DolaCookieError("DOLA_PROFILE_BUSY", "NOT_DISPATCHED") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _bind_profile(profile: Path, account_id: str, binding: str) -> None:
    marker = profile / ".story-auto-dola-binding.json"
    if marker.exists():
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise DolaCookieError("DOLA_PROFILE_BINDING_INVALID", "NOT_DISPATCHED") from error
        if value != {"account_id": account_id, "binding": binding}:
            raise DolaCookieError("DOLA_PROFILE_BINDING_MISMATCH", "NOT_DISPATCHED")
        return
    if profile.exists() and any(profile.iterdir()):
        raise DolaCookieError("DOLA_PROFILE_UNBOUND", "NOT_DISPATCHED")
    profile.mkdir(parents=True, exist_ok=True)
    with marker.open("x", encoding="utf-8") as stream:
        json.dump({"account_id": account_id, "binding": binding}, stream)


def _one_visible(locator):
    visible = [locator.nth(index) for index in range(locator.count())
               if locator.nth(index).is_visible()]
    return visible[0] if len(visible) == 1 else None


def _send_once(page, composer) -> None:
    """Choose the action before dispatch; a failed click never becomes Enter."""
    send = _one_visible(page.locator("button[type='submit'], [aria-label='Send'], [aria-label='Gửi']"))
    if send is not None:
        send.click(timeout=5000)
    else:
        composer.press("Enter", timeout=5000)


def _prepare_video_ui(page, *, duration: int, ratio: str):
    """Only local UI setup. This function never enters a prompt or sends."""
    response = page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=45000)
    if (not response or response.status != 200
            or urlsplit(page.url).hostname not in _DOLA_HOSTS):
        raise DolaCookieError("DOLA_BROWSER_AUTH_UNVERIFIED", "NOT_DISPATCHED")
    entry = None
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        for label in _VIDEO_ENTRIES:
            entry = _one_visible(page.get_by_text(label, exact=True))
            if entry is not None:
                break
        if entry is not None:
            break
        page.wait_for_timeout(500)
    if entry is None:
        raise DolaCookieError("DOLA_VIDEO_MODE_UNAVAILABLE", "NOT_DISPATCHED")
    labels = page.locator("button, [role='button']").all_text_contents()
    if any(_LOGIN.fullmatch(label.strip()) for label in labels):
        raise DolaCookieError("DOLA_BROWSER_AUTH_UNVERIFIED", "NOT_DISPATCHED")
    entry.click(timeout=5000)
    page.wait_for_timeout(500)
    model = _one_visible(page.get_by_text("2.0 Fast", exact=True))
    if (model is None or " ".join(
            (model.evaluate("element => element.parentElement?.textContent ?? ''") or "").split()
    ) != "Model 2.0 Fast"):
        raise DolaCookieError("DOLA_MODEL_UNVERIFIED", "NOT_DISPATCHED")
    if duration == 5:
        current = _one_visible(page.get_by_text("10s", exact=True))
        if current is None:
            raise DolaCookieError("DOLA_DURATION_UNVERIFIED", "NOT_DISPATCHED")
        current.click(timeout=5000)
        option = _one_visible(page.get_by_text("5s", exact=True))
        if option is None:
            raise DolaCookieError("DOLA_DURATION_UNVERIFIED", "NOT_DISPATCHED")
        option.click(timeout=5000)
    elif duration != 10 or _one_visible(page.get_by_text("10s", exact=True)) is None:
        raise DolaCookieError("DOLA_DURATION_UNVERIFIED", "NOT_DISPATCHED")
    ratio_menu = _one_visible(page.get_by_text("Ratio", exact=True))
    if ratio != "16:9" or ratio_menu is None:
        raise DolaCookieError("DOLA_RATIO_UNVERIFIED", "NOT_DISPATCHED")
    ratio_menu.click(timeout=5000)
    ratio_option = _one_visible(page.get_by_text("16:9", exact=True))
    if ratio_option is None:
        raise DolaCookieError("DOLA_RATIO_UNVERIFIED", "NOT_DISPATCHED")
    ratio_option.click(timeout=5000)
    composer = _one_visible(page.locator("textarea, [contenteditable='true']"))
    if composer is None or _CONVERSATION_URL.fullmatch(page.url):
        raise DolaCookieError("DOLA_NEW_CHAT_UNVERIFIED", "NOT_DISPATCHED")
    if _one_visible(page.get_by_text(re.compile(r"captcha|verify|xác minh|滑块", re.I))):
        raise DolaCookieError("DOLA_NEEDS_OPERATOR", "NOT_DISPATCHED")
    return composer


class PatchrightDolaRunner:
    """One native page send, followed only by read-only identity checks."""

    def preflight(self, *, cookie: str, profile: Path, account_id: str,
                  binding: str, ratio: str, duration: int) -> dict[str, object]:
        """Exercise the same pre-send controls with an empty composer."""
        seed = _cookies_for_browser(cookie)
        try:
            from patchright.sync_api import sync_playwright
        except ImportError as error:
            raise DolaCookieError("DOLA_BROWSER_DEPENDENCY_MISSING", "NOT_DISPATCHED") from error
        with _profile_lease(profile):
            _bind_profile(profile, account_id, binding)
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    str(profile), headless=True, locale="en-US",
                    viewport={"width": 1440, "height": 900},
                )
                try:
                    context.clear_cookies()
                    context.add_cookies(seed)
                    page = context.pages[0] if context.pages else context.new_page()
                    composer = _prepare_video_ui(page, duration=duration, ratio=ratio)
                    if composer.evaluate("element => element.value ?? element.textContent ?? ''").strip() or _CONVERSATION_URL.fullmatch(page.url):
                        raise DolaCookieError("DOLA_PREFLIGHT_NOT_EMPTY", "NOT_DISPATCHED")
                    return {"status": "UI_READY_NO_SUBMIT", "account_id": account_id,
                            "ratio": ratio, "duration": duration, "generation_submits": 0}
                finally:
                    context.close()

    def run(self, *, cookie: str, profile: Path, account_id: str, binding: str,
            prompt: str, ratio: str, duration: int,
            on_native_request: Callable[[str], None], on_receipt: Callable[[str], None],
            reader: DolaCookieClient) -> str:
        seed = _cookies_for_browser(cookie)
        try:
            from patchright.sync_api import sync_playwright
        except ImportError as error:
            raise DolaCookieError("DOLA_BROWSER_DEPENDENCY_MISSING", "NOT_DISPATCHED") from error
        with _profile_lease(profile):
            _bind_profile(profile, account_id, binding)
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    str(profile), headless=True, locale="en-US",
                    viewport={"width": 1440, "height": 900},
                )
                try:
                    context.clear_cookies()
                    context.add_cookies(seed)
                    page = context.pages[0] if context.pages else context.new_page()
                    composer = _prepare_video_ui(page, duration=duration, ratio=ratio)
                    composer.fill(prompt)
                    if _one_visible(page.get_by_text(re.compile(r"captcha|verify|xác minh|滑块", re.I))):
                        raise DolaCookieError("DOLA_NEEDS_OPERATOR", "NOT_DISPATCHED")

                    native_ids: list[str] = []
                    problems: list[str] = []
                    def observe(request):
                        parsed = urlsplit(request.url)
                        if (request.method != "POST" or parsed.scheme != "https"
                                or parsed.hostname not in _DOLA_HOSTS or parsed.path != "/chat/completion"):
                            return
                        try:
                            def remember(identifier):
                                if native_ids:
                                    raise DolaCookieError("DOLA_MULTIPLE_NATIVE_REQUESTS", "AMBIGUOUS")
                                native_ids.append(identifier)
                                on_native_request(identifier)
                            _native_request_id(request, prompt, ratio, duration, remember)
                        except DolaCookieError as error:
                            problems.append(error.failure_class)
                        except Exception:
                            problems.append("DOLA_NATIVE_REQUEST_PERSIST_FAILED")
                    page.on("request", observe)
                    _send_once(page, composer)
                    deadline = time.monotonic() + 45
                    conversation_id = None
                    verified = False
                    while time.monotonic() < deadline:
                        if problems:
                            raise DolaCookieError(problems[0], "AMBIGUOUS")
                        matched = _CONVERSATION_URL.fullmatch(page.url)
                        if matched and len(native_ids) == 1:
                            conversation_id = matched.group(1)
                            try:
                                if reader.verify_input(conversation_id, native_ids[0]):
                                    verified = True
                                    break
                            except DolaCookieError:
                                pass
                        page.wait_for_timeout(1500)
                    if not conversation_id or len(native_ids) != 1:
                        raise DolaCookieError("DOLA_UI_RECEIPT_MISSING", "AMBIGUOUS")
                    if not verified:
                        raise DolaCookieError("DOLA_UI_RESULT_IDENTITY_UNVERIFIED", "AMBIGUOUS")
                    on_receipt(conversation_id)
                    return conversation_id
                finally:
                    context.close()


class DolaBrowserUIClient:
    """Explicitly constructed opt-in client for a single named account/profile."""
    transport = "browser_ui"

    def __init__(self, cookie: str, *, account_id: str, profile_dir: Path,
                 runner: PatchrightDolaRunner | None = None) -> None:
        if not isinstance(account_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", account_id):
            raise DolaCookieError("DOLA_ACCOUNT_REQUIRED", "NOT_DISPATCHED")
        self._reader = DolaCookieClient(cookie)
        self._verification_reader = DolaCookieClient(cookie, timeout=5.0)
        self._cookie = cookie
        self._account_id = account_id
        # A refreshed cookie set gets a fresh profile, not stale localStorage
        # from the previous signed-in account. The digest is not a credential.
        cookie_digest = hashlib.sha256(cookie.encode("utf-8")).hexdigest()
        self._profile = Path(profile_dir).resolve() / cookie_digest[:16]
        self.profile_binding = hashlib.sha256(
            (account_id + "\0" + str(self._profile).casefold() + "\0" + cookie_digest).encode("utf-8")
        ).hexdigest()
        self._runner = runner or PatchrightDolaRunner()

    def preflight(self, *, aspect_ratio: str = "16:9", duration: int = 5) -> dict[str, object]:
        if aspect_ratio != "16:9" or duration not in {5, 10}:
            raise DolaCookieError("CAPABILITY_OR_REQUEST_INVALID", "NOT_DISPATCHED")
        return self._runner.preflight(cookie=self._cookie, profile=self._profile,
                                      account_id=self._account_id, binding=self.profile_binding,
                                      ratio=aspect_ratio, duration=duration)

    def submit(self, prompt: str, aspect_ratio: str, duration: int,
               on_receipt: Callable[[str], None], *, client_request_id: str | None = None,
               on_native_request: Callable[[str], None]) -> str:
        if (not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 10_000
                or aspect_ratio != "16:9" or duration not in {5, 10}
                or not callable(on_native_request)):
            raise DolaCookieError("CAPABILITY_OR_REQUEST_INVALID", "NOT_DISPATCHED")
        return self._runner.run(
            cookie=self._cookie, profile=self._profile, account_id=self._account_id,
            binding=self.profile_binding, prompt=prompt, ratio=aspect_ratio,
            duration=duration, on_native_request=on_native_request,
            on_receipt=on_receipt, reader=self._verification_reader,
        )

    def poll(self, conversation_id: str, *, client_request_id: str | None = None) -> dict[str, str]:
        return self._reader.poll(conversation_id, client_request_id=client_request_id)

    def download(self, video_url: str, destination: Path) -> dict:
        return self._reader.download(video_url, destination)

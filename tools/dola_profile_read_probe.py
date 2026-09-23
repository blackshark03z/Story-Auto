"""Qualify a closed, owner-signed-in Dola Chrome profile without generation.

Only boolean authentication indicators and cookie *names* leave the browser.
Run only after Chrome has released the profile directory.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


CHAT_URL = "https://www.dola.com/chat"
LOGIN_LABEL = re.compile(r"^(?:log\s?in|login|sign\s?in|đăng nhập|ログイン|登录|登入)$", re.I)
VIDEO_LABEL = re.compile(r"^(?:create|make|generate|tạo|làm|生成|作成|制作).{0,12}(?:video|vidéo|影片|视频|動画)$", re.I)
SESSION_NAMES = frozenset({"sessionid", "sessionid_ss"})


def _sample(page, context) -> dict[str, object]:
    response = page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3000)
    labels = page.locator("button, [role='button']").all_text_contents()
    login_visible = any(LOGIN_LABEL.fullmatch(label.strip()) for label in labels)
    video_entry_visible = any(VIDEO_LABEL.fullmatch(label.strip()) for label in labels)
    names = {cookie["name"] for cookie in context.cookies(CHAT_URL)}
    return {
        "http_status": response.status if response else None,
        "final_host": urlsplit(page.url).hostname,
        "login_button_visible": login_visible,
        "video_entry_visible": video_entry_visible,
        "session_cookie_names": sorted(names & SESSION_NAMES),
    }


def _qualified(control: dict[str, object], profile: dict[str, object]) -> bool:
    return (
        control["http_status"] == 200
        and profile["http_status"] == 200
        and control["final_host"] == profile["final_host"] == "www.dola.com"
        and control["login_button_visible"] is True
        and profile["login_button_visible"] is False
        and bool(profile["session_cookie_names"])
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    profile = args.profile.resolve(strict=True)
    output = args.output.resolve()
    if not (profile / "Default").is_dir():
        parser.error("PROFILE_DEFAULT_MISSING")
    if output.exists():
        parser.error("OUTPUT_EXISTS")

    result: dict[str, object] = {
        "schema": "story-auto-dola-profile-read-probe/1",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "read-only Dola chat UI; no prompt or generation",
        "provider_generation_submits": 0,
        "cookie_values_recorded": False,
    }
    try:
        with sync_playwright() as playwright:
            control_browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                control_context = control_browser.new_context()
                result["unauthenticated_control"] = _sample(
                    control_context.new_page(), control_context
                )
            finally:
                control_browser.close()

            samples = []
            for _ in range(2):
                context = playwright.chromium.launch_persistent_context(
                    str(profile), channel="chrome", headless=True
                )
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    samples.append(_sample(page, context))
                finally:
                    context.close()
            result["profile_after_restart"] = samples
            result["status"] = (
                "BROWSER_AUTH_READ_PASS"
                if all(_qualified(result["unauthenticated_control"], item) for item in samples)
                else "BROWSER_AUTH_NOT_VERIFIED"
            )
    except Exception as error:
        result["status"] = "PROBE_UNAVAILABLE"
        result["error_type"] = type(error).__name__

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "BROWSER_AUTH_READ_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

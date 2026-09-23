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
VIDEO_LABEL = re.compile(r"^(?:create|make|generate|tạo|làm|生成|作成|制作).{0,12}(?:videos?|vidéos?|影片|视频|動画)$", re.I)
VIDEO_ENTRY_LABELS = (
    "Tạo video", "Create video", "Create Videos", "Make video", "Generate video",
    "動画を作成", "動画生成", "生成视频", "生成影片", "创建视频",
)
SESSION_NAMES = frozenset({"sessionid", "sessionid_ss"})


def _sample(page, context) -> dict[str, object]:
    response = page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3000)
    labels = page.locator("button, [role='button']").all_text_contents()
    login_visible = any(LOGIN_LABEL.fullmatch(label.strip()) for label in labels)
    video_entry_visible = any(VIDEO_LABEL.fullmatch(label.strip()) for label in labels)
    visible_video_labels = [
        label for label in VIDEO_ENTRY_LABELS
        if any(locator.is_visible() for locator in page.get_by_text(label, exact=True).all()[:10])
    ]
    names = {cookie["name"] for cookie in context.cookies(CHAT_URL)}
    return {
        "http_status": response.status if response else None,
        "final_host": urlsplit(page.url).hostname,
        "login_button_visible": login_visible,
        "video_entry_visible": video_entry_visible,
        "visible_video_labels": visible_video_labels,
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
    parser.add_argument("--composer-screenshot", type=Path,
                        help="Optional cropped new-chat composer image for UI inspection")
    parser.add_argument("--video-preflight-screenshot", type=Path,
                        help="Open video mode without prompt or submit, then crop its controls")
    parser.add_argument("--options-preflight-screenshot", type=Path,
                        help="Inspect duration and ratio menus without selecting or submitting")
    parser.add_argument("--model-preflight-screenshot", type=Path,
                        help="Inspect video model menu without selecting or submitting")
    parser.add_argument("--selection-preflight-screenshot", type=Path,
                        help="Select 5s and 16:9 locally without entering a prompt or submitting")
    parser.add_argument("--replay-profile-cookies", action="store_true",
                        help="Replay current profile cookies in a fresh browser, in memory only")
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
            replay_cookies = None
            for _ in range(2):
                context = playwright.chromium.launch_persistent_context(
                    str(profile), channel="chrome", headless=True,
                    viewport={"width": 1440, "height": 900},
                )
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    samples.append(_sample(page, context))
                    if len(samples) == 1 and args.replay_profile_cookies:
                        replay_cookies = context.cookies(CHAT_URL)
                    if len(samples) == 1 and args.composer_screenshot:
                        # Crop near the empty composer, not the sidebar/history.
                        if page.url.rstrip("/") == CHAT_URL:
                            composer = page.locator("textarea, [contenteditable='true']").first
                            box = composer.bounding_box() if composer.count() else None
                            if box:
                                x = max(350, box["x"] - 100)
                                y = max(0, box["y"] - 100)
                                width = min(1440 - x, box["width"] + 200)
                                height = min(900 - y, box["height"] + 150)
                                args.composer_screenshot.parent.mkdir(parents=True, exist_ok=True)
                                page.screenshot(path=str(args.composer_screenshot),
                                                clip={"x": x, "y": y,
                                                      "width": width, "height": height})
                                result["composer_screenshot_saved"] = True
                    if len(samples) == 1 and args.video_preflight_screenshot:
                        if _qualified(result["unauthenticated_control"], samples[0]):
                            entry = page.get_by_text("Create Videos", exact=True)
                            if entry.count() == 1 and entry.is_visible():
                                entry.click(timeout=5000)
                                page.wait_for_timeout(1000)
                                if page.url.rstrip("/") == CHAT_URL:
                                    args.video_preflight_screenshot.parent.mkdir(parents=True, exist_ok=True)
                                    page.screenshot(path=str(args.video_preflight_screenshot),
                                                    clip={"x": 350, "y": 520,
                                                          "width": 1090, "height": 380})
                                    result["video_mode_selected_without_submit"] = True
                    if len(samples) == 1 and args.options_preflight_screenshot:
                        if _qualified(result["unauthenticated_control"], samples[0]):
                            entry = page.get_by_text("Create Videos", exact=True)
                            if entry.count() == 1 and entry.is_visible():
                                entry.click(timeout=5000)
                                page.wait_for_timeout(500)
                                duration = page.get_by_text("10s", exact=True)
                                if duration.count() == 1 and duration.is_visible():
                                    duration.click(timeout=5000)
                                    result["visible_duration_options"] = [
                                        label for label in ("5s", "10s", "15s", "30s")
                                        if any(loc.is_visible() for loc in page.get_by_text(label, exact=True).all()[:10])
                                    ]
                                    page.keyboard.press("Escape")
                                ratio = page.get_by_text("Ratio", exact=True)
                                if ratio.count() == 1 and ratio.is_visible():
                                    ratio.click(timeout=5000)
                                    result["visible_ratio_options"] = [
                                        label for label in ("16:9", "9:16", "1:1", "4:3", "3:4")
                                        if any(loc.is_visible() for loc in page.get_by_text(label, exact=True).all()[:10])
                                    ]
                                    args.options_preflight_screenshot.parent.mkdir(parents=True, exist_ok=True)
                                    page.screenshot(path=str(args.options_preflight_screenshot),
                                                    clip={"x": 350, "y": 480,
                                                          "width": 1090, "height": 420})
                                    result["options_inspected_without_selection_or_submit"] = True
                    if len(samples) == 1 and args.model_preflight_screenshot:
                        if _qualified(result["unauthenticated_control"], samples[0]):
                            entry = page.get_by_text("Create Videos", exact=True)
                            if entry.count() == 1 and entry.is_visible():
                                entry.click(timeout=5000)
                                page.wait_for_timeout(500)
                                model = page.get_by_text("2.0 Fast", exact=True)
                                if model.count() == 1 and model.is_visible():
                                    model.click(timeout=5000)
                                    args.model_preflight_screenshot.parent.mkdir(parents=True, exist_ok=True)
                                    page.screenshot(path=str(args.model_preflight_screenshot),
                                                    clip={"x": 350, "y": 420,
                                                          "width": 1090, "height": 480})
                                    result["model_menu_inspected_without_selection_or_submit"] = True
                    if len(samples) == 1 and args.selection_preflight_screenshot:
                        result["selection_step"] = "AUTH_NOT_VERIFIED"
                        if _qualified(result["unauthenticated_control"], samples[0]):
                            result["selection_step"] = "AUTH_VERIFIED"
                            entry = page.get_by_text("Create Videos", exact=True)
                            if entry.count() == 1 and entry.is_visible():
                                entry.click(timeout=5000)
                                page.wait_for_timeout(500)
                                result["selection_step"] = "VIDEO_MODE_OPEN"
                                duration = page.get_by_text("10s", exact=True)
                                if duration.count() == 1 and duration.is_visible():
                                    duration.click(timeout=5000)
                                    result["selection_step"] = "DURATION_MENU_OPEN"
                                    choice = page.get_by_text("5s", exact=True)
                                    if choice.count() == 1 and choice.is_visible():
                                        choice.click(timeout=5000)
                                        result["selection_step"] = "5S_SELECTED"
                                        ratio = page.get_by_text("Ratio", exact=True)
                                        if ratio.count() == 1 and ratio.is_visible():
                                            ratio.click(timeout=5000)
                                            result["selection_step"] = "RATIO_MENU_OPEN"
                                            widescreen = page.get_by_text("16:9", exact=True)
                                            if widescreen.count() == 1 and widescreen.is_visible():
                                                widescreen.click(timeout=5000)
                                                result["selection_step"] = "16_9_SELECTED"
                                                result["selected_5s_16_9_without_prompt_or_submit"] = (
                                                    page.get_by_text("5s", exact=True).count() == 1
                                                    and page.get_by_text("16:9", exact=True).count() == 1
                                                )
                                                args.selection_preflight_screenshot.parent.mkdir(parents=True, exist_ok=True)
                                                page.screenshot(path=str(args.selection_preflight_screenshot),
                                                                clip={"x": 350, "y": 520,
                                                                      "width": 1090, "height": 380})
                finally:
                    context.close()
            result["profile_after_restart"] = samples
            if replay_cookies is not None:
                replay_browser = playwright.chromium.launch(channel="chrome", headless=True)
                try:
                    replay_context = replay_browser.new_context()
                    replay_context.add_cookies(replay_cookies)
                    result["fresh_context_profile_cookie_replay"] = _sample(
                        replay_context.new_page(), replay_context
                    )
                    result["cookie_replay_auth_distinguished"] = _qualified(
                        result["unauthenticated_control"],
                        result["fresh_context_profile_cookie_replay"],
                    )
                finally:
                    replay_browser.close()
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

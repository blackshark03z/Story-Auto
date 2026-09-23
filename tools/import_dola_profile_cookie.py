"""Import a qualified Dola profile session into a new encrypted account alias.

This never prints or writes plaintext cookie values. It never submits a video.
Close the owner Chrome window for this profile before running it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from story_auto.providers.dola_cookie.accounts import (
    DolaAccountStore, _header_from_cookie_editor,
)
from tools.dola_profile_read_probe import CHAT_URL, _qualified, _sample


def _browser_cookies_from_header(header: str) -> list[dict[str, str]]:
    """Use one target URL; no domain/path attributes are persisted in DPAPI."""
    return [
        {"name": name, "value": value, "url": CHAT_URL}
        for pair in header.split("; ")
        for name, value in [pair.split("=", 1)]
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--save", action="store_true", help="Save only after read-only replay passes")
    args = parser.parse_args()
    profile = args.profile.resolve(strict=True)
    if not (profile / "Default").is_dir():
        parser.error("PROFILE_DEFAULT_MISSING")
    store = DolaAccountStore()
    if any(item["account_id"] == args.alias for item in store.list_accounts()):
        parser.error("ALIAS_ALREADY_EXISTS")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            blank = browser.new_context()
            control = _sample(blank.new_page(), blank)
        finally:
            browser.close()
        profile_context = playwright.chromium.launch_persistent_context(
            str(profile), channel="chrome", headless=True,
        )
        try:
            page = profile_context.pages[0] if profile_context.pages else profile_context.new_page()
            source = _sample(page, profile_context)
            rows = profile_context.cookies(CHAT_URL)
        finally:
            profile_context.close()
        if not _qualified(control, source):
            print(json.dumps({"status": "PROFILE_AUTH_NOT_VERIFIED", "saved": False}))
            return 2

        header = _header_from_cookie_editor(rows)
        replay_browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            replay = replay_browser.new_context()
            replay.add_cookies(_browser_cookies_from_header(header))
            replay_result = _sample(replay.new_page(), replay)
        finally:
            replay_browser.close()
        if not _qualified(control, replay_result):
            print(json.dumps({"status": "COOKIE_REPLAY_NOT_VERIFIED", "saved": False}))
            return 2

    if args.save:
        store.save_accounts([{"account_id": args.alias, "cookie": header}])
    print(json.dumps({"status": "SAVED" if args.save else "READY_TO_SAVE",
                      "account_id": args.alias, "saved": args.save,
                      "cookie_count": len(_browser_cookies_from_header(header)),
                      "generation_submits": 0, "cookie_values_recorded": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

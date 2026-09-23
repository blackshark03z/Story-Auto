"""Read-only positive/negative Dola browser control for one saved alias."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from story_auto.providers.dola_cookie.accounts import DolaAccountStore
from tools.dola_profile_read_probe import _qualified, _sample
from tools.import_dola_profile_cookie import _browser_cookies_from_header


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("OUTPUT_EXISTS")
    result: dict[str, object] = {
        "schema": "story-auto-dola-saved-cookie-read/1",
        "account_id": args.alias,
        "scope": "read-only Dola chat UI; no prompt or generation",
        "generation_submits": 0,
        "cookie_values_recorded": False,
    }
    try:
        header = DolaAccountStore().get_cookie(args.alias)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                blank = browser.new_context()
                result["unauthenticated_control"] = _sample(blank.new_page(), blank)
                saved = browser.new_context()
                saved.add_cookies(_browser_cookies_from_header(header))
                result["saved_alias"] = _sample(saved.new_page(), saved)
            finally:
                browser.close()
        result["status"] = (
            "SAVED_COOKIE_BROWSER_AUTH_READ_PASS"
            if _qualified(result["unauthenticated_control"], result["saved_alias"])
            else "SAVED_COOKIE_BROWSER_AUTH_NOT_VERIFIED"
        )
    except Exception as error:
        result["status"] = "PROBE_UNAVAILABLE"
        result["error_type"] = type(error).__name__
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "SAVED_COOKIE_BROWSER_AUTH_READ_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

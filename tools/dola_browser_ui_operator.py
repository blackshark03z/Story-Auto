"""Open the third canary's exact bound profile for manual operator verification.

No automated prompt entry, send, challenge solving, or generation retry.
Close the browser window when finished; the profile lease lasts until then.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from patchright.sync_api import sync_playwright, Error
from tools.dola_browser_ui_third_canary import client
from story_auto.providers.dola_cookie.browser_ui import (
    CHAT_URL, _profile_lease, _bind_profile, _cookies_for_browser, _seed_profile_cookies,
)


def main():
    active = client()
    with _profile_lease(active._profile):
        _bind_profile(active._profile, active._account_id, active.profile_binding)
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(active._profile), headless=False, locale="en-US",
                viewport={"width": 1280, "height": 800},
            )
            try:
                _seed_profile_cookies(context, _cookies_for_browser(active._cookie))
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=45000)
                page.bring_to_front()
                print("OPERATOR_BROWSER_OPEN; automatic_generation_submits=0; close window when finished", flush=True)
                while context.pages:
                    try:
                        context.pages[0].wait_for_timeout(500)
                    except Error:
                        if not context.pages:
                            break
                        raise
            finally:
                context.close()
                print("OPERATOR_BROWSER_CLOSED; verification_outcome_not_inferred", flush=True)


if __name__ == "__main__":
    main()

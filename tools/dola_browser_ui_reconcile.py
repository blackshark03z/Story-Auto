"""Read-only exact-native-ID search for an ambiguous browser-UI canary.

An absent recent match never proves the provider had no effect. This tool
cannot submit, adopt a receipt, or make a replacement attempt.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

from story_auto.providers.dola_cookie.accounts import DolaAccountStore
from story_auto.providers.dola_cookie.client import DolaCookieClient, DolaCookieError
from tools.dola_browser_ui_canary import ACCOUNT_ID, SLOT_ID, _manifest
from tools.dola_cookie_attempt_reconcile import _matches
from tools.dola_readonly_conversation_shape import _post_json, _recent, _single_body
from tools.import_dola_profile_cookie import _browser_cookies_from_header


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("OUTPUT_EXISTS")
    manifest = _manifest()
    slot = next(item for item in manifest["slots"] if item["slot_id"] == SLOT_ID)
    attempt = slot.get("api_generation") or {}
    if (attempt.get("provider") != "dola_cookie"
            or attempt.get("transport") != "browser_ui"
            or attempt.get("account_id") != ACCOUNT_ID
            or attempt.get("status") != "AMBIGUOUS"
            or attempt.get("submit_attempts") != 1
            or attempt.get("provider_task_id")
            or not attempt.get("provider_local_message_id")):
        raise SystemExit("EXACT_AMBIGUOUS_NATIVE_ATTEMPT_REQUIRED")
    native_id = attempt["provider_local_message_id"]
    result: dict[str, object] = {
        "schema": "story-auto-dola-browser-ui-ambiguous-read/1",
        "scope": "read-only recent/single chain lookup for one native UI input ID",
        "generation_submits": 0, "cookie_values_recorded": False,
        "provider_ids_recorded": False, "message_content_recorded": False,
        "attempt_id": attempt["attempt_id"], "saved_status": "AMBIGUOUS",
    }
    try:
        cookie = DolaAccountStore().get_cookie(ACCOUNT_ID)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context()
                context.add_cookies(_browser_cookies_from_header(cookie))
                recent, ids = _recent(context)
                result["recent_read"] = recent
                matches = []
                failures = 0
                for identifier in ids:
                    status, payload = _post_json(context, "/im/chain/single", _single_body(identifier))
                    if status != 200:
                        failures += 1
                        continue
                    messages = ((payload.get("downlink_body") or {}).get("pull_singe_chain_downlink_body") or {}).get("messages")
                    has_input, linked_video = _matches(messages, native_id, identifier)
                    if has_input:
                        matches.append((identifier, linked_video))
                result["single_read_failures"] = failures
                result["exact_input_conversation_count"] = len(matches)
                result["linked_video_conversation_count"] = sum(linked for _, linked in matches)
                if len(matches) == 1:
                    try:
                        status = DolaCookieClient(cookie).poll(
                            matches[0][0], client_request_id=native_id)["status"]
                    except DolaCookieError as error:
                        status = error.failure_class
                    result["unique_match_poll_status"] = status
                result["conclusion"] = (
                    "EXACT_RECENT_MATCH" if len(matches) == 1 and failures == 0
                    else "MULTIPLE_MATCHES" if len(matches) > 1
                    else "READ_INCOMPLETE" if failures or recent["http_status"] != 200
                    else "NO_MATCH_IN_RECENT_WINDOW_NOT_NO_EFFECT_PROOF"
                )
            finally:
                browser.close()
    except Exception as error:
        result["conclusion"] = "PROBE_UNAVAILABLE"
        result["error_type"] = type(error).__name__
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["conclusion"] in {
        "EXACT_RECENT_MATCH", "NO_MATCH_IN_RECENT_WINDOW_NOT_NO_EFFECT_PROOF"
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())

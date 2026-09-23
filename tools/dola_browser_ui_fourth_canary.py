"""One owner-authorized visible attempt with manual CAPTCHA handling."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import dola_browser_ui_canary as canary
from story_auto.providers.dola_cookie.browser_ui import DolaBrowserUIClient, PatchrightDolaRunner
from story_auto.providers.dola_cookie.accounts import DolaAccountStore

canary.RUNTIME_ROOT = Path(r"D:\Story Auto\evidence\dola-browser-ui-canary-4-20260923")
# Reuse the third attempt's exact bound profile, preserving operator cookies.
canary.PROFILE = Path(r"D:\Story Auto\profiles\dola-browser-ui-candidate-3-20260923")
canary.PROJECT_ID = "prj_dola_browser_ui_canary_4_20260923"
canary.PROMPT = (
    "A five-second cinematic wide shot of a small white lighthouse on a rocky "
    "island at sunrise. Gentle ocean waves, warm natural light. No people, text or logos."
)

def client():
    return DolaBrowserUIClient(
        DolaAccountStore().get_cookie(canary.ACCOUNT_ID), account_id=canary.ACCOUNT_ID,
        profile_dir=canary.PROFILE,
        runner=PatchrightDolaRunner(operator_visible=True,
                                   screenshot_dir=canary.RUNTIME_ROOT / "screenshots"),
    )

canary._client = client

if __name__ == "__main__":
    canary.main()

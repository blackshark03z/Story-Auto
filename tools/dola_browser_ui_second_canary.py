"""Second, separately authorized Dola browser-UI canary.

This uses the original canary's one-submit and same-attempt recovery guards,
but pins a distinct project, browser profile, and visibly distinct prompt.
"""
from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools import dola_browser_ui_canary as canary


canary.RUNTIME_ROOT = Path(r"D:\Story Auto\evidence\dola-browser-ui-canary-2-20260923")
canary.PROFILE = Path(r"D:\Story Auto\profiles\dola-browser-ui-candidate-2-20260923")
canary.PROJECT_ID = "prj_dola_browser_ui_canary_2_20260923"
canary.PROMPT = (
    "A five-second cinematic wide shot of a single red wooden rowboat drifting "
    "beside an old stone bridge at sunrise. Gentle water movement, warm natural "
    "light. No people, text or logos."
)


if __name__ == "__main__":
    canary.main()

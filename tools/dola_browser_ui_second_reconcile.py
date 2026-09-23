"""Read-only exact-native-ID reconciliation for the second Dola canary."""
from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools import dola_browser_ui_canary as canary

canary.RUNTIME_ROOT = Path(r"D:\Story Auto\evidence\dola-browser-ui-canary-2-20260923")
canary.PROJECT_ID = "prj_dola_browser_ui_canary_2_20260923"

from tools.dola_browser_ui_reconcile import main


if __name__ == "__main__":
    raise SystemExit(main())

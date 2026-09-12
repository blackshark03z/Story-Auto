"""Credential-safe, zero-generation BytePlus connectivity probe for Goal 54."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from story_auto.providers.byteplus_seedance import BytePlusSeedanceClient, BytePlusSeedanceError


def main() -> int:
    client = BytePlusSeedanceClient()
    readiness = client.readiness()
    if readiness["status"] != "READY":
        print(json.dumps({"status": "BLOCKED", "reason_code": readiness["reason_code"],
                          "provider": readiness["provider"], "model": readiness["model"]}, sort_keys=True))
        return 2
    try:
        payload = client.list_tasks(page_size=1)
    except BytePlusSeedanceError as error:
        print(json.dumps({"status": "FAIL", "reason_code": error.failure_class,
                          "provider": readiness["provider"], "model": readiness["model"]}, sort_keys=True))
        return 1
    items = payload.get("items", [])
    total = payload.get("total") if isinstance(payload.get("total"), int) else None
    # Never print task IDs, URLs, credentials, or provider error bodies.
    print(json.dumps({"status": "PASS", "provider": readiness["provider"], "model": readiness["model"],
                      "transport": readiness["transport"], "browser_required": False,
                      "visible_task_count": len(items), "reported_total": total}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

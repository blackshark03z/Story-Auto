"""Start the packaged local UI without opening a duplicate server."""
from __future__ import annotations

import json
import socket
import sys
from http.client import HTTPConnection
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = APP_ROOT / "runtime"
HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}/"
EXPECTED_MODULE = (APP_ROOT / "story_auto" / "providers" / "flow" / "live.py").resolve()


def listener_state() -> str:
    """Return free, this_release, or occupied without trusting a page title."""
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5):
            pass
    except OSError:
        return "free"
    try:
        connection = HTTPConnection(HOST, PORT, timeout=2)
        try:
            connection.request("GET", "/api/runtime-attestation")
            response = connection.getresponse()
            attestation = json.loads(response.read()) if response.status == 200 else {}
        finally:
            connection.close()
        module = Path(attestation.get("flow_module", "")).resolve()
        if module == EXPECTED_MODULE:
            return "this_release"
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return "occupied"


def main() -> int:
    if sys.version_info[:2] != (3, 11):
        print("This release requires Python 3.11.", file=sys.stderr)
        return 1
    state = listener_state()
    if state == "this_release":
        print(f"Story Auto is already running at {URL}")
        return 2
    if state == "occupied":
        print("Port 8765 is in use by another server. Story Auto was not started.", file=sys.stderr)
        return 1
    from story_auto.ui.server import serve

    print(f"Story Auto: {URL}", flush=True)
    print("Keep this window open while using Story Auto. Press Ctrl+C to stop it.", flush=True)
    try:
        serve(RUNTIME_ROOT, host=HOST, port=PORT)
    except KeyboardInterrupt:
        print("Story Auto stopped.")
    except OSError as error:
        state = listener_state()
        if state == "this_release":
            print(f"Story Auto is already running at {URL}")
            return 2
        print(f"Story Auto could not start: {type(error).__name__}.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

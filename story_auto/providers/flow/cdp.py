"""Tiny Chrome DevTools Protocol client used only by the Flow provider."""
from __future__ import annotations

import itertools
import json
from urllib.request import urlopen

from .session import FlowSessionError


class CdpPage:
    def __init__(self, websocket): self.websocket, self._ids = websocket, itertools.count(1)

    @classmethod
    def open(cls, runtime, *, opener=urlopen, ws_connect=None):
        try:
            # Chrome's documented target list endpoint is /json/list; /json is
            # a human-facing discovery response and is not consistently a list.
            with opener(runtime.cdp_url.rstrip("/") + "/json/list", timeout=4) as response:
                pages = json.loads(response.read().decode("utf-8"))
            matches = [p for p in pages if p.get("type") == "page" and str(p.get("url", "")).startswith(runtime.project_url)]
            if len(matches) != 1: raise FlowSessionError("FLOW_PROJECT_MISMATCH", f"expected one Flow project tab, found {len(matches)}")
            address = matches[0].get("webSocketDebuggerUrl")
            if not isinstance(address, str): raise ValueError("missing debugger endpoint")
            if ws_connect is None:
                import websocket
                ws_connect = websocket.create_connection
            return cls(ws_connect(address, timeout=10))
        except FlowSessionError: raise
        except Exception as error: raise FlowSessionError("FLOW_CDP_UNAVAILABLE", "cannot attach to dedicated Story Auto Chrome") from error

    def close(self):
        try: self.websocket.close()
        except Exception: pass

    def command(self, method: str, params: dict | None = None) -> dict:
        identifier = next(self._ids); self.websocket.send(json.dumps({"id":identifier, "method":method, "params":params or {}}))
        while True:
            payload = json.loads(self.websocket.recv())
            if payload.get("id") != identifier: continue
            if "error" in payload: raise FlowSessionError("FLOW_UI_CHANGED", f"CDP {method} rejected")
            return payload.get("result", {})

    def evaluate(self, expression: str):
        result = self.command("Runtime.evaluate", {"expression":expression, "awaitPromise":True, "returnByValue":True})
        detail = result.get("exceptionDetails")
        if detail: raise FlowSessionError("FLOW_UI_CHANGED", "page evaluation failed")
        return result.get("result", {}).get("value")

    def set_input_files(self, selector: str, files: list[str]) -> None:
        root = self.command("DOM.getDocument", {"depth":1}).get("root", {}).get("nodeId")
        node = self.command("DOM.querySelector", {"nodeId":root, "selector":selector}).get("nodeId", 0)
        if not node: raise FlowSessionError("FLOW_UI_CHANGED", "reference input not found")
        self.command("DOM.setFileInputFiles", {"nodeId":node, "files":files})

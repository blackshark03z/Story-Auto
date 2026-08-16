"""Tiny Chrome DevTools Protocol client used only by the Flow provider."""
from __future__ import annotations

import itertools
import json
from urllib.request import urlopen

from .session import FlowSessionError


class CdpPage:
    def __init__(self, websocket, runtime=None): self.websocket, self._ids, self.runtime = websocket, itertools.count(1), runtime

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
            return cls(ws_connect(address, timeout=30), runtime)
        except FlowSessionError: raise
        except Exception as error: raise FlowSessionError("FLOW_CDP_UNAVAILABLE", "cannot attach to dedicated Story Auto Chrome") from error

    def close(self):
        try: self.websocket.close()
        except Exception: pass

    def command(self, method: str, params: dict | None = None) -> dict:
        identifier = next(self._ids)
        try:
            self.websocket.send(json.dumps({"id":identifier, "method":method, "params":params or {}}))
            while True:
                payload = json.loads(self.websocket.recv())
                if payload.get("id") != identifier: continue
                if "error" in payload: raise FlowSessionError("FLOW_UI_CHANGED", f"CDP {method} rejected")
                return payload.get("result", {})
        except FlowSessionError:
            raise
        except Exception as error:
            raise FlowSessionError("FLOW_CDP_UNAVAILABLE", f"CDP {method} transport failed") from error

    def evaluate(self, expression: str):
        result = self.command("Runtime.evaluate", {"expression":expression, "awaitPromise":True, "returnByValue":True})
        detail = result.get("exceptionDetails")
        if detail:
            description = str(detail.get("exception", {}).get("description", "page evaluation failed")).split("\n", 1)[0][:180]
            raise FlowSessionError("FLOW_UI_CHANGED", description)
        return result.get("result", {}).get("value")

    def set_input_files(self, selector: str, files: list[str]) -> None:
        root = self.command("DOM.getDocument", {"depth":1}).get("root", {}).get("nodeId")
        node = self.command("DOM.querySelector", {"nodeId":root, "selector":selector}).get("nodeId", 0)
        if not node: raise FlowSessionError("FLOW_UI_CHANGED", "reference input not found")
        self.command("DOM.setFileInputFiles", {"nodeId":node, "files":files})

    def insert_text(self, text: str) -> None:
        self.command("Input.insertText", {"text":text})

    def key(self, key: str, *, code: str | None = None, modifiers: int = 0) -> None:
        """Dispatch real DevTools keyboard events to the currently focused page node."""
        virtual = {"Backspace":8, "Tab":9, "Enter":13, "Escape":27, "End":35}.get(key, ord(key.upper()) if len(key) == 1 else 0)
        params = {"type":"rawKeyDown", "key":key, "code":code or key, "modifiers":modifiers, "windowsVirtualKeyCode":virtual, "nativeVirtualKeyCode":virtual}
        self.command("Input.dispatchKeyEvent", params)
        if key == "Enter":
            self.command("Input.dispatchKeyEvent", {**params, "type":"char", "text":"\r"})
        self.command("Input.dispatchKeyEvent", {**params, "type":"keyUp"})

    def click(self, x: float, y: float) -> None:
        # Move first so Flow receives the same trusted pointer sequence as a
        # human click; some controls update hover/focus state before press.
        self.command("Input.dispatchMouseEvent", {"type":"mouseMoved", "x":x, "y":y})
        self.command("Input.dispatchMouseEvent", {"type":"mousePressed", "x":x, "y":y, "button":"left", "clickCount":1})
        self.command("Input.dispatchMouseEvent", {"type":"mouseReleased", "x":x, "y":y, "button":"left", "clickCount":1})

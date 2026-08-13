"""Small CDP client scoped to the Gemini Web provider runtime."""

from __future__ import annotations

import itertools
import json
from urllib.request import urlopen

from .session import GeminiWebError


class GeminiWebPage:
    def __init__(self, websocket):
        self.websocket = websocket
        self._ids = itertools.count(1)

    @classmethod
    def open(cls, runtime, *, opener=urlopen, ws_connect=None):
        try:
            with opener(runtime.cdp_url.rstrip("/") + "/json/list", timeout=4) as response:
                pages = json.loads(response.read().decode("utf-8"))
            matches = [
                page for page in pages
                if page.get("type") == "page" and str(page.get("url", "")).startswith("https://gemini.google.com/")
            ]
            if len(matches) != 1:
                auth_pages = [
                    page for page in pages if page.get("type") == "page"
                    and any(host in str(page.get("url", "")) for host in (
                        "accounts.google.com/", "gds.google.com/", "gemini.google.com/signin",
                    ))
                ]
                if auth_pages:
                    raise GeminiWebError("AUTH_REQUIRED", "complete sign-in in the dedicated Gemini Web window")
                raise GeminiWebError(
                    "GEMINI_WEB_APP_MISMATCH", f"expected one dedicated Gemini Web tab, found {len(matches)}",
                )
            address = matches[0].get("webSocketDebuggerUrl")
            if not isinstance(address, str):
                raise ValueError("missing debugger endpoint")
            if ws_connect is None:
                import websocket
                ws_connect = websocket.create_connection
            return cls(ws_connect(address, timeout=10))
        except GeminiWebError:
            raise
        except Exception as error:
            raise GeminiWebError("GEMINI_WEB_CDP_UNAVAILABLE", "cannot attach to dedicated Gemini Chrome") from error

    def close(self) -> None:
        try:
            self.websocket.close()
        except Exception:
            pass

    def command(self, method: str, params: dict | None = None) -> dict:
        identifier = next(self._ids)
        self.websocket.send(json.dumps({"id": identifier, "method": method, "params": params or {}}))
        while True:
            payload = json.loads(self.websocket.recv())
            if payload.get("id") != identifier:
                continue
            if "error" in payload:
                raise GeminiWebError("GEMINI_WEB_UI_CHANGED", f"CDP {method} rejected")
            return payload.get("result", {})

    def evaluate(self, expression: str):
        result = self.command("Runtime.evaluate", {
            "expression": expression, "awaitPromise": True, "returnByValue": True,
        })
        if result.get("exceptionDetails"):
            detail = result["exceptionDetails"].get("exception", {}).get("description", "page evaluation failed")
            raise GeminiWebError("GEMINI_WEB_UI_CHANGED", str(detail).split("\n", 1)[0][:180])
        return result.get("result", {}).get("value")

    def insert_text(self, value: str) -> None:
        self.command("Input.insertText", {"text": value})

    def set_input_files(self, selector: str, files: list[str]) -> None:
        root = self.command("DOM.getDocument", {"depth": 1}).get("root", {}).get("nodeId")
        node = self.command("DOM.querySelector", {"nodeId": root, "selector": selector}).get("nodeId", 0)
        if not node:
            raise GeminiWebError("GEMINI_WEB_REFERENCE_UNAVAILABLE", "file input not found")
        self.command("DOM.setFileInputFiles", {"nodeId": node, "files": files})

    def click(self, x: float, y: float) -> None:
        self.command("Page.bringToFront")
        self.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        self.command("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1,
        })
        self.command("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1,
        })

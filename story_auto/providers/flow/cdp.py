"""Tiny Chrome DevTools Protocol client used only by the Flow provider."""
from __future__ import annotations

import itertools
import json
import time
from urllib.request import urlopen

from .session import FlowSessionError

MAX_UNMATCHED_CDP_MESSAGES = 128


class CdpPage:
    def __init__(self, websocket, runtime=None, *, command_timeout_seconds: float = 30.0,
                 clock=time.monotonic):
        self.websocket, self._ids, self.runtime = websocket, itertools.count(1), runtime
        self.command_timeout_seconds, self._clock = command_timeout_seconds, clock

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
            deadline = self._clock() + self.command_timeout_seconds
            unmatched_messages = 0
            self.websocket.send(json.dumps({"id":identifier, "method":method, "params":params or {}}))
            while True:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    raise FlowSessionError(
                        "FLOW_CDP_COMMAND_TIMEOUT",
                        f"CDP {method} did not return a matching response before the pre-provider deadline",
                    )
                set_timeout = getattr(self.websocket, "settimeout", None)
                if callable(set_timeout):
                    set_timeout(remaining)
                payload = json.loads(self.websocket.recv())
                if payload.get("id") != identifier:
                    unmatched_messages += 1
                    if unmatched_messages > MAX_UNMATCHED_CDP_MESSAGES:
                        raise FlowSessionError(
                            "FLOW_CDP_COMMAND_TIMEOUT",
                            f"CDP {method} exceeded the pre-provider unmatched-event limit",
                        )
                    continue
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

    def assert_locator_activation_available(self) -> None:
        """Fail before input if the supported exact-control transport is absent."""
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except Exception as error:
            raise FlowSessionError(
                "FLOW_CAPABILITY_UNAVAILABLE",
                "Playwright locator activation is unavailable",
            ) from error

    def locator_click(self, selector: str, *, timeout_ms: int = 5000) -> None:
        """Click one current project control through Playwright actionability.

        This attaches to the already-selected dedicated Chrome instance.  It
        deliberately offers no coordinate or second-transport fallback: once
        called, the caller must treat any failure as a possibly dispatched
        activation.
        """
        self.assert_locator_activation_available()
        if self.runtime is None:
            raise FlowSessionError("FLOW_CDP_UNAVAILABLE", "locator activation requires a Flow runtime")
        browser = None
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(self.runtime.cdp_url)
                pages = [
                    page
                    for context in browser.contexts
                    for page in context.pages
                    if str(page.url).startswith(self.runtime.project_url)
                ]
                if len(pages) != 1:
                    raise FlowSessionError(
                        "FLOW_PROJECT_MISMATCH",
                        f"expected one Flow project page for locator activation, found {len(pages)}",
                    )
                target = pages[0].locator(selector)
                if target.count() != 1:
                    raise FlowSessionError(
                        "FLOW_UI_CHANGED",
                        "exact Flow Generate locator did not resolve uniquely",
                    )
                target.click(timeout=timeout_ms)
        except FlowSessionError:
            raise
        except Exception as error:
            raise FlowSessionError("FLOW_CDP_UNAVAILABLE", "Playwright locator activation failed") from error
        finally:
            # A CDP-attached browser is owned by Story Auto's dedicated Chrome,
            # not this short Playwright client.  Let Playwright disconnect with
            # its context instead of closing the remote browser.
            del browser

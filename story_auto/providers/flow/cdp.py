"""Tiny Chrome DevTools Protocol client used only by the Flow provider."""
from __future__ import annotations

import itertools
import json
import time
import threading
from collections import deque
from urllib.parse import urlsplit
from urllib.request import urlopen

from .session import FlowSessionError

MAX_UNMATCHED_CDP_MESSAGES = 128
MAX_TRANSPORT_TRACE_EVENTS = 256
SAFE_PRE_DISPATCH_REPLAY_METHODS = frozenset({"Runtime.evaluate", "Page.reload"})
_CONNECTION_GENERATIONS = itertools.count(1)


class CdpPage:
    def __init__(self, websocket, runtime=None, *, command_timeout_seconds: float = 30.0,
                 clock=time.monotonic, opener=urlopen, ws_connect=None, target_id: str = ""):
        self.websocket, self._ids, self.runtime = websocket, itertools.count(1), runtime
        self.command_timeout_seconds, self._clock = command_timeout_seconds, clock
        self._opener, self._ws_connect, self.target_id = opener, ws_connect, target_id
        self.connection_generation = next(_CONNECTION_GENERATIONS)
        self._command_lock = threading.RLock()
        self._transport_trace = deque(maxlen=MAX_TRANSPORT_TRACE_EVENTS)
        self._pre_dispatch_reconnect_enabled = False
        self._pre_dispatch_reconnects = 0
        self._trace("connected")

    @classmethod
    def open(cls, runtime, *, opener=urlopen, ws_connect=None):
        try:
            # Chrome's documented target list endpoint is /json/list; /json is
            # a human-facing discovery response and is not consistently a list.
            with opener(runtime.cdp_url.rstrip("/") + "/json/list", timeout=4) as response:
                pages = json.loads(response.read().decode("utf-8"))
            project_url = urlsplit(runtime.project_url)
            matches = []
            for page in pages:
                target = urlsplit(str(page.get("url", "")))
                if (page.get("type") == "page" and target.scheme == project_url.scheme
                        and target.netloc == project_url.netloc
                        and target.path.rstrip('/') == project_url.path.rstrip('/')):
                    matches.append(page)
            if len(matches) != 1: raise FlowSessionError("FLOW_PROJECT_MISMATCH", f"expected one Flow project tab, found {len(matches)}")
            address = matches[0].get("webSocketDebuggerUrl")
            if not isinstance(address, str): raise ValueError("missing debugger endpoint")
            if ws_connect is None:
                import websocket
                ws_connect = websocket.create_connection
            # Native loopback CDP clients have no web-page Origin. Avoid the
            # synthetic Origin added by websocket-client; Chrome's Origin
            # validation and launch flags remain unchanged.
            options = {"timeout": 30}
            endpoint, debugger = urlsplit(runtime.cdp_url), urlsplit(address)
            if (endpoint.hostname in {"127.0.0.1", "localhost", "::1"}
                    and debugger.hostname == endpoint.hostname
                    and (endpoint.scheme, debugger.scheme) in {('http', 'ws'), ('https', 'wss')}
                    and (endpoint.port or (443 if endpoint.scheme == 'https' else 80))
                    == (debugger.port or (443 if debugger.scheme == 'wss' else 80))):
                options["suppress_origin"] = True
            return cls(ws_connect(address, **options), runtime, opener=opener,
                       ws_connect=ws_connect, target_id=str(matches[0].get("id", "")))
        except FlowSessionError: raise
        except Exception as error: raise FlowSessionError("FLOW_CDP_UNAVAILABLE", "cannot attach to dedicated Story Auto Chrome") from error

    def close(self):
        with self._command_lock:
            self._trace("close")
            try: self.websocket.close()
            except Exception: pass

    def enable_pre_dispatch_reconnect(self) -> None:
        """Permit one replay-safe connection reset before the Generate path."""
        self._pre_dispatch_reconnect_enabled = True

    def disable_pre_dispatch_reconnect(self) -> None:
        """Freeze transport recovery before any prompt/input activation."""
        self._pre_dispatch_reconnect_enabled = False

    def transport_diagnostics(self) -> dict:
        """Bounded, payload-free CDP chronology for durable attempt evidence."""
        return {
            "target_id": self.target_id,
            "connection_generation": self.connection_generation,
            "pre_dispatch_reconnects": self._pre_dispatch_reconnects,
            "events": list(self._transport_trace),
        }

    def _trace(self, event: str, **fields) -> None:
        self._transport_trace.append({"event": event, "at": round(self._clock(), 6),
                                      "thread": threading.get_ident(), **fields})

    @staticmethod
    def _is_timeout(error: Exception) -> bool:
        return isinstance(error, TimeoutError) or error.__class__.__name__ == "WebSocketTimeoutException"

    def _reconnect_pre_dispatch(self, method: str) -> None:
        if self.runtime is None:
            raise FlowSessionError("FLOW_CDP_UNAVAILABLE", "CDP reconnect requires a Flow runtime")
        self._trace("reconnect_start", method=method)
        fresh = type(self).open(self.runtime, opener=self._opener, ws_connect=self._ws_connect)
        old_socket = self.websocket
        self.websocket = fresh.websocket
        self.target_id = fresh.target_id
        self.connection_generation = fresh.connection_generation
        try: old_socket.close()
        except Exception: pass
        self._pre_dispatch_reconnects += 1
        self._trace("reconnect_complete", method=method)

    def command(self, method: str, params: dict | None = None) -> dict:
        with self._command_lock:
            for attempt in range(2):
                identifier = next(self._ids)
                self._trace("command_start", method=method, command_id=identifier,
                            delivery_attempt=attempt + 1)
                try:
                    result = self._command_once(identifier, method, params)
                    self._trace("command_response", method=method, command_id=identifier,
                                delivery_attempt=attempt + 1)
                    return result
                except FlowSessionError as error:
                    self._trace("command_error", method=method, command_id=identifier,
                                delivery_attempt=attempt + 1, failure_class=error.failure_class)
                    can_reconnect = (
                        error.failure_class == "FLOW_CDP_COMMAND_TIMEOUT"
                        and self._pre_dispatch_reconnect_enabled
                        and self._pre_dispatch_reconnects == 0
                        and method in SAFE_PRE_DISPATCH_REPLAY_METHODS
                    )
                    if not can_reconnect:
                        raise
                    self._reconnect_pre_dispatch(method)
            raise AssertionError("CDP command replay loop exhausted")

    def _command_once(self, identifier: int, method: str, params: dict | None) -> dict:
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
                if "error" in payload:
                    detail = payload.get("error", {})
                    code = detail.get("code") if isinstance(detail, dict) else None
                    message = detail.get("message") if isinstance(detail, dict) else None
                    self._trace("protocol_error", method=method, command_id=identifier,
                                cdp_error_code=code, cdp_error_message=str(message or "")[:180])
                    raise FlowSessionError("FLOW_UI_CHANGED", f"CDP {method} rejected: {str(message or '')[:180]}")
                return payload.get("result", {})
        except FlowSessionError:
            raise
        except Exception as error:
            # A websocket read deadline does not prove the DevTools endpoint
            # or target died; Chrome can answer a later fresh connection.
            # Keep this distinct from an actual socket transport failure.
            if self._is_timeout(error):
                raise FlowSessionError("FLOW_CDP_COMMAND_TIMEOUT",
                                       f"CDP {method} did not return before its command deadline") from error
            raise FlowSessionError("FLOW_CDP_UNAVAILABLE", f"CDP {method} transport failed") from error

    def evaluate(self, expression: str):
        result = self.command("Runtime.evaluate", {"expression":expression, "awaitPromise":True, "returnByValue":True})
        detail = result.get("exceptionDetails")
        if detail:
            description = str(detail.get("exception", {}).get("description", "page evaluation failed")).split("\n", 1)[0][:180]
            raise FlowSessionError("FLOW_UI_CHANGED", description)
        return result.get("result", {}).get("value")

    def set_input_files(self, selector: str, files: list[str], *, expected_count: int = 1) -> None:
        """Assign files to one freshly-resolved, canonical Flow input.

        Flow recreates its media-library input during React updates. Resolve
        the node immediately before assignment and reject an ambiguous surface
        rather than retaining a stale DOM node from an earlier upload.
        """
        root = self.command("DOM.getDocument", {"depth":1}).get("root", {}).get("nodeId")
        nodes = self.command("DOM.querySelectorAll", {"nodeId":root, "selector":selector}).get("nodeIds", [])
        if not isinstance(nodes, list) or len(nodes) != expected_count:
            raise FlowSessionError("FLOW_UI_CHANGED", f"expected {expected_count} active reference input, found {len(nodes) if isinstance(nodes, list) else 0}")
        node = nodes[0]
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

    def read_project_urls(self, urls: list[str], *, timeout_ms: int = 8000,
                          max_bytes: int = 10 * 1024 * 1024) -> list[bytes | None]:
        """Read browser-authorized project media without exporting session secrets."""
        self.assert_locator_activation_available()
        if self.runtime is None:
            raise FlowSessionError("FLOW_CDP_UNAVAILABLE", "project media read requires a Flow runtime")
        project_host = urlsplit(self.runtime.project_url).hostname
        allowed_hosts = {project_host, "lh3.googleusercontent.com", "flow-content.google"}
        if (not isinstance(urls, list) or len(urls) > 100
                or any(not isinstance(url, str) or urlsplit(url).hostname not in allowed_hosts for url in urls)):
            raise FlowSessionError("FLOW_UI_CHANGED", "project media URL scope was invalid")
        browser = None
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(self.runtime.cdp_url)
                pages = [
                    page for context in browser.contexts for page in context.pages
                    if str(page.url).startswith(self.runtime.project_url)
                ]
                if len(pages) != 1:
                    raise FlowSessionError(
                        "FLOW_PROJECT_MISMATCH",
                        f"expected one Flow project page for media read, found {len(pages)}",
                    )
                result: list[bytes | None] = []
                for url in urls:
                    response = pages[0].request.get(url, timeout=timeout_ms)
                    if not response.ok or urlsplit(response.url).hostname not in allowed_hosts:
                        result.append(None)
                        continue
                    payload = response.body()
                    if len(payload) > max_bytes:
                        raise FlowSessionError("FLOW_UI_CHANGED", "project media exceeded the bounded read size")
                    result.append(payload)
                return result
        except FlowSessionError:
            raise
        except Exception as error:
            raise FlowSessionError("FLOW_CDP_UNAVAILABLE", "Playwright project media read failed") from error
        finally:
            del browser

    def file_chooser_upload(self, selector: str, files: list[str], *, timeout_ms: int = 5000) -> None:
        """Set files through one exact current-editor upload affordance."""
        self.assert_locator_activation_available()
        if self.runtime is None:
            raise FlowSessionError("FLOW_CDP_UNAVAILABLE", "file upload requires a Flow runtime")
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
                        f"expected one Flow project page for upload, found {len(pages)}",
                    )
                target = pages[0].locator(selector)
                if target.count() != 1:
                    raise FlowSessionError(
                        "FLOW_UI_CHANGED", "exact Flow upload control did not resolve uniquely",
                    )
                with pages[0].expect_file_chooser(timeout=timeout_ms) as chooser:
                    target.click(timeout=timeout_ms)
                chooser.value.set_files(files)
        except FlowSessionError:
            raise
        except Exception as error:
            raise FlowSessionError("FLOW_CDP_UNAVAILABLE", "Flow file chooser upload failed") from error
        finally:
            del browser

"""Tiny Chrome DevTools Protocol client used only by the Flow provider."""
from __future__ import annotations

import itertools
import json
import os
import subprocess
import time
from urllib.parse import urlparse
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

    def os_click(self, x: float, y: float) -> bool:
        """Click exact page coordinates through the owning Windows window.

        Used only after CDP activation has produced no dispatch acknowledgement.
        Window geometry and page coordinates are re-read from this exact target;
        ambiguous native-window matches fail closed.
        """
        if os.name != "nt": return False
        import ctypes
        from ctypes import wintypes
        # Chrome 151 can expose a normal Windows browser window while its CDP
        # Browser domain reports ``Browser window not found`` for a page
        # target. Prefer protocol geometry when available, but fall back to
        # the unique process listening on this dedicated profile's CDP port.
        bounds = {}
        try:
            window = self.command("Browser.getWindowForTarget")
            bounds = self.command("Browser.getWindowBounds", {"windowId":window.get("windowId")}).get("bounds", {})
        except FlowSessionError:
            pass
        metrics = self.evaluate("({innerWidth,innerHeight})") or {}
        required = ("left", "top", "width", "height")
        user32 = ctypes.windll.user32
        matches: list[int] = []
        enum_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        if all(isinstance(bounds.get(k), (int, float)) for k in required):
            def inspect(hwnd, _):
                if not user32.IsWindowVisible(hwnd): return True
                rect = wintypes.RECT()
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)): return True
                actual = (rect.left, rect.top, rect.right-rect.left, rect.bottom-rect.top)
                expected = tuple(round(float(bounds[k])) for k in required)
                if all(abs(a-b) <= 3 for a,b in zip(actual, expected)): matches.append(int(hwnd))
                return True
        else:
            if self.runtime is None: return False
            port = urlparse(self.runtime.cdp_url).port
            if not port: return False
            environment = os.environ.copy(); environment["STORY_AUTO_FLOW_CDP_PORT"] = str(port)
            resolved = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "$p=@(Get-NetTCPConnection -State Listen -LocalPort ([int]$env:STORY_AUTO_FLOW_CDP_PORT) -ErrorAction Stop | Select-Object -ExpandProperty OwningProcess -Unique); if($p.Count -ne 1){exit 1}; [Console]::Out.Write($p[0])"],
                capture_output=True, text=True, creationflags=0x08000000, env=environment)
            try: dedicated_pid = int(resolved.stdout.strip()) if resolved.returncode == 0 else 0
            except ValueError: dedicated_pid = 0
            if not dedicated_pid: return False
            def inspect(hwnd, _):
                if not user32.IsWindowVisible(hwnd): return True
                process_id = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
                if process_id.value == dedicated_pid: matches.append(int(hwnd))
                return True
        callback = enum_type(inspect); user32.EnumWindows(callback, 0)
        if len(matches) != 1: return False
        hwnd = wintypes.HWND(matches[0])
        # A minimized Chrome window reports a zero-sized client rectangle.
        # Restore the already-verified dedicated HWND before deriving the
        # page-to-screen transform; this does not activate another profile.
        user32.ShowWindow(hwnd, 9)
        time.sleep(.2)
        client = wintypes.RECT(); origin = wintypes.POINT(0, 0)
        if not user32.GetClientRect(hwnd, ctypes.byref(client)) or not user32.ClientToScreen(hwnd, ctypes.byref(origin)): return False
        client_width, client_height = client.right-client.left, client.bottom-client.top
        inner_width, inner_height = float(metrics.get("innerWidth", 0)), float(metrics.get("innerHeight", 0))
        if min(client_width, client_height, inner_width, inner_height) <= 0: return False
        screen_x = origin.x + round(float(x) * client_width / inner_width)
        screen_y = origin.y + (client_height-round(inner_height)) + round(float(y) * client_height / inner_height)
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        # Chrome can place the dedicated CDP window in the same browser
        # process as unrelated top-level windows. AppActivate(pid) then picks
        # an arbitrary one. Briefly minimize only sibling windows owned by the
        # exact process, restore them without activation after the click, and
        # require the verified Flow HWND to be foreground before input.
        siblings: list[int] = []
        def inspect_sibling(candidate, _):
            candidate_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(candidate, ctypes.byref(candidate_pid))
            if (int(candidate) != int(hwnd.value) and candidate_pid.value == process_id.value
                    and user32.IsWindowVisible(candidate) and not user32.IsIconic(candidate)):
                siblings.append(int(candidate))
            return True
        sibling_callback = enum_type(inspect_sibling); user32.EnumWindows(sibling_callback, 0)
        for sibling in siblings: user32.ShowWindow(wintypes.HWND(sibling), 6)
        user32.ShowWindow(hwnd, 9); user32.SetForegroundWindow(hwnd)
        # SetForegroundWindow is intentionally restricted when the caller is
        # not the foreground process. WScript's AppActivate performs the
        # supported user-session activation by exact owning process ID.
        activated = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
            f"$s=New-Object -ComObject WScript.Shell; if(-not $s.AppActivate({int(process_id.value)})){{exit 1}}"],
            capture_output=True, creationflags=0x08000000).returncode == 0
        try:
            if not activated: return False
            time.sleep(.35)
            # Windows can report AppActivate success while retaining the
            # caller as the foreground window. A balanced Alt key transition
            # grants the documented foreground handoff opportunity to this
            # user-session process; the exact HWND is still verified below.
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 0x0002, 0)
            user32.ShowWindow(hwnd, 9); user32.BringWindowToTop(hwnd); user32.SetForegroundWindow(hwnd)
            time.sleep(.15)
            if int(user32.GetForegroundWindow()) != int(hwnd.value): return False
            focused=self.evaluate("""(()=>{const e=document.elementFromPoint(%s,%s)?.closest('button');if(!e)return false;e.focus();return document.activeElement===e})()""" % (float(x),float(y)))
            if not focused: return False
            if not user32.SetCursorPos(screen_x, screen_y): return False
            time.sleep(.2)
            user32.keybd_event(0x0D, 0, 0, 0); user32.keybd_event(0x0D, 0, 0x0002, 0)
            time.sleep(.6)
            still_generate=self.evaluate("""(()=>{const e=document.elementFromPoint(%s,%s)?.closest('button');return !!e&&e.type==='submit'&&e.querySelector('i')?.textContent.trim()==='arrow_forward'})()""" % (float(x),float(y)))
            if still_generate:
                user32.mouse_event(0x0002,0,0,0,0); user32.mouse_event(0x0004,0,0,0,0)
                time.sleep(.6)
            return True
        finally:
            for sibling in siblings: user32.ShowWindow(wintypes.HWND(sibling), 4)

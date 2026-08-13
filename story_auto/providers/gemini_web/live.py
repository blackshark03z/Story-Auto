"""Live Gemini Web generation with explicit dispatch and result attribution."""

from __future__ import annotations

import base64
from pathlib import Path
import time

from story_auto.core.artifacts import atomic_write_bytes
from story_auto.providers.flow.validation import validate_image, validate_video

from .cdp import GeminiWebPage
from .page import GeminiWebDom
from .session import GeminiWebError


class LiveGeminiWebGenerator:
    def __init__(self, runtime, *, timeout_seconds: int = 360) -> None:
        self.runtime = runtime
        self.timeout_seconds = timeout_seconds
        self.dispatch_confirmed = False
        self.last_settings: dict | None = None

    @staticmethod
    def _asset_payload(page, record: dict) -> bytes:
        url = record["url"]
        if record["kind"] == "IMG" and url.startswith("blob:"):
            payload = page.evaluate("""(()=>{const u=%s;const e=Array.from(document.images).find(x=>(x.currentSrc||x.src)===u);if(!e)throw Error('image');const c=document.createElement('canvas');c.width=e.naturalWidth;c.height=e.naturalHeight;c.getContext('2d').drawImage(e,0,0);return c.toDataURL('image/png').split(',',2)[1]})()""" % __import__('json').dumps(url))
            if not isinstance(payload, str):
                raise GeminiWebError("GEMINI_WEB_ASSET_ACQUISITION_FAILED", dispatch_confirmed=True)
            try:
                return base64.b64decode(payload, validate=True)
            except ValueError as error:
                raise GeminiWebError("GEMINI_WEB_ASSET_ACQUISITION_FAILED", dispatch_confirmed=True) from error
        frame = page.command("Page.getFrameTree").get("frameTree", {}).get("frame", {}).get("id")
        resource = page.command("Network.loadNetworkResource", {
            "frameId": frame, "url": url,
            "options": {"disableCache": False, "includeCredentials": True},
        }).get("resource", {})
        if not resource.get("success") or not resource.get("stream"):
            raise GeminiWebError("GEMINI_WEB_ASSET_ACQUISITION_FAILED", dispatch_confirmed=True)
        handle = resource["stream"]
        chunks: list[bytes] = []
        try:
            while True:
                part = page.command("IO.read", {"handle": handle, "size": 1048576})
                data = part.get("data", "")
                chunks.append(base64.b64decode(data) if part.get("base64Encoded") else data.encode("latin1"))
                if part.get("eof"):
                    break
        finally:
            page.command("IO.close", {"handle": handle})
        return b"".join(chunks)

    def acquire_existing(self, request: dict, destination: Path) -> Path:
        """Acquire one already-rendered result without dispatching another request."""
        page = GeminiWebPage.open(self.runtime)
        try:
            expected = ("IMG",) if request["media_type"] == "IMAGE" else ("VIDEO", "SOURCE")
            records = [item for item in GeminiWebDom(page).media_records() if item["kind"] in expected]
            if len(records) != 1:
                raise GeminiWebError("GEMINI_WEB_RESULT_AMBIGUOUS", dispatch_confirmed=True)
            atomic_write_bytes(destination, self._asset_payload(page, records[0]))
            (validate_image if request["media_type"] == "IMAGE" else validate_video)(destination)
            return destination
        finally:
            page.close()

    def __call__(self, request: dict, references: list[Path], destination: Path) -> Path:
        if request.get("output_count") != 1:
            raise GeminiWebError("IMAGE_OUTPUT_COUNT_MISMATCH")
        page = GeminiWebPage.open(self.runtime)
        try:
            page.command("Emulation.setFocusEmulationEnabled", {"enabled": True})
            page.command("Page.setWebLifecycleState", {"state": "active"})
            dom = GeminiWebDom(page)
            mode = dom.select_media_mode(request["media_type"])
            dom.attach_references(references)
            # Mode entry can reveal large built-in template thumbnails. Establish
            # attribution only after the requested mode and references are ready.
            before = {item["key"] for item in dom.media_records()}
            dom.set_prompt(request["prompt"])
            prompt_before = dom.editor_state()["text"]
            submit = dom.submit()
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                editors = page.evaluate("""(()=>Array.from(document.querySelectorAll('textarea,[contenteditable=true]')).filter(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'}).map(e=>(e.value??e.innerText??'').trim()))()""") or []
                current = editors[0] if len(editors) == 1 else ""
                if current != prompt_before:
                    self.dispatch_confirmed = True
                    break
                time.sleep(0.25)
            if not self.dispatch_confirmed and dom.editor_state()["text"] == prompt_before:
                dom.submit_dom_fallback()
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    if dom.editor_state()["text"] != prompt_before:
                        self.dispatch_confirmed = True
                        break
                    time.sleep(0.25)
            if not self.dispatch_confirmed:
                raise GeminiWebError("GEMINI_WEB_NOT_DISPATCHED", dispatch_confirmed=False)
            self.last_settings = {
                "observed_mode_identity": mode,
                "requested_output_count": 1,
                "actual_output_count": 1,
                "aspect_ratio": request.get("aspect_ratio", "16:9"),
                "reference_count": len(references),
                "submit_label": submit.get("label"),
                "dispatch_ack_method": "composer_transition",
            }
            deadline = time.monotonic() + self.timeout_seconds
            while time.monotonic() < deadline:
                records = dom.media_records()
                expected = ("IMG",) if request["media_type"] == "IMAGE" else ("VIDEO", "SOURCE")
                added = [item for item in records if item["key"] not in before and item["kind"] in expected]
                if len(added) == 1:
                    try:
                        payload = self._asset_payload(page, added[0])
                    except GeminiWebError as error:
                        raise GeminiWebError(
                            error.failure_class, error.detail, dispatch_confirmed=True,
                        ) from error
                    atomic_write_bytes(destination, payload)
                    (validate_image if request["media_type"] == "IMAGE" else validate_video)(destination)
                    return destination
                if len(added) > 1:
                    raise GeminiWebError("GEMINI_WEB_RESULT_AMBIGUOUS", dispatch_confirmed=True)
                time.sleep(2)
            raise GeminiWebError("GEMINI_WEB_TIMEOUT", dispatch_confirmed=True)
        finally:
            page.close()

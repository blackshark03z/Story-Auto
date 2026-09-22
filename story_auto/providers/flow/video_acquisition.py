"""Exact-tuple acquisition for experimental Flow video response identities."""
from __future__ import annotations

import os
import secrets
import time
from pathlib import Path

from .response_model import FlowObservedIdentity, FlowPassiveResponseObserver
from .session import FlowRuntime, FlowSessionError
from .validation import AssetValidationError, validate_video
from .video_identity import load_attempt_video_identity


VIDEO_ACQUISITION_VERSION = "flow-observed-video-acquisition/0.1.0"


def exact_rendered_video_index(
    identities: list[FlowObservedIdentity | None], target: FlowObservedIdentity,
) -> int:
    matches = [index for index, identity in enumerate(identities) if identity == target]
    if not matches:
        raise FlowSessionError(
            "FLOW_VIDEO_IDENTITY_NOT_RENDERED",
            "the exact observed video identity is not on the rendered surface",
        )
    if len(matches) != 1:
        raise FlowSessionError(
            "FLOW_RESPONSE_IDENTITY_AMBIGUOUS",
            "the exact observed video identity resolved to multiple rendered tiles",
        )
    return matches[0]


class FlowObservedVideoAcquirer:
    """Download one exact rendered video without using gallery order."""

    def __init__(self, runtime: FlowRuntime, observer: FlowPassiveResponseObserver):
        self.runtime = runtime
        self.observer = observer
        self.last_phase = "NOT_STARTED"
        self.last_error_type: str | None = None

    @staticmethod
    def _mark_tile_menu(tile, marker: str) -> None:
        count = tile.evaluate(
            """(root,marker)=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);
            return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled};
            const buttons=Array.from(root.querySelectorAll('button')).filter(e=>visible(e)&&
            Array.from(e.querySelectorAll('i,mat-icon')).some(i=>['more_vert','more_horiz']
            .includes((i.textContent||'').trim())));for(const e of buttons)e.removeAttribute(
            'data-story-auto-video-control');if(buttons.length===1)buttons[0].setAttribute(
            'data-story-auto-video-control',marker);return buttons.length}""",
            marker,
        )
        if count != 1:
            raise FlowSessionError(
                "FLOW_VIDEO_ACQUISITION_UI_CHANGED", "exact video menu control was unavailable",
            )

    @staticmethod
    def _mark_overlay_control(page, marker: str, action: str) -> None:
        count = page.evaluate(
            """([marker,action])=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);
            return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled};
            const overlays=Array.from(document.querySelectorAll('.cdk-overlay-pane,[role=menu]')).filter(visible);
            const controls=Array.from(new Set(overlays.flatMap(root=>Array.from(
            root.querySelectorAll('[role=menuitem],button')))))
            .filter(visible).filter(e=>action==='DOWNLOAD'?
            Array.from(e.querySelectorAll('i,mat-icon')).some(i=>(i.textContent||'').trim()==='download'):
            e.matches('[role=menuitem]')&&
            /(^|\\s)720p($|\\s)/i.test((e.innerText||e.textContent||'').trim()));
            for(const e of controls)e.removeAttribute('data-story-auto-video-control');
            if(controls.length===1)controls[0].setAttribute('data-story-auto-video-control',marker);
            return controls.length}""",
            [marker, action],
        )
        if count != 1:
            raise FlowSessionError(
                "FLOW_VIDEO_ACQUISITION_UI_CHANGED",
                f"exact video {action.lower()} control was unavailable",
            )

    def acquire(
        self, target: FlowObservedIdentity, destination: Path, *, timeout_ms: int = 45_000,
    ) -> dict:
        destination = Path(destination)
        if destination.exists():
            raise FlowSessionError(
                "FLOW_VIDEO_DESTINATION_EXISTS", "refusing to overwrite an existing video",
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(
            destination.stem + ".partial-" + secrets.token_hex(6) + destination.suffix
        )
        tile_menu_marker = secrets.token_hex(12)
        download_marker = secrets.token_hex(12)
        resolution_marker = secrets.token_hex(12)
        try:
            self.last_phase = "ATTACHING_EXACT_PROJECT"
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(
                    self.runtime.cdp_url, timeout=8_000,
                )
                pages = [
                    page
                    for context in browser.contexts
                    for page in context.pages
                    if page.url.rstrip("/") == self.runtime.project_url.rstrip("/")
                ]
                if len(pages) != 1:
                    raise FlowSessionError(
                        "FLOW_PROJECT_MISMATCH", "exact Flow project tab was unavailable",
                    )
                page = pages[0]
                deadline = time.monotonic() + timeout_ms / 1000
                while True:
                    tiles = page.locator("flow-video-tile")
                    urls: list[str] = []
                    for tile_index in range(tiles.count()):
                        image = tiles.nth(tile_index).locator("img.thumbnail")
                        urls.append(
                            image.get_attribute("src") if image.count() == 1 else ""
                        )
                    identities = self.observer.resolve_urls(urls)
                    try:
                        index = exact_rendered_video_index(identities, target)
                        break
                    except FlowSessionError as error:
                        if (
                            error.failure_class != "FLOW_VIDEO_IDENTITY_NOT_RENDERED"
                            or time.monotonic() >= deadline
                        ):
                            raise
                        page.wait_for_timeout(500)
                tile = tiles.nth(index)
                self.last_phase = "OPENING_EXACT_TILE_MENU"
                tile.hover()
                self._mark_tile_menu(tile, tile_menu_marker)
                tile.locator(
                    f'[data-story-auto-video-control="{tile_menu_marker}"]'
                ).click()
                self.last_phase = "SELECTING_DOWNLOAD"
                self._mark_overlay_control(page, download_marker, "DOWNLOAD")
                page.locator(
                    f'[data-story-auto-video-control="{download_marker}"]'
                ).click()
                self.last_phase = "SELECTING_720P"
                self._mark_overlay_control(page, resolution_marker, "720P")
                with page.expect_download(timeout=timeout_ms) as download_info:
                    page.locator(
                        f'[data-story-auto-video-control="{resolution_marker}"]'
                    ).click()
                self.last_phase = "SAVING_DOWNLOAD"
                download_info.value.save_as(str(partial))
            validation = validate_video(partial)
            os.replace(partial, destination)
            self.last_phase = "COMPLETE"
            return {
                "acquisition_version": VIDEO_ACQUISITION_VERSION,
                "identity": target.identity,
                "path": str(destination),
                **validation,
            }
        except FlowSessionError:
            raise
        except AssetValidationError as error:
            self.last_error_type = type(error).__name__
            raise FlowSessionError(
                "FLOW_VIDEO_ACQUISITION_INVALID", "downloaded video failed validation",
            ) from error
        except Exception as error:
            self.last_error_type = type(error).__name__
            raise FlowSessionError(
                "FLOW_VIDEO_ACQUISITION_FAILED", "exact video download failed",
            ) from error
        finally:
            partial.unlink(missing_ok=True)

    def acquire_persisted(
        self,
        runtime_root: Path | str,
        project_id: str,
        request_id: str,
        attempt_number: int,
        destination: Path,
        *,
        timeout_ms: int = 45_000,
    ) -> dict:
        """Acquire only after re-reading a verified canonical attempt binding."""
        binding = load_attempt_video_identity(
            runtime_root, project_id, request_id, attempt_number,
        )
        if binding.observed_identity.project_identity != self.runtime.project_identity.lower():
            raise FlowSessionError(
                "FLOW_PROJECT_MISMATCH", "persisted identity does not match the active Flow project",
            )
        acquired = self.acquire(
            binding.observed_identity, destination, timeout_ms=timeout_ms,
        )
        return {
            **acquired,
            "story_project_id": project_id,
            "request_id": request_id,
            "attempt": attempt_number,
            "identity_binding_sha256": binding.binding_sha256,
        }

"""Project-safe Pexels stock-slot acquisition for Hybrid Visual."""
from __future__ import annotations

from pathlib import Path
import shutil
from typing import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.visual.hybrid_body import (HybridBodyError, adopt_pexels_stock_video,
                                                apply_pexels_search_result, hybrid_body_view)
from .client import PexelsClient, cached_video_search


MAX_PEXELS_DOWNLOAD_BYTES = 512 * 1024 * 1024


def _default_download(url: str, destination: Path, max_bytes: int = MAX_PEXELS_DOWNLOAD_BYTES) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "pexels.com" or host.endswith(".pexels.com")):
        raise HybridBodyError("PEXELS_DOWNLOAD_URL_INVALID")
    request = Request(url, headers={"User-Agent": "StoryAuto/HybridVisual"}, method="GET")
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with urlopen(request, timeout=45) as response:  # nosec - host is restricted to pexels.com
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > max_bytes:
                raise HybridBodyError("PEXELS_DOWNLOAD_TOO_LARGE")
            with destination.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise HybridBodyError("PEXELS_DOWNLOAD_TOO_LARGE")
                    handle.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def resolve_pexels_stock_slot(runtime_root: Path | str, project_id: str, slot_id: str, *,
                              client: PexelsClient | None = None,
                              downloader: Callable[[str, Path, int], None] | None = None,
                              now_epoch: int | None = None) -> dict:
    """Search/select/download/normalize exactly one planned stock slot.

    Search response caching and deterministic selection prevent rerender from
    silently choosing a different provider asset. A no-candidate outcome is a
    normal IMAGE fallback boundary rather than a whole-project failure.
    """
    runtime = RuntimeLayout.from_root(runtime_root)
    paths, config = load_project(runtime, project_id)
    if config.render_mode != "hybrid_hook":
        raise HybridBodyError("HYBRID_BODY_MODE_INVALID")
    plan = hybrid_body_view(runtime.root, project_id)
    if not plan:
        raise HybridBodyError("HYBRID_BODY_PLAN_MISSING")
    slot = next((item for item in plan.get("slots", []) if item.get("slot_id") == slot_id), None)
    if not isinstance(slot, dict) or slot.get("visual_type") != "STOCK_VIDEO":
        raise HybridBodyError("HYBRID_STOCK_SLOT_INVALID")
    normalized = slot.get("normalized_asset")
    if slot.get("status") == "READY" and isinstance(normalized, dict):
        path = normalized.get("path")
        digest = normalized.get("sha256")
        if isinstance(path, str) and isinstance(digest, str):
            local = paths.artifact_path(path)
            from story_auto.core.artifacts import sha256_file
            if local.is_file() and sha256_file(local) == digest:
                return plan
    if not isinstance(slot.get("provider_selection"), dict):
        active = client or PexelsClient()
        result = cached_video_search(runtime.cache, active, str(slot.get("provider_query") or ""),
                                     orientation="landscape", size="medium", locale=str(slot.get("provider_locale") or "vi-VN"),
                                     now_epoch=now_epoch)
        plan = apply_pexels_search_result(runtime.root, project_id, slot_id, result)
        slot = next(item for item in plan["slots"] if item["slot_id"] == slot_id)
        if slot.get("status") == "FALLBACK_IMAGE_REQUIRED":
            return plan
    selection = slot.get("provider_selection")
    selected_file = selection.get("selected_file") if isinstance(selection, dict) else None
    url = selected_file.get("link") if isinstance(selected_file, dict) else None
    if not isinstance(url, str):
        raise HybridBodyError("PEXELS_DOWNLOAD_URL_MISSING")
    temp_dir = runtime.temp / "pexels" / project_id / slot_id
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp = temp_dir / "selected_source.mp4"
    fetch = downloader or _default_download
    try:
        fetch(url, temp, MAX_PEXELS_DOWNLOAD_BYTES)
        return adopt_pexels_stock_video(runtime.root, project_id, slot_id, temp)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

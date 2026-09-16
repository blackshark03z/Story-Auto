"""Small, deterministic Pexels video-search client.

The client owns API transport, response normalization, cache identity and
candidate selection. It never downloads or mutates Story Auto project assets;
that remains a project service responsibility.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from story_auto.core.artifacts import atomic_write_json, read_json


PEXELS_VIDEO_SEARCH_URL = "https://api.pexels.com/v1/videos/search"
PEXELS_SEARCH_TTL_SECONDS = 24 * 60 * 60
PEXELS_DEFAULT_PER_PAGE = 24
PEXELS_MAX_PER_PAGE = 80


class PexelsError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(failure_class + (f": {detail}" if detail else ""))


def _canonical_query(value: str) -> str:
    if not isinstance(value, str):
        raise PexelsError("PEXELS_QUERY_INVALID")
    collapsed = " ".join(value.split()).strip()
    if not collapsed:
        raise PexelsError("PEXELS_QUERY_INVALID")
    return collapsed


def _header_int(headers: dict[str, Any], name: str) -> int | None:
    lowered = {str(key).lower(): value for key, value in headers.items()}
    value = lowered.get(name.lower())
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _rate_limit(headers: dict[str, Any]) -> dict[str, int | None]:
    return {
        "limit": _header_int(headers, "X-Ratelimit-Limit"),
        "remaining": _header_int(headers, "X-Ratelimit-Remaining"),
        "reset": _header_int(headers, "X-Ratelimit-Reset"),
    }


def _default_fetch(url: str, headers: dict[str, str], timeout: int) -> tuple[int, dict[str, str], bytes]:
    request = Request(url, headers=headers, method="GET")
    with urlopen(request, timeout=timeout) as response:  # nosec - fixed HTTPS Pexels API endpoint
        return int(response.status), dict(response.headers.items()), response.read()


def _normalize_file(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    link = value.get("link")
    try:
        width, height = int(value.get("width") or 0), int(value.get("height") or 0)
        fps = float(value.get("fps") or 0)
    except (TypeError, ValueError):
        return None
    if not isinstance(link, str) or not link.startswith("https://") or width <= 0 or height <= 0:
        return None
    file_type = str(value.get("file_type") or "")
    if file_type and file_type != "video/mp4":
        return None
    return {"file_id": str(value.get("id") or ""), "quality": str(value.get("quality") or ""),
            "file_type": file_type or "video/mp4", "width": width, "height": height,
            "fps": fps if fps > 0 else None, "link": link}


def _normalize_video(value: Any, rank: int) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    try:
        asset_id = str(int(value.get("id")))
        duration = float(value.get("duration") or 0)
        width, height = int(value.get("width") or 0), int(value.get("height") or 0)
    except (TypeError, ValueError):
        return None
    page_url = value.get("url")
    if duration <= 0 or width <= 0 or height <= 0 or not isinstance(page_url, str) or not page_url.startswith("https://"):
        return None
    user = value.get("user") if isinstance(value.get("user"), dict) else {}
    creator_name = str(user.get("name") or "Pexels contributor")
    creator_url = user.get("url") if isinstance(user.get("url"), str) else None
    files = [item for raw in value.get("video_files", []) if (item := _normalize_file(raw)) is not None]
    if not files:
        return None
    return {
        "provider": "pexels",
        "provider_asset_id": asset_id,
        "provider_rank": rank,
        "duration_seconds": duration,
        "width": width,
        "height": height,
        "page_url": page_url,
        "creator": {"id": str(user.get("id") or "") or None, "name": creator_name, "url": creator_url},
        "video_files": files,
        "attribution": {
            "provider": "Pexels",
            "provider_url": "https://www.pexels.com/",
            "creator_name": creator_name,
            "creator_url": creator_url,
            "source_url": page_url,
            "text": f"Video by {creator_name} on Pexels",
        },
    }


def search_cache_key(*, query: str, orientation: str, size: str, locale: str, per_page: int) -> str:
    identity = json.dumps({"query": _canonical_query(query).lower(), "orientation": orientation,
                           "size": size, "locale": locale, "per_page": int(per_page)},
                          sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


class PexelsClient:
    def __init__(self, *, key: str | None = None,
                 fetch: Callable[[str, dict[str, str], int], tuple[int, dict[str, str], bytes]] | None = None,
                 timeout_seconds: int = 20) -> None:
        self.key = (key or os.getenv("PEXELS_API_KEY") or "").strip()
        self.fetch = fetch or _default_fetch
        self.timeout_seconds = int(timeout_seconds)

    def readiness(self) -> dict[str, Any]:
        return {"status": "READY" if self.key else "NOT_READY",
                "reason_code": None if self.key else "PEXELS_API_KEY_MISSING"}

    def search_videos(self, query: str, *, orientation: str = "landscape", size: str = "medium",
                      locale: str = "vi-VN", page: int = 1,
                      per_page: int = PEXELS_DEFAULT_PER_PAGE) -> dict[str, Any]:
        if not self.key:
            raise PexelsError("PEXELS_API_KEY_MISSING")
        query = _canonical_query(query)
        if orientation not in {"landscape", "portrait", "square"}:
            raise PexelsError("PEXELS_ORIENTATION_INVALID")
        if size not in {"large", "medium", "small"}:
            raise PexelsError("PEXELS_SIZE_INVALID")
        if not isinstance(page, int) or page < 1 or not isinstance(per_page, int) or not (1 <= per_page <= PEXELS_MAX_PER_PAGE):
            raise PexelsError("PEXELS_PAGINATION_INVALID")
        params = urlencode({"query": query, "orientation": orientation, "size": size,
                            "locale": locale, "page": page, "per_page": per_page})
        status, headers, payload = self.fetch(f"{PEXELS_VIDEO_SEARCH_URL}?{params}",
                                              {"Authorization": self.key, "User-Agent": "StoryAuto/HybridVisual"},
                                              self.timeout_seconds)
        if status == 401:
            raise PexelsError("PEXELS_AUTH_REQUIRED")
        if status == 429:
            raise PexelsError("PEXELS_RATE_LIMITED")
        if status != 200:
            raise PexelsError("PEXELS_HTTP_ERROR", str(status))
        try:
            value = json.loads(payload.decode("utf-8"))
        except Exception as error:
            raise PexelsError("PEXELS_RESPONSE_INVALID") from error
        raw_videos = value.get("videos", []) if isinstance(value, dict) else []
        videos = [item for rank, raw in enumerate(raw_videos, start=1)
                  if (item := _normalize_video(raw, rank)) is not None]
        return {
            "provider": "pexels",
            "query": query,
            "orientation": orientation,
            "size": size,
            "locale": locale,
            "page": page,
            "per_page": per_page,
            "total_results": int(value.get("total_results") or 0) if isinstance(value, dict) else 0,
            "videos": videos,
            "rate_limit": _rate_limit(headers),
            "cache_key": search_cache_key(query=query, orientation=orientation, size=size,
                                          locale=locale, per_page=per_page),
            "fetched_at_epoch": int(time.time()),
        }


def cached_video_search(cache_root: Path | str, client: PexelsClient, query: str, *,
                        orientation: str = "landscape", size: str = "medium", locale: str = "vi-VN",
                        per_page: int = PEXELS_DEFAULT_PER_PAGE, now_epoch: int | None = None,
                        ttl_seconds: int = PEXELS_SEARCH_TTL_SECONDS) -> dict[str, Any]:
    now = int(time.time()) if now_epoch is None else int(now_epoch)
    key = search_cache_key(query=query, orientation=orientation, size=size, locale=locale, per_page=per_page)
    path = Path(cache_root) / "pexels" / f"{key}.json"
    if path.is_file():
        try:
            cached = read_json(path)
            fetched = int(cached.get("fetched_at_epoch") or 0)
            if cached.get("cache_key") == key and 0 <= now - fetched <= int(ttl_seconds):
                result = dict(cached)
                result["cache_hit"] = True
                return result
        except Exception:
            pass
    result = client.search_videos(query, orientation=orientation, size=size, locale=locale, per_page=per_page)
    result["fetched_at_epoch"] = now
    result["cache_hit"] = False
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, result)
    return dict(result)


def select_video_file(candidate: dict[str, Any], *, target_width: int, target_height: int) -> dict[str, Any]:
    files = [item for item in candidate.get("video_files", []) if isinstance(item, dict)]
    if not files:
        raise PexelsError("PEXELS_VIDEO_FILE_MISSING")
    target_aspect = target_width / max(1, target_height)
    def score(item: dict[str, Any]) -> tuple[float, int, int]:
        width, height = int(item["width"]), int(item["height"])
        aspect_penalty = abs((width / max(1, height)) - target_aspect)
        undersize = int(width < target_width or height < target_height)
        pixel_delta = abs(width * height - target_width * target_height)
        return (undersize + aspect_penalty, pixel_delta, -width * height)
    return dict(min(files, key=score))


def select_candidate(search_result: dict[str, Any], *, slot_id: str, used_asset_ids: set[str],
                     target_duration: float, target_width: int, target_height: int,
                     top_relevant: int = 8) -> dict[str, Any]:
    query = _canonical_query(str(search_result.get("query") or ""))
    eligible = []
    for candidate in search_result.get("videos", []):
        if not isinstance(candidate, dict):
            continue
        asset_id = str(candidate.get("provider_asset_id") or "")
        if not asset_id or asset_id in used_asset_ids:
            continue
        if float(candidate.get("duration_seconds") or 0) + .05 < float(target_duration):
            continue
        try:
            chosen_file = select_video_file(candidate, target_width=target_width, target_height=target_height)
        except PexelsError:
            continue
        item = dict(candidate)
        item["selected_file"] = chosen_file
        eligible.append(item)
    eligible.sort(key=lambda item: int(item.get("provider_rank") or 10**9))
    pool = eligible[:max(1, int(top_relevant))]
    if not pool:
        raise PexelsError("PEXELS_NO_COMPATIBLE_CANDIDATE")
    seed = hashlib.sha256(f"{slot_id}|{query}".encode("utf-8")).digest()
    selected = dict(pool[int.from_bytes(seed[:8], "big") % len(pool)])
    selected["selection"] = {"strategy": "TOP_RELEVANT_DETERMINISTIC_V1",
                             "pool_size": len(pool), "slot_id": slot_id, "query": query}
    return selected

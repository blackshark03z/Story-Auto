"""Probe Dola read-only conversation envelope without recording user content.

This uses only recent-conversation and single-conversation reads. It never
submits a prompt, uploads a file, records IDs, or saves message text/media URLs.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from story_auto.providers.dola_cookie.accounts import DolaAccountStore
from story_auto.providers.dola_cookie.client import (
    DolaCookieClient, DolaCookieError, _canonical_media_url, _open,
    _safe_host, _video_urls,
)
from tools.dola_profile_read_probe import _qualified, _sample
from tools.import_dola_profile_cookie import _browser_cookies_from_header


ORIGIN = "https://www.dola.com"
QUERY = urlencode({
    "version_code": "20800", "language": "en", "device_platform": "web",
    "doubao_device_platform": "web", "aid": "495671", "real_aid": "495671",
    "pkg_type": "release_version", "region": "JP", "sys_region": "JP",
    "samantha_web": "1", "web_platform": "browser", "use-olympus-account": "1",
})
HEADERS = {"content-type": "application/json; encoding=utf-8",
           "agw-js-conv": "str", "accept": "*/*",
           "origin": ORIGIN, "referer": ORIGIN + "/chat"}


def _probe_media_url(url: str) -> str:
    """Only probe the exact observed HTTP host through its safe HTTPS twin."""
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname != "v16-dola.dola.com":
        return ""
    canonical = _canonical_media_url(url)
    return canonical if canonical and _safe_host(canonical) else ""


def _post_json(context, path: str, body: dict, *, query: str = QUERY,
               headers: dict[str, str] = HEADERS) -> tuple[int, dict]:
    response = context.request.post(ORIGIN + path + "?" + query,
                                    data=json.dumps(body, separators=(",", ":")),
                                    headers=headers, timeout=25000, max_redirects=0)
    raw = response.body()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("READ_RESPONSE_TOO_LARGE")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        value = {}
    return response.status, value if isinstance(value, dict) else {}


def _recent(context) -> tuple[dict[str, object], list[str]]:
    body = {
        "cmd": 3200,
        "uplink_body": {"pull_recent_conv_chain_uplink_body": {
            "limit": 20, "message_count_per_conv": 0,
            "api_version": 1, "conv_version": 0, "direction": 3,
            "option": {"not_need_message": True,
                       "need_complete_conversation": True,
                       "need_coco_conversation": True,
                       "need_coco_bot": True,
                       "need_pc_pin_chain": True, "pc_pin_query_type": 0},
        }},
        "sequence_id": str(uuid4()), "channel": 2, "version": "1",
    }
    status, data = _post_json(context, "/im/chain/recent_conv", body)
    cells = ((data.get("downlink_body") or {}).get("pull_recent_conv_chain_downlink_body") or {}).get("cells")
    cells = cells if isinstance(cells, list) else []
    ids = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        conversation = cell.get("conversation")
        conversation = conversation if isinstance(conversation, dict) else {}
        identifier = conversation.get("conversation_id") or cell.get("id")
        if isinstance(identifier, str) and re.fullmatch(r"[0-9]{3,40}", identifier):
            ids.append(identifier)
    return {"http_status": status, "cells_count": len(cells),
            "numeric_conversation_count": len(ids)}, ids


def _single_body(identifier: str) -> dict:
    return {
        "cmd": 3100,
        "uplink_body": {"pull_singe_chain_uplink_body": {
            "conversation_id": identifier, "anchor_index": 9007199254740991,
            "conversation_type": 3, "direction": 1, "limit": 20,
            "ext": {}, "filter": {"index_list": []},
            "evaluate_ab_params": "", "evaluate_common_params": "",
        }},
        "sequence_id": str(uuid4()), "channel": 2, "version": "1",
    }


def _single_shape(context, identifier: str) -> tuple[dict[str, object], str | None, str | None]:
    status, data = _post_json(context, "/im/chain/single", _single_body(identifier))
    messages = ((data.get("downlink_body") or {}).get("pull_singe_chain_downlink_body") or {}).get("messages")
    messages = messages if isinstance(messages, list) else []
    block_types: dict[str, int] = {}
    block_type_encodings: dict[str, int] = {}
    creation_type_encodings: dict[str, int] = {}
    video_creation_keys: set[str] = set()
    video_object_keys: set[str] = set()
    download_url_present = False
    candidate_media_urls: set[str] = set()
    download_url_schemes: set[str] = set()
    download_url_hosts: set[str] = set()
    download_url_allowlisted_host = False
    has_input_message_id = False
    has_reply_link = False
    has_video_creation = False
    video_message_keys: set[str] = set()
    text_message_keys: set[str] = set()
    video_local_ids: set[str] = set()
    nonvideo_text_local_ids: set[str] = set()
    nonvideo_text_message_ids: set[str] = set()
    nonvideo_text_local_by_message_id: dict[str, str] = {}
    nonvideo_text_sections: set[str] = set()
    video_reply_ids: set[str] = set()
    video_sections: set[str] = set()
    video_indexes: list[int] = []
    nonvideo_text_indexes: list[int] = []
    video_message_count = 0
    nonvideo_text_message_count = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        has_input_message_id |= isinstance(message.get("local_message_id"), str)
        has_reply_link |= any(isinstance(message.get(key), str) for key in
                              ("reply_to_message_id", "parent_message_id"))
        content = message.get("content")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except ValueError:
                content = None
        if not isinstance(content, list):
            continue
        message_has_video = False
        message_has_text = False
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = str(block.get("block_type"))
            block_types[kind] = block_types.get(kind, 0) + 1
            kind_encoding = type(block.get("block_type")).__name__
            block_type_encodings[kind_encoding] = block_type_encodings.get(kind_encoding, 0) + 1
            message_has_text |= kind == "10000"
            if kind == "2074":
                block_content = block.get("content")
                block_content = block_content if isinstance(block_content, dict) else {}
                creation_block = block_content.get("creation_block")
                creation_block = creation_block if isinstance(creation_block, dict) else {}
                creations = creation_block.get("creations")
                if isinstance(creations, list):
                    for item in creations:
                        if isinstance(item, dict):
                            encoding = type(item.get("type")).__name__
                            creation_type_encodings[encoding] = creation_type_encodings.get(encoding, 0) + 1
                            if item.get("type") == 2:
                                video_creation_keys.update(item)
                                video = item.get("video")
                                if isinstance(video, dict):
                                    video_object_keys.update(video)
                                    download_url_present |= isinstance(video.get("download_url"), str) and bool(video["download_url"])
                                    url = video.get("download_url")
                                    if isinstance(url, str) and url:
                                        candidate_media_urls.add(url)
                                        parsed = urlsplit(url)
                                        download_url_schemes.add(parsed.scheme or "NONE")
                                        host = (parsed.hostname or "").lower()
                                        if host:
                                            download_url_hosts.add(host)
                                        download_url_allowlisted_host |= any(host.endswith(suffix) for suffix in
                                                                         (".byteimg.com", ".volces.com", ".ibytedtos.com", ".bytecdn.cn"))
                message_has_video |= isinstance(creations, list) and any(
                    isinstance(item, dict) and item.get("type") == 2 for item in creations
                )
        has_video_creation |= message_has_video
        if message_has_video:
            video_message_count += 1
            video_message_keys.update(message)
            if isinstance(message.get("local_message_id"), str):
                video_local_ids.add(message["local_message_id"])
            if isinstance(message.get("bot_reply_message_id"), str):
                video_reply_ids.add(message["bot_reply_message_id"])
            if isinstance(message.get("section_id"), str):
                video_sections.add(message["section_id"])
            if isinstance(message.get("index_in_conv"), int):
                video_indexes.append(message["index_in_conv"])
        if message_has_text and not message_has_video:
            nonvideo_text_message_count += 1
            text_message_keys.update(message)
            if isinstance(message.get("local_message_id"), str):
                nonvideo_text_local_ids.add(message["local_message_id"])
            if isinstance(message.get("message_id"), str):
                nonvideo_text_message_ids.add(message["message_id"])
                if isinstance(message.get("local_message_id"), str):
                    nonvideo_text_local_by_message_id[message["message_id"]] = message["local_message_id"]
            if isinstance(message.get("section_id"), str):
                nonvideo_text_sections.add(message["section_id"])
            if isinstance(message.get("index_in_conv"), int):
                nonvideo_text_indexes.append(message["index_in_conv"])
    linked_local_ids = {nonvideo_text_local_by_message_id[message_id]
                        for message_id in video_reply_ids
                        if message_id in nonvideo_text_local_by_message_id}
    summary = {"http_status": status, "messages_count": len(messages),
            "block_type_counts": block_types,
            "block_type_encodings": block_type_encodings,
            "creation_type_encodings": creation_type_encodings,
            "video_creation_keys": sorted(video_creation_keys),
            "video_object_keys": sorted(video_object_keys),
            "download_url_present": download_url_present,
            "download_url_schemes": sorted(download_url_schemes),
            "download_url_hosts": sorted(download_url_hosts),
            "download_url_allowlisted_host": download_url_allowlisted_host,
            "has_local_message_id": has_input_message_id,
            "has_reply_link": has_reply_link,
            "has_video_creation": has_video_creation,
            "video_message_count": video_message_count,
            "nonvideo_text_message_count": nonvideo_text_message_count,
            "video_shares_local_id_with_nonvideo_text": bool(video_local_ids & nonvideo_text_local_ids),
            "video_reply_id_matches_nonvideo_text_message": bool(video_reply_ids & nonvideo_text_message_ids),
            "video_shares_section_with_nonvideo_text": bool(video_sections & nonvideo_text_sections),
            "video_index_after_nonvideo_text": bool(video_indexes and nonvideo_text_indexes
                                                    and min(video_indexes) > min(nonvideo_text_indexes)),
            "video_message_keys": sorted(video_message_keys),
            "text_message_keys": sorted(text_message_keys)}
    local_id = next(iter(linked_local_ids)) if len(linked_local_ids) == 1 else None
    media_url = next(iter(candidate_media_urls)) if len(candidate_media_urls) == 1 else None
    return summary, local_id, media_url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--probe-https-media", action="store_true",
                        help="HEAD only, no cookies, for one exact HTTPS-upgraded Dola media URL")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("OUTPUT_EXISTS")
    result: dict[str, object] = {
        "schema": "story-auto-dola-readonly-conversation-shape/1",
        "account_id": args.alias,
        "scope": "read-only recent/single conversation summaries; no prompt or media content",
        "generation_submits": 0, "cookie_values_recorded": False,
        "conversation_ids_recorded": False,
    }
    try:
        header = DolaAccountStore().get_cookie(args.alias)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                blank = browser.new_context()
                saved = browser.new_context()
                saved.add_cookies(_browser_cookies_from_header(header))
                control_ui = _sample(blank.new_page(), blank)
                saved_ui = _sample(saved.new_page(), saved)
                result["browser_auth_distinguished"] = _qualified(control_ui, saved_ui)
                if not result["browser_auth_distinguished"]:
                    result["status"] = "BROWSER_AUTH_NOT_VERIFIED"
                else:
                    result["unauthenticated_recent"], _ = _recent(blank)
                    result["saved_recent"], ids = _recent(saved)
                    samples = [_single_shape(saved, identifier) for identifier in ids[:3]]
                    result["sampled_conversations"] = len(samples)
                    result["single_shapes"] = [shape for shape, _, _ in samples]
                    for identifier, (shape, local_id, media_url) in zip(ids[:3], samples):
                        if shape["has_video_creation"] and local_id:
                            if args.probe_https_media and media_url:
                                upgraded = _probe_media_url(media_url)
                                if upgraded:
                                    media_request = playwright.request.new_context()
                                    try:
                                        media_response = media_request.head(upgraded, timeout=15000,
                                                                            max_redirects=0)
                                        media_type = media_response.headers.get("content-type", "").split(";", 1)[0].lower()
                                        location = media_response.headers.get("location", "")
                                        result["https_media_head"] = {
                                            "http_status": media_response.status,
                                            "media_type_class": ("VIDEO" if media_type.startswith("video/")
                                                                 else "BINARY" if media_type == "application/octet-stream"
                                                                 else "OTHER"),
                                            "redirect_scheme": urlsplit(location).scheme if location else "",
                                            "redirect_host": urlsplit(location).hostname if location else None,
                                            "cookie_sent": False,
                                            "body_downloaded": False,
                                        }
                                        if media_response.status == 200 and media_type.startswith("video/"):
                                            class NoRedirect(HTTPRedirectHandler):
                                                def redirect_request(self, *args): return None
                                            request = Request(upgraded, method="GET",
                                                              headers={"Range": "bytes=0-1023",
                                                                       "Accept": "video/mp4"})
                                            try:
                                                with build_opener(NoRedirect()).open(request, timeout=15) as stream:
                                                    prefix = stream.read(1024)
                                                    result["https_media_range"] = {
                                                        "http_status": stream.status,
                                                        "content_range_present": bool(stream.headers.get("Content-Range")),
                                                        "mp4_ftyp_present": prefix[4:8] == b"ftyp",
                                                        "bytes_read": len(prefix),
                                                        "cookie_sent": False,
                                                        "full_body_downloaded": False,
                                                    }
                                            except Exception as error:
                                                result["https_media_range"] = {
                                                    "status": "UNAVAILABLE", "error_type": type(error).__name__,
                                                    "cookie_sent": False, "full_body_downloaded": False,
                                                }
                                    except Exception as error:
                                        result["https_media_head"] = {
                                            "status": "UNAVAILABLE", "error_type": type(error).__name__,
                                            "cookie_sent": False, "body_downloaded": False,
                                        }
                                    finally:
                                        media_request.dispose()
                            direct = DolaCookieClient(header)
                            read_variants = {}
                            for label, query, headers in (
                                ("current_params_current_headers", direct._params(), direct._headers(conversation_id=identifier)),
                                ("current_params_browser_headers", direct._params(), HEADERS),
                                ("browser_params_current_headers", QUERY, direct._headers(conversation_id=identifier)),
                            ):
                                variant_status, variant_payload = _post_json(
                                    saved, "/im/chain/single", _single_body(identifier),
                                    query=query, headers=headers)
                                variant_messages = ((variant_payload.get("downlink_body") or {}).get("pull_singe_chain_downlink_body") or {}).get("messages")
                                read_variants[label] = {
                                    "http_status": variant_status,
                                    "messages_count": len(variant_messages) if isinstance(variant_messages, list) else 0,
                                    "video_url_count": len(_video_urls(variant_payload)),
                                }
                            result["adapter_read_variants"] = read_variants
                            direct_headers = {key.lower(): value for key, value in direct._headers(conversation_id=identifier).items()}
                            header_variants = {}
                            for name in ("accept", "content-type", "cookie", "referer", "user-agent"):
                                header_set = {**HEADERS, name: direct_headers[name]}
                                variant_status, variant_payload = _post_json(
                                    saved, "/im/chain/single", _single_body(identifier),
                                    headers=header_set)
                                variant_messages = ((variant_payload.get("downlink_body") or {}).get("pull_singe_chain_downlink_body") or {}).get("messages")
                                header_variants[name] = {
                                    "http_status": variant_status,
                                    "messages_count": len(variant_messages) if isinstance(variant_messages, list) else 0,
                                }
                            result["adapter_header_variants"] = header_variants
                            adapter_wire: dict[str, object] = {}
                            def inspect_opener(request, timeout):
                                with _open(request, timeout) as response:
                                    raw = response.read(2 * 1024 * 1024 + 1)
                                    if len(raw) > 2 * 1024 * 1024:
                                        raise ValueError("READ_RESPONSE_TOO_LARGE")
                                    try:
                                        payload = json.loads(raw)
                                    except ValueError:
                                        payload = {}
                                    payload = payload if isinstance(payload, dict) else {}
                                    messages = ((payload.get("downlink_body") or {}).get("pull_singe_chain_downlink_body") or {}).get("messages")
                                    adapter_wire.update(
                                        http_status=response.status,
                                        messages_count=len(messages) if isinstance(messages, list) else 0,
                                        video_url_count=len(_video_urls(payload)),
                                    )
                                    status = response.status
                                    headers = response.headers
                                    url = response.url
                                class BufferedResponse:
                                    def __init__(self):
                                        self.status = status
                                        self.headers = headers
                                        self.url = url
                                        self.body = BytesIO(raw)
                                    def read(self, amount=-1): return self.body.read(amount)
                                    def __enter__(self): return self
                                    def __exit__(self, *args): return None
                                return BufferedResponse()
                            try:
                                adapter_result = DolaCookieClient(header, opener=inspect_opener).poll(
                                    identifier, client_request_id=local_id)
                                result["adapter_existing_video_identity_status"] = adapter_result["status"]
                            except DolaCookieError as error:
                                result["adapter_existing_video_identity_status"] = error.failure_class
                            result["adapter_read_wire_shape"] = adapter_wire
                            break
                    result["status"] = "READ_COMPLETE"
            finally:
                browser.close()
    except Exception as error:
        result["status"] = "PROBE_UNAVAILABLE"
        result["error_type"] = type(error).__name__
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "READ_COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())

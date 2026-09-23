"""Minimal, bounded Dola cookie transport for experimental text-to-video.

Only the documented-in-evidence Dola web wire shape is used here.  No browser
automation, cookie pool, reference upload, or retry policy is hidden here.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import time
from typing import Any, Callable, Iterable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from story_auto.providers.flow.validation import AssetValidationError, validate_video


ORIGIN = "https://www.dola.com"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024
_DOWNLOAD_HOST_SUFFIXES = (".byteimg.com", ".volces.com", ".ibytedtos.com", ".bytecdn.cn")
_DOLA_MEDIA_HOST = "v16-dola.dola.com"
_CREDIT_FAILURE = re.compile(
    r"unable to (generate|create)|failed to (generate|create)|insufficient|"
    r"余额不足|餘額不足|额度不足|額度不足|额度耗尽|額度耗盡|"
    r"无法生成|無法生成|不能生成|無法完成|无法完成",
    re.IGNORECASE,
)
_DURATION_CONFIRMATION = re.compile(
    r"\bshould i proceed with\s+\d+\s+seconds?\b", re.IGNORECASE,
)


def _safe_http_status(value: Any) -> int | None:
    return (value if isinstance(value, int) and not isinstance(value, bool)
            and 100 <= value <= 599 else None)


def _safe_response_kind(headers: Any) -> str:
    """Record only a fixed media-type class, never provider text or headers."""
    try:
        content_type = headers.get("Content-Type", "")
    except (AttributeError, TypeError, ValueError):
        return "UNKNOWN"
    if not isinstance(content_type, str):
        return "UNKNOWN"
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type == "text/event-stream":
        return "SSE"
    if media_type == "application/json" or media_type.endswith("+json"):
        return "JSON"
    if media_type == "text/html":
        return "HTML"
    return "OTHER" if media_type else "UNKNOWN"


class DolaCookieError(RuntimeError):
    def __init__(self, failure_class: str, dispatch_state: str = "NOT_DISPATCHED",
                 *, http_status: int | None = None, response_kind: str | None = None,
                 receipt_state: str | None = None,
                 read_diagnostic: str | None = None) -> None:
        self.failure_class = failure_class
        self.dispatch_state = dispatch_state
        self.http_status = _safe_http_status(http_status)
        self.response_kind = response_kind if response_kind in {"SSE", "JSON", "HTML", "OTHER", "UNKNOWN"} else None
        self.receipt_state = receipt_state if receipt_state in {"EMPTY_BODY", "NO_ACK", "ACK_INVALID"} else None
        self.read_diagnostic = (read_diagnostic if isinstance(read_diagnostic, str)
                                and re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}(?:\|[A-Z][A-Z0-9_]{1,79})?",
                                                 read_diagnostic) else None)
        super().__init__(failure_class)


class _Response(Protocol):
    status: int
    headers: Any
    url: str
    def read(self, amount: int = -1) -> bytes: ...
    def __enter__(self) -> "_Response": ...
    def __exit__(self, *args: Any) -> None: ...


OpenRequest = Callable[[Request, float], _Response]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise DolaCookieError("DOWNLOAD_REDIRECT_REJECTED", "DISPATCH_CONFIRMED")


def _open(request: Request, timeout: float) -> _Response:
    return build_opener(_NoRedirect()).open(request, timeout=timeout)  # type: ignore[return-value]


def _cookie_value(cookie: str, name: str) -> str:
    found = re.search(r"(?:^|;)\s*" + re.escape(name) + r"=([^;]+)", cookie)
    return found.group(1) if found else ""


def _safe_host(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    try:
        port_allowed = parsed.port in {None, 443}
    except ValueError:
        return False
    return (parsed.scheme == "https" and port_allowed and not parsed.username
            and not parsed.password and not parsed.fragment
            and (host == _DOLA_MEDIA_HOST
                 or any(host.endswith(suffix) for suffix in _DOWNLOAD_HOST_SUFFIXES)))


def _canonical_media_url(url: str) -> str:
    """Upgrade only the Dola host proven to serve this signed path over TLS."""
    parsed = urlparse(url)
    if parsed.scheme == "http" and parsed.hostname == _DOLA_MEDIA_HOST:
        try:
            if parsed.port is not None:
                return ""
        except ValueError:
            return ""
        if parsed.username or parsed.password or parsed.fragment:
            return ""
        return urlunparse(parsed._replace(scheme="https", netloc=_DOLA_MEDIA_HOST))
    return url if parsed.scheme == "https" else ""


def _bounded_read(response: _Response, limit: int = _MAX_RESPONSE_BYTES) -> bytes:
    data = response.read(limit + 1)
    if len(data) > limit:
        raise DolaCookieError("PROVIDER_RESPONSE_TOO_LARGE", "DISPATCH_CONFIRMED")
    return data


def _as_json(data: bytes, failure: str, dispatch_state: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DolaCookieError(failure, dispatch_state) from error
    if not isinstance(value, dict):
        raise DolaCookieError(failure, dispatch_state)
    return value


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _video_urls(payload: dict[str, Any]) -> list[str]:
    """Extract only Dola's observed chain message -> creation video shape."""
    messages = ((payload.get("downlink_body") or {}).get("pull_singe_chain_downlink_body") or {}).get("messages")
    if not isinstance(messages, list):
        return []
    urls: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("block_type") != 2074:
                continue
            creations = ((block.get("content") or {}).get("creation_block") or {}).get("creations")
            if not isinstance(creations, list):
                continue
            for creation in creations:
                if not isinstance(creation, dict) or creation.get("type") != 2:
                    continue
                candidate = ((creation.get("video") or {}).get("download_url"))
                if isinstance(candidate, str) and candidate:
                    canonical = _canonical_media_url(candidate)
                    if not canonical or not _safe_host(canonical):
                        raise DolaCookieError("PROVIDER_RESULT_URL_REJECTED", "DISPATCH_CONFIRMED")
                    urls.append(canonical)
    return list(dict.fromkeys(urls))


def _linked_master_url(payload: dict[str, Any], download_url: str) -> str | None:
    """Prefer a safe master variant inside the exact linked video creation.

    The caller first proves the conversation/input/reply linkage using the
    ordinary download URL. A decoded URL from any other creation is ignored.
    """
    messages = ((payload.get("downlink_body") or {}).get("pull_singe_chain_downlink_body") or {}).get("messages")
    if not isinstance(messages, list):
        return None
    candidates: list[tuple[int, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("block_type") != 2074:
                continue
            creations = ((block.get("content") or {}).get("creation_block") or {}).get("creations")
            if not isinstance(creations, list):
                continue
            for creation in creations:
                if not isinstance(creation, dict) or creation.get("type") != 2:
                    continue
                video = creation.get("video") or {}
                preview = video.get("download_url") if isinstance(video, dict) else None
                if not isinstance(preview, str) or _canonical_media_url(preview) != download_url:
                    continue
                model = video.get("video_model")
                if isinstance(model, str):
                    if len(model) > 128 * 1024:
                        continue
                    try:
                        model = json.loads(model)
                    except json.JSONDecodeError:
                        continue
                variants = model.get("video_list") if isinstance(model, dict) else None
                if not isinstance(variants, dict):
                    continue
                for variant in variants.values():
                    if not isinstance(variant, dict):
                        continue
                    token = variant.get("main_url")
                    if not isinstance(token, str) or not 1 <= len(token) <= 8192:
                        continue
                    try:
                        url = base64.b64decode(token, validate=True).decode("utf-8")
                    except (ValueError, UnicodeDecodeError):
                        continue
                    canonical = _canonical_media_url(url)
                    if not canonical or not _safe_host(canonical):
                        continue
                    bitrate = variant.get("bitrate") or variant.get("real_bitrate") or 0
                    if not isinstance(bitrate, int) or isinstance(bitrate, bool) or bitrate < 0:
                        continue
                    candidates.append((bitrate, canonical))
    if not candidates:
        return None
    highest = max(rate for rate, _ in candidates)
    best = {url for rate, url in candidates if rate == highest}
    if len(best) != 1:
        raise DolaCookieError("PROVIDER_RESULT_AMBIGUOUS", "DISPATCH_CONFIRMED")
    return best.pop()


def _linked_duration_confirmation(payload: dict[str, Any], conversation_id: str, local_id: str) -> bool:
    """Recognize only a duration question replying to this exact native input."""
    messages = ((payload.get("downlink_body") or {}).get("pull_singe_chain_downlink_body") or {}).get("messages")
    if not isinstance(messages, list):
        return False
    inputs = {message.get("message_id") for message in messages
              if isinstance(message, dict) and message.get("local_message_id") == local_id
              and message.get("conversation_id") in {None, "", conversation_id}
              and isinstance(message.get("message_id"), str)}
    if len(inputs) != 1:
        return False
    for message in messages:
        if (not isinstance(message, dict) or message.get("bot_reply_message_id") not in inputs
                or message.get("conversation_id") not in {None, "", conversation_id}):
            continue
        content = message.get("content")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("block_type") != 10000:
                continue
            text = ((block.get("content") or {}).get("text_block") or {}).get("text")
            if isinstance(text, str) and _DURATION_CONFIRMATION.search(text):
                return True
    return False


class DolaCookieClient:
    """One explicit cookie session, with no account rotation or POST retries."""
    provider = "dola_cookie"
    requested_model = "seedance_v2.0"  # observed in upstream seed only; provider acceptance is unverified.
    supported_durations = (5, 10)

    def __init__(self, cookie: str, *, opener: OpenRequest = _open, timeout: float = 120.0) -> None:
        if (not isinstance(cookie, str) or "\r" in cookie or "\n" in cookie
                or not (_cookie_value(cookie, "sessionid") or _cookie_value(cookie, "sessionid_ss"))):
            raise DolaCookieError("CREDENTIAL_MISSING")
        self._cookie = cookie
        self._opener = opener
        self._timeout = timeout
        self._ms_token = _cookie_value(cookie, "msToken")
        self._fp = _cookie_value(cookie, "s_v_web_id")

    def _params(self) -> str:
        values: dict[str, str] = {
            "aid": "495671", "channel": "g", "device_platform": "web", "language": "zh-Hant",
            "region": "JP", "sys_region": "JP", "samantha_web": "1", "use-olympus-account": "1",
            "version_code": "20800", "web_platform": "browser", "web_tab_id": str(uuid4()),
        }
        if self._ms_token:
            values["msToken"] = self._ms_token
        if self._fp:
            values["fp"] = self._fp
        return urlencode(values)

    def _headers(self, *, conversation_id: str = "", sse: bool = False) -> dict[str, str]:
        return {
            "Accept": "text/event-stream" if sse else "application/json",
            # Dola's current read path returns an empty chain with charset;
            # live A/B requires encoding. Keep the unqualified submit form.
            "Content-Type": ("application/json; charset=utf-8" if sse
                             else "application/json; encoding=utf-8"),
            "Cookie": self._cookie,
            "Origin": ORIGIN,
            "Referer": ORIGIN + ("/chat/" + conversation_id if conversation_id else "/chat/"),
            "User-Agent": "StoryAuto Dola experimental transport",
            "agw-js-conv": "str, str" if sse else "str",
        }

    def _video_body(self, prompt: str, aspect_ratio: str, duration: int) -> dict[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 10_000:
            raise DolaCookieError("CAPABILITY_OR_REQUEST_INVALID")
        if aspect_ratio not in {"16:9", "9:16", "1:1"} or duration not in self.supported_durations:
            raise DolaCookieError("CAPABILITY_OR_REQUEST_INVALID")
        now_ms = int(time.time() * 1000)
        now_sec = now_ms // 1000
        return {
            "client_meta": {"local_conversation_id": f"local_{now_ms}", "conversation_id": "",
                            "bot_id": "7339470689562525703", "last_section_id": "", "last_message_index": None},
            "messages": [{"local_message_id": str(uuid4()), "content_block": [{"block_type": 10000,
                "content": {"text_block": {"text": f"生成影片：{prompt.strip()}，{aspect_ratio}", "icon_url": "", "icon_url_dark": "", "summary": ""}, "pc_event_block": ""},
                "block_id": str(uuid4()), "parent_id": "", "meta_info": [], "append_fields": []}], "message_status": 0}],
            "option": {"create_time_ms": now_ms, "need_deep_think": 0, "need_create_conversation": True,
                       "conversation_init_option": {"need_ack_conversation": True}, "unique_key": str(uuid4()),
                       "recovery_option": {"is_recovery": False, "req_create_time_sec": now_sec, "append_sse_event_scene": 0},
                       "sse_recv_event_options": {"support_chunk_delta": True}, "message_from": 0, "is_audio": False},
            "chat_ability": {"ability_type": 17, "ability_param": json.dumps({"ratio": aspect_ratio, "model": self.requested_model, "duration": duration}, separators=(",", ":"))},
            "user_context": [],
            "ext": {"fp": self._fp, "use_deep_think": "0", "sub_conv_firstmet_type": "1",
                    "conversation_init_option": '{"need_ack_conversation":true}', "commerce_credit_config_enable": "0"},
        }

    def submit(self, prompt: str, aspect_ratio: str, duration: int,
               on_receipt: Callable[[str], None], *, client_request_id: str | None = None) -> str:
        """Submit once; persist the receipt via callback before the SSE is consumed further."""
        payload = self._video_body(prompt, aspect_ratio, duration)
        if client_request_id is not None:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", client_request_id):
                raise DolaCookieError("CLIENT_REQUEST_ID_INVALID")
            payload["messages"][0]["local_message_id"] = client_request_id
            payload["option"]["unique_key"] = client_request_id
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(ORIGIN + "/chat/completion?" + self._params(), data=body, method="POST", headers=self._headers(sse=True))
        observed_status: int | None = None
        try:
            response = self._opener(request, self._timeout)
        except HTTPError as error:
            failure = "CREDENTIAL_OR_ACCESS_DENIED" if error.code in {401, 403} else "AMBIGUOUS"
            # A POST reached an HTTP responder; even an auth error is not
            # provider-side proof that no effect occurred.
            raise DolaCookieError(failure, "AMBIGUOUS", http_status=error.code) from error
        except (TimeoutError, URLError, OSError) as error:
            raise DolaCookieError("AMBIGUOUS", "AMBIGUOUS") from error
        try:
            with response:
                observed_status = int(getattr(response, "status", 200))
                if observed_status in {401, 403}:
                    raise DolaCookieError("CREDENTIAL_OR_ACCESS_DENIED", "AMBIGUOUS", http_status=observed_status)
                if observed_status >= 400:
                    raise DolaCookieError("AMBIGUOUS", "AMBIGUOUS", http_status=observed_status)
                try:
                    return self._receipt_from_sse(response, on_receipt)
                except DolaCookieError as error:
                    if error.http_status is None:
                        error.http_status = _safe_http_status(observed_status)
                    if error.response_kind is None:
                        error.response_kind = _safe_response_kind(getattr(response, "headers", None))
                    raise
        except DolaCookieError:
            raise
        except (TimeoutError, URLError, OSError) as error:
            raise DolaCookieError("AMBIGUOUS", "AMBIGUOUS", http_status=observed_status) from error

    def _receipt_from_sse(self, response: _Response, on_receipt: Callable[[str], None]) -> str:
        buffered = b""
        seen = 0
        ack_seen = False
        read_available = getattr(response, "read1", None)
        while True:
            # read1 returns currently available bytes from buffered HTTP streams.
            # It avoids waiting for an arbitrary 4KiB response before recording an ACK.
            chunk = read_available(4096) if callable(read_available) else response.read(4096)
            if not chunk:
                break
            seen += len(chunk)
            if seen > _MAX_RESPONSE_BYTES:
                raise DolaCookieError("PROVIDER_RESPONSE_TOO_LARGE", "AMBIGUOUS")
            buffered = (buffered + chunk).replace(b"\r\n", b"\n")
            while b"\n\n" in buffered:
                raw, buffered = buffered.split(b"\n\n", 1)
                event_name = b""
                for line in raw.splitlines():
                    if line.startswith(b"event:"):
                        event_name = line[6:].strip()
                data = b"\n".join(line[5:].strip() for line in raw.splitlines() if line.startswith(b"data:"))
                if event_name != b"SSE_ACK":
                    continue
                ack_seen = True
                if not data:
                    continue
                try:
                    event = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(event, dict):
                    continue
                receipt = (event.get("ack_client_meta") or {}).get("conversation_id")
                if isinstance(receipt, str) and receipt and len(receipt) <= 160:
                    on_receipt(receipt)
                    return receipt
        state = "EMPTY_BODY" if seen == 0 else "ACK_INVALID" if ack_seen else "NO_ACK"
        raise DolaCookieError("RECEIPT_MISSING", "AMBIGUOUS", receipt_state=state)

    def _read_chain(self, conversation_id: str) -> dict[str, Any]:
        if (not isinstance(conversation_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", conversation_id)):
            raise DolaCookieError("PROVIDER_JOB_ID_INVALID", "DISPATCH_CONFIRMED")
        # Read-only shape verified against a signed-in Dola conversation. The
        # older top-level conversation_id form is not the current web uplink.
        body = json.dumps({
            "cmd": 3100,
            "uplink_body": {"pull_singe_chain_uplink_body": {
                "conversation_id": conversation_id,
                "anchor_index": 9007199254740991,
                "conversation_type": 3,
                "direction": 1,
                "limit": 20,
                "ext": {},
                "filter": {"index_list": []},
                "evaluate_ab_params": "",
                "evaluate_common_params": "",
            }},
            "sequence_id": str(uuid4()), "channel": 2, "version": "1",
        }, separators=(",", ":")).encode("utf-8")
        request = Request(ORIGIN + "/im/chain/single?" + self._params(), data=body, method="POST", headers=self._headers(conversation_id=conversation_id))
        try:
            with self._opener(request, self._timeout) as response:
                status = int(getattr(response, "status", 200))
                if status in {401, 403}:
                    raise DolaCookieError("CREDENTIAL_OR_ACCESS_DENIED", "DISPATCH_CONFIRMED")
                if status >= 400:
                    raise DolaCookieError("PROVIDER_TRANSIENT", "DISPATCH_CONFIRMED")
                payload = _as_json(_bounded_read(response), "PROVIDER_RESPONSE_INVALID", "DISPATCH_CONFIRMED")
        except DolaCookieError:
            raise
        except HTTPError as error:
            code = "CREDENTIAL_OR_ACCESS_DENIED" if error.code in {401, 403} else "PROVIDER_TRANSIENT"
            raise DolaCookieError(code, "DISPATCH_CONFIRMED") from error
        except (TimeoutError, URLError, OSError) as error:
            raise DolaCookieError("PROVIDER_TRANSIENT", "DISPATCH_CONFIRMED") from error
        return payload

    def verify_input(self, conversation_id: str, local_message_id: str) -> bool:
        """Read-only proof that this conversation contains the native UI input."""
        if not isinstance(local_message_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", local_message_id):
            raise DolaCookieError("CLIENT_REQUEST_ID_INVALID", "DISPATCH_CONFIRMED")
        payload = self._read_chain(conversation_id)
        messages = ((payload.get("downlink_body") or {}).get("pull_singe_chain_downlink_body") or {}).get("messages")
        if not isinstance(messages, list):
            raise DolaCookieError("PROVIDER_RESPONSE_INVALID", "DISPATCH_CONFIRMED")
        matches = []
        for message in messages:
            if not isinstance(message, dict) or message.get("local_message_id") != local_message_id:
                continue
            if message.get("conversation_id") not in {None, "", conversation_id}:
                raise DolaCookieError("DOLA_RESULT_IDENTITY_MISMATCH", "DISPATCH_CONFIRMED")
            content = message.get("content")
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    content = None
            if not isinstance(content, list):
                continue
            kinds = {block.get("block_type") for block in content if isinstance(block, dict)}
            if 10000 in kinds and 2074 not in kinds and isinstance(message.get("message_id"), str):
                matches.append(message)
        if len(matches) > 1:
            raise DolaCookieError("DOLA_RESULT_IDENTITY_UNVERIFIED", "DISPATCH_CONFIRMED")
        return len(matches) == 1

    def poll(self, conversation_id: str, *, client_request_id: str | None = None) -> dict[str, str]:
        payload = self._read_chain(conversation_id)
        urls = _video_urls(payload)
        if len(urls) > 1:
            raise DolaCookieError("PROVIDER_RESULT_AMBIGUOUS", "DISPATCH_CONFIRMED")
        if len(urls) == 1:
            if client_request_id is not None:
                # The private contract's echo must be observed, not assumed.
                # A missing echo remains recoverable but cannot authorize import.
                messages = ((payload.get("downlink_body") or {}).get("pull_singe_chain_downlink_body") or {}).get("messages", [])
                chain_messages = [n for n in messages if isinstance(n, dict)]
                matched_inputs = [n for n in chain_messages
                                  if n.get("local_message_id") == client_request_id
                                  and not _video_urls({"downlink_body": {
                                      "pull_singe_chain_downlink_body": {"messages": [n]}}})]
                if not matched_inputs:
                    raise DolaCookieError("DOLA_RESULT_IDENTITY_UNVERIFIED", "DISPATCH_CONFIRMED")
                if any(n.get("conversation_id") not in {None, "", conversation_id}
                       for n in chain_messages):
                    raise DolaCookieError("DOLA_RESULT_IDENTITY_MISMATCH", "DISPATCH_CONFIRMED")
                input_ids = {n.get("message_id") for n in matched_inputs if isinstance(n.get("message_id"), str)}
                linked = False
                for message in messages:
                    if not isinstance(message, dict):
                        continue
                    single = {"downlink_body": {"pull_singe_chain_downlink_body": {"messages": [message]}}}
                    if not _video_urls(single):
                        continue
                    linked = (message.get("local_message_id") == client_request_id
                              or bool(input_ids.intersection({message.get("reply_to_message_id"),
                                                              message.get("parent_message_id"),
                                                              message.get("bot_reply_message_id")})))
                    if not linked:
                        raise DolaCookieError("DOLA_RESULT_IDENTITY_UNVERIFIED", "DISPATCH_CONFIRMED")
                if not linked:
                    raise DolaCookieError("DOLA_RESULT_IDENTITY_UNVERIFIED", "DISPATCH_CONFIRMED")
            master = _linked_master_url(payload, urls[0])
            if master:
                return {"status": "COMPLETED", "video_url": master, "media_variant": "master"}
            return {"status": "COMPLETED", "video_url": urls[0]}
        if client_request_id and _linked_duration_confirmation(payload, conversation_id, client_request_id):
            return {"status": "NEEDS_OPERATOR", "reason": "DOLA_DURATION_CONFIRMATION_REQUIRED"}
        text = " ".join(str(node.get("text", "")) for node in _walk(payload))
        return {"status": "FAILED" if _CREDIT_FAILURE.search(text) else "PENDING"}

    def download(self, video_url: str, destination: Path) -> dict[str, Any]:
        if not _safe_host(video_url):
            raise DolaCookieError("DOWNLOAD_HOST_REJECTED", "DISPATCH_CONFIRMED")
        if destination.exists():
            raise DolaCookieError("ASSET_DESTINATION_EXISTS", "DISPATCH_CONFIRMED")
        candidate = destination.with_suffix(destination.suffix + ".candidate")
        if candidate.exists():
            raise DolaCookieError("ASSET_DESTINATION_EXISTS", "DISPATCH_CONFIRMED")
        request = Request(video_url, headers={"Accept": "video/mp4", "User-Agent": "StoryAuto Dola experimental transport"})
        candidate_started = False
        try:
            with self._opener(request, self._timeout) as response:
                if not _safe_host(str(getattr(response, "url", video_url))):
                    raise DolaCookieError("DOWNLOAD_HOST_REJECTED", "DISPATCH_CONFIRMED")
                if int(getattr(response, "status", 200)) >= 400:
                    raise DolaCookieError("ASSET_ACQUISITION_FAILED", "DISPATCH_CONFIRMED")
                content_type = str(getattr(response, "headers", {}).get("Content-Type", "")).lower()
                if "video" not in content_type and "octet-stream" not in content_type:
                    raise DolaCookieError("ASSET_ACQUISITION_FAILED", "DISPATCH_CONFIRMED")
                destination.parent.mkdir(parents=True, exist_ok=True)
                total = 0
                candidate_started = True
                with candidate.open("wb") as handle:
                    while True:
                        part = response.read(64 * 1024)
                        if not part:
                            break
                        total += len(part)
                        if total > _MAX_DOWNLOAD_BYTES:
                            raise DolaCookieError("ASSET_ACQUISITION_FAILED", "DISPATCH_CONFIRMED")
                        handle.write(part)
                try:
                    metadata = validate_video(candidate)
                except AssetValidationError as error:
                    raise DolaCookieError("ASSET_ACQUISITION_FAILED", "DISPATCH_CONFIRMED") from error
                candidate.replace(destination)
                candidate_started = False
                return metadata
        except DolaCookieError:
            raise
        except (HTTPError, TimeoutError, URLError, OSError) as error:
            raise DolaCookieError("ASSET_ACQUISITION_FAILED", "DISPATCH_CONFIRMED") from error
        finally:
            if candidate_started:
                candidate.unlink(missing_ok=True)

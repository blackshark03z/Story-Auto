from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from story_auto.providers.dola_cookie import DolaCookieClient, DolaCookieError


COOKIE = "sessionid=opaque-session; msToken=opaque-ms; s_v_web_id=opaque-fingerprint"


class _Response:
    def __init__(self, body: bytes, *, status: int = 200, url: str = "https://media.byteimg.com/video.mp4",
                 content_type: str = "application/json") -> None:
        self._body = io.BytesIO(body)
        self.status = status
        self.url = url
        self.headers = {"Content-Type": content_type}

    def read(self, amount: int = -1) -> bytes:
        return self._body.read(amount)

    def __enter__(self): return self
    def __exit__(self, *args): return None


class _Read1OnlyResponse(_Response):
    def __init__(self, chunks: list[bytes]) -> None:
        super().__init__(b"", content_type="text/event-stream")
        self._chunks = iter(chunks)

    def read1(self, amount: int) -> bytes:
        return next(self._chunks, b"")

    def read(self, amount: int = -1) -> bytes:
        raise AssertionError("submit must not wait for a full response when read1 is available")


def _opener_for(*responses: _Response):
    items = iter(responses)
    def open_request(request, timeout):
        return next(items)
    return open_request


def _chain(*urls: str) -> bytes:
    creations = [{"type": 2, "video": {"download_url": url}} for url in urls]
    return json.dumps({"downlink_body": {"pull_singe_chain_downlink_body": {"messages": [
        {"content": json.dumps([{"block_type": 2074, "content": {"creation_block": {"creations": creations}}}])}
    ]}}}).encode()


class DolaCookieClientTests(unittest.TestCase):
    def test_poll_prefers_master_from_the_same_video_creation(self):
        preview = "https://v16-dola.dola.com/preview.mp4"
        master = "https://v16-dola.dola.com/master.mp4"
        unrelated = "https://v16-dola.dola.com/unrelated.mp4"
        payload = json.loads(_chain(preview))
        message = payload["downlink_body"]["pull_singe_chain_downlink_body"]["messages"][0]
        content = json.loads(message["content"])
        video = content[0]["content"]["creation_block"]["creations"][0]["video"]
        video["video_model"] = json.dumps({"video_list": {
            "low": {"main_url": base64.b64encode(unrelated.encode()).decode(), "bitrate": 100},
            "high": {"main_url": base64.b64encode(master.encode()).decode(), "bitrate": 200},
        }})
        content[0]["content"]["creation_block"]["creations"].append({
            "type": 2, "video": {"download_url": "https://v16-dola.dola.com/other.mp4",
                                 "video_model": json.dumps({"video_list": {"higher": {
                                     "main_url": base64.b64encode(unrelated.encode()).decode(),
                                     "bitrate": 1000}}})}})
        # More than one creation is still ambiguous, even if a master matches.
        message["content"] = json.dumps(content)
        with self.assertRaisesRegex(DolaCookieError, "PROVIDER_RESULT_AMBIGUOUS"):
            DolaCookieClient(COOKIE, opener=_opener_for(_Response(json.dumps(payload).encode()))).poll("conv-1")
        content[0]["content"]["creation_block"]["creations"].pop()
        message["content"] = json.dumps(content)
        result = DolaCookieClient(COOKIE, opener=_opener_for(_Response(json.dumps(payload).encode()))).poll("conv-1")
        self.assertEqual(result, {"status": "COMPLETED", "video_url": master, "media_variant": "master"})

    def test_poll_falls_back_to_preview_when_master_is_unsafe(self):
        preview = "https://v16-dola.dola.com/preview.mp4"
        payload = json.loads(_chain(preview))
        message = payload["downlink_body"]["pull_singe_chain_downlink_body"]["messages"][0]
        content = json.loads(message["content"])
        video = content[0]["content"]["creation_block"]["creations"][0]["video"]
        video["video_model"] = json.dumps({"video_list": {"unsafe": {
            "main_url": base64.b64encode(b"http://other.invalid/video.mp4").decode(),
            "bitrate": 9000}}})
        message["content"] = json.dumps(content)
        result = DolaCookieClient(COOKIE, opener=_opener_for(_Response(json.dumps(payload).encode()))).poll("conv-1")
        self.assertEqual(result, {"status": "COMPLETED", "video_url": preview})

    def test_current_sessionid_ss_is_accepted_and_forwarded_without_aliasing(self):
        cookie = "sessionid_ss=opaque-current; passport_csrf_token=opaque-csrf"
        client = DolaCookieClient(cookie)
        self.assertEqual(client._headers()["Cookie"], cookie)
        with self.assertRaises(DolaCookieError):
            DolaCookieClient("passport_csrf_token=opaque-csrf")
        with self.assertRaises(DolaCookieError):
            DolaCookieClient("SessionID_SS=wrong-case")

    def test_submit_records_ack_immediately_without_waiting_for_stream_end(self):
        stream = b'event: SSE_ACK\ndata: {"ack_client_meta":{"conversation_id":"conv-1"}}\n\n' + b"data: never-needed"
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(stream, content_type="text/event-stream")))
        receipts: list[str] = []
        self.assertEqual(client.submit("a river", "16:9", 5, receipts.append), "conv-1")
        self.assertEqual(receipts, ["conv-1"])

    def test_read_header_change_does_not_alter_unqualified_submit_wire(self):
        captured = []
        stream = b'event: SSE_ACK\ndata: {"ack_client_meta":{"conversation_id":"conv-1"}}\n\n'
        def capture(request, timeout):
            captured.append(request)
            return _Response(stream, content_type="text/event-stream")
        client = DolaCookieClient(COOKIE, opener=capture)
        self.assertEqual(client._headers()["Content-Type"], "application/json; encoding=utf-8")
        client.submit("a river", "16:9", 5, lambda _: None)
        self.assertEqual(captured[0].get_header("Content-type"),
                         "application/json; charset=utf-8")

    def test_submit_uses_incremental_read1_and_accepts_crlf_split_ack_only(self):
        response = _Read1OnlyResponse([
            b"event: SSE_ACK\r", b'\ndata: {"ack_client_meta":{"conversation_id":"conv-2"}}\r\n\r\n',
        ])
        receipts: list[str] = []
        self.assertEqual(DolaCookieClient(COOKIE, opener=_opener_for(response)).submit("a river", "16:9", 5, receipts.append), "conv-2")
        self.assertEqual(receipts, ["conv-2"])

        no_event_type = _Response(b'data: {"ack_client_meta":{"conversation_id":"conv-not-an-ack"}}\n\n', content_type="text/event-stream")
        with self.assertRaisesRegex(DolaCookieError, "RECEIPT_MISSING"):
            DolaCookieClient(COOKIE, opener=_opener_for(no_event_type)).submit("a river", "16:9", 5, lambda _: None)

    def test_submit_missing_ack_is_ambiguous(self):
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(b"data: {}\n\n", content_type="text/event-stream")))
        with self.assertRaises(DolaCookieError) as caught:
            client.submit("a river", "16:9", 5, lambda _: None)
        self.assertEqual((caught.exception.failure_class, caught.exception.dispatch_state), ("RECEIPT_MISSING", "AMBIGUOUS"))
        self.assertEqual(caught.exception.http_status, 200)
        self.assertEqual(caught.exception.response_kind, "SSE")
        self.assertEqual(caught.exception.receipt_state, "NO_ACK")

    def test_missing_receipt_diagnostics_are_fixed_classes_not_provider_text(self):
        cases = (
            (b"", "text/event-stream", "SSE", "EMPTY_BODY"),
            (b'{"error":"private-secret"}', "application/json; charset=utf-8", "JSON", "NO_ACK"),
            (b'<html>private-secret</html>', "text/html", "HTML", "NO_ACK"),
            (b'event: SSE_ACK\ndata: {private-secret}\n\n', "text/event-stream", "SSE", "ACK_INVALID"),
        )
        for body, content_type, kind, state in cases:
            with self.subTest(kind=kind, state=state):
                client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(body, content_type=content_type)))
                with self.assertRaises(DolaCookieError) as caught:
                    client.submit("a river", "16:9", 5, lambda _: None)
                self.assertEqual((caught.exception.response_kind, caught.exception.receipt_state), (kind, state))
                self.assertNotIn("private-secret", str(caught.exception))

    def test_diagnostic_fields_reject_unbounded_values(self):
        error = DolaCookieError("RECEIPT_MISSING", "AMBIGUOUS", response_kind="private-secret",
                                receipt_state="private-secret")
        self.assertIsNone(error.response_kind)
        self.assertIsNone(error.receipt_state)

    def test_submit_http_error_records_status_without_claiming_no_dispatch(self):
        from urllib.error import HTTPError
        for status in (401, 404, 429, 503):
            with self.subTest(status=status):
                def rejected(*args):
                    raise HTTPError("https://www.dola.com/chat/completion", status, "private", {}, None)
                with self.assertRaises(DolaCookieError) as caught:
                    DolaCookieClient(COOKIE, opener=rejected).submit("a river", "16:9", 5, lambda _: None)
                self.assertEqual(caught.exception.dispatch_state, "AMBIGUOUS")
                self.assertEqual(caught.exception.http_status, status)
                self.assertNotIn("private", str(caught.exception))

    def test_submit_non_exception_http_error_is_also_ambiguous(self):
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(b"", status=403)))
        with self.assertRaises(DolaCookieError) as caught:
            client.submit("a river", "16:9", 5, lambda _: None)
        self.assertEqual((caught.exception.dispatch_state, caught.exception.http_status), ("AMBIGUOUS", 403))

    def test_abnormal_http_status_never_enters_safe_diagnostic(self):
        for status in (0, 1, 600, True):
            with self.subTest(status=status):
                client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(b"", status=status)))
                with self.assertRaises(DolaCookieError) as caught:
                    client.submit("a river", "16:9", 5, lambda _: None)
                self.assertIsNone(caught.exception.http_status)

    def test_submit_disconnect_is_ambiguous(self):
        def disconnected(request, timeout):
            raise OSError("network details must not surface")
        client = DolaCookieClient(COOKIE, opener=disconnected)
        with self.assertRaises(DolaCookieError) as caught:
            client.submit("a river", "16:9", 5, lambda _: None)
        self.assertEqual((caught.exception.failure_class, caught.exception.dispatch_state), ("AMBIGUOUS", "AMBIGUOUS"))
        self.assertNotIn("network", str(caught.exception))

    def test_poll_requires_exact_single_video_output(self):
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(_chain("https://media.byteimg.com/one.mp4"))))
        self.assertEqual(client.poll("conv-1"), {"status": "COMPLETED", "video_url": "https://media.byteimg.com/one.mp4"})

        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(_chain(
            "https://media.byteimg.com/one.mp4", "https://media.byteimg.com/two.mp4"))))
        with self.assertRaises(DolaCookieError) as caught:
            client.poll("conv-1")
        self.assertEqual(caught.exception.failure_class, "PROVIDER_RESULT_AMBIGUOUS")

    def test_poll_rejects_unsafe_video_url_even_beside_valid_output(self):
        for urls in (("http://other.invalid/video.mp4",),
                     ("https://media.byteimg.com/one.mp4", "http://other.invalid/two.mp4")):
            with self.subTest(urls=urls):
                client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(_chain(*urls))))
                with self.assertRaises(DolaCookieError) as caught:
                    client.poll("conv-1")
                self.assertEqual(caught.exception.failure_class, "PROVIDER_RESULT_URL_REJECTED")

    def test_poll_missing_output_is_pending(self):
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(_chain())))
        self.assertEqual(client.poll("conv-1"), {"status": "PENDING"})

    def test_poll_links_duration_question_to_exact_native_input(self):
        payload = json.loads(_chain())
        messages = payload["downlink_body"]["pull_singe_chain_downlink_body"]["messages"]
        messages.extend([
            {"message_id": "reply-1", "bot_reply_message_id": "input-1",
             "content": json.dumps([{"block_type": 10000, "content": {"text_block": {"text":
                "I can generate it at 15 seconds. Should I proceed with 15 seconds?"}}}])},
            {"message_id": "input-1", "local_message_id": "native-1",
             "content": json.dumps([{"block_type": 10000}])},
        ])
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(json.dumps(payload).encode())))
        self.assertEqual(client.poll("conv-1", client_request_id="native-1"),
                         {"status": "NEEDS_OPERATOR", "reason": "DOLA_DURATION_CONFIRMATION_REQUIRED"})
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(json.dumps(payload).encode())))
        self.assertEqual(client.poll("conv-1", client_request_id="unrelated"), {"status": "PENDING"})
        messages[-2]["bot_reply_message_id"] = "other-input"
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(json.dumps(payload).encode())))
        self.assertEqual(client.poll("conv-1", client_request_id="native-1"), {"status": "PENDING"})
        messages[-2]["bot_reply_message_id"] = "input-1"
        messages[-2]["conversation_id"] = "other-conv"
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(json.dumps(payload).encode())))
        self.assertEqual(client.poll("conv-1", client_request_id="native-1"), {"status": "PENDING"})
        messages[-2]["conversation_id"] = "conv-1"
        messages[-1]["conversation_id"] = "other-conv"
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(json.dumps(payload).encode())))
        self.assertEqual(client.poll("conv-1", client_request_id="native-1"), {"status": "PENDING"})

    def test_poll_uses_observed_nested_read_only_uplink(self):
        bodies = []
        def capture(request, timeout):
            bodies.append(json.loads(request.data))
            return _Response(_chain())
        self.assertEqual(DolaCookieClient(COOKIE, opener=capture).poll("conv-1"),
                         {"status": "PENDING"})
        self.assertEqual(bodies[0]["cmd"], 3100)
        pull = bodies[0]["uplink_body"]["pull_singe_chain_uplink_body"]
        self.assertEqual((pull["conversation_id"], pull["conversation_type"], pull["limit"]),
                         ("conv-1", 3, 20))
        self.assertNotIn("conversation_id", bodies[0])

    def test_verify_input_requires_one_top_level_text_message(self):
        payload = json.loads(_chain())
        messages = payload["downlink_body"]["pull_singe_chain_downlink_body"]["messages"]
        input_message = {
            "local_message_id": "native-1", "message_id": "input-1",
            "conversation_id": "conv-1", "content": json.dumps([{"block_type": 10000}]),
        }
        messages.append(input_message)
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(json.dumps(payload).encode())))
        self.assertTrue(client.verify_input("conv-1", "native-1"))
        messages[-1] = {"metadata": input_message}
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(json.dumps(payload).encode())))
        self.assertFalse(client.verify_input("conv-1", "native-1"))
        messages[-1] = {**input_message, "conversation_id": "other-conv"}
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(json.dumps(payload).encode())))
        with self.assertRaisesRegex(DolaCookieError, "IDENTITY_MISMATCH"):
            client.verify_input("conv-1", "native-1")

    def test_poll_auth_failure_retains_confirmed_dispatch(self):
        from urllib.error import HTTPError
        def expired(*args):
            raise HTTPError("https://www.dola.com", 401, "private", {}, None)
        with self.assertRaises(DolaCookieError) as caught:
            DolaCookieClient(COOKIE, opener=expired).poll("conv-1")
        self.assertEqual(caught.exception.failure_class, "CREDENTIAL_OR_ACCESS_DENIED")
        self.assertEqual(caught.exception.dispatch_state, "DISPATCH_CONFIRMED")

    def test_poll_rejects_output_without_request_echo(self):
        response = _Response(_chain("https://media.byteimg.com/one.mp4"))
        with self.assertRaisesRegex(DolaCookieError, "IDENTITY_UNVERIFIED"):
            DolaCookieClient(COOKIE, opener=_opener_for(response)).poll("conv-1", client_request_id="request-1")

    def test_submit_transmits_persisted_client_identity(self):
        bodies = []
        def capture(request, timeout):
            bodies.append(json.loads(request.data))
            return _Response(b'event: SSE_ACK\ndata: {"ack_client_meta":{"conversation_id":"conv-1"}}\n\n')
        DolaCookieClient(COOKIE, opener=capture).submit("river", "16:9", 5, lambda _: None, client_request_id="request-1")
        self.assertEqual(bodies[0]["messages"][0]["local_message_id"], "request-1")
        self.assertEqual(bodies[0]["option"]["unique_key"], "request-1")

    def test_old_video_in_conversation_cannot_satisfy_new_request(self):
        payload = json.loads(_chain("https://media.byteimg.com/old.mp4"))
        messages = payload["downlink_body"]["pull_singe_chain_downlink_body"]["messages"]
        messages.append({"local_message_id": "request-1", "message_id": "input-1"})
        with self.assertRaisesRegex(DolaCookieError, "IDENTITY_UNVERIFIED"):
            DolaCookieClient(COOKIE, opener=_opener_for(_Response(json.dumps(payload).encode()))).poll("conv-1", client_request_id="request-1")
        messages[0]["reply_to_message_id"] = "input-1"
        result = DolaCookieClient(COOKIE, opener=_opener_for(_Response(json.dumps(payload).encode()))).poll("conv-1", client_request_id="request-1")
        self.assertEqual(result["status"], "COMPLETED")

    def test_observed_bot_reply_link_qualifies_only_matching_input(self):
        payload = json.loads(_chain("https://media.byteimg.com/one.mp4"))
        messages = payload["downlink_body"]["pull_singe_chain_downlink_body"]["messages"]
        messages[0]["bot_reply_message_id"] = "unrelated"
        messages.append({"local_message_id": "request-1", "message_id": "input-1",
                         "conversation_id": "conv-1"})
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(json.dumps(payload).encode())))
        with self.assertRaisesRegex(DolaCookieError, "IDENTITY_UNVERIFIED"):
            client.poll("conv-1", client_request_id="request-1")
        messages[0]["bot_reply_message_id"] = "input-1"
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(json.dumps(payload).encode())))
        self.assertEqual(client.poll("conv-1", client_request_id="request-1")["status"],
                         "COMPLETED")

    def test_nested_fake_input_id_cannot_qualify_video_result(self):
        payload = json.loads(_chain("https://media.byteimg.com/one.mp4"))
        output = payload["downlink_body"]["pull_singe_chain_downlink_body"]["messages"][0]
        output["bot_reply_message_id"] = "input-1"
        output["metadata"] = {"local_message_id": "request-1", "message_id": "input-1"}
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(json.dumps(payload).encode())))
        with self.assertRaisesRegex(DolaCookieError, "IDENTITY_UNVERIFIED"):
            client.poll("conv-1", client_request_id="request-1")

    def test_observed_dola_http_media_url_is_upgraded_only_for_exact_tls_host(self):
        payload = json.loads(_chain("http://v16-dola.dola.com/one.mp4?token=opaque"))
        messages = payload["downlink_body"]["pull_singe_chain_downlink_body"]["messages"]
        messages[0]["bot_reply_message_id"] = "input-1"
        messages.append({"local_message_id": "request-1", "message_id": "input-1",
                         "conversation_id": "conv-1"})
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(json.dumps(payload).encode())))
        self.assertEqual(client.poll("conv-1", client_request_id="request-1"), {
            "status": "COMPLETED",
            "video_url": "https://v16-dola.dola.com/one.mp4?token=opaque",
        })
        for unsafe in ("http://v16-dola.dola.com.evil.invalid/one.mp4",
                       "http://user@v16-dola.dola.com/one.mp4",
                       "http://v16-dola.dola.com:8080/one.mp4"):
            with self.subTest(url=unsafe):
                with self.assertRaisesRegex(DolaCookieError, "DOWNLOAD_HOST_REJECTED"):
                    DolaCookieClient(COOKIE).download(unsafe, Path("ignored.mp4"))

    def test_download_rejects_untrusted_host_and_sends_no_cookie(self):
        client = DolaCookieClient(COOKIE, opener=lambda *_: self.fail("must not open untrusted URL"))
        with self.assertRaises(DolaCookieError) as caught:
            client.download("https://evil.example/video.mp4", Path("ignored.mp4"))
        self.assertEqual(caught.exception.failure_class, "DOWNLOAD_HOST_REJECTED")

        requests = []
        def capture(request, timeout):
            requests.append(request)
            return _Response(b"video", content_type="video/mp4")
        with TemporaryDirectory() as directory, patch("story_auto.providers.dola_cookie.client.validate_video", return_value={"width": 1}):
            metadata = DolaCookieClient(COOKIE, opener=capture).download("https://media.byteimg.com/video.mp4", Path(directory) / "out.mp4")
        self.assertEqual(metadata, {"width": 1})
        self.assertNotIn("Cookie", requests[0].headers)

        requests.clear()
        with TemporaryDirectory() as directory, patch("story_auto.providers.dola_cookie.client.validate_video", return_value={"width": 1}):
            DolaCookieClient(COOKIE, opener=capture).download(
                "https://v16-dola.dola.com/video.mp4", Path(directory) / "out.mp4")
        self.assertEqual(requests[0].full_url, "https://v16-dola.dola.com/video.mp4")
        self.assertNotIn("Cookie", requests[0].headers)

    def test_download_refuses_existing_destination_and_cleans_partial_candidate(self):
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "out.mp4"
            destination.write_bytes(b"owner-file")
            with self.assertRaisesRegex(DolaCookieError, "ASSET_DESTINATION_EXISTS"):
                DolaCookieClient(COOKIE).download("https://media.byteimg.com/video.mp4", destination)

        with TemporaryDirectory() as directory:
            destination = Path(directory) / "out.mp4"
            response = _Response(b"abcd", content_type="video/mp4")
            with patch("story_auto.providers.dola_cookie.client._MAX_DOWNLOAD_BYTES", 2):
                with self.assertRaisesRegex(DolaCookieError, "ASSET_ACQUISITION_FAILED"):
                    DolaCookieClient(COOKIE, opener=_opener_for(response)).download("https://media.byteimg.com/video.mp4", destination)
            self.assertFalse(destination.with_suffix(".mp4.candidate").exists())

    def test_cookie_and_conversation_id_reject_header_or_path_injection(self):
        with self.assertRaisesRegex(DolaCookieError, "CREDENTIAL_MISSING"):
            DolaCookieClient("sessionid=valid\r\nInjected: no")
        client = DolaCookieClient(COOKIE, opener=lambda *_: self.fail("must not make request"))
        with self.assertRaisesRegex(DolaCookieError, "PROVIDER_JOB_ID_INVALID"):
            client.poll("valid\r\nother")


if __name__ == "__main__":
    unittest.main()

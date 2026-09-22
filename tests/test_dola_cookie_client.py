from __future__ import annotations

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
    def test_submit_records_ack_immediately_without_waiting_for_stream_end(self):
        stream = b'event: SSE_ACK\ndata: {"ack_client_meta":{"conversation_id":"conv-1"}}\n\n' + b"data: never-needed"
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(stream, content_type="text/event-stream")))
        receipts: list[str] = []
        self.assertEqual(client.submit("a river", "16:9", 5, receipts.append), "conv-1")
        self.assertEqual(receipts, ["conv-1"])

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

    def test_poll_missing_output_is_pending(self):
        client = DolaCookieClient(COOKIE, opener=_opener_for(_Response(_chain())))
        self.assertEqual(client.poll("conv-1"), {"status": "PENDING"})

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

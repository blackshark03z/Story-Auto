"""Offline boundaries for the non-generating Dola conversation probe."""
from __future__ import annotations

import unittest
from unittest.mock import patch
import json

from tools.dola_readonly_conversation_shape import _probe_media_url, _single_body, _single_shape


class DolaConversationShapeTests(unittest.TestCase):
    def test_media_probe_only_uses_exact_default_port_https_twin(self):
        self.assertEqual(_probe_media_url("http://v16-dola.dola.com/a.mp4?opaque=1"),
                         "https://v16-dola.dola.com/a.mp4?opaque=1")
        for unsafe in (
            "http://v16-dola.dola.com:8080/a.mp4",
            "http://user@v16-dola.dola.com/a.mp4",
            "http://v16-dola.dola.com/a.mp4#fragment",
            "http://v16-dola.dola.com.evil.invalid/a.mp4",
            "https://v16-dola.dola.com/a.mp4",
        ):
            with self.subTest(url=unsafe):
                self.assertEqual(_probe_media_url(unsafe), "")

    def test_single_conversation_request_uses_read_only_envelope(self):
        body = _single_body("12345")
        self.assertEqual(body["cmd"], 3100)
        self.assertEqual(body["uplink_body"]["pull_singe_chain_uplink_body"]["conversation_id"],
                         "12345")
        self.assertNotIn("messages", body)
        self.assertNotIn("conversation_id", body)

    def test_shape_summary_excludes_private_content_ids_and_signed_path(self):
        media_url = "http://v16-dola.dola.com/private.mp4?token=secret-marker"
        payload = {"downlink_body": {"pull_singe_chain_downlink_body": {"messages": [
            {"local_message_id": "private-local", "message_id": "private-input",
             "content": json.dumps([{"block_type": 10000,
                                     "content": {"text_block": {"text": "secret-marker"}}}])},
            {"bot_reply_message_id": "private-input", "content": json.dumps([{
                "block_type": 2074, "content": {"creation_block": {"creations": [
                    {"type": 2, "video": {"download_url": media_url}}]}}}])},
        ]}}}
        with patch("tools.dola_readonly_conversation_shape._post_json", return_value=(200, payload)):
            summary, local_id, url = _single_shape(None, "private-conversation")
        self.assertEqual((local_id, url), ("private-local", media_url))
        recorded = json.dumps(summary)
        for secret in ("secret-marker", "private-local", "private-input", "private-conversation",
                       "private.mp4"):
            self.assertNotIn(secret, recorded)
        self.assertTrue(summary["video_reply_id_matches_nonvideo_text_message"])


if __name__ == "__main__":
    unittest.main()

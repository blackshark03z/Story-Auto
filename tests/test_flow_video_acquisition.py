from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_auto.providers.flow.response_model import FlowObservedIdentity
from story_auto.providers.flow.session import FlowRuntime, FlowSessionError
from story_auto.providers.flow.video_acquisition import (
    FlowObservedVideoAcquirer,
    exact_rendered_video_index,
)


PROJECT = "11111111-2222-3333-4444-555555555555"
ONE = FlowObservedIdentity(
    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    PROJECT,
    "99999999-8888-7777-6666-555555555555",
)
TWO = FlowObservedIdentity(
    "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
    PROJECT,
    "88888888-7777-6666-5555-444444444444",
)


class ExactRenderedVideoTargetTests(unittest.TestCase):
    def test_exact_identity_resolves_without_using_position(self):
        self.assertEqual(exact_rendered_video_index([TWO, None, ONE], ONE), 2)

    def test_missing_identity_fails_closed(self):
        with self.assertRaises(FlowSessionError) as caught:
            exact_rendered_video_index([TWO, None], ONE)
        self.assertEqual(caught.exception.failure_class, "FLOW_VIDEO_IDENTITY_NOT_RENDERED")

    def test_duplicate_identity_fails_closed(self):
        with self.assertRaises(FlowSessionError) as caught:
            exact_rendered_video_index([ONE, TWO, ONE], ONE)
        self.assertEqual(caught.exception.failure_class, "FLOW_RESPONSE_IDENTITY_AMBIGUOUS")

    def test_existing_destination_is_rejected_before_browser_access(self):
        runtime = FlowRuntime(Path("profile"), "http://127.0.0.1:9222", "url", PROJECT)
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "existing.mp4"
            destination.write_bytes(b"owner-data")
            with self.assertRaises(FlowSessionError) as caught:
                FlowObservedVideoAcquirer(runtime, object()).acquire(ONE, destination)
            self.assertEqual(caught.exception.failure_class, "FLOW_VIDEO_DESTINATION_EXISTS")
            self.assertEqual(destination.read_bytes(), b"owner-data")


if __name__ == "__main__":
    unittest.main()

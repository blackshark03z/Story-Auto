from __future__ import annotations

import json
import unittest

from story_auto.providers.flow.response_model import (
    MAX_RESPONSE_BODY_BYTES,
    FlowObservedIdentity,
    FlowResponseModelDecoder,
    FlowResponseModelError,
)
from story_auto.providers.flow.live import exact_new_response_identity
from story_auto.providers.flow.service import FlowError


PROJECT = "11111111-2222-3333-4444-555555555555"
COMPONENT_A = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
COMPONENT_B = "99999999-8888-7777-6666-555555555555"
THUMBNAIL = "https://lh3.googleusercontent.com/asb/AB-observed-token-1234567890"


def response_body(*rows) -> str:
    payload = json.dumps([list(rows)])
    envelope = [["wrb.fr", "Observed", payload]]
    return ")]}'\n" + json.dumps(envelope)


def row(first=COMPONENT_A, project=PROJECT, third=COMPONENT_B, url=THUMBNAIL):
    return [first, project, third, "VID", None, [[url]], None, []]


class FlowResponseModelDecoderTests(unittest.TestCase):
    def test_nested_framed_response_maps_media_token_to_neutral_identity_tuple(self):
        decoder = FlowResponseModelDecoder(PROJECT)
        self.assertEqual(decoder.observe_body(response_body(row())), 1)
        found = decoder.resolve_url(
            "https://flow.google.com/asb/AB-observed-token-1234567890"
        )
        self.assertEqual(
            (found.component_1, found.project_identity, found.component_3),
            (COMPONENT_A, PROJECT, COMPONENT_B),
        )
        self.assertNotIn("job", found.identity)
        self.assertEqual(decoder.identities(), {found})

    def test_unrelated_project_and_unknown_shape_are_ignored(self):
        decoder = FlowResponseModelDecoder(PROJECT)
        other = row(project="22222222-3333-4444-5555-666666666666")
        malformed = [COMPONENT_A, PROJECT, COMPONENT_B, THUMBNAIL]
        self.assertEqual(decoder.observe_body(response_body(other, malformed)), 0)
        self.assertIsNone(decoder.resolve_url(THUMBNAIL))

    def test_same_token_with_two_identity_tuples_fails_closed(self):
        decoder = FlowResponseModelDecoder(PROJECT)
        second = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
        decoder.observe_body(response_body(row(), row(first=second)))
        with self.assertRaisesRegex(
            FlowResponseModelError, "FLOW_RESPONSE_IDENTITY_AMBIGUOUS"
        ):
            decoder.resolve_url(THUMBNAIL)

    def test_non_asb_urls_do_not_become_identity_keys(self):
        decoder = FlowResponseModelDecoder(PROJECT)
        plain = "https://flow.google.com/media/not-an-observed-token"
        self.assertEqual(decoder.observe_body(response_body(row(url=plain))), 0)
        self.assertIsNone(decoder.resolve_url(plain))

    def test_oversized_body_fails_without_incrementing_observation_count(self):
        decoder = FlowResponseModelDecoder(PROJECT)
        with self.assertRaisesRegex(
            FlowResponseModelError, "FLOW_RESPONSE_MODEL_LIMIT_EXCEEDED"
        ):
            decoder.observe_body("x" * (MAX_RESPONSE_BODY_BYTES + 1))
        self.assertEqual(decoder.observed_response_count, 0)

    def test_invalid_project_identity_is_rejected(self):
        with self.assertRaises(ValueError):
            FlowResponseModelDecoder("not-a-project-uuid")

    def test_prompt_epoch_delta_requires_exactly_one_new_identity(self):
        old = FlowObservedIdentity(COMPONENT_A, PROJECT, COMPONENT_B)
        new = FlowObservedIdentity(
            "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
            PROJECT,
            "88888888-7777-6666-5555-444444444444",
        )
        another = FlowObservedIdentity(
            "cccccccc-dddd-eeee-ffff-aaaaaaaaaaaa",
            PROJECT,
            "77777777-6666-5555-4444-333333333333",
        )
        self.assertIsNone(exact_new_response_identity({old}, {old}))
        self.assertEqual(exact_new_response_identity({old}, {old, new}), new)
        with self.assertRaises(FlowError) as caught:
            exact_new_response_identity({old}, {old, new, another})
        self.assertEqual(caught.exception.failure_class, "OUTPUT_ATTRIBUTION_AMBIGUOUS")


if __name__ == "__main__":
    unittest.main()

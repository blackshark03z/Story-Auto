"""Synthetic coverage for evidence-only Flow terminal classification."""
from __future__ import annotations

from copy import deepcopy
import unittest

from story_auto.providers.flow.service import _append_terminal_observations
from story_auto.providers.flow.live import ProviderPollEvidenceTimeline
from story_auto.providers.flow.terminal_evidence import (
    TERMINAL_CLASSIFIER_VERSION,
    build_terminal_evidence,
)


def attempt(*, card_id: str = "tile-1", exact: bool = True) -> dict:
    return {
        "attempt": 1,
        "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED",
        "dispatch_confirmed": True,
        "attribution_state": "CONFIRMED" if exact else "UNCERTAIN",
        "attributed_provider_identity": {"identity": f"card:{card_id}", "card_id": card_id},
        "flow_connection": {
            "flow_connection_id": "conn-1",
            "connection_revision": "revision-7",
            "project_identity": "flow-project-1",
        },
    }


def terminal(message: str, *, card_id: str = "tile-1", structural: bool = True) -> dict:
    return {
        "card_id": card_id,
        "provider_job_id": "job-1",
        "state": "FAILED" if structural else "PENDING",
        "failure_class": "PROVIDER_VISIBLE_TERMINAL_FAILURE" if structural else None,
        "terminal_structural_signals": ["warning", "refresh", "delete_forever"] if structural else [],
        "raw_message": message,
        "locale": "en-US",
    }


def evidence(message: str, *, item: dict | None = None, source: dict | None = None) -> dict:
    return build_terminal_evidence(
        request_id="req-synthetic",
        attempt=source or attempt(),
        observation=item or terminal(message),
        observed_at="2026-09-02T00:00:00+00:00",
    )


class FlowTerminalEvidenceTests(unittest.TestCase):
    def assert_authoritative_family(self, item: dict, family: str) -> None:
        self.assertTrue(item["terminal_structural_evidence"])
        self.assertTrue(item["exact_attribution_confirmed"])
        self.assertTrue(item["authoritative"])
        self.assertEqual(item["failure_family"], family)

    def test_terminal_policy_with_exact_attribution_is_authoritative(self):
        item = evidence("This request was blocked by policy due to current events.")
        self.assert_authoritative_family(item, "PROVIDER_POLICY_BLOCK")

    def test_policy_text_without_terminal_structure_is_not_authoritative(self):
        item = evidence("This request was blocked by policy.", item=terminal(
            "This request was blocked by policy.", structural=False,
        ))
        self.assertEqual(item["classification_candidate"], "PROVIDER_POLICY_BLOCK")
        self.assertFalse(item["authoritative"])
        self.assertIsNone(item["failure_family"])

    def test_policy_terminal_with_mismatched_attribution_fails_closed(self):
        item = evidence("This request was blocked by policy.", item=terminal(
            "This request was blocked by policy.", card_id="foreign-tile",
        ))
        self.assertEqual(item["classification_candidate"], "PROVIDER_POLICY_BLOCK")
        self.assertFalse(item["exact_attribution_confirmed"])
        self.assertFalse(item["authoritative"])
        self.assertIsNone(item["failure_family"])

    def test_terminal_unknown_message_is_authoritative_unknown_only_with_exact_attribution(self):
        exact = evidence("An unfamiliar provider failure occurred.")
        self.assert_authoritative_family(exact, "PROVIDER_TERMINAL_UNKNOWN")
        missing = evidence("An unfamiliar provider failure occurred.", source=attempt(exact=False))
        self.assertFalse(missing["authoritative"])
        self.assertIsNone(missing["failure_family"])

    def test_supported_rate_auth_and_credit_families_are_deterministic(self):
        cases = {
            "Rate limit reached. Try again later.": "PROVIDER_RATE_LIMIT",
            "Your session expired. Please sign in again.": "PROVIDER_AUTH_BLOCK",
            "Insufficient credit to complete this request.": "PROVIDER_CREDIT_BLOCK",
        }
        for message, family in cases.items():
            with self.subTest(family=family):
                item = evidence(message)
                self.assert_authoritative_family(item, family)

    def test_missing_exact_attribution_cannot_authorize_any_supported_family(self):
        cases = (
            "This request was blocked by policy.",
            "Rate limit reached. Try again later.",
            "Your session expired. Please sign in again.",
            "Insufficient credit to complete this request.",
        )
        for message in cases:
            with self.subTest(message=message):
                item = evidence(message, source=attempt(exact=False))
                self.assertFalse(item["exact_attribution_confirmed"])
                self.assertFalse(item["authoritative"])
                self.assertIsNone(item["failure_family"])

    def test_rate_limit_evidence_carries_no_backoff_or_dispatch_authority(self):
        item = evidence("Rate limit reached. Try again later.")
        self.assert_authoritative_family(item, "PROVIDER_RATE_LIMIT")
        self.assertNotIn("rate_limit_backoff_ready", item)
        self.assertNotIn("safe_to_dispatch", item)
        self.assertNotIn("provider_generation_required", item)

    def test_raw_message_locale_classifier_and_bindings_are_retained(self):
        item = evidence("  POLICY\ncurrent events  ")
        self.assertEqual(item["raw_provider_message"], "  POLICY\ncurrent events  ")
        self.assertEqual(item["observed_locale"], "en-US")
        self.assertEqual(item["classifier_version"], TERMINAL_CLASSIFIER_VERSION)
        self.assertEqual(item["provider_card_id"], "tile-1")
        self.assertEqual(item["provider_job_id"], "job-1")
        self.assertEqual((item["request_id"], item["attempt"]), ("req-synthetic", 1))
        self.assertEqual((item["flow_project_identity"], item["flow_connection_revision"]),
                         ("flow-project-1", "revision-7"))

    def test_digest_is_deterministic_and_changes_for_material_evidence(self):
        first = evidence("This request was blocked by policy.")
        second = evidence("This request was blocked by policy.")
        changed = evidence("Rate limit reached. Try again later.")
        self.assertEqual(first["evidence_digest_sha256"], second["evidence_digest_sha256"])
        self.assertNotEqual(first["evidence_digest_sha256"], changed["evidence_digest_sha256"])

    def test_generic_terminal_does_not_silently_become_policy(self):
        item = evidence("Generation could not be completed.")
        self.assert_authoritative_family(item, "PROVIDER_TERMINAL_UNKNOWN")

    def test_raw_terminal_observation_is_retained_by_existing_hash_chained_poll_evidence(self):
        timeline = ProviderPollEvidenceTimeline()
        timeline.append({
            "phase": "POST_DISPATCH",
            "terminal_observations": [terminal("This request was blocked by policy.")],
        })
        snapshot = ProviderPollEvidenceTimeline.verify_snapshot(timeline.snapshot())
        retained = snapshot["observations"][0]["terminal_observations"][0]
        self.assertEqual(retained["raw_message"], "This request was blocked by policy.")
        self.assertEqual(retained["card_id"], "tile-1")

    def test_classifier_is_pure_and_append_path_never_calls_generation(self):
        source = attempt()
        source["provider_submissions"] = 1
        observation = terminal("This request was blocked by policy.")
        before_source = deepcopy(source)
        before_observation = deepcopy(observation)
        item = evidence("This request was blocked by policy.", item=observation, source=source)
        self.assertEqual(source, before_source)
        self.assertEqual(observation, before_observation)
        generator = type("Generator", (), {
            "last_settings": {"terminal_observations": [terminal("This request was blocked by policy.")]},
            "generation_calls": 0,
        })()
        appended = _append_terminal_observations({"request_id": "req-synthetic"}, source, generator)
        self.assertEqual(generator.generation_calls, 0)
        self.assertEqual(len(appended), 1)
        self.assertEqual(source["terminal_evidence"][0]["failure_family"], "PROVIDER_POLICY_BLOCK")
        self.assertEqual(source["provider_submissions"], 1)
        self.assertEqual(item["failure_family"], "PROVIDER_POLICY_BLOCK")


if __name__ == "__main__":
    unittest.main()

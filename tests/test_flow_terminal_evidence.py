"""Synthetic coverage for evidence-only Flow terminal classification."""
from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

from story_auto.providers.flow.service import _append_terminal_observations
from story_auto.providers.flow.live import ProviderPollEvidenceTimeline
from story_auto.providers.flow.terminal_evidence import (
    TERMINAL_CLASSIFIER_VERSION,
    build_terminal_evidence,
)


def attempt(*, card_id: str = "tile-1", provider_job_id: str | None = "job-1",
            exact: bool = True, include_connection: bool = True,
            provider_execution_state: str = "PROVIDER_BOUNDARY_ENTERED") -> dict:
    attributed_identity = {"identity": f"card:{card_id}", "card_id": card_id}
    if provider_job_id is not None:
        attributed_identity["provider_job_id"] = provider_job_id
    value = {
        "attempt": 1,
        "provider_execution_state": provider_execution_state,
        "dispatch_confirmed": True,
        "dispatch_confirmation_state": "CONFIRMED",
        "attribution_state": "CONFIRMED" if exact else "UNCERTAIN",
        "attributed_provider_identity": attributed_identity,
        "provider_job_id": provider_job_id,
        "provider_submissions": 1,
    }
    if include_connection:
        value["flow_connection"] = {
            "flow_connection_id": "conn-1",
            "flow_connection_revision": 7,
            "project_identity": "flow-project-1",
        }
    return value


def terminal(message: str, *, card_id: str = "tile-1",
             provider_job_id: str | None = "job-1", structural: bool = True) -> dict:
    return {
        "card_id": card_id,
        "provider_job_id": provider_job_id,
        "state": "FAILED" if structural else "PENDING",
        "failure_class": "PROVIDER_VISIBLE_TERMINAL_FAILURE" if structural else None,
        "terminal_structural_signals": ["warning", "refresh", "delete_forever"] if structural else [],
        "raw_message": message,
        "locale": "en-US",
    }


def poll_snapshot(item: dict) -> tuple[dict, dict]:
    timeline = ProviderPollEvidenceTimeline()
    source = timeline.append({
        "phase": "POST_DISPATCH",
        "job_card_identities_observed": [item["card_id"]],
        "dispatch_evidence_state": "CONFIRMED",
        "attribution_evidence_state": "CONFIRMED",
        "input_dispatched": True,
        "terminal_observations": [deepcopy(item)],
    })
    timeline.finish("PROVIDER_VISIBLE_TERMINAL_FAILURE")
    return timeline.snapshot(), source


def poll_snapshot_with_job_binding(item: dict) -> tuple[dict, dict, dict]:
    timeline = ProviderPollEvidenceTimeline()
    source = timeline.append({
        "phase": "POST_DISPATCH",
        "job_card_identities_observed": [item["card_id"]],
        "dispatch_evidence_state": "CONFIRMED",
        "attribution_evidence_state": "CONFIRMED",
        "input_dispatched": True,
        "terminal_observations": [deepcopy(item)],
    })
    binding = timeline.append_decision_binding(
        source,
        dispatch_state="CONFIRMED",
        dispatch_signal="provider_job_id",
        dispatch_signal_state="CONFIRMED",
        attribution_state="CONFIRMED",
        durable_identity=f"job:{item['provider_job_id']}",
    )
    timeline.finish("PROVIDER_VISIBLE_TERMINAL_FAILURE")
    return timeline.snapshot(), source, binding


def evidence(message: str, *, item: dict | None = None,
             attempt_record: dict | None = None, with_poll: bool = True,
             snapshot: dict | None = None, source_poll_sequence: int | None = None,
             source_observation_sha256: str | None = None,
             flow_project_identity: str | None = None,
             flow_connection_revision: str | int | None = None) -> dict:
    observation = item or terminal(message)
    source = None
    if snapshot is None and with_poll:
        snapshot, source = poll_snapshot(observation)
    if source is not None:
        if source_poll_sequence is None:
            source_poll_sequence = source["poll_sequence"]
        if source_observation_sha256 is None:
            source_observation_sha256 = source["observation_sha256"]
    return build_terminal_evidence(
        request_id="req-synthetic",
        attempt=attempt_record or attempt(),
        observation=observation,
        observed_at="2026-09-02T00:00:00+00:00",
        provider_poll_evidence=snapshot,
        source_poll_sequence=source_poll_sequence,
        source_observation_sha256=source_observation_sha256,
        flow_project_identity=flow_project_identity,
        flow_connection_revision=flow_connection_revision,
    )


class FlowTerminalEvidenceTests(unittest.TestCase):
    def assert_authoritative_family(self, item: dict, family: str) -> None:
        self.assertTrue(item["terminal_structural_evidence"])
        self.assertTrue(item["source_poll_verified"])
        self.assertTrue(item["exact_attribution_confirmed"])
        self.assertTrue(item["attempt_evidence_consistent"])
        self.assertTrue(item["connection_provenance_confirmed"])
        self.assertTrue(item["authoritative"])
        self.assertEqual(item["failure_family"], family)

    def test_verified_poll_exact_job_and_strong_policy_is_authoritative(self):
        item = evidence("This request was blocked by policy due to current events.")
        self.assert_authoritative_family(item, "PROVIDER_POLICY_BLOCK")
        self.assertEqual(item["provider_job_id"], "job-1")

    def test_mutable_last_settings_observation_without_verified_poll_is_not_authoritative(self):
        source = attempt()
        generator = type("Generator", (), {
            "last_settings": {
                "terminal_observations": [
                    terminal("This request was blocked by policy due to current events."),
                ],
            },
            "generation_calls": 0,
        })()
        appended = _append_terminal_observations({"request_id": "req-synthetic"}, source, generator)
        self.assertEqual(len(appended), 1)
        self.assertFalse(appended[0]["source_poll_verified"])
        self.assertFalse(appended[0]["authoritative"])
        self.assertIsNone(appended[0]["failure_family"])

    def test_tampered_source_observation_or_hash_fails_closed(self):
        observation = terminal("This request was blocked by policy due to current events.")
        snapshot, source = poll_snapshot(observation)
        tampered = deepcopy(snapshot)
        tampered["observations"][0]["terminal_observations"][0]["raw_message"] = "tampered"
        item = evidence(observation["raw_message"], item=observation, snapshot=tampered,
                        source_poll_sequence=source["poll_sequence"],
                        source_observation_sha256=source["observation_sha256"])
        self.assertFalse(item["source_poll_verified"])
        self.assertFalse(item["authoritative"])
        self.assertIsNone(item["failure_family"])

    def test_source_poll_sequence_or_hash_mismatch_fails_closed(self):
        observation = terminal("This request was blocked by policy due to current events.")
        snapshot, source = poll_snapshot(observation)
        cases = (
            (source["poll_sequence"] + 1, source["observation_sha256"]),
            (source["poll_sequence"], "0" * 64),
        )
        for sequence, source_hash in cases:
            with self.subTest(sequence=sequence, source_hash=source_hash):
                item = evidence(observation["raw_message"], item=observation, snapshot=snapshot,
                                source_poll_sequence=sequence,
                                source_observation_sha256=source_hash)
                self.assertFalse(item["source_poll_verified"])
                self.assertFalse(item["authoritative"])
                self.assertIsNone(item["failure_family"])

    def test_same_card_with_foreign_provider_job_is_not_exact(self):
        item = evidence(
            "This request was blocked by policy due to current events.",
            item=terminal(
                "This request was blocked by policy due to current events.",
                provider_job_id="job-B",
            ),
            attempt_record=attempt(provider_job_id="job-A"),
        )
        self.assertFalse(item["exact_attribution_confirmed"])
        self.assertFalse(item["authoritative"])
        self.assertIsNone(item["failure_family"])

    def test_same_card_with_exact_durable_job_binding_may_be_exact(self):
        item = evidence(
            "This request was blocked by policy due to current events.",
            item=terminal(
                "This request was blocked by policy due to current events.",
                provider_job_id="job-A",
            ),
            attempt_record=attempt(provider_job_id="job-A"),
        )
        self.assert_authoritative_family(item, "PROVIDER_POLICY_BLOCK")

    def test_job_identity_on_only_one_side_requires_verified_authoritative_binding(self):
        observation = terminal(
            "This request was blocked by policy due to current events.",
            provider_job_id="job-A",
        )
        unbound = evidence(
            observation["raw_message"], item=observation,
            attempt_record=attempt(provider_job_id=None),
        )
        self.assertFalse(unbound["exact_attribution_confirmed"])
        self.assertFalse(unbound["authoritative"])

        snapshot, source, binding = poll_snapshot_with_job_binding(observation)
        bound_attempt = attempt(provider_job_id=None)
        bound_attempt["provider_poll_authoritative_binding"] = binding
        bound = evidence(
            observation["raw_message"], item=observation,
            attempt_record=bound_attempt, snapshot=snapshot,
            source_poll_sequence=source["poll_sequence"],
            source_observation_sha256=source["observation_sha256"],
        )
        self.assert_authoritative_family(bound, "PROVIDER_POLICY_BLOCK")

    def test_missing_flow_connection_provenance_is_not_authoritative(self):
        item = evidence(
            "This request was blocked by policy due to current events.",
            attempt_record=attempt(include_connection=False),
        )
        self.assertFalse(item["connection_provenance_confirmed"])
        self.assertFalse(item["authoritative"])
        self.assertIsNone(item["failure_family"])

    def test_connection_revision_override_cannot_replace_attempt_truth(self):
        item = evidence(
            "This request was blocked by policy due to current events.",
            flow_connection_revision=8,
        )
        self.assertEqual(item["flow_connection_revision"], 7)
        self.assertFalse(item["connection_provenance_confirmed"])
        self.assertFalse(item["authoritative"])
        self.assertIsNone(item["failure_family"])

    def test_project_override_cannot_replace_attempt_truth(self):
        item = evidence(
            "This request was blocked by policy due to current events.",
            flow_project_identity="flow-project-foreign",
        )
        self.assertEqual(item["flow_project_identity"], "flow-project-1")
        self.assertFalse(item["connection_provenance_confirmed"])
        self.assertFalse(item["authoritative"])

    def test_generic_try_again_later_is_terminal_unknown_not_rate_limit(self):
        item = evidence("Please try again later.")
        self.assert_authoritative_family(item, "PROVIDER_TERMINAL_UNKNOWN")
        self.assertNotEqual(item["failure_family"], "PROVIDER_RATE_LIMIT")

    def test_current_events_prompt_text_is_terminal_unknown_not_policy(self):
        item = evidence("Prompt topic: current events. Generation could not be completed.")
        self.assert_authoritative_family(item, "PROVIDER_TERMINAL_UNKNOWN")
        self.assertNotEqual(item["failure_family"], "PROVIDER_POLICY_BLOCK")

    def test_stray_sign_in_or_generic_quota_text_is_terminal_unknown(self):
        cases = (
            "Prompt text mentions a sign in the background. Generation failed.",
            "Quota exceeded. Generation failed.",
        )
        for message in cases:
            with self.subTest(message=message):
                self.assert_authoritative_family(
                    evidence(message), "PROVIDER_TERMINAL_UNKNOWN",
                )

    def test_strong_message_families_are_conservative_and_deterministic(self):
        cases = {
            "Rate limit reached because there were too many requests.": "PROVIDER_RATE_LIMIT",
            "This request was blocked by policy due to current events.": "PROVIDER_POLICY_BLOCK",
            "Authentication required. Your session expired; please sign in to continue.": "PROVIDER_AUTH_BLOCK",
            "Insufficient credits are available for this generation.": "PROVIDER_CREDIT_BLOCK",
        }
        for message, family in cases.items():
            with self.subTest(family=family):
                self.assert_authoritative_family(evidence(message), family)

    def test_not_started_with_dispatch_confirmed_is_non_authoritative_contradiction(self):
        contradictory = attempt(provider_execution_state="NOT_STARTED")
        contradictory["dispatch_confirmed"] = True
        item = evidence(
            "Rate limit reached because there were too many requests.",
            attempt_record=contradictory,
        )
        self.assertFalse(item["attempt_evidence_consistent"])
        self.assertFalse(item["authoritative"])
        self.assertIsNone(item["failure_family"])

    def test_not_started_with_confirmed_identity_is_non_authoritative_contradiction(self):
        contradictory = attempt(provider_execution_state="NOT_STARTED")
        contradictory["dispatch_confirmed"] = False
        contradictory["dispatch_confirmation_state"] = "NOT_CONFIRMED"
        item = evidence(
            "Rate limit reached because there were too many requests.",
            attempt_record=contradictory,
        )
        self.assertFalse(item["attempt_evidence_consistent"])
        self.assertFalse(item["authoritative"])
        self.assertIsNone(item["failure_family"])

    def test_same_verified_raw_terminal_observation_is_appended_once(self):
        observation = terminal("This request was blocked by policy due to current events.")
        snapshot, source_poll = poll_snapshot(observation)
        source_attempt = attempt()
        settings = {
            "provider_poll_evidence": snapshot,
            "terminal_observations": [observation],
            "terminal_observation_sources": [{
                "source_poll_sequence": source_poll["poll_sequence"],
                "source_observation_sha256": source_poll["observation_sha256"],
                "terminal_observation": observation,
            }],
        }
        generator = type("Generator", (), {"last_settings": settings, "generation_calls": 0})()
        request = {"request_id": "req-synthetic"}
        first = _append_terminal_observations(request, source_attempt, generator)
        second = _append_terminal_observations(request, source_attempt, generator)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(len(source_attempt["terminal_evidence"]), 1)
        self.assertEqual(
            source_attempt["terminal_evidence"][0]["canonical_source_identity_sha256"],
            first[0]["canonical_source_identity_sha256"],
        )

    def test_classification_does_not_generate_change_submission_count_or_execute_recovery(self):
        observation = terminal("Rate limit reached because there were too many requests.")
        snapshot, source_poll = poll_snapshot(observation)
        source_attempt = attempt()
        before_submissions = source_attempt["provider_submissions"]
        generator = type("Generator", (), {
            "last_settings": {
                "provider_poll_evidence": snapshot,
                "terminal_observations": [observation],
                "terminal_observation_sources": [{
                    "source_poll_sequence": source_poll["poll_sequence"],
                    "source_observation_sha256": source_poll["observation_sha256"],
                    "terminal_observation": observation,
                }],
            },
            "generation_calls": 0,
        })()
        with patch("story_auto.core.visual.recovery.evaluate_recovery",
                   side_effect=AssertionError("RecoveryDecision must not execute")):
            appended = _append_terminal_observations(
                {"request_id": "req-synthetic"}, source_attempt, generator,
            )
        self.assertEqual(len(appended), 1)
        self.assertEqual(generator.generation_calls, 0)
        self.assertEqual(source_attempt["provider_submissions"], before_submissions)

    def test_canonical_evidence_retains_verified_source_binding_and_projection(self):
        observation = terminal("This request was blocked by policy due to current events.")
        item = evidence(observation["raw_message"], item=observation)
        self.assertIsInstance(item["source_poll_sequence"], int)
        self.assertEqual(len(item["source_observation_sha256"]), 64)
        self.assertEqual(len(item["provider_poll_evidence_head_sha256"]), 64)
        self.assertEqual(len(item["terminal_observation_sha256"]), 64)
        self.assertEqual(item["terminal_observation"], observation)
        self.assertEqual(len(item["canonical_source_identity_sha256"]), 64)

    def test_nonterminal_structure_cannot_be_authoritative(self):
        item = evidence(
            "This request was blocked by policy.",
            item=terminal("This request was blocked by policy.", structural=False),
        )
        self.assertEqual(item["classification_candidate"], "PROVIDER_POLICY_BLOCK")
        self.assertFalse(item["terminal_structural_evidence"])
        self.assertFalse(item["authoritative"])
        self.assertIsNone(item["failure_family"])

    def test_unknown_terminal_with_exact_attribution_remains_fail_closed_unknown(self):
        exact = evidence("An unfamiliar provider failure occurred.")
        self.assert_authoritative_family(exact, "PROVIDER_TERMINAL_UNKNOWN")
        missing = evidence(
            "An unfamiliar provider failure occurred.",
            attempt_record=attempt(exact=False),
        )
        self.assertFalse(missing["exact_attribution_confirmed"])
        self.assertFalse(missing["authoritative"])
        self.assertIsNone(missing["failure_family"])

    def test_raw_message_locale_classifier_and_attempt_bindings_are_retained(self):
        raw = "  This request was BLOCKED by POLICY due to current events.  "
        item = evidence(raw)
        self.assertEqual(item["raw_provider_message"], raw)
        self.assertEqual(item["observed_locale"], "en-US")
        self.assertEqual(item["classifier_version"], TERMINAL_CLASSIFIER_VERSION)
        self.assertEqual(item["provider_card_id"], "tile-1")
        self.assertEqual(item["provider_job_id"], "job-1")
        self.assertEqual((item["request_id"], item["attempt"]), ("req-synthetic", 1))
        self.assertEqual(
            (item["flow_connection_id"], item["flow_project_identity"],
             item["flow_connection_revision"]),
            ("conn-1", "flow-project-1", 7),
        )

    def test_digest_is_deterministic_and_material_evidence_changes_it(self):
        observation = terminal("This request was blocked by policy due to current events.")
        snapshot, source = poll_snapshot(observation)
        source_args = {
            "item": observation,
            "snapshot": snapshot,
            "source_poll_sequence": source["poll_sequence"],
            "source_observation_sha256": source["observation_sha256"],
        }
        first = evidence(observation["raw_message"], **source_args)
        second = evidence(observation["raw_message"], **source_args)
        changed = evidence("Rate limit reached because there were too many requests.")
        self.assertEqual(first["evidence_digest_sha256"], second["evidence_digest_sha256"])
        self.assertNotEqual(first["evidence_digest_sha256"], changed["evidence_digest_sha256"])

    def test_rate_limit_evidence_carries_no_backoff_or_dispatch_authority(self):
        item = evidence("Rate limit reached because there were too many requests.")
        self.assert_authoritative_family(item, "PROVIDER_RATE_LIMIT")
        self.assertNotIn("rate_limit_backoff_ready", item)
        self.assertNotIn("safe_to_dispatch", item)
        self.assertNotIn("provider_generation_required", item)

    def test_raw_terminal_observation_is_retained_by_existing_hash_chained_poll_evidence(self):
        observation = terminal("This request was blocked by policy due to current events.")
        snapshot, _source = poll_snapshot(observation)
        retained = ProviderPollEvidenceTimeline.verify_snapshot(
            snapshot,
        )["observations"][0]["terminal_observations"][0]
        self.assertEqual(retained, observation)


if __name__ == "__main__":
    unittest.main()

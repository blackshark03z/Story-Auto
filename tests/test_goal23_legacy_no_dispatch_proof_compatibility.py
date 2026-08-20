from __future__ import annotations

import unittest

from story_auto.providers.flow.live import ProviderPollEvidenceTimeline
from story_auto.providers.flow.service import (
    _provider_generation_retry_authorized,
    _proven_safe_pre_dispatch_attempt,
    canonical_no_dispatch_proof,
)


GOAL21_PROJECT_ID = "prj_4f895eb1436c42c4ba5b908381b14fd1"
GOAL21_REPLACEMENT_ID = "req_2f755d20c25245314761"


def _legacy_goal21_attempt(*, missing_nested=False, later_dispatched=False,
                           later_attribution_uncertain=False) -> dict:
    """Offline fixture for the preserved Goal21 replacement's relevant evidence.

    It retains the real replacement identity and the same 26-observation
    pre-dispatch shape: three discovery polls, then 23 baseline polls.  The
    generated hashes are fixture-local; runtime evidence is never opened or
    modified by this test.
    """
    timeline = ProviderPollEvidenceTimeline()
    for sequence in range(1, 27):
        observation = {
            "phase": "PRE_DISPATCH_DISCOVERY" if sequence <= 3 else "PRE_DISPATCH_BASELINE",
            "input_dispatched": False,
            "dispatch_evidence_state": "NOT_CONFIRMED",
            "dispatch_signal_state": "NONE",
            "attribution_evidence_state": "NOT_ATTEMPTED",
            "durable_dispatch_identity": None,
            "lineage_card_id": None,
            "candidate_identities": ([{"identity": "card:preexisting"}] if sequence >= 4 else []),
        }
        if missing_nested and sequence == 1:
            observation.pop("input_dispatched")
        if later_dispatched and sequence == 26:
            observation["input_dispatched"] = True
        if later_attribution_uncertain and sequence == 26:
            observation["attribution_evidence_state"] = "UNCERTAIN"
        timeline.append(observation)
    timeline.finish("NOT_ATTEMPTED")
    return {
        "attempt": 1,
        "status": "NOT_DISPATCHED",
        "failure_class": "OUTPUT_ATTRIBUTION_NOT_QUIESCENT",
        "dispatch_confirmed": False,
        "dispatch_confirmation_state": "PRE_DISPATCH_FAILURE",
        "dispatch_confirmation_signal": "input_not_dispatched",
        "provider_job_id": None,
        "durable_dispatch_identity": None,
        "provider_lineage_card_id": None,
        "attributed_provider_identity": None,
        "attribution_state": "NOT_ATTEMPTED",
        "poll_evidence_version": "story-auto-flow-poll-evidence/1.2.0",
        "provider_settings": {"provider_poll_evidence": timeline.snapshot()},
    }


class Goal23LegacyNoDispatchCompatibilityTests(unittest.TestCase):
    @staticmethod
    def _entry(attempt: dict) -> dict:
        return {"request_id": GOAL21_REPLACEMENT_ID, "attempts": [attempt]}

    def test_exact_preserved_goal21_shape_gains_only_semantic_retry_authority(self):
        attempt = _legacy_goal21_attempt()
        self.assertFalse(_proven_safe_pre_dispatch_attempt(attempt))
        self.assertTrue(canonical_no_dispatch_proof(attempt))
        self.assertTrue(_provider_generation_retry_authorized(self._entry(attempt)))

    def test_legacy_evidence_rejects_missing_tampered_or_contradictory_nested_fact(self):
        cases = {
            "nested_field_missing": _legacy_goal21_attempt(missing_nested=True),
            "later_input_dispatched": _legacy_goal21_attempt(later_dispatched=True),
            "later_attribution_uncertain": _legacy_goal21_attempt(later_attribution_uncertain=True),
        }
        tampered = _legacy_goal21_attempt()
        tampered["provider_settings"]["provider_poll_evidence"]["observations"][0]["input_dispatched"] = True
        cases["not_integrity_bound"] = tampered
        for name, attempt in cases.items():
            with self.subTest(name=name):
                self.assertFalse(canonical_no_dispatch_proof(attempt))
                self.assertFalse(_provider_generation_retry_authorized(self._entry(attempt)))

    def test_legacy_evidence_rejects_any_later_dispatch_or_attribution_authority(self):
        mutations = {
            "dispatch_confirmed": lambda a: a.update({"dispatch_confirmed": True}),
            "dispatch_uncertain": lambda a: a.update({"dispatch_confirmation_state": "UNCERTAIN"}),
            "provider_job": lambda a: a.update({"provider_job_id": "job:unexpected"}),
            "durable_identity": lambda a: a.update({"durable_dispatch_identity": "asset:unexpected"}),
            "lineage_card": lambda a: a.update({"provider_lineage_card_id": "card:unexpected"}),
            "attributed_output": lambda a: a.update({"attributed_provider_identity": {"identity": "asset:unexpected"}}),
            "attribution_uncertain": lambda a: a.update({"attribution_state": "UNCERTAIN"}),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                attempt = _legacy_goal21_attempt()
                mutate(attempt)
                self.assertFalse(canonical_no_dispatch_proof(attempt))
                self.assertFalse(_provider_generation_retry_authorized(self._entry(attempt)))

    def test_diagnostic_state_alone_never_becomes_no_dispatch_proof(self):
        cases = {
            "dispatch_false_only": {"dispatch_confirmed": False},
            "null_job_only": {"provider_job_id": None},
            "failure_label_only": {"failure_class": "OUTPUT_ATTRIBUTION_NOT_QUIESCENT"},
            "failed_retryable": {"status": "FAILED_RETRYABLE", "dispatch_confirmed": False,
                                 "provider_job_id": None, "attribution_state": "NOT_ATTEMPTED"},
        }
        for name, attempt in cases.items():
            with self.subTest(name=name):
                self.assertFalse(canonical_no_dispatch_proof(attempt))
                self.assertFalse(_provider_generation_retry_authorized(self._entry(attempt)))

    def test_current_goal22_canonical_activation_rule_is_unchanged(self):
        attempt = {
            "dispatch_confirmed": False,
            "provider_job_id": None,
            "durable_dispatch_identity": None,
            "provider_lineage_card_id": None,
            "attributed_provider_identity": None,
            "attribution_state": "NOT_ATTEMPTED",
            "dispatch_confirmation_state": "PRE_DISPATCH_FAILURE",
            "provider_settings": {"activation": {"input_dispatched": False}},
        }
        self.assertTrue(_proven_safe_pre_dispatch_attempt(attempt))
        self.assertTrue(canonical_no_dispatch_proof(attempt))
        self.assertTrue(_provider_generation_retry_authorized(self._entry(attempt)))


if __name__ == "__main__":
    unittest.main()

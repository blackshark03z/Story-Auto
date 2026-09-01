"""Deterministic unit coverage for the provider-independent recovery core."""
from __future__ import annotations

import unittest
from dataclasses import replace

from story_auto.core.visual.recovery import (
    AttemptOutcome,
    DispatchCertainty,
    FailureFamily,
    ReasonCode,
    RecoveryAction,
    RecoveryInput,
    evaluate_recovery,
)


def evidence(family: FailureFamily, **changes: object) -> RecoveryInput:
    base = RecoveryInput(
        failure_family=family,
        attempt_outcome=AttemptOutcome.FAILED,
        dispatch_certainty=DispatchCertainty.TERMINAL_CONFIRMED,
        terminal_evidence_confirmed=True,
        exact_attribution_confirmed=True,
    )
    return replace(base, **changes)


class FlowRecoveryDecisionTests(unittest.TestCase):
    def assert_dispatchable(self, decision) -> None:
        self.assertTrue(decision.safe_to_dispatch)
        self.assertTrue(decision.provider_generation_required)
        self.assertTrue(decision.consumes_provider_attempt)
        self.assertTrue(decision.final_revalidation_required)
        self.assertTrue(decision.single_flight_required)

    def assert_local_recovery(self, decision, action: RecoveryAction) -> None:
        self.assertEqual(decision.action, action)
        self.assertFalse(decision.safe_to_dispatch)
        self.assertFalse(decision.provider_generation_required)
        self.assertFalse(decision.consumes_provider_attempt)

    def test_pre_dispatch_transient_safe_retry(self):
        decision = evaluate_recovery(evidence(
            FailureFamily.PRE_DISPATCH_FAILURE,
            dispatch_certainty=DispatchCertainty.NOT_DISPATCHED,
            canonical_no_dispatch_proof=True,
        ))
        self.assertEqual(decision.reason_code, ReasonCode.TRANSIENT_RETRY_ALLOWED)
        self.assert_dispatchable(decision)

    def test_pre_dispatch_retry_budget_exhausted(self):
        decision = evaluate_recovery(evidence(
            FailureFamily.PRE_DISPATCH_FAILURE,
            dispatch_certainty=DispatchCertainty.NOT_DISPATCHED,
            canonical_no_dispatch_proof=True,
            transient_redispatch_count=2,
        ))
        self.assertEqual((decision.action, decision.reason_code),
                         (RecoveryAction.NO_RETRY, ReasonCode.TRANSIENT_RETRY_BUDGET_EXHAUSTED))

    def test_lifetime_stop_loss_exhausted(self):
        decision = evaluate_recovery(evidence(
            FailureFamily.PROVIDER_TERMINAL_TRANSIENT, provider_attempt_count=12,
        ))
        self.assertEqual((decision.action, decision.reason_code),
                         (RecoveryAction.NO_RETRY, ReasonCode.LIFETIME_ATTEMPT_LIMIT_REACHED))

    def test_dispatch_ambiguous_requires_reconciliation_regardless_of_budget(self):
        decision = evaluate_recovery(evidence(
            FailureFamily.DISPATCH_AMBIGUOUS,
            dispatch_certainty=DispatchCertainty.DISPATCH_UNCERTAIN,
            transient_redispatch_count=0,
            provider_attempt_count=0,
        ))
        self.assertEqual((decision.action, decision.reason_code),
                         (RecoveryAction.RECONCILE_FIRST, ReasonCode.DISPATCH_AMBIGUOUS))
        self.assertTrue(decision.reconciliation_required)
        self.assertFalse(decision.safe_to_dispatch)

    def test_actively_generating_attempt_resumes_polling(self):
        decision = evaluate_recovery(evidence(
            FailureFamily.PROVIDER_IN_PROGRESS,
            attempt_outcome=AttemptOutcome.GENERATING,
            dispatch_certainty=DispatchCertainty.DISPATCH_CONFIRMED,
            provider_progress_active=True,
        ))
        self.assertEqual((decision.action, decision.reason_code),
                         (RecoveryAction.RESUME_POLLING, ReasonCode.EXISTING_ATTEMPT_ACTIVE))

    def test_confirmed_terminal_transient_dispatches(self):
        decision = evaluate_recovery(evidence(FailureFamily.PROVIDER_TERMINAL_TRANSIENT))
        self.assert_dispatchable(decision)

    def test_terminal_transient_without_exact_attribution_reconciles(self):
        decision = evaluate_recovery(evidence(
            FailureFamily.PROVIDER_TERMINAL_TRANSIENT, exact_attribution_confirmed=False,
        ))
        self.assertEqual(decision.action, RecoveryAction.RECONCILE_FIRST)
        self.assertFalse(decision.safe_to_dispatch)

    def test_rate_limit_waits_until_backoff_is_due(self):
        decision = evaluate_recovery(evidence(
            FailureFamily.PROVIDER_RATE_LIMIT, rate_limit_backoff_ready=False,
        ))
        self.assertEqual((decision.action, decision.reason_code),
                         (RecoveryAction.WAIT_AND_RETRY, ReasonCode.RATE_LIMIT_BACKOFF_REQUIRED))
        self.assertFalse(decision.safe_to_dispatch)

    def test_rate_limit_dispatches_after_fresh_due_evidence(self):
        decision = evaluate_recovery(evidence(
            FailureFamily.PROVIDER_RATE_LIMIT, rate_limit_backoff_ready=True,
        ))
        self.assert_dispatchable(decision)

    def test_policy_block_never_retries_same_prompt(self):
        decision = evaluate_recovery(evidence(FailureFamily.PROVIDER_POLICY_BLOCK))
        self.assertEqual((decision.action, decision.reason_code),
                         (RecoveryAction.PROMPT_REPAIR, ReasonCode.POLICY_PROMPT_REPAIR_REQUIRED))
        self.assertTrue(decision.prompt_revision_required)
        self.assertFalse(decision.safe_to_dispatch)

    def test_unproven_policy_classification_reconciles_before_prompt_repair(self):
        decision = evaluate_recovery(evidence(
            FailureFamily.PROVIDER_POLICY_BLOCK, exact_attribution_confirmed=False,
        ))
        self.assertEqual(decision.action, RecoveryAction.RECONCILE_FIRST)
        self.assertFalse(decision.safe_to_dispatch)

    def test_non_material_policy_remediation_is_eligible(self):
        decision = evaluate_recovery(evidence(
            FailureFamily.PROVIDER_POLICY_BLOCK, prompt_remediation_non_material=True,
        ))
        self.assertEqual(decision.reason_code, ReasonCode.AUTOMATIC_PROMPT_REMEDIATION_ELIGIBLE)
        self.assertEqual(decision.action, RecoveryAction.PROMPT_REPAIR)
        self.assertFalse(decision.safe_to_dispatch)

    def test_material_prompt_change_requires_owner(self):
        decision = evaluate_recovery(evidence(
            FailureFamily.PROVIDER_POLICY_BLOCK, semantic_remediation_material=True,
        ))
        self.assertEqual(decision.reason_code, ReasonCode.OWNER_PROMPT_APPROVAL_REQUIRED)
        self.assertTrue(decision.owner_decision_required)
        self.assertFalse(decision.safe_to_dispatch)

    def test_provider_account_blockers_require_owner_action(self):
        cases = {
            FailureFamily.PROVIDER_AUTH_BLOCK: ReasonCode.AUTH_REQUIRED,
            FailureFamily.PROVIDER_CREDIT_BLOCK: ReasonCode.CREDIT_BLOCKED,
            FailureFamily.PROVIDER_UI_CHANGED: ReasonCode.PROVIDER_UI_CHANGED,
            FailureFamily.PROVIDER_TERMINAL_UNKNOWN: ReasonCode.PROVIDER_TERMINAL_UNKNOWN,
        }
        for family, reason in cases.items():
            with self.subTest(family=family):
                decision = evaluate_recovery(evidence(family))
                self.assertEqual((decision.action, decision.reason_code), (RecoveryAction.OWNER_ACTION, reason))
                self.assertTrue(decision.owner_decision_required)
                self.assertFalse(decision.safe_to_dispatch)

    def test_output_acquisition_and_local_failures_are_provider_free(self):
        cases = {
            FailureFamily.ASSET_ACQUISITION_FAILURE: (RecoveryAction.REACQUIRE, {"provider_output_exists": True}),
            FailureFamily.LOCAL_VALIDATION_FAILURE: (RecoveryAction.REVALIDATE, {}),
            FailureFamily.LOCAL_POSTPROCESS_FAILURE: (RecoveryAction.REPOSTPROCESS, {}),
            FailureFamily.QC_TECHNICAL_FAILURE: (RecoveryAction.REVALIDATE, {}),
        }
        for family, (action, changes) in cases.items():
            with self.subTest(family=family):
                self.assert_local_recovery(evaluate_recovery(evidence(family, **changes)), action)

    def test_qc_creative_retry_needs_authorization_and_budget(self):
        denied = evaluate_recovery(evidence(FailureFamily.QC_CREATIVE_REJECTION))
        self.assertEqual(denied.reason_code, ReasonCode.OWNER_AUTHORIZATION_REQUIRED)
        unproven = evaluate_recovery(evidence(
            FailureFamily.QC_CREATIVE_REJECTION, creative_regeneration_authorized=True,
        ))
        self.assertEqual(unproven.reason_code, ReasonCode.OWNER_AUTHORIZATION_REQUIRED)
        allowed = evaluate_recovery(evidence(
            FailureFamily.QC_CREATIVE_REJECTION, creative_rejection_confirmed=True,
            creative_regeneration_authorized=True,
        ))
        self.assertEqual(allowed.reason_code, ReasonCode.CREATIVE_RETRY_ALLOWED)
        self.assert_dispatchable(allowed)
        exhausted = evaluate_recovery(evidence(
            FailureFamily.QC_CREATIVE_REJECTION,
            creative_rejection_confirmed=True,
            creative_regeneration_authorized=True,
            creative_correction_count=3,
        ))
        self.assertEqual(exhausted.reason_code, ReasonCode.CREATIVE_RETRY_BUDGET_EXHAUSTED)

    def test_manual_regenerate_requires_exact_owner_authorization(self):
        denied = evaluate_recovery(evidence(FailureFamily.MANUAL_REGENERATE))
        self.assertEqual(denied.reason_code, ReasonCode.OWNER_AUTHORIZATION_REQUIRED)
        allowed = evaluate_recovery(evidence(FailureFamily.MANUAL_REGENERATE, owner_authorized=True))
        self.assertEqual(allowed.action, RecoveryAction.MANUAL_REGENERATE)
        self.assert_dispatchable(allowed)
        unresolved = evaluate_recovery(evidence(
            FailureFamily.MANUAL_REGENERATE,
            owner_authorized=True,
            dispatch_certainty=DispatchCertainty.DISPATCH_CONFIRMED,
        ))
        self.assertEqual(unresolved.action, RecoveryAction.RECONCILE_FIRST)

    def test_failed_retryable_text_alone_never_authorizes_dispatch(self):
        decision = evaluate_recovery(RecoveryInput(
            failure_family=FailureFamily.PRE_DISPATCH_FAILURE,
            attempt_outcome=AttemptOutcome.FAILED,
            dispatch_certainty=DispatchCertainty.DISPATCH_CONFIRMED,
            legacy_request_status="FAILED_RETRYABLE",
        ))
        self.assertEqual(decision.action, RecoveryAction.RECONCILE_FIRST)
        self.assertFalse(decision.safe_to_dispatch)

    def test_every_dispatchable_decision_has_required_revalidation_and_single_flight(self):
        cases = [
            evidence(FailureFamily.INITIAL_ATTEMPT, attempt_outcome=AttemptOutcome.NOT_STARTED,
                     dispatch_certainty=DispatchCertainty.NOT_DISPATCHED, provider_attempt_count=0),
            evidence(FailureFamily.PRE_DISPATCH_FAILURE, dispatch_certainty=DispatchCertainty.NOT_DISPATCHED,
                     canonical_no_dispatch_proof=True),
            evidence(FailureFamily.PROVIDER_TERMINAL_TRANSIENT),
            evidence(FailureFamily.PROVIDER_RATE_LIMIT, rate_limit_backoff_ready=True),
            evidence(FailureFamily.QC_CREATIVE_REJECTION, creative_rejection_confirmed=True,
                     creative_regeneration_authorized=True),
            evidence(FailureFamily.MANUAL_REGENERATE, owner_authorized=True),
        ]
        for item in cases:
            with self.subTest(family=item.failure_family):
                self.assert_dispatchable(evaluate_recovery(item))

    def test_dispatch_uncertain_is_never_dispatchable_for_every_failure_family(self):
        for family in FailureFamily:
            with self.subTest(family=family):
                decision = evaluate_recovery(evidence(
                    family,
                    dispatch_certainty=DispatchCertainty.DISPATCH_UNCERTAIN,
                    canonical_no_dispatch_proof=True,
                    terminal_evidence_confirmed=True,
                    exact_attribution_confirmed=True,
                    transient_redispatch_count=0,
                    provider_attempt_count=0,
                ))
                self.assertFalse(decision.safe_to_dispatch)
                self.assertEqual(decision.action, RecoveryAction.RECONCILE_FIRST)


if __name__ == "__main__":
    unittest.main()

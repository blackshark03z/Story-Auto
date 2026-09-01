"""Deterministic unit coverage for the provider-independent recovery core."""
from __future__ import annotations

from dataclasses import replace
import unittest

from story_auto.core.visual.recovery import (
    AttemptOutcome,
    DispatchCertainty,
    FailureFamily,
    ReasonCode,
    RecoveryAction,
    RecoveryInput,
    evaluate_recovery,
)


def terminal_failure_evidence(family: FailureFamily, **changes: object) -> RecoveryInput:
    """Evidence for an exactly attributed, resolved terminal provider failure."""
    return replace(RecoveryInput(
        failure_family=family,
        attempt_outcome=AttemptOutcome.FAILED,
        dispatch_certainty=DispatchCertainty.TERMINAL_CONFIRMED,
        terminal_evidence_confirmed=True,
        exact_attribution_confirmed=True,
        provider_attempt_count=1,
    ), **changes)


def pre_dispatch_evidence(family: FailureFamily, **changes: object) -> RecoveryInput:
    """Evidence that the exact logical request did not cross the provider boundary."""
    return replace(RecoveryInput(
        failure_family=family,
        attempt_outcome=AttemptOutcome.NOT_STARTED,
        dispatch_certainty=DispatchCertainty.NOT_DISPATCHED,
        canonical_no_dispatch_proof=True,
    ), **changes)


def active_attempt_evidence(family: FailureFamily = FailureFamily.PROVIDER_IN_PROGRESS,
                            **changes: object) -> RecoveryInput:
    return replace(RecoveryInput(
        failure_family=family,
        attempt_outcome=AttemptOutcome.GENERATING,
        dispatch_certainty=DispatchCertainty.DISPATCH_CONFIRMED,
        provider_progress_active=True,
        provider_attempt_count=1,
    ), **changes)


def resolved_output_evidence(family: FailureFamily, **changes: object) -> RecoveryInput:
    """Evidence for an exactly attributed, terminal successful provider output."""
    return replace(RecoveryInput(
        failure_family=family,
        attempt_outcome=AttemptOutcome.SUCCEEDED,
        dispatch_certainty=DispatchCertainty.TERMINAL_CONFIRMED,
        terminal_evidence_confirmed=True,
        exact_attribution_confirmed=True,
        provider_output_exists=True,
        provider_attempt_count=1,
    ), **changes)


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

    def test_initial_attempt_dispatches_only_from_clean_pre_dispatch_evidence(self):
        decision = evaluate_recovery(RecoveryInput(
            failure_family=FailureFamily.INITIAL_ATTEMPT,
            attempt_outcome=AttemptOutcome.NOT_STARTED,
            dispatch_certainty=DispatchCertainty.NOT_DISPATCHED,
        ))
        self.assertEqual(decision.reason_code, ReasonCode.INITIAL_DISPATCH_ALLOWED)
        self.assert_dispatchable(decision)

    def test_pre_dispatch_transient_safe_retry(self):
        decision = evaluate_recovery(pre_dispatch_evidence(FailureFamily.PRE_DISPATCH_FAILURE))
        self.assertEqual(decision.reason_code, ReasonCode.TRANSIENT_RETRY_ALLOWED)
        self.assert_dispatchable(decision)

    def test_transient_retry_boundary_one_remaining_two_exhausted(self):
        allowed = evaluate_recovery(terminal_failure_evidence(
            FailureFamily.PROVIDER_TERMINAL_TRANSIENT, transient_redispatch_count=1,
        ))
        self.assert_dispatchable(allowed)
        exhausted = evaluate_recovery(terminal_failure_evidence(
            FailureFamily.PROVIDER_TERMINAL_TRANSIENT, transient_redispatch_count=2,
        ))
        self.assertEqual(exhausted.reason_code, ReasonCode.TRANSIENT_RETRY_BUDGET_EXHAUSTED)

    def test_lifetime_attempt_boundary_eleven_remaining_twelve_exhausted(self):
        allowed = evaluate_recovery(terminal_failure_evidence(
            FailureFamily.PROVIDER_TERMINAL_TRANSIENT, provider_attempt_count=11,
        ))
        self.assert_dispatchable(allowed)
        exhausted = evaluate_recovery(terminal_failure_evidence(
            FailureFamily.PROVIDER_TERMINAL_TRANSIENT, provider_attempt_count=12,
        ))
        self.assertEqual(exhausted.reason_code, ReasonCode.LIFETIME_ATTEMPT_LIMIT_REACHED)

    def test_dispatch_ambiguous_requires_reconciliation_regardless_of_authorization(self):
        for family in FailureFamily:
            with self.subTest(family=family):
                decision = evaluate_recovery(active_attempt_evidence(
                    family,
                    dispatch_certainty=DispatchCertainty.DISPATCH_UNCERTAIN,
                    canonical_no_dispatch_proof=True,
                    terminal_evidence_confirmed=True,
                    exact_attribution_confirmed=True,
                    provider_output_exists=True,
                    owner_authorized=True,
                    creative_rejection_confirmed=True,
                    creative_regeneration_authorized=True,
                    prompt_revision_ready=True,
                    prompt_revision_authorized=True,
                    prompt_remediation_non_material=True,
                    rate_limit_backoff_ready=True,
                    provider_attempt_count=1,
                ))
                self.assertEqual((decision.action, decision.reason_code),
                                 (RecoveryAction.RECONCILE_FIRST, ReasonCode.DISPATCH_AMBIGUOUS))
                self.assertFalse(decision.safe_to_dispatch)

    def test_active_attempt_resumes_polling(self):
        decision = evaluate_recovery(active_attempt_evidence())
        self.assertEqual((decision.action, decision.reason_code),
                         (RecoveryAction.RESUME_POLLING, ReasonCode.EXISTING_ATTEMPT_ACTIVE))

    def test_contradictory_evidence_fails_closed_before_dispatchable_branches(self):
        cases = [
            RecoveryInput(FailureFamily.INITIAL_ATTEMPT, AttemptOutcome.NOT_STARTED,
                          DispatchCertainty.NOT_DISPATCHED, terminal_evidence_confirmed=True),
            terminal_failure_evidence(FailureFamily.PRE_DISPATCH_FAILURE,
                                      canonical_no_dispatch_proof=True),
            terminal_failure_evidence(FailureFamily.PROVIDER_TERMINAL_TRANSIENT,
                                      provider_progress_active=True),
            terminal_failure_evidence(FailureFamily.PROVIDER_RATE_LIMIT,
                                      rate_limit_backoff_ready=True, provider_progress_active=True),
            resolved_output_evidence(FailureFamily.QC_CREATIVE_REJECTION,
                                     creative_rejection_confirmed=True,
                                     creative_regeneration_authorized=True,
                                     provider_progress_active=True),
            resolved_output_evidence(FailureFamily.MANUAL_REGENERATE, owner_authorized=True,
                                     provider_progress_active=True),
            terminal_failure_evidence(FailureFamily.PROVIDER_POLICY_BLOCK,
                                      prompt_revision_ready=True,
                                      prompt_remediation_non_material=True,
                                      provider_progress_active=True),
        ]
        for item in cases:
            with self.subTest(family=item.failure_family):
                decision = evaluate_recovery(item)
                self.assertEqual((decision.action, decision.reason_code),
                                 (RecoveryAction.RECONCILE_FIRST, ReasonCode.EVIDENCE_CONTRADICTION))
                self.assertFalse(decision.safe_to_dispatch)

    def test_evidence_consistency_gate_covers_each_required_family(self):
        contradictions = [
            RecoveryInput(FailureFamily.INITIAL_ATTEMPT, AttemptOutcome.NOT_STARTED,
                          DispatchCertainty.NOT_DISPATCHED, terminal_evidence_confirmed=True),
            RecoveryInput(FailureFamily.INITIAL_ATTEMPT, AttemptOutcome.NOT_STARTED,
                          DispatchCertainty.NOT_DISPATCHED, provider_progress_active=True),
            RecoveryInput(FailureFamily.INITIAL_ATTEMPT, AttemptOutcome.NOT_STARTED,
                          DispatchCertainty.NOT_DISPATCHED, provider_output_exists=True),
            active_attempt_evidence(terminal_evidence_confirmed=True),
            terminal_failure_evidence(FailureFamily.PROVIDER_TERMINAL_TRANSIENT,
                                      provider_progress_active=True),
            terminal_failure_evidence(FailureFamily.PRE_DISPATCH_FAILURE,
                                      canonical_no_dispatch_proof=True),
            RecoveryInput(FailureFamily.PROVIDER_TERMINAL_TRANSIENT, AttemptOutcome.FAILED,
                          DispatchCertainty.NOT_DISPATCHED, terminal_evidence_confirmed=True),
            RecoveryInput(FailureFamily.PROVIDER_TERMINAL_TRANSIENT, AttemptOutcome.FAILED,
                          DispatchCertainty.TERMINAL_CONFIRMED),
            terminal_failure_evidence(FailureFamily.PROVIDER_TERMINAL_TRANSIENT,
                                      transient_redispatch_count=1, provider_attempt_count=0),
            resolved_output_evidence(FailureFamily.QC_CREATIVE_REJECTION,
                                     creative_correction_count=2, provider_attempt_count=1),
        ]
        for item in contradictions:
            with self.subTest(item=item):
                decision = evaluate_recovery(item)
                self.assertEqual(decision.reason_code, ReasonCode.EVIDENCE_CONTRADICTION)
                self.assertFalse(decision.safe_to_dispatch)

    def test_rate_limit_requires_backoff_exact_attribution_and_authority(self):
        missing_attribution = evaluate_recovery(pre_dispatch_evidence(
            FailureFamily.PROVIDER_RATE_LIMIT,
            rate_limit_backoff_ready=True,
            exact_attribution_confirmed=False,
        ))
        self.assertEqual(missing_attribution.action, RecoveryAction.RECONCILE_FIRST)
        allowed_pre_dispatch = evaluate_recovery(pre_dispatch_evidence(
            FailureFamily.PROVIDER_RATE_LIMIT,
            rate_limit_backoff_ready=True,
            exact_attribution_confirmed=True,
        ))
        self.assert_dispatchable(allowed_pre_dispatch)
        missing_terminal_attribution = evaluate_recovery(terminal_failure_evidence(
            FailureFamily.PROVIDER_RATE_LIMIT,
            rate_limit_backoff_ready=True,
            exact_attribution_confirmed=False,
        ))
        self.assertEqual(missing_terminal_attribution.action, RecoveryAction.RECONCILE_FIRST)
        self.assertFalse(missing_terminal_attribution.safe_to_dispatch)

    def test_rate_limit_waits_until_backoff_is_due(self):
        decision = evaluate_recovery(terminal_failure_evidence(
            FailureFamily.PROVIDER_RATE_LIMIT, rate_limit_backoff_ready=False,
        ))
        self.assertEqual((decision.action, decision.reason_code),
                         (RecoveryAction.WAIT_AND_RETRY, ReasonCode.RATE_LIMIT_BACKOFF_REQUIRED))

    def test_policy_block_never_retries_same_rejected_prompt(self):
        decision = evaluate_recovery(terminal_failure_evidence(FailureFamily.PROVIDER_POLICY_BLOCK))
        self.assertEqual((decision.action, decision.reason_code),
                         (RecoveryAction.PROMPT_REPAIR, ReasonCode.POLICY_PROMPT_REPAIR_REQUIRED))
        self.assertTrue(decision.prompt_revision_required)
        self.assertFalse(decision.safe_to_dispatch)

    def test_policy_revised_non_material_prompt_dispatches_once(self):
        allowed = evaluate_recovery(terminal_failure_evidence(
            FailureFamily.PROVIDER_POLICY_BLOCK,
            prompt_revision_ready=True,
            prompt_remediation_non_material=True,
            prompt_remediation_count=0,
        ))
        self.assertEqual(allowed.reason_code, ReasonCode.PROMPT_REVISION_DISPATCH_ALLOWED)
        self.assert_dispatchable(allowed)
        exhausted = evaluate_recovery(terminal_failure_evidence(
            FailureFamily.PROVIDER_POLICY_BLOCK,
            prompt_revision_ready=True,
            prompt_remediation_non_material=True,
            prompt_remediation_count=1,
        ))
        self.assertEqual((exhausted.action, exhausted.reason_code),
                         (RecoveryAction.OWNER_ACTION, ReasonCode.OWNER_PROMPT_APPROVAL_REQUIRED))

    def test_policy_revised_material_prompt_requires_exact_owner_approval(self):
        unclassified = evaluate_recovery(terminal_failure_evidence(
            FailureFamily.PROVIDER_POLICY_BLOCK,
            prompt_revision_ready=True,
        ))
        self.assertEqual(unclassified.reason_code, ReasonCode.OWNER_PROMPT_APPROVAL_REQUIRED)
        denied = evaluate_recovery(terminal_failure_evidence(
            FailureFamily.PROVIDER_POLICY_BLOCK,
            prompt_revision_ready=True,
            semantic_remediation_material=True,
        ))
        self.assertEqual(denied.reason_code, ReasonCode.OWNER_PROMPT_APPROVAL_REQUIRED)
        allowed = evaluate_recovery(terminal_failure_evidence(
            FailureFamily.PROVIDER_POLICY_BLOCK,
            prompt_revision_ready=True,
            semantic_remediation_material=True,
            prompt_revision_authorized=True,
        ))
        self.assertEqual(allowed.reason_code, ReasonCode.PROMPT_REVISION_DISPATCH_ALLOWED)
        self.assert_dispatchable(allowed)

    def test_policy_revised_prompt_obeys_lifetime_stop_loss(self):
        decision = evaluate_recovery(terminal_failure_evidence(
            FailureFamily.PROVIDER_POLICY_BLOCK,
            prompt_revision_ready=True,
            prompt_remediation_non_material=True,
            provider_attempt_count=12,
        ))
        self.assertEqual(decision.reason_code, ReasonCode.LIFETIME_ATTEMPT_LIMIT_REACHED)

    def test_provider_account_blockers_require_owner_action(self):
        cases = {
            FailureFamily.PROVIDER_AUTH_BLOCK: ReasonCode.AUTH_REQUIRED,
            FailureFamily.PROVIDER_CREDIT_BLOCK: ReasonCode.CREDIT_BLOCKED,
            FailureFamily.PROVIDER_UI_CHANGED: ReasonCode.PROVIDER_UI_CHANGED,
            FailureFamily.PROVIDER_TERMINAL_UNKNOWN: ReasonCode.PROVIDER_TERMINAL_UNKNOWN,
        }
        for family, reason in cases.items():
            with self.subTest(family=family):
                decision = evaluate_recovery(terminal_failure_evidence(family))
                self.assertEqual((decision.action, decision.reason_code), (RecoveryAction.OWNER_ACTION, reason))
                self.assertTrue(decision.owner_decision_required)
                self.assertFalse(decision.safe_to_dispatch)

    def test_output_acquisition_and_local_failures_are_provider_free(self):
        cases = {
            FailureFamily.ASSET_ACQUISITION_FAILURE: (RecoveryAction.REACQUIRE,
                                                       resolved_output_evidence(FailureFamily.ASSET_ACQUISITION_FAILURE)),
            FailureFamily.LOCAL_VALIDATION_FAILURE: (RecoveryAction.REVALIDATE,
                                                      RecoveryInput(FailureFamily.LOCAL_VALIDATION_FAILURE,
                                                                    AttemptOutcome.FAILED,
                                                                    DispatchCertainty.DISPATCH_CONFIRMED)),
            FailureFamily.LOCAL_POSTPROCESS_FAILURE: (RecoveryAction.REPOSTPROCESS,
                                                       RecoveryInput(FailureFamily.LOCAL_POSTPROCESS_FAILURE,
                                                                     AttemptOutcome.FAILED,
                                                                     DispatchCertainty.DISPATCH_CONFIRMED)),
            FailureFamily.QC_TECHNICAL_FAILURE: (RecoveryAction.REVALIDATE,
                                                  RecoveryInput(FailureFamily.QC_TECHNICAL_FAILURE,
                                                                AttemptOutcome.FAILED,
                                                                DispatchCertainty.DISPATCH_CONFIRMED)),
        }
        for family, (action, item) in cases.items():
            with self.subTest(family=family):
                self.assert_local_recovery(evaluate_recovery(item), action)

    def test_qc_creative_rejection_accepts_successful_resolved_output(self):
        allowed = evaluate_recovery(resolved_output_evidence(
            FailureFamily.QC_CREATIVE_REJECTION,
            creative_rejection_confirmed=True,
            creative_regeneration_authorized=True,
            creative_correction_count=2,
            provider_attempt_count=3,
        ))
        self.assertEqual(allowed.reason_code, ReasonCode.CREATIVE_RETRY_ALLOWED)
        self.assert_dispatchable(allowed)
        exhausted = evaluate_recovery(resolved_output_evidence(
            FailureFamily.QC_CREATIVE_REJECTION,
            creative_rejection_confirmed=True,
            creative_regeneration_authorized=True,
            creative_correction_count=3,
            provider_attempt_count=4,
        ))
        self.assertEqual(exhausted.reason_code, ReasonCode.CREATIVE_RETRY_BUDGET_EXHAUSTED)

    def test_qc_creative_rejection_requires_output_resolution_and_authorization(self):
        missing_output = evaluate_recovery(terminal_failure_evidence(
            FailureFamily.QC_CREATIVE_REJECTION,
            creative_rejection_confirmed=True,
            creative_regeneration_authorized=True,
        ))
        self.assertEqual(missing_output.action, RecoveryAction.RECONCILE_FIRST)
        denied = evaluate_recovery(resolved_output_evidence(FailureFamily.QC_CREATIVE_REJECTION))
        self.assertEqual(denied.reason_code, ReasonCode.OWNER_AUTHORIZATION_REQUIRED)

    def test_manual_regenerate_requires_owner_and_resolved_state(self):
        denied = evaluate_recovery(resolved_output_evidence(FailureFamily.MANUAL_REGENERATE))
        self.assertEqual(denied.reason_code, ReasonCode.OWNER_AUTHORIZATION_REQUIRED)
        allowed = evaluate_recovery(resolved_output_evidence(
            FailureFamily.MANUAL_REGENERATE, owner_authorized=True,
        ))
        self.assert_dispatchable(allowed)
        exhausted = evaluate_recovery(resolved_output_evidence(
            FailureFamily.MANUAL_REGENERATE, owner_authorized=True, provider_attempt_count=12,
        ))
        self.assertEqual(exhausted.reason_code, ReasonCode.LIFETIME_ATTEMPT_LIMIT_REACHED)

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
            RecoveryInput(FailureFamily.INITIAL_ATTEMPT, AttemptOutcome.NOT_STARTED,
                          DispatchCertainty.NOT_DISPATCHED),
            pre_dispatch_evidence(FailureFamily.PRE_DISPATCH_FAILURE),
            terminal_failure_evidence(FailureFamily.PROVIDER_TERMINAL_TRANSIENT),
            pre_dispatch_evidence(FailureFamily.PROVIDER_RATE_LIMIT, rate_limit_backoff_ready=True,
                                  exact_attribution_confirmed=True),
            terminal_failure_evidence(FailureFamily.PROVIDER_RATE_LIMIT, rate_limit_backoff_ready=True),
            terminal_failure_evidence(FailureFamily.PROVIDER_POLICY_BLOCK, prompt_revision_ready=True,
                                      prompt_remediation_non_material=True),
            terminal_failure_evidence(FailureFamily.PROVIDER_POLICY_BLOCK, prompt_revision_ready=True,
                                      semantic_remediation_material=True, prompt_revision_authorized=True),
            resolved_output_evidence(FailureFamily.QC_CREATIVE_REJECTION,
                                     creative_rejection_confirmed=True,
                                     creative_regeneration_authorized=True),
            resolved_output_evidence(FailureFamily.MANUAL_REGENERATE, owner_authorized=True),
        ]
        for item in cases:
            with self.subTest(family=item.failure_family):
                self.assert_dispatchable(evaluate_recovery(item))

    def test_lifetime_stop_loss_blocks_every_provider_generation_path(self):
        cases = [
            RecoveryInput(FailureFamily.INITIAL_ATTEMPT, AttemptOutcome.NOT_STARTED,
                          DispatchCertainty.NOT_DISPATCHED, provider_attempt_count=12),
            pre_dispatch_evidence(FailureFamily.PRE_DISPATCH_FAILURE, provider_attempt_count=12),
            pre_dispatch_evidence(FailureFamily.PROVIDER_RATE_LIMIT, provider_attempt_count=12,
                                  rate_limit_backoff_ready=True, exact_attribution_confirmed=True),
            terminal_failure_evidence(FailureFamily.PROVIDER_TERMINAL_TRANSIENT, provider_attempt_count=12),
            terminal_failure_evidence(FailureFamily.PROVIDER_RATE_LIMIT, provider_attempt_count=12,
                                      rate_limit_backoff_ready=True),
            terminal_failure_evidence(FailureFamily.PROVIDER_POLICY_BLOCK, provider_attempt_count=12,
                                      prompt_revision_ready=True, prompt_remediation_non_material=True),
            resolved_output_evidence(FailureFamily.QC_CREATIVE_REJECTION, provider_attempt_count=12,
                                     creative_rejection_confirmed=True,
                                     creative_regeneration_authorized=True),
            resolved_output_evidence(FailureFamily.MANUAL_REGENERATE, provider_attempt_count=12,
                                     owner_authorized=True),
        ]
        for item in cases:
            with self.subTest(family=item.failure_family):
                decision = evaluate_recovery(item)
                self.assertEqual(decision.reason_code, ReasonCode.LIFETIME_ATTEMPT_LIMIT_REACHED)
                self.assertFalse(decision.safe_to_dispatch)


if __name__ == "__main__":
    unittest.main()

"""Provider-independent recovery authorization for logical visual requests.

This module deliberately evaluates only normalized evidence.  It neither reads
manifests nor crosses a provider boundary; a future executor must obtain its
own single-flight lease and revalidate a dispatchable decision immediately
before invoking a provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


RECOVERY_POLICY_VERSION = "story-auto-flow-recovery/1"
MAX_AUTOMATIC_TRANSIENT_REDISPATCHES = 2
MAX_AUTOMATIC_PROMPT_REMEDIATIONS = 1
MAX_CREATIVE_CORRECTIONS = 3
MAX_LIFETIME_PROVIDER_ATTEMPTS = 12


class AttemptOutcome(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    DISPATCHING = "DISPATCHING"
    GENERATING = "GENERATING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class DispatchCertainty(str, Enum):
    NOT_DISPATCHED = "NOT_DISPATCHED"
    DISPATCH_CONFIRMED = "DISPATCH_CONFIRMED"
    DISPATCH_UNCERTAIN = "DISPATCH_UNCERTAIN"
    TERMINAL_CONFIRMED = "TERMINAL_CONFIRMED"


class FailureFamily(str, Enum):
    INITIAL_ATTEMPT = "INITIAL_ATTEMPT"
    PRE_DISPATCH_FAILURE = "PRE_DISPATCH_FAILURE"
    DISPATCH_AMBIGUOUS = "DISPATCH_AMBIGUOUS"
    PROVIDER_IN_PROGRESS = "PROVIDER_IN_PROGRESS"
    PROVIDER_TERMINAL_TRANSIENT = "PROVIDER_TERMINAL_TRANSIENT"
    PROVIDER_POLICY_BLOCK = "PROVIDER_POLICY_BLOCK"
    PROVIDER_AUTH_BLOCK = "PROVIDER_AUTH_BLOCK"
    PROVIDER_CREDIT_BLOCK = "PROVIDER_CREDIT_BLOCK"
    PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
    PROVIDER_UI_CHANGED = "PROVIDER_UI_CHANGED"
    PROVIDER_TERMINAL_UNKNOWN = "PROVIDER_TERMINAL_UNKNOWN"
    ASSET_ACQUISITION_FAILURE = "ASSET_ACQUISITION_FAILURE"
    LOCAL_VALIDATION_FAILURE = "LOCAL_VALIDATION_FAILURE"
    LOCAL_POSTPROCESS_FAILURE = "LOCAL_POSTPROCESS_FAILURE"
    QC_TECHNICAL_FAILURE = "QC_TECHNICAL_FAILURE"
    QC_CREATIVE_REJECTION = "QC_CREATIVE_REJECTION"
    MANUAL_REGENERATE = "MANUAL_REGENERATE"


class RecoveryAction(str, Enum):
    DISPATCH_INITIAL = "DISPATCH_INITIAL"
    AUTO_RETRY = "AUTO_RETRY"
    RESUME_POLLING = "RESUME_POLLING"
    RECONCILE_FIRST = "RECONCILE_FIRST"
    WAIT_AND_RETRY = "WAIT_AND_RETRY"
    REACQUIRE = "REACQUIRE"
    REVALIDATE = "REVALIDATE"
    REPOSTPROCESS = "REPOSTPROCESS"
    PROMPT_REPAIR = "PROMPT_REPAIR"
    CREATIVE_REGENERATE = "CREATIVE_REGENERATE"
    MANUAL_REGENERATE = "MANUAL_REGENERATE"
    OWNER_ACTION = "OWNER_ACTION"
    NO_RETRY = "NO_RETRY"


class ReasonCode(str, Enum):
    INITIAL_DISPATCH_ALLOWED = "INITIAL_DISPATCH_ALLOWED"
    DISPATCH_AMBIGUOUS = "DISPATCH_AMBIGUOUS"
    EXISTING_ATTEMPT_ACTIVE = "EXISTING_ATTEMPT_ACTIVE"
    TRANSIENT_RETRY_ALLOWED = "TRANSIENT_RETRY_ALLOWED"
    TRANSIENT_RETRY_BUDGET_EXHAUSTED = "TRANSIENT_RETRY_BUDGET_EXHAUSTED"
    LIFETIME_ATTEMPT_LIMIT_REACHED = "LIFETIME_ATTEMPT_LIMIT_REACHED"
    TERMINAL_EVIDENCE_INSUFFICIENT = "TERMINAL_EVIDENCE_INSUFFICIENT"
    RATE_LIMIT_BACKOFF_REQUIRED = "RATE_LIMIT_BACKOFF_REQUIRED"
    POLICY_PROMPT_REPAIR_REQUIRED = "POLICY_PROMPT_REPAIR_REQUIRED"
    AUTOMATIC_PROMPT_REMEDIATION_ELIGIBLE = "AUTOMATIC_PROMPT_REMEDIATION_ELIGIBLE"
    OWNER_PROMPT_APPROVAL_REQUIRED = "OWNER_PROMPT_APPROVAL_REQUIRED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CREDIT_BLOCKED = "CREDIT_BLOCKED"
    PROVIDER_UI_CHANGED = "PROVIDER_UI_CHANGED"
    PROVIDER_TERMINAL_UNKNOWN = "PROVIDER_TERMINAL_UNKNOWN"
    LOCAL_RECOVERY_REQUIRED = "LOCAL_RECOVERY_REQUIRED"
    CREATIVE_RETRY_ALLOWED = "CREATIVE_RETRY_ALLOWED"
    CREATIVE_RETRY_BUDGET_EXHAUSTED = "CREATIVE_RETRY_BUDGET_EXHAUSTED"
    OWNER_AUTHORIZATION_REQUIRED = "OWNER_AUTHORIZATION_REQUIRED"


@dataclass(frozen=True)
class RecoveryBudgets:
    transient_redispatches_used: int
    transient_redispatches_limit: int
    provider_attempts_used: int
    provider_attempts_limit: int
    prompt_remediations_used: int
    prompt_remediations_limit: int
    creative_corrections_used: int
    creative_corrections_limit: int

    @property
    def transient_redispatches_remaining(self) -> int:
        return max(0, self.transient_redispatches_limit - self.transient_redispatches_used)

    @property
    def provider_attempts_remaining(self) -> int:
        return max(0, self.provider_attempts_limit - self.provider_attempts_used)

    @property
    def prompt_remediations_remaining(self) -> int:
        return max(0, self.prompt_remediations_limit - self.prompt_remediations_used)

    @property
    def creative_corrections_remaining(self) -> int:
        return max(0, self.creative_corrections_limit - self.creative_corrections_used)


@dataclass(frozen=True)
class RecoveryInput:
    """Normalized, canonical evidence for one logical visual request.

    ``legacy_request_status`` is deliberately diagnostic-only.  In particular,
    ``FAILED_RETRYABLE`` cannot change a decision unless the typed evidence
    independently satisfies a rule below.
    """

    failure_family: FailureFamily
    attempt_outcome: AttemptOutcome
    dispatch_certainty: DispatchCertainty
    canonical_no_dispatch_proof: bool = False
    terminal_evidence_confirmed: bool = False
    exact_attribution_confirmed: bool = False
    provider_progress_active: bool = False
    provider_output_exists: bool = False
    prompt_remediation_non_material: bool = False
    prompt_revision_authorized: bool = False
    semantic_remediation_material: bool = False
    owner_authorized: bool = False
    creative_rejection_confirmed: bool = False
    creative_regeneration_authorized: bool = False
    rate_limit_backoff_ready: bool = False
    transient_redispatch_count: int = 0
    provider_attempt_count: int = 0
    prompt_remediation_count: int = 0
    creative_correction_count: int = 0
    legacy_request_status: str | None = None

    def __post_init__(self) -> None:
        if any(value < 0 for value in (
            self.transient_redispatch_count,
            self.provider_attempt_count,
            self.prompt_remediation_count,
            self.creative_correction_count,
        )):
            raise ValueError("recovery counters must be monotonic non-negative integers")

    @property
    def budgets(self) -> RecoveryBudgets:
        return RecoveryBudgets(
            transient_redispatches_used=self.transient_redispatch_count,
            transient_redispatches_limit=MAX_AUTOMATIC_TRANSIENT_REDISPATCHES,
            provider_attempts_used=self.provider_attempt_count,
            provider_attempts_limit=MAX_LIFETIME_PROVIDER_ATTEMPTS,
            prompt_remediations_used=self.prompt_remediation_count,
            prompt_remediations_limit=MAX_AUTOMATIC_PROMPT_REMEDIATIONS,
            creative_corrections_used=self.creative_correction_count,
            creative_corrections_limit=MAX_CREATIVE_CORRECTIONS,
        )


@dataclass(frozen=True)
class RecoveryDecision:
    action: RecoveryAction
    safe_to_dispatch: bool
    provider_generation_required: bool
    consumes_provider_attempt: bool
    reconciliation_required: bool
    prompt_revision_required: bool
    owner_decision_required: bool
    final_revalidation_required: bool
    single_flight_required: bool
    reason_code: ReasonCode
    budgets: RecoveryBudgets
    policy_version: str = RECOVERY_POLICY_VERSION


def evaluate_recovery(input: RecoveryInput) -> RecoveryDecision:
    """Return the deterministic recovery disposition for normalized evidence."""
    budgets = input.budgets

    # This barrier intentionally precedes every budget or special-case rule.
    if (input.dispatch_certainty is DispatchCertainty.DISPATCH_UNCERTAIN
            or input.failure_family is FailureFamily.DISPATCH_AMBIGUOUS):
        return _decision(RecoveryAction.RECONCILE_FIRST, ReasonCode.DISPATCH_AMBIGUOUS, budgets,
                         reconciliation_required=True)

    if (input.provider_progress_active
            or input.attempt_outcome in {AttemptOutcome.DISPATCHING, AttemptOutcome.GENERATING}
            or input.failure_family is FailureFamily.PROVIDER_IN_PROGRESS):
        return _decision(RecoveryAction.RESUME_POLLING, ReasonCode.EXISTING_ATTEMPT_ACTIVE, budgets)

    if input.failure_family is FailureFamily.ASSET_ACQUISITION_FAILURE and input.provider_output_exists:
        return _local_recovery(RecoveryAction.REACQUIRE, budgets)
    if input.failure_family is FailureFamily.LOCAL_VALIDATION_FAILURE:
        return _local_recovery(RecoveryAction.REVALIDATE, budgets)
    if input.failure_family is FailureFamily.LOCAL_POSTPROCESS_FAILURE:
        return _local_recovery(RecoveryAction.REPOSTPROCESS, budgets)
    if input.failure_family is FailureFamily.QC_TECHNICAL_FAILURE:
        return _local_recovery(RecoveryAction.REVALIDATE, budgets)

    if input.failure_family is FailureFamily.PROVIDER_AUTH_BLOCK:
        return _decision(RecoveryAction.OWNER_ACTION, ReasonCode.AUTH_REQUIRED, budgets,
                         owner_decision_required=True)
    if input.failure_family is FailureFamily.PROVIDER_CREDIT_BLOCK:
        return _decision(RecoveryAction.OWNER_ACTION, ReasonCode.CREDIT_BLOCKED, budgets,
                         owner_decision_required=True)
    if input.failure_family is FailureFamily.PROVIDER_UI_CHANGED:
        return _decision(RecoveryAction.OWNER_ACTION, ReasonCode.PROVIDER_UI_CHANGED, budgets,
                         owner_decision_required=True)
    if input.failure_family is FailureFamily.PROVIDER_TERMINAL_UNKNOWN:
        return _decision(RecoveryAction.OWNER_ACTION, ReasonCode.PROVIDER_TERMINAL_UNKNOWN, budgets,
                         owner_decision_required=True)

    if input.failure_family is FailureFamily.PROVIDER_POLICY_BLOCK:
        if not _has_confirmed_terminal_authority(input):
            return _decision(RecoveryAction.RECONCILE_FIRST, ReasonCode.TERMINAL_EVIDENCE_INSUFFICIENT, budgets,
                             reconciliation_required=True)
        if input.semantic_remediation_material:
            return _decision(RecoveryAction.OWNER_ACTION, ReasonCode.OWNER_PROMPT_APPROVAL_REQUIRED, budgets,
                             prompt_revision_required=True, owner_decision_required=True)
        if (input.prompt_remediation_non_material
                and budgets.prompt_remediations_remaining > 0):
            return _decision(RecoveryAction.PROMPT_REPAIR,
                             ReasonCode.AUTOMATIC_PROMPT_REMEDIATION_ELIGIBLE, budgets,
                             prompt_revision_required=True)
        return _decision(RecoveryAction.PROMPT_REPAIR, ReasonCode.POLICY_PROMPT_REPAIR_REQUIRED, budgets,
                         prompt_revision_required=True, owner_decision_required=not input.prompt_revision_authorized)

    if budgets.provider_attempts_remaining == 0:
        return _decision(RecoveryAction.NO_RETRY, ReasonCode.LIFETIME_ATTEMPT_LIMIT_REACHED, budgets,
                         owner_decision_required=True)

    if input.failure_family is FailureFamily.INITIAL_ATTEMPT:
        if (input.attempt_outcome is AttemptOutcome.NOT_STARTED
                and input.dispatch_certainty is DispatchCertainty.NOT_DISPATCHED
                and input.provider_attempt_count == 0):
            return _dispatch(RecoveryAction.DISPATCH_INITIAL, ReasonCode.INITIAL_DISPATCH_ALLOWED, budgets)
        return _decision(RecoveryAction.RECONCILE_FIRST, ReasonCode.TERMINAL_EVIDENCE_INSUFFICIENT, budgets,
                         reconciliation_required=True)

    if input.failure_family is FailureFamily.PRE_DISPATCH_FAILURE:
        if not _has_proven_no_dispatch(input):
            return _decision(RecoveryAction.RECONCILE_FIRST, ReasonCode.TERMINAL_EVIDENCE_INSUFFICIENT, budgets,
                             reconciliation_required=True)
        if budgets.transient_redispatches_remaining == 0:
            return _decision(RecoveryAction.NO_RETRY, ReasonCode.TRANSIENT_RETRY_BUDGET_EXHAUSTED, budgets,
                             owner_decision_required=True)
        return _dispatch(RecoveryAction.AUTO_RETRY, ReasonCode.TRANSIENT_RETRY_ALLOWED, budgets)

    if input.failure_family is FailureFamily.PROVIDER_RATE_LIMIT:
        if not input.rate_limit_backoff_ready:
            return _decision(RecoveryAction.WAIT_AND_RETRY, ReasonCode.RATE_LIMIT_BACKOFF_REQUIRED, budgets)
        if not _has_terminal_or_no_dispatch_authority(input):
            return _decision(RecoveryAction.RECONCILE_FIRST, ReasonCode.TERMINAL_EVIDENCE_INSUFFICIENT, budgets,
                             reconciliation_required=True)
        if budgets.transient_redispatches_remaining == 0:
            return _decision(RecoveryAction.NO_RETRY, ReasonCode.TRANSIENT_RETRY_BUDGET_EXHAUSTED, budgets,
                             owner_decision_required=True)
        return _dispatch(RecoveryAction.AUTO_RETRY, ReasonCode.TRANSIENT_RETRY_ALLOWED, budgets)

    if input.failure_family is FailureFamily.PROVIDER_TERMINAL_TRANSIENT:
        if not _has_confirmed_terminal_authority(input):
            return _decision(RecoveryAction.RECONCILE_FIRST, ReasonCode.TERMINAL_EVIDENCE_INSUFFICIENT, budgets,
                             reconciliation_required=True)
        if budgets.transient_redispatches_remaining == 0:
            return _decision(RecoveryAction.NO_RETRY, ReasonCode.TRANSIENT_RETRY_BUDGET_EXHAUSTED, budgets,
                             owner_decision_required=True)
        return _dispatch(RecoveryAction.AUTO_RETRY, ReasonCode.TRANSIENT_RETRY_ALLOWED, budgets)

    if input.failure_family is FailureFamily.QC_CREATIVE_REJECTION:
        if not input.creative_rejection_confirmed or not input.creative_regeneration_authorized:
            return _decision(RecoveryAction.OWNER_ACTION, ReasonCode.OWNER_AUTHORIZATION_REQUIRED, budgets,
                             owner_decision_required=True)
        if budgets.creative_corrections_remaining == 0:
            return _decision(RecoveryAction.NO_RETRY, ReasonCode.CREATIVE_RETRY_BUDGET_EXHAUSTED, budgets,
                             owner_decision_required=True)
        if not _has_confirmed_terminal_authority(input):
            return _decision(RecoveryAction.RECONCILE_FIRST, ReasonCode.TERMINAL_EVIDENCE_INSUFFICIENT, budgets,
                             reconciliation_required=True)
        return _dispatch(RecoveryAction.CREATIVE_REGENERATE, ReasonCode.CREATIVE_RETRY_ALLOWED, budgets)

    if input.failure_family is FailureFamily.MANUAL_REGENERATE:
        if not input.owner_authorized:
            return _decision(RecoveryAction.OWNER_ACTION, ReasonCode.OWNER_AUTHORIZATION_REQUIRED, budgets,
                             owner_decision_required=True)
        if (input.dispatch_certainty in {DispatchCertainty.DISPATCH_CONFIRMED,
                                         DispatchCertainty.TERMINAL_CONFIRMED}
                and not _has_resolved_terminal_authority(input)):
            return _decision(RecoveryAction.RECONCILE_FIRST, ReasonCode.TERMINAL_EVIDENCE_INSUFFICIENT, budgets,
                             reconciliation_required=True)
        if (input.dispatch_certainty is DispatchCertainty.NOT_DISPATCHED
                and not input.canonical_no_dispatch_proof):
            return _decision(RecoveryAction.RECONCILE_FIRST, ReasonCode.TERMINAL_EVIDENCE_INSUFFICIENT, budgets,
                             reconciliation_required=True)
        return _dispatch(RecoveryAction.MANUAL_REGENERATE, ReasonCode.TRANSIENT_RETRY_ALLOWED, budgets)

    return _decision(RecoveryAction.OWNER_ACTION, ReasonCode.PROVIDER_TERMINAL_UNKNOWN, budgets,
                     owner_decision_required=True)


def _has_proven_no_dispatch(input: RecoveryInput) -> bool:
    return (input.dispatch_certainty is DispatchCertainty.NOT_DISPATCHED
            and input.canonical_no_dispatch_proof)


def _has_confirmed_terminal_authority(input: RecoveryInput) -> bool:
    return (input.attempt_outcome is AttemptOutcome.FAILED
            and input.dispatch_certainty is DispatchCertainty.TERMINAL_CONFIRMED
            and input.terminal_evidence_confirmed
            and input.exact_attribution_confirmed)


def _has_resolved_terminal_authority(input: RecoveryInput) -> bool:
    return (input.attempt_outcome in {AttemptOutcome.SUCCEEDED, AttemptOutcome.FAILED}
            and input.dispatch_certainty is DispatchCertainty.TERMINAL_CONFIRMED
            and input.terminal_evidence_confirmed
            and input.exact_attribution_confirmed)


def _has_terminal_or_no_dispatch_authority(input: RecoveryInput) -> bool:
    return _has_proven_no_dispatch(input) or _has_confirmed_terminal_authority(input)


def _dispatch(action: RecoveryAction, reason: ReasonCode, budgets: RecoveryBudgets) -> RecoveryDecision:
    return _decision(action, reason, budgets, safe_to_dispatch=True,
                     provider_generation_required=True, consumes_provider_attempt=True,
                     final_revalidation_required=True, single_flight_required=True)


def _local_recovery(action: RecoveryAction, budgets: RecoveryBudgets) -> RecoveryDecision:
    return _decision(action, ReasonCode.LOCAL_RECOVERY_REQUIRED, budgets)


def _decision(action: RecoveryAction, reason: ReasonCode, budgets: RecoveryBudgets, *,
              safe_to_dispatch: bool = False, provider_generation_required: bool = False,
              consumes_provider_attempt: bool = False, reconciliation_required: bool = False,
              prompt_revision_required: bool = False, owner_decision_required: bool = False,
              final_revalidation_required: bool = False, single_flight_required: bool = False) -> RecoveryDecision:
    return RecoveryDecision(
        action=action,
        safe_to_dispatch=safe_to_dispatch,
        provider_generation_required=provider_generation_required,
        consumes_provider_attempt=consumes_provider_attempt,
        reconciliation_required=reconciliation_required,
        prompt_revision_required=prompt_revision_required,
        owner_decision_required=owner_decision_required,
        final_revalidation_required=final_revalidation_required,
        single_flight_required=single_flight_required,
        reason_code=reason,
        budgets=budgets,
    )

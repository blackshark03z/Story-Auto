"""The sole recovery-authorized provider generation gate for Flow.

The gate owns no artifact ledger.  Callers supply the existing durable read,
append, and provider-boundary operations, while this module makes their order
non-negotiable: initial decision, single flight, fresh re-read, final decision,
append, then one boundary crossing.
"""
from __future__ import annotations

from dataclasses import dataclass
import random
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from story_auto.core.project.lock import ProjectLock, ProjectLockedError
from story_auto.core.visual.recovery import RecoveryDecision, RecoveryInput, evaluate_recovery


class SingleFlight(Protocol):
    def acquire(self) -> bool: ...
    def release(self) -> None: ...


class InMemorySingleFlight:
    """Thread-safe local single-flight implementation for one logical key."""
    _guard = threading.Lock()
    _held: set[str] = set()

    def __init__(self, key: str) -> None:
        self.key = key
        self.owned = False

    def acquire(self) -> bool:
        with self._guard:
            if self.key in self._held:
                return False
            self._held.add(self.key)
            self.owned = True
            return True

    def release(self) -> None:
        with self._guard:
            if self.owned:
                self._held.discard(self.key)
                self.owned = False


class FlowSessionSingleFlight:
    """Cross-process exclusion for the actual shared Flow browser session."""
    def __init__(self, runtime, session_identity: str) -> None:
        if not isinstance(session_identity, str) or not session_identity.strip():
            raise ValueError("Flow session identity is required")
        import hashlib
        digest = hashlib.sha256(session_identity.encode("utf-8")).hexdigest()
        self.key = f"flow-session-{digest}"
        self.lock = ProjectLock(runtime, self.key)
        self.owned = False

    def acquire(self) -> bool:
        try:
            self.lock.acquire()
        except ProjectLockedError:
            return False
        self.owned = True
        return True

    def release(self) -> None:
        if self.owned:
            self.lock.release()
            self.owned = False


class AlreadyOwnedSingleFlight:
    """Adapter for Story Auto's cross-process ProjectLock already acquired."""
    def __init__(self) -> None:
        self.owned = False

    def acquire(self) -> bool:
        self.owned = True
        return True

    def release(self) -> None:
        self.owned = False


@dataclass(frozen=True)
class RecoveryExecutionResult:
    dispatched: bool
    reason: str
    decision: RecoveryDecision


class RecoveryRetryTiming:
    """Bounded automatic retry timing; it never invokes a provider itself."""
    def __init__(self, *, base_delay_seconds: float = 2.0, max_delay_seconds: float = 32.0,
                 max_total_wait_seconds: float = 120.0, jitter_seconds: float = 1.0,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 random_fn: Callable[[], float] = random.random) -> None:
        if (base_delay_seconds < 0 or max_delay_seconds < base_delay_seconds
                or max_total_wait_seconds < 0 or jitter_seconds < 0):
            raise ValueError("invalid recovery retry timing")
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.max_total_wait_seconds = max_total_wait_seconds
        self.jitter_seconds = jitter_seconds
        self.clock, self.sleep, self.random_fn = clock, sleep, random_fn
        self.started_at = clock()

    def delay_for(self, transient_redispatches_used: int) -> float:
        if transient_redispatches_used < 0:
            raise ValueError("transient redispatch count must be non-negative")
        base = min(self.max_delay_seconds,
                   self.base_delay_seconds * (2 ** transient_redispatches_used))
        return base + (self.random_fn() * self.jitter_seconds)

    def wait(self, transient_redispatches_used: int) -> bool:
        delay = self.delay_for(transient_redispatches_used)
        if self.clock() - self.started_at + delay > self.max_total_wait_seconds:
            return False
        self.sleep(delay)
        return True


class RecoveryExecutionGate:
    """Authorize at most one caller to cross a supplied provider boundary."""
    def __init__(self, single_flight: SingleFlight) -> None:
        self.single_flight = single_flight

    @staticmethod
    def _dispatchable(decision: RecoveryDecision) -> bool:
        return bool(
            decision.safe_to_dispatch
            and decision.provider_generation_required
            and decision.consumes_provider_attempt
            and decision.single_flight_required
            and decision.final_revalidation_required
        )

    def execute(self, initial_facts: RecoveryInput, *,
                load_fresh: Callable[[], RecoveryInput],
                append_attempt: Callable[[RecoveryDecision], Any],
                dispatch: Callable[[Any], Any],
                before_final_revalidation: Callable[[], None] | None = None) -> RecoveryExecutionResult:
        initial = evaluate_recovery(initial_facts)
        if not self._dispatchable(initial):
            return RecoveryExecutionResult(False, "INITIAL_DECISION_REJECTED", initial)
        if not self.single_flight.acquire():
            return RecoveryExecutionResult(False, "SINGLE_FLIGHT_CONFLICT", initial)
        try:
            if before_final_revalidation is not None:
                before_final_revalidation()
            final = evaluate_recovery(load_fresh())
            if not self._dispatchable(final):
                return RecoveryExecutionResult(False, "FINAL_REVALIDATION_REJECTED", final)
            attempt = append_attempt(final)
            dispatch(attempt)
            return RecoveryExecutionResult(True, "DISPATCHED", final)
        finally:
            self.single_flight.release()

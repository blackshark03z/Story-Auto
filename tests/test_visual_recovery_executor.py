"""Offline Slice 3 tests for the sole safe Flow recovery execution gate."""
from __future__ import annotations

import threading
import tempfile
import unittest

from story_auto.core.visual.recovery_executor import (
    InMemorySingleFlight,
    RecoveryExecutionGate,
    RecoveryRetryTiming,
)
from story_auto.core.visual.recovery import (
    AttemptOutcome,
    DispatchCertainty,
    FailureFamily,
    RecoveryInput,
)
from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.service import FlowExecutor, execute_generation
from story_auto.providers.flow.session import FlowCapabilities


def initial() -> RecoveryInput:
    return RecoveryInput(FailureFamily.INITIAL_ATTEMPT, AttemptOutcome.NOT_STARTED,
                         DispatchCertainty.NOT_DISPATCHED)


def retry(*, retries: int = 0, attempts: int | None = None, family: FailureFamily = FailureFamily.PRE_DISPATCH_FAILURE,
          safe: bool = True) -> RecoveryInput:
    if attempts is None:
        attempts = retries
    return RecoveryInput(
        family, AttemptOutcome.FAILED,
        DispatchCertainty.NOT_DISPATCHED if safe else DispatchCertainty.DISPATCH_CONFIRMED,
        canonical_no_dispatch_proof=safe,
        terminal_evidence_confirmed=family is FailureFamily.PROVIDER_TERMINAL_TRANSIENT,
        exact_attribution_confirmed=family in {FailureFamily.PROVIDER_TERMINAL_TRANSIENT,
                                               FailureFamily.PROVIDER_RATE_LIMIT},
        rate_limit_backoff_ready=family is FailureFamily.PROVIDER_RATE_LIMIT,
        transient_redispatch_count=retries, provider_attempt_count=attempts,
        legacy_request_status="FAILED_RETRYABLE",
    )


def terminal_retry(*, retries: int = 0, attempts: int = 1) -> RecoveryInput:
    return RecoveryInput(
        FailureFamily.PROVIDER_TERMINAL_TRANSIENT, AttemptOutcome.FAILED,
        DispatchCertainty.TERMINAL_CONFIRMED, terminal_evidence_confirmed=True,
        exact_attribution_confirmed=True, transient_redispatch_count=retries,
        provider_attempt_count=attempts,
    )


class RecoveryExecutionGateTests(unittest.TestCase):
    def run_gate(self, original, fresh=None, *, fresh_loader=None, flight=None, before_final=None, dispatch=None):
        appended: list[dict] = []
        calls: list[dict] = []
        gate = RecoveryExecutionGate(flight or InMemorySingleFlight("request"))
        result = gate.execute(
            original,
            load_fresh=fresh_loader or (lambda: fresh if fresh is not None else original),
            append_attempt=lambda decision: appended.append({"attempt": len(appended) + 1, "decision": decision}),
            dispatch=dispatch or (lambda attempt: calls.append(attempt)),
            before_final_revalidation=before_final,
        )
        return result, appended, calls

    def test_safe_transient_dispatches_once_and_appends_once(self):
        result, appended, calls = self.run_gate(retry())
        self.assertTrue(result.dispatched)
        self.assertEqual((len(appended), len(calls)), (1, 1))

    def test_safe_terminal_transient_dispatches_once(self):
        result, appended, calls = self.run_gate(terminal_retry())
        self.assertTrue(result.dispatched)
        self.assertEqual((len(appended), len(calls)), (1, 1))

    def test_stale_pre_lock_decision_cannot_dispatch(self):
        result, appended, calls = self.run_gate(retry(), retry(safe=False))
        self.assertFalse(result.dispatched)
        self.assertEqual((appended, calls), ([], []))

    def test_stale_post_lock_decision_cannot_dispatch(self):
        current = [retry()]
        result, appended, calls = self.run_gate(
            retry(), flight=InMemorySingleFlight("post-lock"),
            before_final=lambda: current.__setitem__(0, retry(safe=False)),
            fresh_loader=lambda: current[0],
        )
        self.assertFalse(result.dispatched)
        self.assertEqual((appended, calls), ([], []))

    def test_two_concurrent_callers_dispatch_at_most_once(self):
        flight = InMemorySingleFlight("same-request")
        entered = threading.Event()
        release = threading.Event()
        calls: list[dict] = []
        first = RecoveryExecutionGate(flight)
        second = RecoveryExecutionGate(flight)
        results = []

        def slow_dispatch(attempt):
            calls.append(attempt)
            entered.set()
            release.wait(2)

        worker = threading.Thread(target=lambda: results.append(first.execute(
            retry(), load_fresh=retry, append_attempt=lambda _d: {"attempt": 1}, dispatch=slow_dispatch,
        )))
        worker.start(); self.assertTrue(entered.wait(2))
        loser = second.execute(retry(), load_fresh=retry, append_attempt=lambda _d: self.fail("must not append"),
                               dispatch=lambda _a: self.fail("must not dispatch"))
        release.set(); worker.join(2)
        self.assertTrue(results[0].dispatched)
        self.assertEqual((loser.reason, len(calls)), ("SINGLE_FLIGHT_CONFLICT", 1))

    def test_lock_conflict_does_not_consume_attempt(self):
        flight = InMemorySingleFlight("conflict"); flight.acquire()
        try:
            result, appended, calls = self.run_gate(retry(), flight=flight)
        finally:
            flight.release()
        self.assertEqual((result.reason, appended, calls), ("SINGLE_FLIGHT_CONFLICT", [], []))

    def test_ambiguous_and_unsafe_evidence_never_dispatch(self):
        cases = [
            RecoveryInput(FailureFamily.PRE_DISPATCH_FAILURE, AttemptOutcome.FAILED,
                          DispatchCertainty.DISPATCH_UNCERTAIN),
            RecoveryInput(FailureFamily.DISPATCH_AMBIGUOUS, AttemptOutcome.FAILED,
                          DispatchCertainty.NOT_DISPATCHED),
            retry(safe=False),
        ]
        for facts in cases:
            with self.subTest(facts=facts):
                result, appended, calls = self.run_gate(facts)
                self.assertFalse(result.dispatched)
                self.assertEqual((appended, calls), ([], []))

    def test_transient_budget_and_lifetime_stop_loss(self):
        allowed_one = self.run_gate(retry(retries=0))[0]
        allowed_two = self.run_gate(retry(retries=1))[0]
        exhausted = self.run_gate(retry(retries=2))[0]
        lifetime = self.run_gate(retry(attempts=12))[0]
        self.assertEqual((allowed_one.dispatched, allowed_two.dispatched, exhausted.dispatched, lifetime.dispatched),
                         (True, True, False, False))

    def test_rate_limit_shares_transient_budget(self):
        self.assertTrue(self.run_gate(retry(family=FailureFamily.PROVIDER_RATE_LIMIT, retries=1))[0].dispatched)
        self.assertFalse(self.run_gate(retry(family=FailureFamily.PROVIDER_RATE_LIMIT, retries=2))[0].dispatched)

    def test_initial_is_not_an_automatic_retry(self):
        result, appended, calls = self.run_gate(initial())
        self.assertTrue(result.dispatched)
        self.assertEqual((len(appended), len(calls)), (1, 1))

    def test_policy_and_provider_account_blocks_never_dispatch(self):
        cases = [
            RecoveryInput(FailureFamily.PROVIDER_POLICY_BLOCK, AttemptOutcome.FAILED,
                          DispatchCertainty.TERMINAL_CONFIRMED, terminal_evidence_confirmed=True,
                          exact_attribution_confirmed=True),
            RecoveryInput(FailureFamily.PROVIDER_AUTH_BLOCK, AttemptOutcome.FAILED,
                          DispatchCertainty.TERMINAL_CONFIRMED),
            RecoveryInput(FailureFamily.PROVIDER_CREDIT_BLOCK, AttemptOutcome.FAILED,
                          DispatchCertainty.TERMINAL_CONFIRMED),
            RecoveryInput(FailureFamily.PROVIDER_TERMINAL_UNKNOWN, AttemptOutcome.FAILED,
                          DispatchCertainty.TERMINAL_CONFIRMED),
        ]
        for facts in cases:
            with self.subTest(facts=facts):
                result, appended, calls = self.run_gate(facts)
                self.assertFalse(result.dispatched)
                self.assertEqual((appended, calls), ([], []))

    def test_single_flight_releases_after_success(self):
        flight = InMemorySingleFlight("success-release")
        result, _appended, _calls = self.run_gate(retry(), flight=flight)
        self.assertTrue(result.dispatched)
        self.assertTrue(flight.acquire()); flight.release()

    def test_provider_exception_has_no_recursive_retry_and_releases_lock(self):
        flight = InMemorySingleFlight("exception")
        calls = []
        with self.assertRaisesRegex(RuntimeError, "provider"):
            RecoveryExecutionGate(flight).execute(
                retry(), load_fresh=retry, append_attempt=lambda _d: {"attempt": 1},
                dispatch=lambda _a: (calls.append("once"), (_ for _ in ()).throw(RuntimeError("provider")))[1],
            )
        self.assertEqual(calls, ["once"])
        self.assertTrue(flight.acquire()); flight.release()

    def test_adversarial_stale_caller_rereads_after_other_owner_changes_evidence(self):
        facts = [retry()]
        flight = InMemorySingleFlight("adversarial")
        flight.acquire()
        gate = RecoveryExecutionGate(flight)
        flight.release()
        result = gate.execute(retry(), load_fresh=lambda: facts[0],
                              append_attempt=lambda _d: self.fail("stale decision appended"),
                              dispatch=lambda _a: self.fail("stale decision dispatched"),
                              before_final_revalidation=lambda: facts.__setitem__(0, retry(safe=False)))
        self.assertFalse(result.dispatched)


class RecoveryRetryTimingTests(unittest.TestCase):
    def test_backoff_is_exponential_bounded_and_deterministic(self):
        clock = [0.0]; slept = []
        timing = RecoveryRetryTiming(base_delay_seconds=2, max_delay_seconds=5, max_total_wait_seconds=10,
                                     clock=lambda: clock[0], sleep=lambda value: (slept.append(value), clock.__setitem__(0, clock[0] + value)),
                                     random_fn=lambda: 0.5, jitter_seconds=1)
        self.assertEqual((timing.delay_for(0), timing.delay_for(1), timing.delay_for(2)), (2.5, 4.5, 5.5))
        self.assertTrue(timing.wait(0)); self.assertTrue(timing.wait(1)); self.assertFalse(timing.wait(2))
        self.assertEqual(slept, [2.5, 4.5])


class FlowRecoveryServiceBoundaryTests(unittest.TestCase):
    def test_authorized_execution_appends_once_and_records_one_submission(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = RuntimeLayout.from_root(root)
            paths = create_project(runtime, ProjectConfig("prj_slice3"))
            atomic_write_json(paths.artifact_path("output/review_state.json"),
                              {"plan_approval": {"status": "APPROVED"}})
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": [{
                "request_id": "req_slice3", "fingerprint": "slice3", "purpose": "REFERENCE",
                "media_type": "IMAGE", "prompt": "synthetic", "depends_on": [], "provider": "google_flow",
            }]})
            calls = []

            def provider(request, _references, destination):
                from PIL import Image
                calls.append(request["request_id"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (1280, 720), "navy").save(destination, "PNG")
                return destination

            result = execute_generation(
                runtime.root, "prj_slice3",
                executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), provider),
                execute=True,
            )
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((result["new_submissions"], calls, entry["provider_submissions"]),
                             (1, ["req_slice3"], 1))
            self.assertEqual((len(entry["attempts"]), entry["attempts"][0]["recovery_action"]),
                             (1, "DISPATCH_INITIAL"))


if __name__ == "__main__":
    unittest.main()

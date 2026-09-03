"""Offline Goal 25 semantic no-dispatch authority contract tests."""
from __future__ import annotations

import copy
import tempfile
import unittest
from unittest.mock import patch

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.providers.flow.live import ProviderPollEvidenceTimeline
from story_auto.providers.flow.service import (
    FlowExecutor,
    _abandoned_unresolved_entry_valid,
    _provider_generation_retry_authorized,
    _runnable,
    _unresolved_flow_entry,
    canonical_no_dispatch_proof,
    execute_generation,
)
from story_auto.providers.flow.session import FlowCapabilities
from tests import test_goal20_flow_evidence_and_unresolved_replay as goal20_tests


GOAL24_REPLACEMENT_ID = "req_2f755d20c25245314761"


def _goal24_legacy_attempt() -> dict:
    """Fixture-only copy of the preserved replacement's verified old shape."""
    timeline = ProviderPollEvidenceTimeline(
        poll_evidence_version="story-auto-flow-poll-evidence/1.2.0",
        parser_extractor_version="flow-provider-surface/2.1.0",
    )
    for sequence in range(1, 27):
        timeline.append({
            "phase": "PRE_DISPATCH_DISCOVERY" if sequence <= 3 else "PRE_DISPATCH_BASELINE",
            "input_dispatched": False,
            "dispatch_evidence_state": "NOT_CONFIRMED",
            "dispatch_signal_state": "NONE",
            "attribution_evidence_state": "NOT_ATTEMPTED",
            "durable_dispatch_identity": None,
            "lineage_card_id": None,
            "candidate_identities": ([{"identity": "card:preexisting"}] if sequence >= 4 else []),
        })
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


class Goal25NoDispatchSemanticAuthorityTests(unittest.TestCase):
    OLD_ID = goal20_tests.Goal20UnresolvedReplayTests.OLD_ID

    def _project(self, root: str):
        return goal20_tests.Goal20UnresolvedReplayTests._project(self, root)

    def _replay(self, runtime, config, **kwargs):
        return goal20_tests.Goal20UnresolvedReplayTests._replay(self, runtime, config, **kwargs)

    def _fixture(self, root: str):
        runtime, config, paths = self._project(root)
        with patch("story_auto.providers.flow.service._replacement_identity",
                   return_value=(GOAL24_REPLACEMENT_ID, "goal24-preserved-fingerprint")):
            replay = self._replay(runtime, config)
        self.assertEqual(replay["replacement_request_id"], GOAL24_REPLACEMENT_ID)
        manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
        replacement = next(item for item in manifest["requests"]
                           if item["request_id"] == GOAL24_REPLACEMENT_ID)
        replacement.update({
            "status": "NOT_DISPATCHED",
            "failure_class": "OUTPUT_ATTRIBUTION_NOT_QUIESCENT",
            "attempts": [_goal24_legacy_attempt()],
        })
        atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
        requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
        entries = {entry["request_id"]: entry for entry in manifest["requests"]}
        old = entries[self.OLD_ID]
        return runtime, config, paths, requests, entries, old, replacement

    def test_exact_preserved_goal24_replacement_passes_every_no_dispatch_consumer(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths, requests, entries, old, replacement = self._fixture(root)
            request = next(item for item in requests if item["request_id"] == GOAL24_REPLACEMENT_ID)
            attempt = replacement["attempts"][-1]

            self.assertTrue(canonical_no_dispatch_proof(attempt))
            self.assertTrue(_provider_generation_retry_authorized(replacement))
            self.assertTrue(_abandoned_unresolved_entry_valid(paths, config.project_id, old, requests, entries))
            self.assertFalse(_unresolved_flow_entry(replacement))
            self.assertTrue(_runnable(request, entries))

            calls = []

            class ProviderBoundaryReached(Exception):
                pass

            def provider_boundary(request, _references, _destination):
                calls.append(request["request_id"])
                raise ProviderBoundaryReached("offline provider boundary reached")

            executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), provider_boundary)
            with self.assertRaises(ProviderBoundaryReached):
                execute_generation(runtime.root, config.project_id, executor=executor, execute=True,
                                   request_ids={GOAL24_REPLACEMENT_ID}, max_requests=1)
            self.assertEqual(calls, [GOAL24_REPLACEMENT_ID])

    def test_negative_evidence_matrix_denies_all_semantic_consumers_consistently(self):
        def replace_with(attempt):
            def mutate(_base):
                return attempt
            return mutate

        def nested_change(path, value):
            def mutate(attempt):
                target = attempt
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                return attempt
            return mutate

        cases = {
            "broken_or_missing_evidence_chain": nested_change(
                ("provider_settings", "provider_poll_evidence", "observations", 0, "input_dispatched"), True),
            "arbitrary_nested_input_dispatched_false": replace_with({"provider_settings": {"activation": {"input_dispatched": False}}}),
            "input_dispatched_true": nested_change(
                ("provider_settings", "provider_poll_evidence", "observations", 25, "input_dispatched"), True),
            "dispatch_confirmed": nested_change(("dispatch_confirmed",), True),
            "dispatch_uncertain": nested_change(("dispatch_confirmation_state",), "UNCERTAIN"),
            "provider_job_exists": nested_change(("provider_job_id",), "job:unexpected"),
            "durable_dispatch_identity_exists": nested_change(("durable_dispatch_identity",), "asset:unexpected"),
            "lineage_card_exists": nested_change(("provider_lineage_card_id",), "card:unexpected"),
            "attributed_identity_exists": nested_change(("attributed_provider_identity",), {"identity": "asset:unexpected"}),
            "attribution_uncertain": nested_change(("attribution_state",), "UNCERTAIN"),
            "attribution_ambiguous": nested_change(("attribution_state",), "AMBIGUOUS"),
            "provider_boundary_entered": nested_change(("provider_execution_state",), "PROVIDER_BOUNDARY_ENTERED"),
            "timeout_without_positive_proof": replace_with({"status": "FAILED_RETRYABLE", "failure_class": "FLOW_TIMEOUT"}),
            "failed_retryable_without_positive_proof": replace_with({"status": "FAILED_RETRYABLE", "dispatch_confirmed": False}),
            "missing_provider_job_only": replace_with({"provider_job_id": None}),
            "dispatch_confirmed_false_only": replace_with({"dispatch_confirmed": False}),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                runtime, config, paths, requests, entries, old, replacement = self._fixture(root)
                broken = mutate(copy.deepcopy(replacement["attempts"][-1]))
                replacement["attempts"] = [broken]
                atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
                    "schema_version": "story-auto-generation-manifest/1.0.0",
                    "project_id": config.project_id,
                    "requests": list(entries.values()),
                })
                self.assertFalse(canonical_no_dispatch_proof(broken))
                self.assertFalse(_provider_generation_retry_authorized(replacement))
                self.assertFalse(_abandoned_unresolved_entry_valid(paths, config.project_id, old, requests, entries))
                self.assertTrue(_unresolved_flow_entry(replacement))

                calls = []
                executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True),
                                        lambda *_: calls.append("provider"))
                result = execute_generation(runtime.root, config.project_id, executor=executor, execute=True,
                                            request_ids={GOAL24_REPLACEMENT_ID}, max_requests=1)
                self.assertEqual((result["blocked"], calls), (True, []))


if __name__ == "__main__":
    unittest.main()

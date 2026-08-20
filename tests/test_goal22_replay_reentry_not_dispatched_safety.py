"""Offline Goal 22 replay-genesis and retry-barrier contract tests."""
from __future__ import annotations

import tempfile
import unittest

from PIL import Image

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.providers.flow.service import FlowError, FlowExecutor, execute_generation
from story_auto.providers.flow.session import FlowCapabilities
from tests.test_goal20_flow_evidence_and_unresolved_replay import Goal20UnresolvedReplayTests


class Goal22ReplayReentrySafetyTests(Goal20UnresolvedReplayTests):
    """Extend the Goal 20 fixture with the preserved Goal 21 failure shape."""

    @staticmethod
    def _entry(paths, request_id):
        manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
        return next(item for item in manifest["requests"] if item["request_id"] == request_id)

    def test_exact_pre_dispatch_not_dispatched_shape_reenters_without_second_epoch(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            replacement_id = self._replay(runtime, config)["replacement_request_id"]
            old_before = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]["attempts"]

            class SafeThenExactSuccess:
                def __init__(self):
                    self.calls = 0
                    self.dispatch_confirmed = False
                    self.last_settings = None

                def __call__(self, _request, _references, destination):
                    self.calls += 1
                    if self.calls == 1:
                        self.last_settings = {
                            "activation": {"input_dispatched": False,
                                           "proof": "PRE_DISPATCH_BASELINE_NOT_QUIESCENT"},
                            "dispatch_confirmation_state": "PRE_DISPATCH_FAILURE",
                            "provider_job_id": None,
                            "attribution_state": "NOT_ATTEMPTED",
                        }
                        raise FlowError("OUTPUT_ATTRIBUTION_NOT_QUIESCENT")
                    self.last_settings = None
                    self.dispatch_confirmed = True
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (1280, 720), "navy").save(destination, "PNG")
                    return destination

            generator = SafeThenExactSuccess()
            executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), generator)
            first = execute_generation(runtime.root, config.project_id, executor=executor, execute=True,
                                       request_ids={replacement_id}, max_requests=1)
            replacement = self._entry(paths, replacement_id)
            self.assertEqual((first["new_submissions"], replacement["status"]), (0, "NOT_DISPATCHED"))
            self.assertEqual((replacement["attempts"][-1]["dispatch_confirmed"],
                              replacement["attempts"][-1]["provider_job_id"],
                              replacement["attempts"][-1]["attribution_state"]), (False, None, "NOT_ATTEMPTED"))
            self.assertTrue(self._replay(runtime, config)["idempotent"])
            self.assertEqual(len(read_json(paths.artifact_path("output/generation_requests.json"))["requests"]), 2)

            second = execute_generation(runtime.root, config.project_id, executor=executor, execute=True,
                                        request_ids={replacement_id}, max_requests=1)
            replacement = self._entry(paths, replacement_id)
            self.assertEqual((second["new_submissions"], replacement["status"], generator.calls), (1, "SUCCEEDED", 2))
            self.assertIn("selected_asset", replacement)
            self.assertEqual(self._entry(paths, self.OLD_ID)["attempts"], old_before)

    def test_immutable_replay_facts_and_transaction_lineage_fail_closed(self):
        for label in ("old_attempts", "replacement_prompt", "dependencies", "references", "lineage"):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as root:
                runtime, config, paths = self._project(root)
                replacement_id = self._replay(runtime, config)["replacement_request_id"]
                manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
                requests = read_json(paths.artifact_path("output/generation_requests.json"))
                old = next(item for item in manifest["requests"] if item["request_id"] == self.OLD_ID)
                replacement = next(item for item in manifest["requests"] if item["request_id"] == replacement_id)
                request = next(item for item in requests["requests"] if item["request_id"] == replacement_id)
                if label == "old_attempts":
                    old["attempts"].append({"attempt": 99})
                elif label == "replacement_prompt":
                    request["prompt"] = "tampered"
                elif label == "dependencies":
                    request["depends_on"] = ["req_tampered"]
                elif label == "references":
                    request["reference_asset_ids"] = ["req_tampered"]
                else:
                    replacement["replay_creation_transaction_id"] = "unresolved-replay-tampered"
                if label in {"replacement_prompt", "dependencies", "references"}:
                    atomic_write_json(paths.artifact_path("output/generation_requests.json"), requests)
                else:
                    atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
                calls = []
                result = execute_generation(runtime.root, config.project_id,
                                            executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True),
                                                                  lambda *_: calls.append("provider")),
                                            execute=True, request_ids={replacement_id}, max_requests=1)
                self.assertEqual((result["blocked"], result["blocked_request_id"], calls), (True, self.OLD_ID, []))

    def test_unproven_or_uncertain_attempts_remain_serial_barriers(self):
        cases = {
            "missing_job_id_only": ("FLOW_PRE_DISPATCH_ACTIVATION_FAILED", None),
            "timeout_without_output": ("FLOW_TIMEOUT", None),
            "confirmed_dispatch": ("FLOW_DISPATCH_UNCERTAIN", {"dispatch_confirmed": True,
                                                                    "dispatch_confirmation_state": "CONFIRMED",
                                                                    "attribution_state": "UNCERTAIN"}),
            "uncertain_dispatch": ("FLOW_DISPATCH_UNCERTAIN", {"dispatch_confirmed": False,
                                                                    "dispatch_confirmation_state": "UNCERTAIN",
                                                                    "attribution_state": "UNCERTAIN"}),
            "uncertain_attribution": ("OUTPUT_ATTRIBUTION_UNCERTAIN", {"dispatch_confirmed": True,
                                                                            "dispatch_confirmation_state": "CONFIRMED",
                                                                            "attribution_state": "UNCERTAIN"}),
        }
        for label, (failure, evidence) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as root:
                runtime, config, paths = self._project(root)
                replacement_id = self._replay(runtime, config)["replacement_request_id"]

                class UnsafeGenerator:
                    def __init__(self):
                        self.dispatch_confirmed = False
                        self.last_settings = evidence
                    def __call__(self, *_): raise FlowError(failure)

                calls = []
                executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), UnsafeGenerator())
                result = execute_generation(runtime.root, config.project_id, executor=executor, execute=True,
                                            request_ids={replacement_id}, max_requests=1)
                self.assertTrue(result["blocked"])
                replacement = self._entry(paths, replacement_id)
                self.assertEqual(replacement["status"], "AMBIGUOUS")
                self.assertNotIn("selected_asset", replacement)
                retry = execute_generation(runtime.root, config.project_id,
                                           executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True),
                                                                 lambda *_: calls.append("provider")),
                                           execute=True, request_ids={replacement_id}, max_requests=1)
                self.assertEqual((retry["blocked"], calls), (True, []))


if __name__ == "__main__":
    unittest.main()

"""Offline Goal 22 replay-genesis and retry-barrier contract tests."""
from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.providers.flow.attribution import AttributionObservation
from story_auto.providers.flow.live import DispatchEvidenceTracker, LiveFlowGenerator, _dhash_bytes
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

    def test_failed_retryable_never_authorizes_replay_or_ordinary_provider_resubmission(self):
        for replay in (True, False):
            with self.subTest(replay=replay), tempfile.TemporaryDirectory() as root:
                runtime, config, paths = self._project(root)
                request_id = self._replay(runtime, config)["replacement_request_id"] if replay else self.OLD_ID
                if not replay:
                    manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
                    entry = next(item for item in manifest["requests"] if item["request_id"] == request_id)
                    entry.update({"status": "PENDING", "failure_class": None, "attempts": []})
                    atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)

                class ArbitraryFailure:
                    dispatch_confirmed = False
                    last_settings = {"dispatch_confirmation_state": "PRE_DISPATCH_FAILURE",
                                     "provider_job_id": None, "attribution_state": "NOT_ATTEMPTED"}
                    def __call__(self, *_):
                        raise FlowError("FLOW_ARBITRARY_RETRYABLE_FAILURE")

                first = execute_generation(
                    runtime.root, config.project_id,
                    executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), ArbitraryFailure()),
                    execute=True, request_ids={request_id}, max_requests=1,
                )
                self.assertTrue(first["blocked"])
                self.assertEqual(self._entry(paths, request_id)["status"], "FAILED_RETRYABLE")
                calls = []
                second = execute_generation(
                    runtime.root, config.project_id,
                    executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True),
                                          lambda *_: calls.append("provider")),
                    execute=True, request_ids={request_id}, max_requests=1,
                )
                self.assertEqual((second["blocked"], second["blocked_request_id"], calls),
                                 (True, request_id, []))

    @staticmethod
    def _candidate_observation(candidate):
        return AttributionObservation(
            state="CONFIRMED", method="fixture-exact", candidate=candidate,
            lineage_card_id=candidate["card_id"], candidate_delta_count=1,
            candidate_identities=[{"identity": f"asset:{candidate['asset_id']}"}],
            foreign_candidate_identities=[], stable_polls=3,
        )

    @staticmethod
    def _image_bytes(*, reverse=False):
        image = Image.new("L", (9, 8))
        for x in range(9):
            for y in range(8):
                image.putpixel((x, y), 255 if (x >= 4) ^ reverse else 0)
        buffer = BytesIO(); image.save(buffer, "PNG")
        return buffer.getvalue()

    def test_candidate_observation_precedes_reference_echo_exclusion_without_confirmation(self):
        generator = LiveFlowGenerator(None, timeout_seconds=0)
        with tempfile.TemporaryDirectory() as root:
            generator._reset_poll_evidence(Path(root) / "fixture-polls.json")
            generator.last_settings = {}
            candidate = {"card_id": "card-exact", "asset_id": "asset-exact", "media_type": "IMAGE", "state": "READY"}
            observation = self._candidate_observation(candidate)
            persisted = generator._persist_candidate_observation_before_acquisition(
                phase="POST_DISPATCH", media_type="IMAGE", baseline=[], current=[candidate],
                surface={"global_pending_count": 0}, observation=observation,
                dispatch=DispatchEvidenceTracker(), activation={"input_dispatched": True},
            )
            settings = generator.last_settings
            self.assertEqual((settings["candidate_observation_state"], settings["candidate_acquisition_state"],
                              settings["attribution_state"], settings["durable_candidate_identity"]["identity"]),
                             ("DURABLE_OBSERVED", "PENDING", "PENDING", "asset:asset-exact"))
            self.assertEqual(persisted["poll_sequence"], settings["candidate_observed_poll_sequence"])
            self.assertIsNone(settings["provider_poll_authoritative_binding"])

    def test_reference_echo_is_quarantined_without_authoritative_confirmation(self):
        generator = LiveFlowGenerator(None, timeout_seconds=0)
        with tempfile.TemporaryDirectory() as root:
            generator._reset_poll_evidence(Path(root) / "fixture-polls.json")
            generator.last_settings = {}
            candidate = {"card_id": "card-echo", "asset_id": "asset-echo", "media_type": "IMAGE", "state": "READY"}
            observation = self._candidate_observation(candidate)
            dispatch = DispatchEvidenceTracker()
            generator._persist_candidate_observation_before_acquisition(
                phase="POST_DISPATCH", media_type="IMAGE", baseline=[], current=[candidate],
                surface={"global_pending_count": 0}, observation=observation,
                dispatch=dispatch, activation={"input_dispatched": True},
            )
            echo_bytes = self._image_bytes()
            self.assertTrue(generator._is_reference_input_echo(echo_bytes, [_dhash_bytes(echo_bytes)]))
            quarantined = generator._quarantine_reference_echo_candidate(
                phase="POST_DISPATCH", media_type="IMAGE", baseline=[], current=[candidate],
                surface={"global_pending_count": 0}, observation=observation,
                dispatch=dispatch, activation={"input_dispatched": True},
            )
            settings = generator.last_settings
            self.assertEqual(quarantined[0]["reason"], "REFERENCE_INPUT_ECHO")
            self.assertEqual((settings["candidate_observation_state"], settings["attribution_state"]),
                             ("QUARANTINED_REFERENCE_INPUT_ECHO", "PENDING"))
            self.assertIsNone(settings["provider_poll_authoritative_binding"])
            self.assertNotIn("attributed_provider_identity", settings)

    def test_candidate_observation_acquisition_failure_blocks_generate_without_false_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            entry = manifest["requests"][0]
            entry.update({"status": "PENDING", "failure_class": None, "attempts": []})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)

            generator = LiveFlowGenerator(None, timeout_seconds=0)
            generator._reset_poll_evidence(paths.artifact_path("output/fixture-polls.json"))
            generator.last_settings = {}
            candidate = {"card_id": "card-exact", "asset_id": "asset-exact", "media_type": "IMAGE", "state": "READY"}
            observation = self._candidate_observation(candidate)
            generator._persist_candidate_observation_before_acquisition(
                phase="POST_DISPATCH", media_type="IMAGE", baseline=[], current=[candidate],
                surface={"global_pending_count": 0}, observation=observation,
                dispatch=DispatchEvidenceTracker(), activation={"input_dispatched": True,
                                                                "activation_verified": True,
                                                                "provider_acceptance_transition": True},
            )
            settings = generator.last_settings
            self.assertEqual((settings["dispatch_confirmation_state"], settings["attribution_state"],
                              settings["durable_candidate_identity"]["identity"]),
                             ("CONFIRMED", "PENDING", "asset:asset-exact"))
            self.assertIsNone(settings["provider_poll_authoritative_binding"])

            class AcquisitionFails:
                dispatch_confirmed = True
                last_settings = settings
                def __call__(self, *_):
                    raise FlowError("ASSET_ACQUISITION_FAILED")

            first = execute_generation(
                runtime.root, config.project_id,
                executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), AcquisitionFails()),
                execute=True, request_ids={self.OLD_ID}, max_requests=1,
            )
            entry = self._entry(paths, self.OLD_ID)
            attempt = entry["attempts"][-1]
            self.assertEqual((first["blocked"], entry["status"], attempt["dispatch_confirmation_state"],
                              attempt["attribution_state"], attempt["durable_candidate_identity"]["identity"]),
                             (True, "FAILED_RETRYABLE", "CONFIRMED", "PENDING", "asset:asset-exact"))
            self.assertNotIn("selected_asset", entry)
            calls = []
            second = execute_generation(
                runtime.root, config.project_id,
                executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True),
                                      lambda *_: calls.append("provider")),
                execute=True, request_ids={self.OLD_ID}, max_requests=1,
            )
            self.assertEqual((second["blocked"], calls), (True, []))

    def test_non_echo_candidate_confirms_only_after_exclusion(self):
        generator = LiveFlowGenerator(None, timeout_seconds=0)
        with tempfile.TemporaryDirectory() as root:
            generator._reset_poll_evidence(Path(root) / "fixture-polls.json")
            generator.last_settings = {}
            candidate = {"card_id": "card-valid", "asset_id": "asset-valid", "media_type": "IMAGE", "state": "READY"}
            observation = self._candidate_observation(candidate)
            dispatch = DispatchEvidenceTracker()
            persisted = generator._persist_candidate_observation_before_acquisition(
                phase="POST_DISPATCH", media_type="IMAGE", baseline=[], current=[candidate],
                surface={"global_pending_count": 0}, observation=observation,
                dispatch=dispatch, activation={"input_dispatched": True,
                                               "activation_verified": True,
                                               "provider_acceptance_transition": True},
            )
            self.assertFalse(generator._is_reference_input_echo(
                self._image_bytes(reverse=True),
                [_dhash_bytes(self._image_bytes())],
            ))
            generator._confirm_candidate_attribution_after_required_exclusions(
                persisted=persisted, observation=observation, dispatch=dispatch,
            )
            settings = generator.last_settings
            self.assertEqual((settings["candidate_acquisition_state"], settings["attribution_state"],
                              settings["attributed_provider_identity"]["identity"]),
                             ("RESOLVED", "CONFIRMED", "asset:asset-valid"))
            self.assertTrue(settings["provider_poll_authoritative_binding"])
            runtime, config, paths = self._project(root)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            entry = manifest["requests"][0]
            entry.update({"status": "PENDING", "failure_class": None, "attempts": [],
                          "reference_asset_hashes": [_dhash_bytes(self._image_bytes())]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)

            class ValidExcludedCandidate:
                dispatch_confirmed = True
                last_settings = settings
                def __call__(self, _request, _references, destination):
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (1280, 720), "navy").save(destination, "PNG")
                    return destination

            result = execute_generation(
                runtime.root, config.project_id,
                executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), ValidExcludedCandidate()),
                execute=True, request_ids={self.OLD_ID}, max_requests=1,
            )
            entry = self._entry(paths, self.OLD_ID)
            self.assertEqual((result["new_submissions"], entry["attempts"][-1]["attribution_state"]), (1, "CONFIRMED"))
            self.assertIn("selected_asset", entry)


if __name__ == "__main__":
    unittest.main()

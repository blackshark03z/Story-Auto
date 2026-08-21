"""Goal33 offline regression fixtures for Flow dispatch causal binding."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image
from story_auto.core.artifacts import atomic_write_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.attribution import RequestAttributionTracker
from story_auto.providers.flow.live import DispatchEvidenceTracker, LiveFlowGenerator
from story_auto.providers.flow.service import (
    FlowExecutor,
    _provider_generation_retry_authorized,
    canonical_no_dispatch_proof,
    execute_generation,
    replay_unresolved_request,
)
from story_auto.providers.flow.session import FlowCapabilities


OLD_REQUEST_ID = "req_1757ad26a03ff73774b1"
EXISTING_REPLAY_CHILD_ID = "req_4b8dba2869afe1e12a52"


class Goal33DispatchCausalBindingTests(unittest.TestCase):
    def _record_stable_card(self, generator, dispatch, activation):
        baseline = [{"card_id": "old-card", "asset_id": "old-asset", "media_type": "IMAGE", "state": "READY"}]
        late_card = baseline + [{"card_id": "late-card", "asset_id": "late-asset", "media_type": "IMAGE", "state": "READY"}]
        tracker = RequestAttributionTracker(baseline, media_type="IMAGE", expected_count=1)
        for _ in range(3):
            observation = tracker.observe(late_card)
            generator._record_poll(
                phase="POST_DISPATCH", media_type="IMAGE", baseline=baseline,
                current=late_card, surface={"records": late_card, "global_pending_count": 0},
                stable_polls=observation.stable_polls, observation=observation,
                dispatch=dispatch, activation=activation,
            )
        return observation

    def test_req_1757_unverified_activation_plus_delayed_card_is_uncertain_and_retry_denied(self):
        """The Goal32 forensic shape cannot become request acceptance proof."""
        with tempfile.TemporaryDirectory() as root:
            generator = LiveFlowGenerator(None, timeout_seconds=0)
            generator._reset_poll_evidence(Path(root) / "polls.json")
            activation = {
                "input_dispatched": True,
                "trusted_click_seen": False,
                "activation_verified": False,
            }
            dispatch = DispatchEvidenceTracker()
            dispatch.observe(input_dispatched=True, trusted_click_seen=False)
            observation = self._record_stable_card(generator, dispatch, activation)

            self.assertEqual(observation.state, "CONFIRMED")  # surface delta only
            self.assertEqual(dispatch.state, "UNCERTAIN")
            self.assertEqual(dispatch.signal, "unverified_activation_provider_surface_activity")
            self.assertEqual(generator.last_settings["provider_poll_decision_bindings"], [])
            self.assertEqual(generator.last_settings["provider_poll_timeline"][-1]["identity_delta"][0]["identity"], "asset:late-asset")

            attempt = {
                "attempt": 1,
                "failure_class": "FLOW_DISPATCH_UNCERTAIN",
                "dispatch_confirmed": False,
                "provider_settings": {"activation": activation},
            }
            self.assertFalse(canonical_no_dispatch_proof(attempt))
            self.assertFalse(_provider_generation_retry_authorized({"attempts": [attempt]}))

    def test_verified_activation_compound_provider_ui_ack_confirms_before_attribution(self):
        with tempfile.TemporaryDirectory() as root:
            generator = LiveFlowGenerator(None, timeout_seconds=0)
            generator._reset_poll_evidence(Path(root) / "polls.json")
            dispatch = DispatchEvidenceTracker()
            dispatch.observe(input_dispatched=True, trusted_click_seen=True, activation_verified=True)
            pending = [{"card_id": "pending-card", "asset_id": None, "media_type": "IMAGE", "state": "PENDING"}]
            observation = RequestAttributionTracker([], media_type="IMAGE", expected_count=1).observe(pending)
            generator._record_poll(
                phase="POST_DISPATCH", media_type="IMAGE", baseline=[], current=pending,
                surface={"records": pending, "global_pending_count": 1}, stable_polls=0,
                observation=observation, dispatch=dispatch,
                activation={"input_dispatched": True, "activation_verified": True,
                            "provider_acceptance_transition": True},
            )

            self.assertEqual(dispatch.state, "CONFIRMED")
            self.assertEqual(dispatch.signal, "verified_activation_provider_ui_job")
            self.assertEqual(observation.state, "WAITING")
            self.assertNotIn("attributed_provider_identity", generator.last_settings)

    def test_direct_provider_ack_confirms_without_final_output(self):
        dispatch = DispatchEvidenceTracker()
        self.assertEqual(
            dispatch.observe(
                input_dispatched=True, provider_job_id="flow-job-request-bound-1",
                durable_evidence_serialized=True, evidence_poll_sequence=1,
            ),
            "CONFIRMED",
        )
        self.assertEqual(dispatch.signal, "provider_job_id")

    def test_negative_dispatch_matrix_never_confirms(self):
        cases = {
            "click_return_only": {"input_dispatched": True},
            "trusted_click_only": {"input_dispatched": True, "trusted_click_seen": True},
            "prompt_transition_only": {"input_dispatched": True, "prompt_transition": True},
            "unrelated_dom": {"input_dispatched": True, "unrelated_dom_mutation": True},
            "card_without_verified_activation": {"input_dispatched": True, "attributable_output": True, "durable_evidence_serialized": True},
            "asset_without_verified_activation": {"input_dispatched": True, "attributable_job": True, "durable_job_identity": "card:late", "durable_evidence_serialized": True},
            "delayed_foreign_card": {"input_dispatched": True, "attributable_output": True, "durable_evidence_serialized": True},
            "old_pending_ready": {"input_dispatched": True, "attributable_output": True, "durable_evidence_serialized": True},
            "baseline_instability": {"input_dispatched": True, "attributable_output": True, "durable_evidence_serialized": True},
            "competing_cards": {"input_dispatched": True, "attributable_output": True, "durable_evidence_serialized": True},
            "stale_coordinates": {"input_dispatched": True},
            "target_changed": {"input_dispatched": False},
        }
        for name, values in cases.items():
            with self.subTest(name=name):
                self.assertNotEqual(DispatchEvidenceTracker().observe(**values), "CONFIRMED")

    def test_existing_replay_child_fixture_preserves_old_barrier_and_new_epoch_shape(self):
        """Offline compatibility contract for the existing Goal32 replay child."""
        old_attempt = {
            "attempt": 1,
            "failure_class": "FLOW_DISPATCH_UNCERTAIN",
            "dispatch_confirmed": False,
            "provider_settings": {"activation": {"input_dispatched": True, "trusted_click_seen": False}},
        }
        replay_child = {
            "request_id": EXISTING_REPLAY_CHILD_ID,
            "replays_unresolved_request_id": OLD_REQUEST_ID,
            "attempts": [],
            "provider_submissions": 0,
            "selected_asset": None,
        }
        self.assertFalse(canonical_no_dispatch_proof(old_attempt))
        self.assertFalse(_provider_generation_retry_authorized({"attempts": [old_attempt]}))
        self.assertEqual(replay_child["replays_unresolved_request_id"], OLD_REQUEST_ID)
        self.assertEqual((replay_child["attempts"], replay_child["provider_submissions"], replay_child["selected_asset"]), ([], 0, None))
        self.assertTrue(_provider_generation_retry_authorized(replay_child))

        # Exercise the same canonical replay transaction entirely under a
        # temporary runtime.  The fake boundary proves that only the new epoch
        # is runnable; no browser or real provider is involved.
        with tempfile.TemporaryDirectory() as root:
            runtime = RuntimeLayout.from_root(root)
            config = ProjectConfig("prj_goal33_replay_fixture")
            paths = create_project(runtime, config)
            atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {"status": "APPROVED"}})
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"schema_version": "story-auto-generation-requests/1.0.0", "project_id": config.project_id, "requests": [{
                "request_id": OLD_REQUEST_ID, "fingerprint": "goal33-old", "purpose": "REFERENCE",
                "entity_id": "subject", "media_type": "IMAGE", "provider": "google_flow",
                "prompt": "subject reference", "output_count": 1, "depends_on": [], "reference_asset_ids": [],
            }]})
            atomic_write_json(paths.artifact_path("output/media_plan.json"), {"shots": []})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"schema_version": "story-auto-generation-manifest/1.0.0", "project_id": config.project_id, "requests": [{
                "request_id": OLD_REQUEST_ID, "request_identity_sha256": "goal33-old",
                "related_identity": "subject", "media_type": "IMAGE", "provider": "google_flow",
                "prompt_sha256": "goal33-old", "reference_asset_hashes": [],
                "attempts": [{"attempt": 1, "status": "AMBIGUOUS",
                              "failure_class": "FLOW_DISPATCH_UNCERTAIN", "dispatch_confirmed": False,
                              "dispatch_confirmation_state": "UNCERTAIN", "attribution_state": "UNCERTAIN"}],
                "status": "AMBIGUOUS", "failure_class": "FLOW_DISPATCH_UNCERTAIN",
            }]})
            result = replay_unresolved_request(
                runtime.root, config.project_id, OLD_REQUEST_ID,
                reason="Provider ownership remains irreducible; create one acknowledged fresh epoch.",
                acknowledge_previous_dispatch_or_cost_may_have_occurred=True,
                acknowledge_previous_output_ownership_unresolved=True,
                acknowledge_replacement_may_consume_provider_credit=True,
            )
            fake_boundary_calls = []

            def fake_provider(request, _references, destination):
                fake_boundary_calls.append(request["request_id"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (1280, 720), "navy").save(destination, "PNG")
                return destination

            outcome = execute_generation(
                runtime.root, config.project_id,
                executor=FlowExecutor(
                    FlowCapabilities(True, True, True, True, True, True),
                    fake_provider,
                ),
                execute=True, request_ids={result["replacement_request_id"]}, max_requests=1,
            )
            self.assertEqual((outcome["new_submissions"], fake_boundary_calls), (1, [result["replacement_request_id"]]))

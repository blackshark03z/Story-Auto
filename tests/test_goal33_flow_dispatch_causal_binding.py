"""Goal33 offline regression fixtures for Flow dispatch causal binding."""
from __future__ import annotations

import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest import mock

from PIL import Image
from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.attribution import RequestAttributionTracker
from story_auto.providers.flow.live import DispatchEvidenceTracker, LiveFlowGenerator
from story_auto.providers.flow.service import (
    FlowExecutor,
    _abandoned_unresolved_entry_valid,
    _first_invalid_request_replacement,
    _json_sha256,
    _provider_generation_retry_authorized,
    _replay_genesis_projection,
    _resolve_current_canonical_descendant,
    canonical_no_dispatch_proof,
    execute_generation,
    replay_unresolved_request,
)
from story_auto.providers.flow.session import FlowCapabilities


OLD_REQUEST_ID = "req_1757ad26a03ff73774b1"
EXISTING_REPLAY_CHILD_ID = "req_4b8dba2869afe1e12a52"
QC_PARENT_ID = "req_08ec2e4e057f013e4aec"
PROJECT_ID = "prj_goal33_exact_runtime_projection"

# Sanitized, canonical projection of the read-only Trial A records named above.
# Provider URLs, cookies, generated assets, and raw poll evidence are excluded.
# The replay validator consumes the recorded attempts digest, not those raw
# provider-surface payloads; that immutable digest is retained below.
RUNTIME_PROJECTION = {
    "schema": "story-auto-goal33-exact-runtime-projection/1.0.0",
    "parent": {
        "request_id": OLD_REQUEST_ID,
        "status_before_replay": "AMBIGUOUS",
        "failure_class_before_replay": "OUTPUT_ATTRIBUTION_UNCERTAIN",
        "dispatch_confirmed": True,
        "dispatch_confirmation_state": "CONFIRMED",
        "attribution_state": "UNCERTAIN",
        "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED",
        "selected_asset": None,
        "attempts_sha256": "af816ea94c4c07a418b179b393ec84eb41ca29c0f9b1fb4c51055c46a750a9b8",
        "historical_provider_dispatch": "CONFIRMED",
        "historical_attribution": "UNRESOLVED",
        "same_request_retry": "DENY",
    },
    "existing_replay": {
        "transaction_id": "unresolved-replay-3d30afcf53ba8e12b174e86a",
        "genesis_sha256": "578d66dcc27af014e7932cf2509268f0c3583914b8edfa01db3b240a978bf711",
        "old_request_id": OLD_REQUEST_ID,
        "replacement_request_id": EXISTING_REPLAY_CHILD_ID,
        "replay_epoch": 3,
    },
    "child": {
        "request_id": EXISTING_REPLAY_CHILD_ID,
        "replays_unresolved_request_id": OLD_REQUEST_ID,
        "request_identity_sha256": "4b8dba2869afe1e12a525995bc1b577ea0a8aa89250cca75cb0b307fc0c65db6",
        "prompt_sha256": "2aca56945cfacaaaf814f9f9c5cbc8650d5ca025687e82a8dbb52d07a0b24f69",
        "related_identity": "sh_0003",
        "media_type": "IMAGE",
        "provider": "google_flow",
        "replay_epoch": 3,
        "attempts": 0,
        "provider_submissions": 0,
        "selected_asset": None,
        "status": "PENDING",
    },
}
RUNTIME_PROJECTION_SHA256 = "65fc2e7fb7174b8b3c8caa1490a193c96d786d41029e78c6447d55e2d277bbc8"

EXACT_PROMPT = (
    "Visual anchor: Scipio Africanus in the concrete environment of the decisive accomplishment, "
    "a decisive accomplishment changes the balance of power. Dominant subject: Scipio Africanus. "
    "Dominant state: a decisive accomplishment changes the balance of power. Environment: the concrete "
    "environment of the decisive accomplishment. Composition: clear subject hierarchy with clean, uncluttered "
    "visual breathing room. Continuity: Appears young during initial command in Spain; Appears as a victorious "
    "general in Roman toga or commander armor. Keep key details out of the bottom-right provider-mark safe area. "
    "Ambient style: Cool-neutral restrained natural realism in a serious institutional environment; clear character "
    "hierarchy, restrained contrast, and meaningful negative space; no glossy or HDR treatment. Natural soft "
    "realism; practical light, restrained color, natural skin and materials. No overlay subtitles/captions, lower "
    "thirds, title cards, placeholders, or UI. Avoid retouching, wax, CGI, HDR, heavy bokeh, stylization, pristine "
    "surfaces, and symmetry."
)
DEPENDENCIES = [
    "req_34a9ff26b9992fe4ef10",
    "req_3591b82710f9c1c59acf",
    "req_b985b298a712b11d3272",
    "req_66afa3ecef677ad8acb0",
]
REFERENCE_IDS = [
    "char_scipio_africanus", "char_hannibal_barca", "char_masinissa", "char_lucius_scipio",
]


def _target(path: str, value: dict) -> dict:
    return {"path": path, "value": value, "sha256": _json_sha256(value)}


def _write_committed_transaction(paths, directory: str, transaction: dict) -> None:
    transaction_id = transaction["transaction_id"]
    atomic_write_json(paths.artifact_path(f"output/{directory}/{transaction_id}.prepared.json"), transaction)
    atomic_write_json(paths.artifact_path(f"output/{directory}/{transaction_id}.committed.json"), {
        "schema_version": transaction["schema_version"], "state": "COMMITTED",
        "transaction_id": transaction_id, "prepared_sha256": _json_sha256(transaction),
    })


class Goal33DispatchCausalBindingTests(unittest.TestCase):
    def _exact_existing_replay_runtime(self, root: str):
        """Build a minimal, self-contained projection of the real replay pair.

        It deliberately *does not* call replay_unresolved_request: both the
        receipt-backed QC edge and the receipt-backed unresolved-replay edge
        exist before any validator is asked to inspect them.
        """
        runtime = RuntimeLayout.from_root(root)
        config = ProjectConfig(PROJECT_ID)
        paths = create_project(runtime, config)
        parent_request = {
            "request_id": OLD_REQUEST_ID,
            "fingerprint": "1757ad26a03ff73774b1ebe56a9498ce2e32c8b8e2fea05199f97d8a1b4293f2",
            "prompt": EXACT_PROMPT, "purpose": "SHOT", "shot_id": "sh_0003",
            "media_type": "IMAGE", "provider": "google_flow", "output_count": 1,
            "execution_tier": "STANDARD_PRODUCTION", "depends_on": list(DEPENDENCIES),
            "reference_asset_ids": list(REFERENCE_IDS), "replacement_of": QC_PARENT_ID,
            "replacement_reason": "QC_REJECTED_ASSET_REPLACEMENT", "replacement_epoch": 2,
            "epoch_nonce": "8a9057d15c1b440da3d253d81951630b",
            "prompt_construction": {
                "version": "story-auto-caption-safe-prompt/1.0.0",
                "source": "CURRENT_AMBIENT_PROMPT_CONSTRUCTION",
                "historical_prompt_sha256": "2511d9cf97830ea888e622c8f0dc48c9ec6c2169e9fc1b7ac11560417e4536ad",
                "effective_prompt_sha256": "2aca56945cfacaaaf814f9f9c5cbc8650d5ca025687e82a8dbb52d07a0b24f69",
            },
        }
        child_request = {
            **parent_request,
            "request_id": EXISTING_REPLAY_CHILD_ID,
            "fingerprint": RUNTIME_PROJECTION["child"]["request_identity_sha256"],
            "replays_unresolved_request_id": OLD_REQUEST_ID,
            "replay_epoch": 3,
            "epoch_nonce": "9ea9e80154c34af98a5634bf7e385cea",
        }
        historical_attempt = {
            "attempt": 1, "status": "AMBIGUOUS",
            "failure_class": "OUTPUT_ATTRIBUTION_UNCERTAIN",
            "dispatch_confirmed": True, "dispatch_confirmation_state": "CONFIRMED",
            "attribution_state": "UNCERTAIN",
            "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED",
        }
        replay_event = {
            "event": "ABANDONED_UNRESOLVED",
            "operator_reason": "Goal32 authorized one canonical unresolved replay after confirmed dispatch and unresolved attribution",
            "old_request_id": OLD_REQUEST_ID,
            "replacement_request_id": EXISTING_REPLAY_CHILD_ID,
            "historical_provider_dispatch": "CONFIRMED",
            "historical_attribution": "UNRESOLVED",
            "attempts_sha256": _json_sha256([historical_attempt]),
            "previous_dispatch_or_cost_may_have_occurred_acknowledged": True,
            "previous_output_ownership_unresolved_acknowledged": True,
            "replacement_may_consume_provider_credit_acknowledged": True,
        }
        replay_transaction_id = RUNTIME_PROJECTION["existing_replay"]["transaction_id"]
        replay_event["replay_genesis"] = _replay_genesis_projection(
            replacement=child_request, queue_position=len(DEPENDENCIES), event=replay_event,
            transaction_id=replay_transaction_id,
        )
        self.assertIsNotNone(replay_event["replay_genesis"])
        replay_event["replay_genesis_sha256"] = _json_sha256(replay_event["replay_genesis"])
        parent_entry = {
            "request_id": OLD_REQUEST_ID,
            "request_identity_sha256": parent_request["fingerprint"], "related_identity": "sh_0003",
            "media_type": "IMAGE", "provider": "google_flow",
            "prompt_sha256": sha256(EXACT_PROMPT.encode("utf-8")).hexdigest(),
            "reference_asset_hashes": [], "attempts": [historical_attempt],
            "status": "ABANDONED_UNRESOLVED", "failure_class": "UNRESOLVED_REPLAY_CREATED",
            "selected_asset": None, "attribution_claim": "NONE",
            "historical_provider_dispatch": "CONFIRMED", "historical_attribution": "UNRESOLVED",
            "replacement_request_id": EXISTING_REPLAY_CHILD_ID,
            "replacement_of": QC_PARENT_ID, "replacement_reason": "QC_REJECTED_ASSET_REPLACEMENT",
            "unresolved_replay_events": [replay_event],
        }
        child_entry = {
            "request_id": EXISTING_REPLAY_CHILD_ID,
            "request_identity_sha256": child_request["fingerprint"], "related_identity": "sh_0003",
            "media_type": "IMAGE", "provider": "google_flow",
            "prompt_sha256": sha256(EXACT_PROMPT.encode("utf-8")).hexdigest(),
            "reference_asset_hashes": [], "attempts": [], "status": "PENDING",
            "replays_unresolved_request_id": OLD_REQUEST_ID, "replay_epoch": 3,
            "epoch_nonce": child_request["epoch_nonce"],
            "replay_creation_transaction_id": replay_transaction_id,
            "replay_genesis_sha256": replay_event["replay_genesis_sha256"],
        }
        dependency_requests = []
        dependency_entries = []
        for number, request_id in enumerate(DEPENDENCIES, start=1):
            relative_asset = f"assets/image/{request_id}.png"
            asset_path = paths.artifact_path(relative_asset)
            asset_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1280, 720), (number * 20, 30, 40)).save(asset_path, "PNG")
            dependency_requests.append({
                "request_id": request_id, "fingerprint": f"dependency-{number}", "purpose": "REFERENCE",
                "entity_id": REFERENCE_IDS[number - 1], "media_type": "IMAGE", "provider": "google_flow",
                "prompt": f"dependency {number}", "output_count": 1, "depends_on": [], "reference_asset_ids": [],
            })
            dependency_entries.append({
                "request_id": request_id, "request_identity_sha256": f"dependency-{number}",
                "related_identity": REFERENCE_IDS[number - 1], "media_type": "IMAGE", "provider": "google_flow",
                "prompt_sha256": sha256(f"dependency {number}".encode("utf-8")).hexdigest(),
                "reference_asset_hashes": [], "attempts": [], "status": "SUCCEEDED",
                "selected_asset": {"path": relative_asset, "sha256": sha256(asset_path.read_bytes()).hexdigest(), "attempt": 1},
            })
        requests_value = {
            "schema_version": "story-auto-generation-requests/1.0.0", "project_id": config.project_id,
            "requests": dependency_requests + [child_request],
        }
        manifest_value = {
            "schema_version": "story-auto-generation-manifest/1.0.0", "project_id": config.project_id,
            "requests": dependency_entries + [parent_entry, child_entry],
        }
        atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {"status": "APPROVED"}})
        atomic_write_json(paths.artifact_path("output/media_plan.json"), {"shots": [{"shot_id": "sh_0003", "selected_request_id": EXISTING_REPLAY_CHILD_ID}]})
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), requests_value)
        atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest_value)
        replay_transaction = {
            "schema_version": "story-auto-unresolved-replay-transaction/1.0.0", "state": "PREPARED",
            "transaction_id": replay_transaction_id, "project_id": config.project_id,
            "old_request_id": OLD_REQUEST_ID, "replacement_request_id": EXISTING_REPLAY_CHILD_ID,
            "replay_genesis_sha256": replay_event["replay_genesis_sha256"],
            "targets": {
                "generation_requests": _target("output/generation_requests.json", requests_value),
                "generation_manifest": _target("output/generation_manifest.json", manifest_value),
            },
        }
        _write_committed_transaction(paths, "unresolved_replay_transactions", replay_transaction)
        qc_event = {
            "event": "QC_REJECTED_ASSET_REPLACEMENT", "old_request_id": QC_PARENT_ID,
            "replacement_request_id": OLD_REQUEST_ID,
        }
        qc_transaction = {
            "schema_version": "story-auto-qc-rejected-asset-replacement-transaction/1.0.0", "state": "PREPARED",
            "transaction_id": "qc-rejected-asset-replacement-318f4a8e7edf5f9f6cd56b50",
            "project_id": config.project_id, "old_request_id": QC_PARENT_ID,
            "replacement_request_id": OLD_REQUEST_ID,
            "targets": {
                "generation_requests": _target("output/generation_requests.json", {
                    "requests": [parent_request],
                }),
                "generation_manifest": _target("output/generation_manifest.json", {
                    "requests": [{"request_id": QC_PARENT_ID, "qc_replacement_events": [qc_event]}],
                }),
            },
        }
        _write_committed_transaction(paths, "qc_rejected_asset_replacement_transactions", qc_transaction)
        return runtime, config, paths

    @staticmethod
    def _exact_state(paths):
        requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
        entries = {
            item["request_id"]: item
            for item in read_json(paths.artifact_path("output/generation_manifest.json"))["requests"]
        }
        return requests, entries

    def _assert_parent_never_runnable(self, paths, config):
        _requests, entries = self._exact_state(paths)
        self.assertFalse(_provider_generation_retry_authorized(entries[OLD_REQUEST_ID]))

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

    def test_exact_existing_runtime_replay_is_valid_without_creating_a_replay(self):
        """The real parent shape is confirmed-dispatch, not Goal33's old surrogate."""
        self.assertEqual(_json_sha256(RUNTIME_PROJECTION), RUNTIME_PROJECTION_SHA256)
        with tempfile.TemporaryDirectory() as root, mock.patch(
            "story_auto.providers.flow.service.replay_unresolved_request",
            side_effect=AssertionError("primary compatibility validation must not create a replay"),
        ):
            runtime, config, paths = self._exact_existing_replay_runtime(root)
            requests, entries = self._exact_state(paths)
            parent = entries[OLD_REQUEST_ID]
            child = entries[EXISTING_REPLAY_CHILD_ID]

            self.assertTrue(_abandoned_unresolved_entry_valid(paths, config.project_id, parent, requests, entries))
            self.assertEqual(
                _resolve_current_canonical_descendant(paths, config.project_id, OLD_REQUEST_ID, requests, entries),
                EXISTING_REPLAY_CHILD_ID,
            )
            self.assertTrue(parent["attempts"][-1]["dispatch_confirmed"])
            self.assertEqual(parent["attempts"][-1]["failure_class"], "OUTPUT_ATTRIBUTION_UNCERTAIN")
            self.assertFalse(_provider_generation_retry_authorized(parent))
            self.assertEqual((child["attempts"], child.get("provider_submissions", 0), child.get("selected_asset")), ([], 0, None))
            self.assertTrue(_provider_generation_retry_authorized(child))

            fake_boundary_calls = []

            def fake_provider(request, _references, destination):
                fake_boundary_calls.append(request["request_id"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                image = Image.new("RGB", (1280, 720), "navy")
                image.paste("white", (0, 0, 640, 360))
                image.save(destination, "PNG")
                return destination

            outcome = execute_generation(
                runtime.root, config.project_id,
                executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), fake_provider),
                execute=True, request_ids={EXISTING_REPLAY_CHILD_ID}, max_requests=1,
            )
            self.assertEqual((outcome["blocked"], outcome["new_submissions"], fake_boundary_calls),
                             (False, 1, [EXISTING_REPLAY_CHILD_ID]))

    def test_exact_existing_runtime_replay_negative_matrix_fails_closed(self):
        def missing_transaction(paths, _requests, _entries):
            paths.artifact_path(
                "output/unresolved_replay_transactions/unresolved-replay-3d30afcf53ba8e12b174e86a.committed.json"
            ).unlink()

        def altered_child_id(_paths, requests, _entries):
            next(item for item in requests if item["request_id"] == EXISTING_REPLAY_CHILD_ID)["request_id"] = "req_not_the_existing_child"

        def altered_parent_link(_paths, _requests, entries):
            entries[EXISTING_REPLAY_CHILD_ID]["replays_unresolved_request_id"] = "req_wrong_parent"

        def corrupt_genesis(_paths, _requests, entries):
            entries[OLD_REQUEST_ID]["unresolved_replay_events"][0]["replay_genesis"]["old_request_id"] = "req_corrupt"

        def altered_parent_attempt(_paths, _requests, entries):
            entries[OLD_REQUEST_ID]["attempts"].append({"attempt": 2, "status": "AMBIGUOUS"})

        def competing_child(_paths, requests, entries):
            competing_id = "req_competing_replay_child"
            child_request = next(item for item in requests if item["request_id"] == EXISTING_REPLAY_CHILD_ID)
            child_entry = entries[EXISTING_REPLAY_CHILD_ID]
            requests.append({**child_request, "request_id": competing_id, "fingerprint": "competing-replay-fingerprint"})
            entries[competing_id] = {
                **child_entry, "request_id": competing_id, "request_identity_sha256": "competing-replay-fingerprint",
            }

        def altered_logical_identity(_paths, requests, _entries):
            next(item for item in requests if item["request_id"] == EXISTING_REPLAY_CHILD_ID)["shot_id"] = "sh_wrong"

        def altered_child_state(_paths, _requests, entries):
            entries[EXISTING_REPLAY_CHILD_ID]["attempts"] = [{"attempt": 1, "status": "SUBMITTED"}]

        def lineage_cycle(_paths, _requests, entries):
            entries[EXISTING_REPLAY_CHILD_ID].update({
                "status": "ABANDONED_UNRESOLVED", "replacement_request_id": OLD_REQUEST_ID,
                "unresolved_replay_events": [],
            })

        mutations = {
            "missing_child_transaction": missing_transaction,
            "child_request_id_altered": altered_child_id,
            "replay_parent_link_altered": altered_parent_link,
            "immutable_replay_genesis_corrupted": corrupt_genesis,
            "parent_historical_attempt_mutated": altered_parent_attempt,
            "child_logical_visual_identity_changed": altered_logical_identity,
            "child_pristine_state_changed": altered_child_state,
            "lineage_cycle_introduced": lineage_cycle,
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                _runtime, config, paths = self._exact_existing_replay_runtime(root)
                requests, entries = self._exact_state(paths)
                mutate(paths, requests, entries)
                atomic_write_json(paths.artifact_path("output/generation_requests.json"), {
                    "schema_version": "story-auto-generation-requests/1.0.0", "project_id": config.project_id,
                    "requests": requests,
                })
                atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
                    "schema_version": "story-auto-generation-manifest/1.0.0", "project_id": config.project_id,
                    "requests": list(entries.values()),
                })
                current_requests, current_entries = self._exact_state(paths)
                self.assertFalse(_abandoned_unresolved_entry_valid(
                    paths, config.project_id, current_entries[OLD_REQUEST_ID], current_requests, current_entries,
                ))
                self.assertIsNone(_resolve_current_canonical_descendant(
                    paths, config.project_id, OLD_REQUEST_ID, current_requests, current_entries,
                ))
                self._assert_parent_never_runnable(paths, config)

        # A second live child with no receipt-backed genesis is itself a queue
        # barrier.  It cannot make the historic parent provider-runnable or
        # permit the existing child to bypass replacement-lineage validation.
        with tempfile.TemporaryDirectory() as root:
            _runtime, config, paths = self._exact_existing_replay_runtime(root)
            requests, entries = self._exact_state(paths)
            competing_child(paths, requests, entries)
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), {
                "schema_version": "story-auto-generation-requests/1.0.0", "project_id": config.project_id,
                "requests": requests,
            })
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
                "schema_version": "story-auto-generation-manifest/1.0.0", "project_id": config.project_id,
                "requests": list(entries.values()),
            })
            current_requests, current_entries = self._exact_state(paths)
            invalid = _first_invalid_request_replacement(paths, config.project_id, current_entries, current_requests)
            self.assertIsNotNone(invalid)
            self.assertEqual(invalid[0]["request_id"], "req_competing_replay_child")
            self._assert_parent_never_runnable(paths, config)

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

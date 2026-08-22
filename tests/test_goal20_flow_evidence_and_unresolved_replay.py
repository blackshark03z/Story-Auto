from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.attribution import RequestAttributionTracker
from story_auto.providers.flow.live import (
    DispatchEvidenceTracker,
    LiveFlowGenerator,
    ProviderPollEvidenceTimeline,
    _stable_surface,
    dispatch_timeout_failure,
    _json_sha256,
)
from story_auto.providers.flow.service import (
    ABANDONED_UNRESOLVED_STATUS,
    FlowError,
    FlowExecutor,
    execute_generation,
    replay_unresolved_request,
    _confirm_executor_attribution,
)
from story_auto.providers.flow.session import FlowCapabilities


class Goal20PollEvidenceTests(unittest.TestCase):
    @staticmethod
    def _reseal_bindings(snapshot: dict) -> None:
        for index, binding in enumerate(snapshot["decision_bindings"], start=1):
            binding["binding_sequence"] = index
            binding["previous_binding_sha256"] = (
                snapshot["decision_bindings"][index - 2]["binding_sha256"] if index > 1 else None
            )
            unsigned = dict(binding); unsigned.pop("binding_sha256", None)
            binding["binding_sha256"] = _json_sha256(unsigned)
        snapshot["decision_binding_count"] = len(snapshot["decision_bindings"])
        snapshot["decision_bindings_sha256"] = _json_sha256(snapshot["decision_bindings"])
        snapshot["evidence_head_sha256"] = ProviderPollEvidenceTimeline._head_sha256(snapshot)

    @staticmethod
    def _confirmed_bound_settings() -> dict:
        timeline = ProviderPollEvidenceTimeline(max_observations=8)
        source = timeline.append({
            "phase": "POST_DISPATCH",
            "current_identity_set": [{"identity": "asset:new", "card_id": "new", "asset_id": "new"}],
            "job_card_identities_observed": ["new"],
            "output_asset_identities_observed": ["new"],
            "candidate_identities": [{"identity": "asset:new", "card_id": "new", "asset_id": "new"}],
            "attribution_evidence_state": "CONFIRMED",
            "dispatch_evidence_state": "UNCERTAIN",
            "durable_dispatch_identity": "asset:new",
        })
        binding = timeline.append_decision_binding(
            source, dispatch_state="CONFIRMED", dispatch_signal="new_attributable_output",
            dispatch_signal_state="DISPATCH_CONFIRMED", attribution_state="CONFIRMED",
            durable_identity="asset:new",
        )
        snapshot = timeline.snapshot()
        return {
            "provider_poll_evidence": snapshot,
            "provider_poll_authoritative_binding": binding,
            "dispatch_confirmation_state": "CONFIRMED",
            "dispatch_confirmation_signal": "new_attributable_output",
            "attribution_state": "CONFIRMED",
            "attributed_provider_identity": {"identity": "asset:new"},
        }

    def test_durable_job_then_exact_output_are_bound_and_finalizer_accepts(self):
        generator = LiveFlowGenerator(None, timeout_seconds=0)
        generator._reset_poll_evidence(Path(tempfile.gettempdir()) / "goal20-binding-polls.json")
        baseline = [{"card_id": "old", "asset_id": "old", "media_type": "IMAGE", "state": "READY"}]
        pending = baseline + [{"card_id": "new", "asset_id": None, "media_type": "IMAGE", "state": "PENDING"}]
        dispatch = DispatchEvidenceTracker()
        dispatch.observe(input_dispatched=True, attributable_job=True)
        pending_observation = RequestAttributionTracker(baseline, media_type="IMAGE", expected_count=1).observe(pending)
        raw = generator._record_poll(
            phase="POST_DISPATCH", media_type="IMAGE", baseline=baseline, current=pending,
            surface={"records": pending, "global_pending_count": 1}, stable_polls=0,
            observation=pending_observation, dispatch=dispatch, activation={"input_dispatched": True, "activation_verified": True, "provider_acceptance_transition": True},
        )
        self.assertEqual(raw["dispatch_evidence_state"], "UNCERTAIN")
        first_binding = generator.last_settings["provider_poll_authoritative_binding"]
        self.assertEqual((first_binding["source_poll_sequence"], first_binding["resulting_dispatch_state"]), (1, "CONFIRMED"))
        self.assertEqual(first_binding["source_observation_sha256"], raw["observation_sha256"])

        current = baseline + [{"card_id": "new", "asset_id": "new", "media_type": "IMAGE", "state": "READY"}]
        tracker = RequestAttributionTracker(baseline, media_type="IMAGE", expected_count=1)
        for _ in range(3):
            exact = tracker.observe(current)
            generator._record_poll(
                phase="POST_DISPATCH", media_type="IMAGE", baseline=baseline, current=current,
                surface={"records": current, "global_pending_count": 0}, stable_polls=exact.stable_polls,
                observation=exact, dispatch=dispatch, activation={"input_dispatched": True, "activation_verified": True, "provider_acceptance_transition": True},
            )
        generator._record_observation(exact)
        generator.last_settings["attributed_provider_identity"] = {"identity": "asset:new"}
        self.assertEqual((exact.state, generator.last_settings["dispatch_confirmation_state"],
                          generator.last_settings["attribution_state"]), ("CONFIRMED", "CONFIRMED", "CONFIRMED"))
        _confirm_executor_attribution({"attribution_state": "CONFIRMED"}, type("Generator", (), {"last_settings": generator.last_settings})())

    def test_unbound_authoritative_state_and_binding_corruption_fail_closed(self):
        settings = self._confirmed_bound_settings()
        raw_only = copy.deepcopy(settings)
        raw_only["provider_poll_evidence"]["decision_bindings"] = []
        self._reseal_bindings(raw_only["provider_poll_evidence"])
        with self.assertRaisesRegex(FlowError, "FLOW_POLL_EVIDENCE_INVALID"):
            _confirm_executor_attribution({}, type("Generator", (), {"last_settings": raw_only})())

        for name, mutate in {
            "hash": lambda snapshot: snapshot["decision_bindings"][0].update({"binding_sha256": "0" * 64}),
            "source_sequence": lambda snapshot: snapshot["decision_bindings"][0].update({"source_poll_sequence": 99}),
            "source_hash": lambda snapshot: snapshot["decision_bindings"][0].update({"source_observation_sha256": "0" * 64}),
            "foreign_identity": lambda snapshot: snapshot["decision_bindings"][0].update({"durable_identity_used": "asset:foreign"}),
        }.items():
            with self.subTest(name=name):
                corrupted = copy.deepcopy(settings)
                mutate(corrupted["provider_poll_evidence"])
                if name in {"source_sequence", "source_hash", "foreign_identity"}:
                    self._reseal_bindings(corrupted["provider_poll_evidence"])
                with self.assertRaisesRegex(FlowError, "FLOW_POLL_EVIDENCE_INVALID"):
                    _confirm_executor_attribution({}, type("Generator", (), {"last_settings": corrupted})())

    def test_incomplete_or_transient_evidence_cannot_create_confirmed_binding(self):
        timeline = ProviderPollEvidenceTimeline(max_provider_identities=2)
        with self.assertRaisesRegex(FlowError, "FLOW_POLL_EVIDENCE_LIMIT_EXCEEDED"):
            timeline.append({"current_identity_set": [{"identity": f"asset:{index}"} for index in range(3)]})
        with self.assertRaisesRegex(FlowError, "FLOW_POLL_EVIDENCE_LIMIT_EXCEEDED"):
            timeline.append_decision_binding(
                timeline.observations[0], dispatch_state="CONFIRMED", dispatch_signal="test",
                dispatch_signal_state="DISPATCH_CONFIRMED", attribution_state="CONFIRMED",
                durable_identity="asset:0",
            )

        generator = LiveFlowGenerator(None, timeout_seconds=0)
        generator._reset_poll_evidence(Path(tempfile.gettempdir()) / "goal20-transient-polls.json")
        baseline = [{"card_id": "old", "asset_id": "old", "media_type": "IMAGE", "state": "READY"}]
        dispatch = DispatchEvidenceTracker()
        dispatch.observe(input_dispatched=True, attributable_job=True)
        generator._record_poll(
            phase="POST_DISPATCH", media_type="IMAGE", baseline=baseline, current=baseline,
            surface={"records": baseline, "global_pending_count": 0}, stable_polls=0,
            dispatch=dispatch, activation={"input_dispatched": True},
        )
        self.assertEqual(dispatch.state, "UNCERTAIN")
        self.assertEqual(generator.last_settings["provider_poll_decision_bindings"], [])
    @staticmethod
    def _complete_snapshot() -> dict:
        timeline = ProviderPollEvidenceTimeline(max_observations=8)
        for phase in ("BASELINE", "POST_DISPATCH", "FINAL"):
            timeline.append({"phase": phase, "current_identity_set": [{"identity": f"asset:{phase}"}]})
        timeline.finish("COMPLETE")
        return timeline.snapshot()

    def test_persisted_hash_chain_verifier_rejects_each_required_corruption(self):
        mutations = {
            "modified_payload": lambda value: value["observations"][1].update({"phase": "MUTATED"}),
            "changed_sequence": lambda value: value["observations"][1].update({"poll_sequence": 99}),
            "deleted_middle": lambda value: value["observations"].pop(1),
            "reordered": lambda value: value["observations"].__setitem__(slice(0, 2), [value["observations"][1], value["observations"][0]]),
            "duplicated": lambda value: value["observations"].append(copy.deepcopy(value["observations"][1])),
            "broken_previous_hash": lambda value: value["observations"][2].update({"previous_observation_sha256": "0" * 64}),
            "incorrect_timeline_head": lambda value: value.update({"timeline_sha256": "0" * 64}),
            "incorrect_terminal_head": lambda value: value.update({"terminal_state": "MUTATED"}),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                corrupted = copy.deepcopy(self._complete_snapshot())
                mutate(corrupted)
                with self.assertRaisesRegex(FlowError, "FLOW_POLL_EVIDENCE_INVALID"):
                    ProviderPollEvidenceTimeline.verify_snapshot(corrupted)

    def test_normal_thirty_identity_surface_is_bounded_and_verifiable(self):
        identities = [{"identity": f"asset:{index:03d}"} for index in range(30)]
        timeline = ProviderPollEvidenceTimeline()
        timeline.append({
            "phase": "BASELINE", "baseline_identity_set": identities,
            "current_identity_set": identities, "identity_delta": [],
            "candidate_identities": [], "quarantined_identities": [],
        })
        timeline.finish("COMPLETE")
        verified = ProviderPollEvidenceTimeline.verify_snapshot(timeline.snapshot())
        self.assertTrue(verified["evidence_complete"])

    def test_collection_and_byte_overflow_persist_bounded_incomplete_summary(self):
        cases = {
            "provider": ("current_identity_set", [{"identity": f"asset:{index}"} for index in range(3)],
                         {"max_provider_identities": 2}, 2),
            "candidate": ("candidate_identities", [{"identity": f"asset:{index}"} for index in range(3)],
                          {"max_candidate_identities": 2}, 2),
            "quarantine": ("quarantined_identities", [{"identity": f"asset:{index}"} for index in range(3)],
                           {"max_quarantined_identities": 2}, 2),
            "bytes": ("current_identity_set", [{"identity": "asset:" + ("x" * 240) + str(index)} for index in range(30)],
                      {"max_provider_identities": 64, "max_serialized_bytes": 9000}, 9000),
        }
        for name, (field, values, limits, expected_limit) in cases.items():
            with self.subTest(name=name):
                timeline = ProviderPollEvidenceTimeline(max_observations=8, **limits)
                with self.assertRaisesRegex(FlowError, "FLOW_POLL_EVIDENCE_LIMIT_EXCEEDED"):
                    timeline.append({"phase": "POST_DISPATCH", field: values})
                snapshot = timeline.snapshot()
                self.assertFalse(snapshot["evidence_complete"])
                self.assertEqual(len(snapshot["observations"]), 1)
                summary = snapshot["observations"][0]["overflow"][0]
                self.assertLessEqual(len(snapshot["observations"][0]["overflow"]), 7)
                self.assertEqual(summary["configured_limit"], expected_limit)
                ProviderPollEvidenceTimeline.verify_snapshot(snapshot)

    def test_overflow_cannot_confirm_dispatch_or_attribution(self):
        generator = LiveFlowGenerator(None, timeout_seconds=0)
        generator._poll_timeline = ProviderPollEvidenceTimeline(max_provider_identities=2)
        generator.last_settings = {}
        records = [
            {"card_id": f"card-{index}", "asset_id": f"asset-{index}", "media_type": "IMAGE", "state": "READY"}
            for index in range(3)
        ]
        tracker = RequestAttributionTracker([], media_type="IMAGE", expected_count=1)
        observation = tracker.observe(records)
        dispatch = DispatchEvidenceTracker()
        with self.assertRaisesRegex(FlowError, "FLOW_POLL_EVIDENCE_LIMIT_EXCEEDED"):
            generator._record_poll(
                phase="POST_DISPATCH", media_type="IMAGE", baseline=[], current=records,
                surface={"records": records, "global_pending_count": 0},
                stable_polls=observation.stable_polls, observation=observation,
                dispatch=dispatch, activation={"input_dispatched": True},
            )
        self.assertNotEqual(dispatch.state, "CONFIRMED")
        self.assertFalse(generator._poll_timeline.snapshot()["evidence_complete"])

    def test_reconciliation_rejects_invalid_persisted_evidence_before_browser_access(self):
        corrupted = self._complete_snapshot()
        corrupted["observations"][0]["phase"] = "MUTATED"
        result = LiveFlowGenerator(None).reconcile(
            {"media_type": "IMAGE", "output_count": 1},
            {"provider_settings": {"provider_poll_evidence": corrupted}},
            Path("unused.png"),
        )
        self.assertEqual(result, {"state": "REMAINS_AMBIGUOUS", "evidence": {"reason": "FLOW_POLL_EVIDENCE_INVALID"}})

    def test_reconciliation_rejects_missing_decision_binding_before_browser_access(self):
        result = LiveFlowGenerator(None).reconcile(
            {"media_type": "IMAGE", "output_count": 1},
            {"provider_settings": {"provider_poll_evidence": self._complete_snapshot()}},
            Path("unused.png"),
        )
        self.assertEqual(result, {"state": "REMAINS_AMBIGUOUS", "evidence": {"reason": "FLOW_POLL_EVIDENCE_INVALID"}})

    def test_quiescent_baseline_records_the_terminal_stable_poll(self):
        records = [{"card_id": "old-card", "asset_id": "old-asset", "media_type": "IMAGE", "state": "READY"}]

        class Dom:
            def provider_surface(self):
                return {"records": records, "global_pending_count": 0}

        observations = []
        _, stable = _stable_surface(
            Dom(), "IMAGE", timeout_seconds=1, required_stable_polls=3, poll_seconds=0,
            poll_observer=lambda _surface, _records, count: observations.append(count),
        )
        self.assertEqual((stable, observations), (3, [1, 2, 3]))

    def test_trial_b_pre_dispatch_history_persists_asset_through_empty_video_baseline(self):
        old_video = {"card_id": "old-card", "asset_id": "asset-a", "media_type": "VIDEO", "state": "READY"}
        old_thumbnail = {**old_video, "media_type": "VIDEO_THUMBNAIL"}
        surfaces = iter([
            {"records": [old_video], "global_pending_count": 0},
            {"records": [old_thumbnail], "global_pending_count": 0},
            {"records": [], "global_pending_count": 0},
            {"records": [], "global_pending_count": 0},
        ])

        class Dom:
            def provider_surface(self):
                return next(surfaces)

        with tempfile.TemporaryDirectory() as root:
            generator = LiveFlowGenerator(None, timeout_seconds=0)
            path = Path(root) / "provider_poll_evidence.json"
            generator._reset_poll_evidence(path)
            baseline, stable = _stable_surface(
                Dom(), "VIDEO", timeout_seconds=1, required_stable_polls=2, poll_seconds=0,
                poll_observer=lambda surface, records, count: generator._record_poll(
                    phase="PRE_DISPATCH_BASELINE", media_type="VIDEO", baseline=[],
                    current=records, surface=surface, stable_polls=count,
                ),
            )

            self.assertEqual(stable, 2)
            self.assertEqual(
                generator.last_settings["provider_poll_timeline"][-1]["pre_dispatch_asset_identity_set"],
                [{"identity": "asset:asset-a", "asset_id": "asset-a"}],
            )
            self.assertEqual(
                read_json(path)["observations"][-1]["pre_dispatch_asset_identity_set"][0]["identity"],
                "asset:asset-a",
            )

            tracker = RequestAttributionTracker(baseline, media_type="VIDEO", expected_count=1)
            pending = [
                {"card_id": "new-wrapper", "asset_id": "asset-a", "media_type": "VIDEO", "state": "READY"},
                {"card_id": "pending-card", "asset_id": None, "media_type": None, "state": "PENDING"},
            ]
            stale = tracker.observe(pending)
            self.assertEqual((stale.state, stale.candidate_delta_count), ("WAITING", 0))

            resolved = [
                pending[0],
                {"card_id": "pending-card", "asset_id": "asset-b", "media_type": "VIDEO", "state": "READY"},
            ]
            tracker.observe(resolved)
            tracker.observe(list(reversed(resolved)))
            confirmed = tracker.observe(resolved)
            self.assertEqual((confirmed.state, confirmed.candidate["asset_id"]), ("CONFIRMED", "asset-b"))

    def test_complete_poll_timeline_is_append_only_hash_chained_and_retains_early_polls(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "provider_poll_evidence.json"
            generator = LiveFlowGenerator(None, timeout_seconds=0)
            generator._reset_poll_evidence(path)
            baseline = [{"card_id": "old-card", "asset_id": "old-asset", "media_type": "IMAGE", "state": "READY"}]
            dispatch = DispatchEvidenceTracker()
            first = generator._record_poll(
                phase="PRE_DISPATCH_BASELINE", media_type="IMAGE", baseline=baseline,
                current=baseline, surface={"records": baseline, "global_pending_count": 0},
                stable_polls=3,
            )
            original_first = copy.deepcopy(first)

            # A transient request-local job signal has no stable provider ID.
            dispatch.observe(input_dispatched=True, attributable_job=True)
            generator._record_poll(
                phase="POST_DISPATCH", media_type="IMAGE", baseline=baseline,
                current=baseline, surface={"records": baseline, "global_pending_count": 1},
                stable_polls=0, dispatch=dispatch, activation={"input_dispatched": True},
            )
            generator._record_poll(
                phase="POST_DISPATCH", media_type="IMAGE", baseline=baseline,
                current=baseline, surface={"records": baseline, "global_pending_count": 0},
                stable_polls=0, dispatch=dispatch, activation={"input_dispatched": True},
            )
            generator._finish_poll_evidence("FLOW_DISPATCH_UNCERTAIN")

            persisted = read_json(path)
            self.assertEqual(persisted["observation_count"], 3)
            self.assertTrue(persisted["complete"])
            self.assertEqual(persisted["terminal_state"], "FLOW_DISPATCH_UNCERTAIN")
            self.assertEqual(persisted["observations"][0], original_first)
            self.assertEqual([item["poll_sequence"] for item in persisted["observations"]], [1, 2, 3])
            self.assertEqual(
                persisted["observations"][1]["previous_observation_sha256"],
                persisted["observations"][0]["observation_sha256"],
            )
            self.assertEqual(persisted["observations"][1]["dispatch_signal_state"], "SIGNAL_OBSERVED")
            self.assertEqual(persisted["observations"][2]["candidate_identities"], [])
            self.assertEqual(len(generator.last_settings["provider_poll_timeline"]), 3)

    def test_transient_job_signal_is_dispatch_uncertain_but_serialized_identity_confirms(self):
        tracker = DispatchEvidenceTracker()
        self.assertEqual(tracker.observe(input_dispatched=True, attributable_job=True), "UNCERTAIN")
        self.assertEqual(dispatch_timeout_failure(tracker), "FLOW_DISPATCH_UNCERTAIN")
        self.assertEqual(tracker.signal_state, "SIGNAL_OBSERVED")

        self.assertEqual(
            tracker.observe(
                input_dispatched=True,
                activation_verified=True,
                provider_acceptance_transition=True,
                attributable_job=True,
                durable_job_identity="card:stable-provider-card",
                durable_evidence_serialized=True,
                evidence_poll_sequence=2,
            ),
            "CONFIRMED",
        )
        self.assertEqual(dispatch_timeout_failure(tracker), "OUTPUT_ATTRIBUTION_UNCERTAIN")
        self.assertEqual(tracker.durable_identity, "card:stable-provider-card")

    def test_stable_exact_output_confirms_and_foreign_candidate_is_quarantined_not_selected(self):
        with tempfile.TemporaryDirectory() as root:
            generator = LiveFlowGenerator(None, timeout_seconds=0)
            generator._reset_poll_evidence(Path(root) / "polls.json")
            baseline = [{"card_id": "old", "asset_id": "asset-old", "media_type": "IMAGE", "state": "READY"}]
            current = baseline + [{"card_id": "new", "asset_id": "asset-new", "media_type": "IMAGE", "state": "READY"}]
            tracker = RequestAttributionTracker(baseline, media_type="IMAGE", expected_count=1)
            dispatch = DispatchEvidenceTracker()
            observation = None
            for _ in range(3):
                observation = tracker.observe(current)
                generator._record_poll(
                    phase="POST_DISPATCH", media_type="IMAGE", baseline=baseline,
                    current=current, surface={"records": current, "global_pending_count": 0},
                    stable_polls=observation.stable_polls, observation=observation,
                    dispatch=dispatch, activation={"input_dispatched": True, "activation_verified": True, "provider_acceptance_transition": True},
                )
            self.assertEqual(observation.state, "CONFIRMED")
            self.assertEqual(dispatch.state, "CONFIRMED")
            self.assertEqual(dispatch_timeout_failure(dispatch), "OUTPUT_ATTRIBUTION_UNCERTAIN")

            competing = current + [{"card_id": "foreign", "asset_id": "asset-foreign", "media_type": "IMAGE", "state": "READY"}]
            ambiguous = RequestAttributionTracker(baseline, media_type="IMAGE", expected_count=1).observe(competing)
            self.assertEqual(ambiguous.state, "AMBIGUOUS")
            self.assertIsNone(ambiguous.candidate)
            generator._record_poll(
                phase="POST_DISPATCH", media_type="IMAGE", baseline=baseline,
                current=competing, surface={"records": competing, "global_pending_count": 0},
                stable_polls=0, observation=ambiguous, dispatch=dispatch,
                activation={"input_dispatched": True},
                quarantined=[{"identity": "asset:asset-foreign", "reason": "REFERENCE_INPUT_ECHO"}],
            )
            last = generator.last_settings["provider_poll_timeline"][-1]
            self.assertEqual(last["candidate_classification"], "AMBIGUOUS")
            self.assertEqual(last["quarantined_identities"][0]["reason"], "REFERENCE_INPUT_ECHO")

    def test_timeline_bound_fails_closed_without_overwriting(self):
        timeline = ProviderPollEvidenceTimeline(max_observations=2)
        first = timeline.append({"phase": "BASELINE"})
        timeline.append({"phase": "POLL"})
        with self.assertRaisesRegex(FlowError, "FLOW_POLL_EVIDENCE_LIMIT_EXCEEDED"):
            timeline.append({"phase": "OVERFLOW"})
        self.assertEqual((len(timeline.observations), timeline.observations[0]), (2, first))


class Goal20UnresolvedReplayTests(unittest.TestCase):
    OLD_ID = "req_fresh_unresolved"

    def _project(self, root: str, *, dispatch_confirmed: bool = True):
        runtime = RuntimeLayout.from_root(root)
        config = ProjectConfig("prj_goal20_fixture")
        paths = create_project(runtime, config)
        atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {"status": "APPROVED"}})
        requests = {"requests": [
            {"request_id": self.OLD_ID, "fingerprint": "semantic-old", "purpose": "REFERENCE",
             "entity_id": "subject", "media_type": "IMAGE", "provider": "google_flow",
             "prompt": "subject reference", "output_count": 1, "depends_on": [], "reference_asset_ids": []},
            {"request_id": "req_later", "fingerprint": "semantic-later", "purpose": "SHOT",
             "shot_id": "sh_0001", "media_type": "IMAGE", "provider": "google_flow",
             "prompt": "later shot", "output_count": 1, "depends_on": [self.OLD_ID],
             "reference_asset_ids": [self.OLD_ID]},
        ]}
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), requests)
        atomic_write_json(paths.artifact_path("output/media_plan.json"), {
            "shots": [{"shot_id": "sh_0001", "selected_request_id": self.OLD_ID}]
        })
        attempt = {
            "attempt": 1,
            "status": "AMBIGUOUS",
            "failure_class": "OUTPUT_ATTRIBUTION_UNCERTAIN" if dispatch_confirmed else "FLOW_DISPATCH_UNCERTAIN",
            "dispatch_confirmed": dispatch_confirmed,
            "dispatch_confirmation_state": "CONFIRMED" if dispatch_confirmed else "UNCERTAIN",
            "attribution_state": "UNCERTAIN",
            "candidate_identities": [],
        }
        manifest = {
            "schema_version": "story-auto-generation-manifest/1.0.0",
            "project_id": config.project_id,
            "requests": [{
                "request_id": self.OLD_ID,
                "request_identity_sha256": "semantic-old",
                "related_identity": "subject",
                "media_type": "IMAGE",
                "provider": "google_flow",
                "prompt_sha256": "semantic-old",
                "reference_asset_hashes": [],
                "attempts": [attempt],
                "status": "AMBIGUOUS",
                "failure_class": attempt["failure_class"],
            }],
        }
        atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
        return runtime, config, paths

    def _replay(self, runtime, config, **kwargs):
        return replay_unresolved_request(
            runtime.root, config.project_id, self.OLD_ID,
            reason="Provider ownership remains irreducible; create one acknowledged fresh epoch.",
            acknowledge_previous_dispatch_or_cost_may_have_occurred=True,
            acknowledge_previous_output_ownership_unresolved=True,
            acknowledge_replacement_may_consume_provider_credit=True,
            **kwargs,
        )

    def test_replay_requires_reason_and_all_cost_ownership_acknowledgements(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, _ = self._project(root)
            base = dict(
                runtime_root=runtime.root, project_id=config.project_id, request_id=self.OLD_ID,
                reason="reason", acknowledge_previous_dispatch_or_cost_may_have_occurred=True,
                acknowledge_previous_output_ownership_unresolved=True,
                acknowledge_replacement_may_consume_provider_credit=True,
            )
            with self.assertRaisesRegex(FlowError, "UNRESOLVED_REPLAY_REASON_REQUIRED"):
                replay_unresolved_request(**{**base, "reason": ""})
            for key in (
                "acknowledge_previous_dispatch_or_cost_may_have_occurred",
                "acknowledge_previous_output_ownership_unresolved",
                "acknowledge_replacement_may_consume_provider_credit",
            ):
                with self.subTest(key=key), self.assertRaisesRegex(FlowError, "UNRESOLVED_REPLAY_ACKNOWLEDGEMENTS_REQUIRED"):
                    replay_unresolved_request(**{**base, key: False})

    def test_replay_preserves_attempt_truth_creates_fresh_pending_epoch_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            before_attempts = copy.deepcopy(read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]["attempts"])
            result = self._replay(runtime, config)
            replacement_id = result["replacement_request_id"]
            self.assertNotEqual(replacement_id, self.OLD_ID)
            self.assertEqual(result["provider_submissions"], 0)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            old, replacement = manifest["requests"]
            self.assertEqual(old["attempts"], before_attempts)
            self.assertEqual(
                (old["status"], old["historical_provider_dispatch"], old["historical_attribution"]),
                (ABANDONED_UNRESOLVED_STATUS, "CONFIRMED", "UNRESOLVED"),
            )
            self.assertNotIn("selected_asset", old)
            self.assertEqual(
                (replacement["request_id"], replacement["status"], replacement["attempts"], replacement["replays_unresolved_request_id"]),
                (replacement_id, "PENDING", [], self.OLD_ID),
            )
            requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
            self.assertFalse(any(item["request_id"] == self.OLD_ID for item in requests))
            self.assertEqual(requests[1]["depends_on"], [replacement_id])
            self.assertEqual(read_json(paths.artifact_path("output/media_plan.json"))["shots"][0]["selected_request_id"], replacement_id)
            snapshot = {name: paths.artifact_path(name).read_bytes() for name in (
                "output/generation_requests.json", "output/generation_manifest.json", "output/media_plan.json")}
            repeated = self._replay(runtime, config)
            self.assertTrue(repeated["idempotent"])
            self.assertEqual(repeated["replacement_request_id"], replacement_id)
            self.assertEqual(snapshot, {name: paths.artifact_path(name).read_bytes() for name in snapshot})

    def test_every_publication_fault_recovers_deterministically_without_provider_call(self):
        for boundary in ("prepared", "media_plan", "generation_requests", "generation_manifest", "committed"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as root:
                runtime, config, paths = self._project(root)

                def fail_once(point):
                    if point == boundary:
                        raise OSError(f"fault at {point}")

                with self.assertRaises(OSError):
                    self._replay(runtime, config, _fault_injector=fail_once)
                calls = []
                executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), lambda *_: calls.append("provider"))
                execute_generation(runtime.root, config.project_id, executor=executor, execute=True, request_ids=set())
                self.assertEqual(calls, [])
                repeated = self._replay(runtime, config)
                self.assertEqual(repeated["idempotent"], boundary != "prepared")
                directory = paths.artifact_path("output/unresolved_replay_transactions")
                self.assertEqual((len(list(directory.glob("*.prepared.json"))), len(list(directory.glob("*.committed.json")))), (1, 1))

    def test_malformed_replay_proof_is_queue_barrier_and_old_request_never_executes(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            with self.assertRaises(OSError):
                self._replay(
                    runtime, config,
                    _fault_injector=lambda point: (_ for _ in ()).throw(OSError("partial"))
                    if point == "generation_requests" else None,
                )
            transaction = read_json(next(paths.artifact_path("output/unresolved_replay_transactions").glob("*.prepared.json")))
            replacement_id = transaction["replacement_request_id"]
            calls = []

            def generate(request, _refs, destination):
                calls.append(request["request_id"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (1280, 720), "navy").save(destination, "PNG")
                return destination

            executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), generate)
            stale = execute_generation(
                runtime.root, config.project_id, executor=executor, execute=True,
                request_ids={self.OLD_ID}, max_requests=1,
            )
            self.assertEqual((stale["selected"], stale["new_submissions"], calls), (0, 0, []))
            current = execute_generation(
                runtime.root, config.project_id, executor=executor, execute=True,
                request_ids={replacement_id}, max_requests=1,
            )
            self.assertEqual((current["new_submissions"], calls), (1, [replacement_id]))
            self.assertNotIn(self.OLD_ID, calls)

            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            manifest["requests"][0]["unresolved_replay_events"] = []
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            calls.clear()
            blocked = execute_generation(
                runtime.root, config.project_id, executor=executor, execute=True,
                request_ids={"req_later"}, max_requests=1,
            )
            self.assertEqual((blocked["blocked"], blocked["blocked_request_id"], calls), (True, self.OLD_ID, []))

    def test_transaction_target_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            with self.assertRaises(OSError):
                self._replay(
                    runtime, config,
                    _fault_injector=lambda point: (_ for _ in ()).throw(OSError("partial"))
                    if point == "committed" else None,
                )
            prepared = next(paths.artifact_path("output/unresolved_replay_transactions").glob("*.prepared.json"))
            transaction = read_json(prepared)
            transaction["targets"]["generation_manifest"]["path"] = "output/wrong.json"
            atomic_write_json(prepared, transaction)
            calls = []
            executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), lambda *_: calls.append("provider"))
            with self.assertRaisesRegex(FlowError, "UNRESOLVED_REPLAY_RECOVERY_INVALID"):
                execute_generation(runtime.root, config.project_id, executor=executor, execute=True, request_ids=set())
            self.assertEqual(calls, [])

    def test_overflow_failure_cannot_create_selected_asset(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            manifest["requests"][0].update({"status": "PENDING", "failure_class": None, "attempts": []})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            timeline = ProviderPollEvidenceTimeline(max_provider_identities=2)
            with self.assertRaises(FlowError):
                timeline.append({"phase": "POST_DISPATCH", "current_identity_set": [
                    {"identity": "asset:one"}, {"identity": "asset:two"}, {"identity": "asset:three"},
                ]})

            class OverflowGenerator:
                dispatch_confirmed = False
                last_settings = {
                    "provider_poll_evidence": timeline.snapshot(),
                    "provider_poll_evidence_complete": False,
                    "attribution_state": "UNCERTAIN",
                }
                def __call__(self, *_args):
                    raise FlowError("FLOW_POLL_EVIDENCE_LIMIT_EXCEEDED")

            result = execute_generation(
                runtime.root, config.project_id,
                executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), OverflowGenerator()),
                execute=True, request_ids={self.OLD_ID}, max_requests=1,
            )
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertTrue(result["blocked"])
            self.assertEqual(entry["status"], "AMBIGUOUS")
            self.assertNotIn("selected_asset", entry)

    def test_verified_exact_output_binding_can_finalize_selected_asset(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            manifest["requests"][0].update({"status": "PENDING", "failure_class": None, "attempts": []})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            settings = Goal20PollEvidenceTests._confirmed_bound_settings()

            class BoundExactGenerator:
                dispatch_confirmed = True
                last_settings = settings
                def __call__(self, _request, _refs, destination):
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (1280, 720), "navy").save(destination, "PNG")
                    return destination

            result = execute_generation(
                runtime.root, config.project_id,
                executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), BoundExactGenerator()),
                execute=True, request_ids={self.OLD_ID}, max_requests=1,
            )
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertFalse(result["blocked"])
            self.assertEqual(entry["status"], "SUCCEEDED")
            self.assertIn("selected_asset", entry)

    def test_invalid_persisted_evidence_cannot_finalize_selected_asset(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            manifest["requests"][0].update({"status": "PENDING", "failure_class": None, "attempts": []})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            timeline = ProviderPollEvidenceTimeline()
            timeline.append({"phase": "POST_DISPATCH"})
            timeline.finish("CONFIRMED_OUTPUT")
            corrupted = timeline.snapshot()
            corrupted["observations"][0]["phase"] = "MUTATED"

            class InvalidEvidenceGenerator:
                dispatch_confirmed = True
                last_settings = {
                    "provider_poll_evidence": corrupted,
                    "provider_poll_evidence_complete": True,
                    "attribution_state": "CONFIRMED",
                    "attribution_method": "fixture",
                    "attributed_provider_identity": {"identity": "fixture:output"},
                }
                def __call__(self, _request, _refs, destination):
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (1280, 720), "navy").save(destination, "PNG")
                    return destination

            execute_generation(
                runtime.root, config.project_id,
                executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), InvalidEvidenceGenerator()),
                execute=True, request_ids={self.OLD_ID}, max_requests=1,
            )
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual(entry["status"], "AMBIGUOUS")
            self.assertNotIn("selected_asset", entry)


if __name__ == "__main__":
    unittest.main()

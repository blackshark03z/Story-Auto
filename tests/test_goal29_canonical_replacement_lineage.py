from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.service import (
    FlowExecutor,
    _abandoned_unresolved_entry_valid,
    _first_invalid_request_replacement,
    _provider_generation_retry_authorized,
    _qc_rejected_asset_replacement_valid,
    _resolve_current_canonical_descendant,
    _runnable,
    _unresolved_flow_entry,
    execute_generation,
    LEGACY_EPOCH_CLASSIFICATIONS,
    replay_unresolved_request,
    replace_qc_rejected_asset,
    supersede_ambiguous_request,
)
from story_auto.providers.flow.session import FlowCapabilities


class Goal29CanonicalReplacementLineageTests(unittest.TestCase):
    ANCESTOR = "req_8842b45b5666c9677562"

    def _project(self, root: str):
        runtime = RuntimeLayout.from_root(root)
        config = ProjectConfig("prj_goal29_fixture")
        paths = create_project(runtime, config)
        request = {
            "request_id": self.ANCESTOR, "fingerprint": "goal29-ancestor", "purpose": "SHOT",
            "shot_id": "sh_0003", "media_type": "IMAGE", "provider": "google_flow",
            "prompt": "decisive accomplishment", "output_count": 1, "depends_on": [],
            "reference_asset_ids": [],
        }
        atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {"status": "APPROVED"}})
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": [request]})
        atomic_write_json(paths.artifact_path("output/media_plan.json"), {"shots": [{"shot_id": "sh_0003", "selected_request_id": self.ANCESTOR}]})
        atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
            "schema_version": "story-auto-generation-manifest/1.0.0", "project_id": config.project_id,
            "requests": [{
                "request_id": self.ANCESTOR, "request_identity_sha256": request["fingerprint"],
                "related_identity": request["shot_id"], "media_type": "IMAGE", "provider": "google_flow",
                "prompt_sha256": "ancestor-prompt", "reference_asset_hashes": [],
                "attempts": [{"attempt": 1, "status": "AMBIGUOUS", "dispatch_confirmed": True,
                              "dispatch_confirmation_state": "CONFIRMED", "attribution_state": "UNCERTAIN",
                              "failure_class": "OUTPUT_ATTRIBUTION_UNCERTAIN"}],
                "status": "AMBIGUOUS", "failure_class": "OUTPUT_ATTRIBUTION_UNCERTAIN",
            }],
        })
        return runtime, config, paths

    def _replay(self, runtime, config):
        return replay_unresolved_request(
            runtime.root, config.project_id, self.ANCESTOR,
            reason="exact Trial A lineage fixture", acknowledge_previous_dispatch_or_cost_may_have_occurred=True,
            acknowledge_previous_output_ownership_unresolved=True, acknowledge_replacement_may_consume_provider_credit=True,
        )["replacement_request_id"]

    def _replay_then_qc_replace(self, runtime, config, paths):
        intermediate = self._replay(runtime, config)
        manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
        entry = next(item for item in manifest["requests"] if item["request_id"] == intermediate)
        entry.update({
            "status": "FAILED_RETRYABLE", "failure_class": "NATURALNESS_QC_REJECTED",
            "attempts": [{"attempt": 1, "status": "SUCCEEDED", "dispatch_confirmed": True,
                          "dispatch_confirmation_state": "CONFIRMED", "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED",
                          "attribution_state": "CONFIRMED", "attributed_provider_identity": {"identity": "fixture:b"}}],
            "selected_asset": {"path": "assets/image/b.png", "sha256": "b" * 64, "attempt": 1, "production_qc": "PENDING"},
        })
        atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
        current = replace_qc_rejected_asset(runtime.root, config.project_id, intermediate, reason="mandatory QC rejection")
        return intermediate, current["replacement_request_id"]

    @staticmethod
    def _state(paths):
        requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
        manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
        return requests, {item["request_id"]: item for item in manifest["requests"]}

    def test_abandoned_replay_resolves_through_qc_replacement_and_only_current_executes(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            intermediate = self._replay(runtime, config)
            requests, entries = self._state(paths)
            self.assertTrue(_abandoned_unresolved_entry_valid(paths, config.project_id, entries[self.ANCESTOR], requests, entries))
            self.assertEqual(_resolve_current_canonical_descendant(paths, config.project_id, self.ANCESTOR, requests, entries), intermediate)

            intermediate, current = self._replay_then_qc_replace(runtime, config, paths)
            requests, entries = self._state(paths)
            self.assertTrue(_abandoned_unresolved_entry_valid(paths, config.project_id, entries[self.ANCESTOR], requests, entries))
            self.assertTrue(_qc_rejected_asset_replacement_valid(paths, config.project_id, entries[intermediate], requests, entries))
            self.assertEqual(_resolve_current_canonical_descendant(paths, config.project_id, self.ANCESTOR, requests, entries), current)
            self.assertIsNone(_first_invalid_request_replacement(paths, config.project_id, entries, requests))
            self.assertFalse(_unresolved_flow_entry(entries[self.ANCESTOR]))
            self.assertFalse(_provider_generation_retry_authorized(entries[self.ANCESTOR]))
            self.assertFalse(_provider_generation_retry_authorized(entries[intermediate]))
            self.assertTrue(_provider_generation_retry_authorized(entries[current]))
            self.assertTrue(_runnable(next(item for item in requests if item["request_id"] == current), entries))

            calls: list[str] = []
            def fake_provider(request, _refs, destination: Path):
                calls.append(request["request_id"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (1280, 720), "navy").save(destination, "PNG")
                return destination

            result = execute_generation(
                runtime.root, config.project_id,
                executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), fake_provider),
                execute=True, request_ids={current}, max_requests=1,
            )
            self.assertEqual((result["blocked"], result["new_submissions"], calls), (False, 1, [current]))

    def test_broken_edges_missing_or_wrong_logical_descendant_fail_closed(self):
        mutations = {
            "missing_current": lambda requests, entries, current: requests.clear(),
            "wrong_logical_visual": lambda requests, entries, current: next(item for item in requests if item["request_id"] == current).update({"shot_id": "wrong-shot"}),
            "broken_qc_edge": lambda requests, entries, current: entries[current].update({"replacement_of": "wrong"}),
            "old_history_mutated": lambda requests, entries, current: entries[self.ANCESTOR]["attempts"].append({"attempt": 99}),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                runtime, config, paths = self._project(root)
                intermediate, current = self._replay_then_qc_replace(runtime, config, paths)
                requests, entries = self._state(paths)
                mutate(requests, entries, current)
                self.assertIsNone(_resolve_current_canonical_descendant(paths, config.project_id, self.ANCESTOR, requests, entries))
                expected_invalid = self.ANCESTOR if name == "old_history_mutated" else intermediate
                self.assertEqual(_first_invalid_request_replacement(paths, config.project_id, entries, requests)[0]["request_id"], expected_invalid)

    def test_competing_replacement_and_cycles_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            intermediate, current = self._replay_then_qc_replace(runtime, config, paths)
            requests, entries = self._state(paths)
            duplicate = dict(next(item for item in requests if item["request_id"] == current))
            duplicate.update({"request_id": "req_competing", "fingerprint": "competing", "replacement_of": intermediate})
            requests.append(duplicate)
            self.assertIsNone(_resolve_current_canonical_descendant(paths, config.project_id, self.ANCESTOR, requests, entries))

            requests.pop()
            entries[current].update({"status": "ABANDONED_UNRESOLVED", "replacement_request_id": self.ANCESTOR})
            self.assertIsNone(_resolve_current_canonical_descendant(paths, config.project_id, self.ANCESTOR, requests, entries))

    def test_legacy_supersession_can_resolve_through_later_qc_replacement(self):
        project_id, ancestor = next(iter(LEGACY_EPOCH_CLASSIFICATIONS))
        with tempfile.TemporaryDirectory() as root:
            runtime = RuntimeLayout.from_root(root)
            config = ProjectConfig(project_id)
            paths = create_project(runtime, config)
            request = {"request_id": ancestor, "fingerprint": "legacy-goal29", "purpose": "REFERENCE",
                       "entity_id": "scipio", "media_type": "IMAGE", "provider": "google_flow",
                       "prompt": "canonical Scipio reference", "depends_on": [], "reference_asset_ids": []}
            atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {"status": "APPROVED"}})
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": [request]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {"schema_version": "story-auto-generation-manifest/1.0.0", "project_id": project_id, "requests": [{
                "request_id": ancestor, "request_identity_sha256": request["fingerprint"], "related_identity": "scipio",
                "media_type": "IMAGE", "provider": "google_flow", "prompt_sha256": request["fingerprint"], "reference_asset_hashes": [],
                "attempts": [{"attempt": 1, "status": "AMBIGUOUS", "failure_class": "FLOW_DISPATCH_UNCERTAIN", "dispatch_confirmed": False,
                              "provider_job_id": None, "reconciliation_events": [{"state": "REMAINS_AMBIGUOUS", "evidence": {"reason": "LEGACY_BASELINE_IDENTITIES_UNAVAILABLE"}}]}],
                "reconciliation_events": [{"state": "REMAINS_AMBIGUOUS"}], "status": "AMBIGUOUS", "failure_class": "FLOW_DISPATCH_UNCERTAIN",
            }]})
            middle = supersede_ambiguous_request(runtime.root, project_id, ancestor, reason="legacy replacement", acknowledge_historical_dispatch_unknown=True)["replacement_request_id"]
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            entry = next(item for item in manifest["requests"] if item["request_id"] == middle)
            entry.update({"status": "FAILED_RETRYABLE", "failure_class": "NATURALNESS_QC_REJECTED", "attempts": [{"attempt": 1, "status": "SUCCEEDED", "dispatch_confirmed": True, "attribution_state": "CONFIRMED"}], "selected_asset": {"path": "assets/image/legacy.png", "sha256": "l" * 64, "attempt": 1, "production_qc": "PENDING"}})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            current = replace_qc_rejected_asset(runtime.root, project_id, middle, reason="mandatory QC rejection")["replacement_request_id"]
            requests, entries = self._state(paths)
            self.assertEqual(_resolve_current_canonical_descendant(paths, project_id, ancestor, requests, entries), current)
            self.assertIsNone(_first_invalid_request_replacement(paths, project_id, entries, requests))


if __name__ == "__main__":
    unittest.main()

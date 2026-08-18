from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.service import (
    FlowError,
    FlowExecutor,
    LEGACY_EPOCH_CLASSIFICATIONS,
    adopt_manual_recovery,
    execute_generation,
    supersede_ambiguous_request,
)
from story_auto.providers.flow.session import FlowCapabilities


LEGACY_PROJECT_ID, LEGACY_REQUEST_ID = next(iter(LEGACY_EPOCH_CLASSIFICATIONS))


class Goal19LegacySupersessionTests(unittest.TestCase):
    def _project(self, root: str, *, project_id: str = LEGACY_PROJECT_ID,
                 request_id: str = LEGACY_REQUEST_ID,
                 reason: str = "LEGACY_BASELINE_IDENTITIES_UNAVAILABLE"):
        runtime = RuntimeLayout.from_root(root)
        config = ProjectConfig(project_id)
        paths = create_project(runtime, config)
        atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {"status": "APPROVED"}})
        requests = {"requests": [
            {"request_id": request_id, "fingerprint": "semantic-ref", "purpose": "REFERENCE", "entity_id": "scipio",
             "media_type": "IMAGE", "provider": "google_flow", "prompt": "canonical Scipio reference", "output_count": 1,
             "depends_on": [], "reference_asset_ids": []},
            {"request_id": "shot", "fingerprint": "semantic-shot", "purpose": "SHOT", "shot_id": "sh_0001",
             "media_type": "IMAGE", "provider": "google_flow", "prompt": "Scipio enters the senate", "output_count": 1,
             "depends_on": [request_id], "reference_asset_ids": [request_id]},
        ]}
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), requests)
        atomic_write_json(paths.artifact_path("output/media_plan.json"), {"shots": [
            {"shot_id": "sh_0001", "selected_request_id": request_id},
            {"shot_id": "unrelated", "selected_request_id": "unrelated_request"},
        ]})
        attempt = {"attempt": 2, "status": "AMBIGUOUS", "failure_class": "FLOW_DISPATCH_UNCERTAIN",
                   "dispatch_confirmed": False, "provider_job_id": None,
                   "reconciliation_events": [{"at": "2026-08-16T11:36:43+00:00", "state": "REMAINS_AMBIGUOUS",
                                                "evidence": {"reason": reason}}]}
        manifest = {"schema_version": "story-auto-generation-manifest/1.0.0", "project_id": config.project_id, "requests": [
            {"request_id": request_id, "request_identity_sha256": "semantic-ref", "related_identity": "scipio",
             "media_type": "IMAGE", "provider": "google_flow", "prompt_sha256": "semantic-ref", "reference_asset_hashes": [],
             "attempts": [{"attempt": 1, "status": "NOT_DISPATCHED", "dispatch_confirmed": False}, attempt],
             "reconciliation_events": [{"at": "2026-08-16T11:36:43+00:00", "attempt": 2, "state": "REMAINS_AMBIGUOUS"}],
             "status": "AMBIGUOUS", "failure_class": "FLOW_DISPATCH_UNCERTAIN"},
        ]}
        atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
        return runtime, config, paths

    def _supersede(self, runtime, config, request_id=LEGACY_REQUEST_ID, **kwargs):
        return supersede_ambiguous_request(
            runtime.root, config.project_id, request_id,
            reason="Historical dispatch remains UNKNOWN; baseline cannot be recovered; create a fresh epoch.",
            acknowledge_historical_dispatch_unknown=True, **kwargs,
        )

    def _assert_coherent(self, paths, old_id: str, replacement_id: str, before_attempts, before_reconciliation):
        requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
        self.assertEqual(len([item for item in requests if item["request_id"] == replacement_id]), 1)
        self.assertFalse(any(item["request_id"] == old_id for item in requests))
        replacement = next(item for item in requests if item["request_id"] == replacement_id)
        self.assertEqual((replacement["replaces_request_id"], replacement["replacement_epoch"]), (old_id, 1))
        downstream = next(item for item in requests if item["request_id"] == "shot")
        self.assertEqual((downstream["depends_on"], downstream["reference_asset_ids"]), ([replacement_id], [replacement_id]))
        media = read_json(paths.artifact_path("output/media_plan.json"))["shots"]
        self.assertEqual(media[0]["selected_request_id"], replacement_id)
        self.assertEqual(media[1]["selected_request_id"], "unrelated_request")
        old, fresh = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"]
        self.assertEqual((old["status"], old["historical_provider_dispatch"], old["historical_attribution"]),
                         ("SUPERSEDED_AMBIGUOUS", "UNKNOWN", "UNRESOLVED"))
        self.assertEqual(old["attempts"], before_attempts)
        self.assertEqual(old["reconciliation_events"], before_reconciliation)
        self.assertNotIn("selected_asset", old)
        event = old["supersession_events"][-1]
        self.assertEqual((event["replacement_request_id"], event["prior_dispatch_state"], event["prior_attribution_state"]),
                         (replacement_id, "UNKNOWN", "UNRESOLVED"))
        self.assertEqual((fresh["request_id"], fresh["status"], fresh["attempts"], fresh["replaces_request_id"]),
                         (replacement_id, "PENDING", [], old_id))

    def test_preserved_legacy_epoch_requires_reason_unknown_ack_and_migrates_real_media_plan(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            before = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            before_attempts, before_reconciliation = copy.deepcopy(before["attempts"]), copy.deepcopy(before["reconciliation_events"])
            calls = []
            executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), lambda *_: calls.append("provider"))
            blocked = execute_generation(runtime.root, config.project_id, executor=executor, execute=True, production_batch=True)
            self.assertEqual((blocked["blocked"], blocked["blocked_request_id"], calls), (True, LEGACY_REQUEST_ID, []))
            with self.assertRaisesRegex(FlowError, "LEGACY_SUPERSESSION_REASON_REQUIRED"):
                supersede_ambiguous_request(runtime.root, config.project_id, LEGACY_REQUEST_ID, reason="", acknowledge_historical_dispatch_unknown=True)
            with self.assertRaisesRegex(FlowError, "LEGACY_SUPERSESSION_UNKNOWN_ACK_REQUIRED"):
                supersede_ambiguous_request(runtime.root, config.project_id, LEGACY_REQUEST_ID, reason="legacy is unrecoverable", acknowledge_historical_dispatch_unknown=False)
            result = self._supersede(runtime, config)
            self.assertEqual((result["provider_submissions"], calls), (0, []))
            self._assert_coherent(paths, LEGACY_REQUEST_ID, result["replacement_request_id"], before_attempts, before_reconciliation)

    def test_fresh_same_error_shape_cannot_use_legacy_supersession(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, _ = self._project(root, project_id="prj_fresh_goal17", request_id="fresh_request")
            with self.assertRaisesRegex(FlowError, "LEGACY_SUPERSESSION_NOT_ELIGIBLE"):
                self._supersede(runtime, config, "fresh_request")

    def test_successful_supersession_is_idempotent_without_second_epoch_or_event(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            before = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            result = self._supersede(runtime, config)
            snapshot = {name: paths.artifact_path(name).read_bytes() for name in (
                "output/generation_requests.json", "output/generation_manifest.json", "output/media_plan.json")}
            repeated = self._supersede(runtime, config)
            self.assertTrue(repeated["idempotent"])
            self.assertEqual(repeated["replacement_request_id"], result["replacement_request_id"])
            self.assertEqual(snapshot, {name: paths.artifact_path(name).read_bytes() for name in snapshot})
            self._assert_coherent(paths, LEGACY_REQUEST_ID, result["replacement_request_id"], before["attempts"], before["reconciliation_events"])

    def test_every_publication_fault_recovers_one_transaction_without_provider_call(self):
        for boundary in ("prepared", "media_plan", "generation_requests", "generation_manifest", "committed"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as root:
                runtime, config, paths = self._project(root)
                before = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
                def fail_once(point):
                    if point == boundary:
                        raise OSError(f"fault at {point}")
                with self.assertRaises(OSError):
                    self._supersede(runtime, config, _fault_injector=fail_once)
                calls = []
                executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), lambda *_: calls.append("provider"))
                execute_generation(runtime.root, config.project_id, executor=executor, execute=True, request_ids=set())
                self.assertEqual(calls, [])
                result = self._supersede(runtime, config)
                self._assert_coherent(paths, LEGACY_REQUEST_ID, result["replacement_request_id"], before["attempts"], before["reconciliation_events"])
                directory = paths.artifact_path("output/legacy_supersession_transactions")
                self.assertEqual(len(list(directory.glob("*.prepared.json"))), 1)
                self.assertEqual(len(list(directory.glob("*.committed.json"))), 1)

    def test_malformed_superseded_status_remains_a_queue_barrier(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            replacement_id = self._supersede(runtime, config)["replacement_request_id"]
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            manifest["requests"][0]["supersession_events"] = []
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            calls = []
            executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), lambda *_: calls.append("provider"))
            blocked = execute_generation(runtime.root, config.project_id, executor=executor, execute=True, request_ids={replacement_id})
            self.assertEqual((blocked["blocked"], blocked["blocked_request_id"], calls), (True, LEGACY_REQUEST_ID, []))

    def test_superseded_epoch_releases_only_replacement_and_fresh_ambiguity_stays_blocking(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            replacement_id = self._supersede(runtime, config)["replacement_request_id"]
            calls = []
            def generate(request, _refs, destination):
                calls.append(request["request_id"]); destination.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (1280, 720), "navy").save(destination, "PNG"); return destination
            executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), generate)
            result = execute_generation(runtime.root, config.project_id, executor=executor, execute=True, request_ids={replacement_id})
            self.assertEqual((result["new_submissions"], result["blocked"], calls), (1, False, [replacement_id]))
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            current = next(item for item in manifest["requests"] if item["request_id"] == replacement_id)
            current.update({"status": "AMBIGUOUS", "failure_class": "FLOW_DISPATCH_UNCERTAIN"})
            current["attempts"].append({"attempt": 2, "status": "AMBIGUOUS", "failure_class": "FLOW_DISPATCH_UNCERTAIN", "dispatch_confirmed": False})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            blocked = execute_generation(runtime.root, config.project_id, executor=executor, execute=True, request_ids={"shot"})
            self.assertEqual((blocked["blocked"], blocked["blocked_request_id"], calls), (True, replacement_id, [replacement_id]))

    def test_local_file_override_never_claims_confirmed_flow_attribution(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            entry = manifest["requests"][0]
            entry.update({"status": "FAILED_RETRYABLE", "failure_class": "OUTPUT_ATTRIBUTION_INVALID"})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            local = Path(root) / "operator.png"; Image.new("RGB", (1280, 720), "green").save(local, "PNG")
            selected = adopt_manual_recovery(runtime.root, config.project_id, LEGACY_REQUEST_ID, local, settings={"source": "operator"}, attribution="operator local file")
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            attempt = entry["attempts"][-1]
            self.assertEqual((selected["provenance"], attempt["attribution_state"], attempt["attribution_method"]),
                             ("OPERATOR_LOCAL_ASSET", "LOCAL_OVERRIDE", "operator_local_asset"))
            self.assertNotIn("attributed_provider_identity", attempt)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.service import (
    FlowError, FlowExecutor, adopt_manual_recovery, execute_generation,
    supersede_ambiguous_request,
)
from story_auto.providers.flow.session import FlowCapabilities


class Goal19LegacySupersessionTests(unittest.TestCase):
    def _project(self, root: str, *, reason: str = "LEGACY_BASELINE_IDENTITIES_UNAVAILABLE"):
        runtime = RuntimeLayout.from_root(root)
        config = ProjectConfig("prj_goal19")
        paths = create_project(runtime, config)
        atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {"status": "APPROVED"}})
        requests = {"requests": [
            {"request_id": "legacy_ref", "fingerprint": "semantic-ref", "purpose": "REFERENCE", "entity_id": "scipio",
             "media_type": "IMAGE", "provider": "google_flow", "prompt": "canonical Scipio reference", "output_count": 1,
             "depends_on": [], "reference_asset_ids": []},
            {"request_id": "shot", "fingerprint": "semantic-shot", "purpose": "SHOT", "shot_id": "sh_0001",
             "media_type": "IMAGE", "provider": "google_flow", "prompt": "Scipio enters the senate", "output_count": 1,
             "depends_on": ["legacy_ref"], "reference_asset_ids": ["legacy_ref"]},
        ]}
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), requests)
        atomic_write_json(paths.artifact_path("output/media_plan.json"), {"shots": [{"shot_id": "sh_0001", "selected_request_id": "shot"}]})
        attempt = {"attempt": 2, "status": "AMBIGUOUS", "failure_class": "FLOW_DISPATCH_UNCERTAIN",
                   "dispatch_confirmed": False, "provider_job_id": None,
                   "reconciliation_events": [{"at": "2026-08-16T11:36:43+00:00", "state": "REMAINS_AMBIGUOUS",
                                                "evidence": {"reason": reason}}]}
        manifest = {"schema_version": "story-auto-generation-manifest/1.0.0", "project_id": config.project_id, "requests": [
            {"request_id": "legacy_ref", "request_identity_sha256": "semantic-ref", "related_identity": "scipio",
             "media_type": "IMAGE", "provider": "google_flow", "prompt_sha256": "semantic-ref", "reference_asset_hashes": [],
             "attempts": [{"attempt": 1, "status": "NOT_DISPATCHED", "dispatch_confirmed": False}, attempt],
             "reconciliation_events": [{"at": "2026-08-16T11:36:43+00:00", "attempt": 2, "state": "REMAINS_AMBIGUOUS"}],
             "status": "AMBIGUOUS", "failure_class": "FLOW_DISPATCH_UNCERTAIN"},
        ]}
        atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
        return runtime, config, paths

    def test_legacy_epoch_requires_exact_evidence_reason_and_unknown_acknowledgement(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            before = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            before_attempts, before_reconciliation = copy.deepcopy(before["attempts"]), copy.deepcopy(before["reconciliation_events"])
            calls = []
            executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), lambda *_: calls.append("provider"))
            blocked = execute_generation(runtime.root, config.project_id, executor=executor, execute=True, production_batch=True)
            self.assertEqual((blocked["blocked"], blocked["blocked_request_id"], calls), (True, "legacy_ref", []))
            with self.assertRaisesRegex(FlowError, "LEGACY_SUPERSESSION_REASON_REQUIRED"):
                supersede_ambiguous_request(runtime.root, config.project_id, "legacy_ref", reason="", acknowledge_historical_dispatch_unknown=True)
            with self.assertRaisesRegex(FlowError, "LEGACY_SUPERSESSION_UNKNOWN_ACK_REQUIRED"):
                supersede_ambiguous_request(runtime.root, config.project_id, "legacy_ref", reason="legacy is unrecoverable", acknowledge_historical_dispatch_unknown=False)
            result = supersede_ambiguous_request(runtime.root, config.project_id, "legacy_ref",
                                                  reason="Historical dispatch remains UNKNOWN; baseline cannot be recovered; create a fresh epoch.",
                                                  acknowledge_historical_dispatch_unknown=True)
            self.assertEqual((result["provider_submissions"], calls), (0, []))
            replacement_id = result["replacement_request_id"]
            requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
            replacement = next(item for item in requests if item["request_id"] == replacement_id)
            self.assertNotEqual(replacement_id, "legacy_ref")
            self.assertEqual((replacement["prompt"], replacement["purpose"], replacement["epoch_nonce"] != ""),
                             ("canonical Scipio reference", "REFERENCE", True))
            self.assertNotEqual(replacement["fingerprint"], "semantic-ref")
            downstream = next(item for item in requests if item["request_id"] == "shot")
            self.assertEqual((downstream["depends_on"], downstream["reference_asset_ids"]), ([replacement_id], [replacement_id]))
            old, fresh = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"]
            self.assertEqual(old["status"], "SUPERSEDED_AMBIGUOUS")
            self.assertEqual((old["historical_provider_dispatch"], old["historical_attribution"]), ("UNKNOWN", "UNRESOLVED"))
            self.assertEqual(old["attempts"], before_attempts)
            self.assertEqual(old["reconciliation_events"], before_reconciliation)
            self.assertNotIn("selected_asset", old)
            event = old["supersession_events"][-1]
            self.assertEqual((event["prior_dispatch_state"], event["prior_attribution_state"], event["replacement_request_id"]),
                             ("UNKNOWN", "UNRESOLVED", replacement_id))
            self.assertEqual((fresh["request_id"], fresh["status"], fresh["attempts"], fresh["replaces_request_id"]),
                             (replacement_id, "PENDING", [], "legacy_ref"))
            self.assertEqual(read_json(paths.artifact_path("output/media_plan.json"))["shots"][0]["selected_request_id"], "shot")

    def test_superseded_epoch_releases_only_replacement_and_fresh_ambiguity_stays_blocking(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            replacement_id = supersede_ambiguous_request(runtime.root, config.project_id, "legacy_ref", reason="legacy evidence gap", acknowledge_historical_dispatch_unknown=True)["replacement_request_id"]
            calls = []
            def generate(request, _refs, destination):
                calls.append(request["request_id"]); destination.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (1280, 720), "navy").save(destination, "PNG"); return destination
            executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), generate)
            result = execute_generation(runtime.root, config.project_id, executor=executor, execute=True, request_ids={replacement_id})
            self.assertEqual((result["new_submissions"], result["blocked"], calls), (1, False, [replacement_id]))
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            self.assertEqual(next(item for item in manifest["requests"] if item["request_id"] == replacement_id)["status"], "SUCCEEDED")
            current = next(item for item in manifest["requests"] if item["request_id"] == replacement_id)
            current.update({"status": "AMBIGUOUS", "failure_class": "FLOW_DISPATCH_UNCERTAIN"})
            current["attempts"].append({"attempt": 2, "status": "AMBIGUOUS", "failure_class": "FLOW_DISPATCH_UNCERTAIN", "dispatch_confirmed": False})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            blocked = execute_generation(runtime.root, config.project_id, executor=executor, execute=True, request_ids={"shot"})
            self.assertEqual((blocked["blocked"], blocked["blocked_request_id"], calls), (True, replacement_id, [replacement_id]))

    def test_other_ambiguous_shapes_cannot_be_superseded(self):
        for reason in ("OUTPUT_ATTRIBUTION_AMBIGUOUS", "LEGACY_BASELINE_IDENTITIES_UNAVAILABLE"):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as root:
                runtime, config, _ = self._project(root, reason=reason)
                if reason == "OUTPUT_ATTRIBUTION_AMBIGUOUS":
                    with self.assertRaisesRegex(FlowError, "LEGACY_SUPERSESSION_NOT_ELIGIBLE"):
                        supersede_ambiguous_request(runtime.root, config.project_id, "legacy_ref", reason="not legacy shape", acknowledge_historical_dispatch_unknown=True)
                else:
                    # The same evidence reason is eligible only with the preserved dispatch-uncertain shape.
                    result = supersede_ambiguous_request(runtime.root, config.project_id, "legacy_ref", reason="legacy gap", acknowledge_historical_dispatch_unknown=True)
                    self.assertTrue(result["replacement_request_id"].startswith("req_"))

    def test_local_file_override_never_claims_confirmed_flow_attribution(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            entry = manifest["requests"][0]
            entry.update({"status": "FAILED_RETRYABLE", "failure_class": "OUTPUT_ATTRIBUTION_INVALID"})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            local = Path(root) / "operator.png"; Image.new("RGB", (1280, 720), "green").save(local, "PNG")
            selected = adopt_manual_recovery(runtime.root, config.project_id, "legacy_ref", local, settings={"source": "operator"}, attribution="operator local file")
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            attempt = entry["attempts"][-1]
            self.assertEqual((selected["provenance"], attempt["attribution_state"], attempt["attribution_method"]),
                             ("OPERATOR_LOCAL_ASSET", "LOCAL_OVERRIDE", "operator_local_asset"))
            self.assertNotIn("attributed_provider_identity", attempt)


if __name__ == "__main__":
    unittest.main()

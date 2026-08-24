from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.service import (
    FlowError,
    FlowExecutor,
    _first_invalid_request_replacement,
    _provider_generation_retry_authorized,
    _runnable,
    execute_generation,
    queue_regeneration,
    replace_qc_rejected_asset,
    review_production_asset,
)
from story_auto.core.visual import EDITORIAL_OVERLAY_SAFETY_CONSTRAINT
from story_auto.providers.flow.session import FlowCapabilities


class Goal27QcRejectedAssetReplacementTests(unittest.TestCase):
    OLD_REQUEST_ID = "req_2f755d20c25245314761"

    def _project(self, root: str):
        runtime = RuntimeLayout.from_root(root)
        config = ProjectConfig("prj_goal27")
        paths = create_project(runtime, config)
        atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {"status": "APPROVED"}})
        atomic_write_json(paths.artifact_path("output/continuity_bible.json"), {
            "characters": [], "locations": [], "props": [],
        })
        atomic_write_json(paths.artifact_path("output/shot_plan.json"), {"shots": [{
            "shot_id": "sh_001", "subject": "the witness", "action": "speaks calmly",
            "location_id": "courtroom", "composition_intent": "medium close-up at the witness stand",
        }]})
        old = {
            "request_id": self.OLD_REQUEST_ID, "fingerprint": "old-semantic-fingerprint", "purpose": "SHOT",
            "shot_id": "sh_001", "media_type": "IMAGE", "provider": "google_flow", "prompt": "quiet courtroom at dusk",
            "depends_on": [], "reference_asset_ids": [], "execution_tier": "STANDARD_PRODUCTION",
        }
        later = {
            "request_id": "req_later", "fingerprint": "later-fingerprint", "purpose": "SHOT", "shot_id": "sh_002",
            "media_type": "IMAGE", "provider": "google_flow", "prompt": "same witness later", "depends_on": [self.OLD_REQUEST_ID],
            "reference_asset_ids": [self.OLD_REQUEST_ID], "execution_tier": "STANDARD_PRODUCTION",
        }
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": [old, later]})
        selected = {"path": "assets/image/original.png", "sha256": "a" * 64, "attempt": 1, "production_qc": "REJECTED"}
        attempt = {
            "attempt": 1, "status": "SUCCEEDED", "dispatch_confirmed": True,
            "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED", "provider_job_id": "flow-job-1",
            "attribution_state": "CONFIRMED", "attributed_provider_identity": {"identity": "flow-card-1"},
        }
        atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
            "schema_version": "story-auto-generation-manifest/1.0.0", "project_id": config.project_id,
            "requests": [{"request_id": self.OLD_REQUEST_ID, "request_identity_sha256": old["fingerprint"],
                          "related_identity": old["shot_id"], "media_type": "IMAGE", "provider": "google_flow",
                          "prompt_sha256": "old-prompt", "reference_asset_hashes": [], "attempts": [attempt],
                          "status": "FAILED_RETRYABLE", "failure_class": "NATURALNESS_QC_REJECTED",
                          "selected_asset": selected, "quality_reviews": [{"status": "REJECTED", "failure_class": "NATURALNESS_QC_REJECTED"}]}],
        })
        return runtime, config, paths, old, selected, attempt

    def _executor(self, calls: list[str]) -> FlowExecutor:
        def generate(request, _refs, destination: Path):
            calls.append(request["request_id"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1280, 720), "maroon" if request["request_id"] == "req_later" else "navy").save(destination, "PNG")
            return destination
        return FlowExecutor(FlowCapabilities(True, True, True, True, True, True), generate)

    def test_owned_qc_rejection_creates_one_immutable_replacement_epoch(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths, old_request, selected, attempt = self._project(root)
            first = queue_regeneration(runtime.root, config.project_id, self.OLD_REQUEST_ID, reason="mandatory naturalness QC rejected")
            second = replace_qc_rejected_asset(runtime.root, config.project_id, self.OLD_REQUEST_ID, reason="same operation retry")
            self.assertFalse(first["idempotent"])
            self.assertTrue(second["idempotent"])
            self.assertEqual(first["replacement_request_id"], second["replacement_request_id"])
            replacement_id = first["replacement_request_id"]
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            old_entry, replacement_entry = manifest["requests"]
            requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
            replacement_request = requests[0]
            self.assertEqual(old_entry["request_id"], self.OLD_REQUEST_ID)
            self.assertEqual(old_entry["attempts"], [attempt])
            self.assertEqual(old_entry["selected_asset"], selected)
            self.assertEqual(old_entry["failure_class"], "NATURALNESS_QC_REJECTED")
            self.assertEqual(old_entry["status"], "QC_REJECTED_ASSET_REPLACED")
            self.assertFalse(_provider_generation_retry_authorized(old_entry))
            self.assertEqual((replacement_entry["attempts"], replacement_entry["provider_submissions"], replacement_entry["selected_asset"], replacement_entry["attribution_claim"]), ([], 0, None, "NONE"))
            self.assertEqual((replacement_request["replacement_of"], replacement_request["replacement_reason"]), (self.OLD_REQUEST_ID, "QC_REJECTED_ASSET_REPLACEMENT"))
            self.assertEqual((replacement_request["shot_id"], replacement_request["purpose"]), (old_request["shot_id"], old_request["purpose"]))
            self.assertEqual(old_entry["historical_prompt"], old_request["prompt"])
            self.assertIn(EDITORIAL_OVERLAY_SAFETY_CONSTRAINT, replacement_request["prompt"])
            self.assertEqual(requests[1]["depends_on"], [replacement_id])
            self.assertEqual(requests[1]["reference_asset_ids"], [replacement_id])
            self.assertTrue(_provider_generation_retry_authorized(replacement_entry))
            calls: list[str] = []
            self.assertEqual(calls, [])  # replacement creation is local-only: no provider call occurred.
            generated = execute_generation(runtime.root, config.project_id, executor=self._executor(calls), execute=True, request_ids={replacement_id})
            self.assertEqual((generated["new_submissions"], calls), (1, [replacement_id]))
            report = {"results": {key: "PASS" for key in ("SKIN_REALISM", "LIGHTING_NATURALISM", "MATERIAL_REALISM", "COMPOSITION_NATURALISM", "AI_POLISH", "CONTINUITY", "TECHNICAL_VALIDITY")}, "visible_provider_watermark": False, "reviewer": "fixture", "alignment_classification": "PASS_DIRECT"}
            review_production_asset(runtime.root, config.project_id, replacement_id, report)
            post_qc = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][1]
            self.assertEqual((post_qc["status"], post_qc["provider_submissions"]), ("SUCCEEDED", 1))
            resumed = execute_generation(runtime.root, config.project_id, executor=self._executor(calls), execute=True, request_ids={replacement_id})
            self.assertEqual((resumed["blocked"], resumed["new_submissions"], calls), (False, 0, [replacement_id]))
            entries = {entry["request_id"]: entry for entry in read_json(paths.artifact_path("output/generation_manifest.json"))["requests"]}
            self.assertTrue(_runnable(read_json(paths.artifact_path("output/generation_requests.json"))["requests"][1], entries))

    def test_operator_regenerate_of_confirmed_qc_pending_asset_creates_one_fresh_epoch(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths, _old, selected, attempt = self._project(root)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            parent = manifest["requests"][0]
            parent.update({"status": "QC_PENDING", "failure_class": None, "quality_reviews": [], "selected_asset": selected})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)

            result = queue_regeneration(runtime.root, config.project_id, self.OLD_REQUEST_ID, reason="visible duplicate seam")
            again = queue_regeneration(runtime.root, config.project_id, self.OLD_REQUEST_ID, reason="same UI action retry")

            self.assertFalse(result["idempotent"])
            self.assertTrue(again["idempotent"])
            self.assertEqual(result["replacement_request_id"], again["replacement_request_id"])
            entries = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"]
            parent = entries[0]
            child = entries[1]
            self.assertEqual(parent["attempts"], [attempt])
            self.assertEqual(parent["selected_asset"], selected)
            self.assertEqual(parent["status"], "QC_REJECTED_ASSET_REPLACED")
            self.assertEqual(parent["failure_class"], "CREATIVE_REJECTED")
            self.assertEqual(parent["creative_rejections"][0]["provenance"], "OPERATOR_REGENERATE_ACTION")
            self.assertFalse(_provider_generation_retry_authorized(parent))
            self.assertEqual((child["attempts"], child["provider_submissions"], child["status"]), ([], 0, "PENDING"))

    def test_legacy_qc_replacement_child_can_start_epoch_two(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths, _old, _selected, _attempt = self._project(root)
            result = replace_qc_rejected_asset(runtime.root, config.project_id, self.OLD_REQUEST_ID, reason="mandatory QC")
            replacement_id = result["replacement_request_id"]
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            replacement = manifest["requests"][1]
            replacement.update({"status": "FAILED_RETRYABLE", "failure_class": "NATURALNESS_QC_REJECTED", "selected_asset": {"attempt": 1},
                                "attempts": [{"attempt": 1, "attribution_state": "CONFIRMED", "dispatch_confirmed": True}]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            epoch2 = replace_qc_rejected_asset(runtime.root, config.project_id, replacement_id, reason="second bounded correction")
            self.assertEqual(epoch2["status"], "QC_REJECTED_ASSET_REPLACED")
            child = next(item for item in read_json(paths.artifact_path("output/generation_manifest.json"))["requests"]
                         if item["request_id"] == epoch2["replacement_request_id"])
            self.assertEqual((child["replacement_epoch"], child["attempts"], child["provider_submissions"]), (2, [], 0))

    def test_bounded_creative_correction_epochs_replan_then_exhaust(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths, _old, selected, attempt = self._project(root)
            epoch1 = replace_qc_rejected_asset(
                runtime.root, config.project_id, self.OLD_REQUEST_ID, reason="first bounded correction"
            )["replacement_request_id"]
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            replacement = next(item for item in manifest["requests"] if item["request_id"] == epoch1)
            replacement.update({
                "status": "QC_PENDING", "failure_class": None, "selected_asset": selected,
                "attempts": [attempt], "provider_submissions": 1,
            })
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            epoch2 = queue_regeneration(runtime.root, config.project_id, epoch1, reason="second bounded correction")["replacement_request_id"]
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            epoch2_entry = next(item for item in manifest["requests"] if item["request_id"] == epoch2)
            self.assertEqual((epoch2_entry["attempts"], epoch2_entry["provider_submissions"], epoch2_entry["status"]), ([], 0, "PENDING"))
            self.assertEqual(epoch2_entry["replacement_epoch"], 2)
            self.assertEqual(epoch2_entry["creative_correction_replan_proof"]["mode"], "FULL_REPLAN")
            self.assertNotEqual(epoch2_entry["creative_correction_replan_proof"]["prior_generation_input_sha256"],
                                epoch2_entry["creative_correction_replan_proof"]["replanned_generation_input_sha256"])
            requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
            entries = {item["request_id"]: item for item in manifest["requests"]}
            self.assertIsNone(_first_invalid_request_replacement(paths, config.project_id, entries, requests))

            epoch2_entry.update({"status": "QC_PENDING", "failure_class": None, "selected_asset": selected,
                                 "attempts": [attempt], "provider_submissions": 1})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            epoch3 = queue_regeneration(runtime.root, config.project_id, epoch2, reason="third bounded correction")["replacement_request_id"]
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            epoch3_entry = next(item for item in manifest["requests"] if item["request_id"] == epoch3)
            self.assertEqual((epoch3_entry["replacement_epoch"], epoch3_entry["attempts"], epoch3_entry["provider_submissions"]), (3, [], 0))

            epoch3_entry.update({"status": "QC_PENDING", "failure_class": None, "selected_asset": selected,
                                 "attempts": [attempt], "provider_submissions": 1})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            before_manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            before_requests = read_json(paths.artifact_path("output/generation_requests.json"))
            with self.assertRaisesRegex(FlowError, "CORRECTION_CHAIN_EXHAUSTED"):
                queue_regeneration(runtime.root, config.project_id, epoch3, reason="must not create epoch four")
            self.assertEqual(read_json(paths.artifact_path("output/generation_manifest.json")), before_manifest)
            self.assertEqual(read_json(paths.artifact_path("output/generation_requests.json")), before_requests)

    def test_broken_immutable_lineage_history_or_duplicate_replacement_fails_closed(self):
        mutations = {
            "broken_lineage": lambda requests, manifest, replacement_id: requests[0].update({"replacement_of": "wrong"}),
            "wrong_reason": lambda requests, manifest, replacement_id: requests[0].update({"replacement_reason": "WRONG_REASON"}),
            "old_history": lambda requests, manifest, replacement_id: manifest["requests"][0]["attempts"].append({"attempt": 99}),
            "duplicate_replacement": lambda requests, manifest, replacement_id: requests.append({
                **requests[0], "request_id": "req_duplicate", "fingerprint": "duplicate-fingerprint",
            }),
            "duplicate_manifest_replacement": lambda requests, manifest, replacement_id: manifest["requests"].append({
                **manifest["requests"][1], "request_id": "req_duplicate_manifest",
            }),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                runtime, config, paths, _old, _selected, _attempt = self._project(root)
                replacement_id = replace_qc_rejected_asset(runtime.root, config.project_id, self.OLD_REQUEST_ID, reason="mandatory QC")["replacement_request_id"]
                requests_data = read_json(paths.artifact_path("output/generation_requests.json"))
                manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
                mutate(requests_data["requests"], manifest, replacement_id)
                atomic_write_json(paths.artifact_path("output/generation_requests.json"), requests_data)
                atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
                calls: list[str] = []
                result = execute_generation(runtime.root, config.project_id, executor=self._executor(calls), execute=True, request_ids={replacement_id})
                self.assertTrue(result["blocked"])
                self.assertEqual((result["attention"], calls), ("FLOW_GENERATION_RECONCILIATION_REQUIRED", []))


if __name__ == "__main__":
    unittest.main()

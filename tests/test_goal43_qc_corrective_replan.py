from __future__ import annotations

import copy
import tempfile
import unittest

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.gemini_qc import MOTION_PLAN_VERSION
from story_auto.core.planning.service import validate_generation_requests
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.visual import default_visual_policy
from story_auto.providers.flow.service import (
    QC_CORRECTIVE_REPLANNED_STATUS,
    _first_invalid_request_replacement,
    _provider_generation_retry_authorized,
    _resolve_current_canonical_descendant,
    _runnable,
    qc_corrective_replan,
    replace_qc_rejected_asset,
)
from story_auto.providers.llm import ReasoningResult


class _FixtureRouter:
    def __init__(self) -> None:
        self.calls = []

    def reason(self, **kwargs):
        self.calls.append(kwargs)
        value = {
            "subject": "Elias Venn",
            "action": "continues examining the sealed official envelope and runs his thumb over the unbroken wax seal",
            "location": "the dim kitchen inside Marrow Bay Lighthouse",
            "composition_intent": "direct continuation from sh_0006 part 1 at the same kitchen table",
            "continuity_requirements": [
                "continue the exact moment from sh_0006 part 1",
                "the official envelope remains sealed and the wax seal remains unbroken",
            ],
            "exclusions": [
                "no lantern room",
                "no great lighthouse lens",
                "no ocean-facing gallery or tower/gallery relocation",
            ],
            "selected_reference_entity_ids": [],
            "semantic_delta": [
                "narrowed the broad lighthouse location to the dim interior kitchen",
                "made continuation and the sealed-envelope hand state explicit",
                "removed the visually conflicting lantern-room character reference",
            ],
            "reference_selection_rationale": "The available Elias reference relocates the scene to a lantern room.",
        }
        validator = kwargs.get("acceptance_validator")
        if validator:
            validator(value)
        return ReasoningResult(value, "gemini-3.6-flash", "key-fixture", "project-fixture", False, 0, 1, "f" * 64)


class Goal43QcCorrectiveReplanTests(unittest.TestCase):
    ROOT = "req_9bf6057af18642d39faf"
    REF = "req_elias_lantern_reference"

    def _project(self, root: str, *, media_type: str = "IMAGE"):
        runtime = RuntimeLayout.from_root(root)
        config = ProjectConfig("prj_goal43_trial_b_fixture")
        paths = create_project(runtime, config)
        policy = default_visual_policy()
        reference = {
            "request_id": self.REF,
            "fingerprint": "elias-reference-fingerprint",
            "purpose": "REFERENCE",
            "reference_type": "CHARACTER_REFERENCE",
            "entity_id": "char_elias_venn",
            "media_type": "IMAGE",
            "provider": "google_flow",
            "prompt": "Elias Venn in the lantern room beside the lighthouse lens and ocean gallery",
            "visual_policy": policy,
            "output_count": 1,
            "execution_tier": "STANDARD_PRODUCTION",
            "reference_asset_ids": [],
            "depends_on": [],
        }
        request = {
            "request_id": self.ROOT,
            "fingerprint": "trial-b-root-fingerprint",
            "purpose": "SHOT",
            "shot_id": "sh_0006",
            "media_type": media_type,
            "provider": "google_flow",
            "prompt": "Elias Venn at Marrow Bay Lighthouse with an official envelope",
            "visual_policy": policy,
            "output_count": 1,
            "execution_tier": "STANDARD_PRODUCTION",
            "reference_asset_ids": ["char_elias_venn"],
            "depends_on": [self.REF],
            "part_index": 1,
            "part_count": 1,
            "target_start": 40.0,
            "target_end": 48.0,
            "target_duration": 8.0,
        }
        if media_type == "VIDEO":
            request["motion_risk_analysis"] = {
                "schema_version": MOTION_PLAN_VERSION,
                "source_request_id": self.ROOT,
                "physical_complexity": "LOW",
                "anatomy_risk": "LOW",
                "looping_risk": "LOW",
                "interaction_objects": ["sealed official envelope", "wax seal"],
                "hand_object_contact": "Elias keeps his thumb on the unbroken wax seal",
                "atomic_clip": {
                    "start_state": "Elias studies the sealed official envelope at the kitchen table",
                    "action": "Elias examines the sealed official envelope and runs his thumb over the unbroken wax seal",
                    "end_state": "the envelope remains sealed in Elias's hands",
                    "natural_stillness": "Elias pauses with the unbroken wax seal visible",
                },
            }
        continuity = {
            "schema_version": "story-auto-continuity-bible/1.0.0",
            "project_id": config.project_id,
            "style": {},
            "characters": [{"entity_id": "char_elias_venn", "name": "Elias Venn"}],
            "locations": [{"entity_id": "loc_marrow_bay_lighthouse", "name": "Marrow Bay Lighthouse",
                           "constraints": ["sh_0006 occurs in the dim kitchen"]}],
            "props": [{"entity_id": "prop_official_envelope", "name": "sealed official envelope",
                       "constraints": ["wax seal remains unbroken"]}],
        }
        shot = {
            "shot_id": "sh_0006",
            "scene_id": "scn_0002",
            "start": 40.0,
            "end": 48.0,
            "subject": "Elias Venn",
            "action": "continues holding the sealed official envelope, thumb over the unbroken wax seal",
            "location_id": "loc_marrow_bay_lighthouse",
            "character_ids": ["char_elias_venn"],
            "prop_ids": ["prop_official_envelope"],
            "composition_intent": "dim kitchen interior, continuing directly from sh_0006 part 1",
            "camera_intent": "STATIC",
            "visual_emotional_purpose": "quiet continuity and restrained tension",
        }
        media = {
            "schema_version": "story-auto-media-plan/1.0.0",
            "project_id": config.project_id,
            "render_mode": "hybrid_hook",
            "shots": [{"shot_id": "sh_0006", "media_type": media_type, "target_duration": 8.0,
                       "selected_request_id": self.ROOT}],
        }
        atomic_write_json(paths.artifact_path("output/shot_plan.json"), {
            "schema_version": "story-auto-shot-plan/1.0.0", "project_id": config.project_id, "shots": [shot]})
        atomic_write_json(paths.artifact_path("output/continuity_bible.json"), continuity)
        atomic_write_json(paths.artifact_path("output/media_plan.json"), media)
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), {
            "schema_version": "story-auto-generation-requests/1.0.0",
            "project_id": config.project_id,
            "requests": [reference, request],
            **({"motion_plan_version": MOTION_PLAN_VERSION} if media_type == "VIDEO" else {}),
        })
        root_selected = {"path": "assets/image/root.png", "sha256": "a" * 64, "attempt": 1,
                         "production_qc": "REJECTED"}
        if media_type == "VIDEO":
            root_selected["temporal_qc"] = "APPROVED"
        root_attempt = {"attempt": 1, "status": "SUCCEEDED", "dispatch_confirmed": True,
                        "attribution_state": "CONFIRMED", "provider_job_id": "root-job"}
        results = {"CONTINUITY": "FAIL"}
        if media_type == "VIDEO":
            results.update({"SKIN_REALISM": "PASS", "LIGHTING_NATURALISM": "PASS", "MATERIAL_REALISM": "PASS",
                            "COMPOSITION_NATURALISM": "PASS", "AI_POLISH": "PASS", "TECHNICAL_VALIDITY": "PASS"})
        root_review = {"status": "REJECTED", "failure_class": "NATURALNESS_QC_REJECTED",
                       "report": {"results": results,
                                  "reason": "Generated lantern room instead of the dim kitchen"}}
        atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
            "schema_version": "story-auto-generation-manifest/1.0.0",
            "project_id": config.project_id,
            "requests": [
                {"request_id": self.REF, "request_identity_sha256": reference["fingerprint"],
                 "related_identity": "char_elias_venn", "media_type": "IMAGE", "provider": "google_flow",
                 "prompt_sha256": reference["fingerprint"], "reference_asset_hashes": [], "attempts": [],
                 "status": "SUCCEEDED", "selected_asset": {"path": "assets/image/elias-lantern.png", "sha256": "c" * 64}},
                {"request_id": self.ROOT, "request_identity_sha256": request["fingerprint"],
                 "related_identity": "sh_0006", "media_type": media_type, "provider": "google_flow",
                 "prompt_sha256": "root-prompt", "reference_asset_hashes": [], "attempts": [root_attempt],
                 "provider_submissions": 1, "status": "FAILED_RETRYABLE",
                 "failure_class": "NATURALNESS_QC_REJECTED", "selected_asset": root_selected,
                 "quality_reviews": [root_review]},
            ],
        })
        return runtime, config, paths

    def _assert_sh_0006_append_only_correction(self, media_type: str):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, media_type=media_type)
            epoch1 = replace_qc_rejected_asset(
                runtime.root, config.project_id, self.ROOT, reason="first mandatory QC replacement")
            epoch1_id = epoch1["replacement_request_id"]
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            epoch1_entry = next(item for item in manifest["requests"] if item["request_id"] == epoch1_id)
            epoch1_entry.update({
                "status": "FAILED_RETRYABLE",
                "failure_class": "NATURALNESS_QC_REJECTED",
                "provider_submissions": 1,
                "attempts": [{"attempt": 1, "status": "SUCCEEDED", "dispatch_confirmed": True,
                              "attribution_state": "CONFIRMED", "provider_job_id": "epoch-1-job"}],
                "selected_asset": {"path": "assets/image/epoch-1.png", "sha256": "b" * 64,
                                   "attempt": 1, "production_qc": "REJECTED"},
                "quality_reviews": [{"status": "REJECTED", "failure_class": "NATURALNESS_QC_REJECTED",
                                     "report": {"results": {"CONTINUITY": "FAIL"},
                                                "reason": "Lantern-room reference relocated the continuation"}}],
            })
            if media_type == "VIDEO":
                epoch1_entry["selected_asset"]["temporal_qc"] = "APPROVED"
                epoch1_entry["quality_reviews"][0]["report"]["results"].update({
                    "SKIN_REALISM": "PASS", "LIGHTING_NATURALISM": "PASS", "MATERIAL_REALISM": "PASS",
                    "COMPOSITION_NATURALISM": "PASS", "AI_POLISH": "PASS", "TECHNICAL_VALIDITY": "PASS",
                })
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            before = copy.deepcopy({item["request_id"]: item for item in manifest["requests"]})
            epoch1_request_before = copy.deepcopy(next(
                item for item in read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
                if item["request_id"] == epoch1_id))
            router = _FixtureRouter()

            result = qc_corrective_replan(
                runtime.root, config.project_id, epoch1_id,
                reason="correct Trial B sh_0006 continuity semantics", router=router)

            self.assertEqual(result["root_request_id"], self.ROOT)
            self.assertEqual(result["supersedes_request_id"], epoch1_id)
            self.assertEqual(result["correction_epoch"], 2)
            self.assertEqual(result["gemini_model"], "gemini-3.6-flash")
            self.assertEqual(result["provider_submissions"], 0)
            self.assertEqual(len(router.calls), 1)

            requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
            entries = {item["request_id"]: item for item in read_json(
                paths.artifact_path("output/generation_manifest.json"))["requests"]}
            correction_id = result["correction_request_id"]
            correction = next(item for item in requests if item["request_id"] == correction_id)
            self.assertEqual(correction["media_type"], media_type)
            self.assertNotIn(self.ROOT, {item["request_id"] for item in requests})
            self.assertNotIn(epoch1_id, {item["request_id"] for item in requests})
            lowered = correction["prompt"].lower()
            for required in ("dim kitchen", "continuation", "sealed", "unbroken wax seal"):
                self.assertIn(required, lowered)
            for exclusion in ("no lantern room", "no great lighthouse lens", "no ocean-facing gallery", "tower/gallery relocation"):
                self.assertIn(exclusion, lowered)
            self.assertEqual(correction["reference_asset_ids"], [])
            self.assertEqual(correction["depends_on"], [])
            delta = correction["corrective_replan_provenance"]["reference_selection_delta"]
            self.assertEqual(delta["removed_reference_entity_ids"], ["char_elias_venn"])
            self.assertEqual(correction["root_request_id"], self.ROOT)
            self.assertEqual(correction["supersedes_request_id"], epoch1_id)
            transaction = read_json(next(paths.artifact_path(
                "output/qc_corrective_replan_transactions").glob("*.prepared.json")))
            self.assertEqual(transaction["superseded_request"], epoch1_request_before)

            for old_id in (self.ROOT, epoch1_id):
                self.assertEqual(entries[old_id]["attempts"], before[old_id]["attempts"])
                self.assertEqual(entries[old_id]["selected_asset"], before[old_id]["selected_asset"])
                self.assertEqual(entries[old_id]["quality_reviews"], before[old_id]["quality_reviews"])
                self.assertFalse(_provider_generation_retry_authorized(entries[old_id]))
            self.assertEqual(entries[epoch1_id]["status"], QC_CORRECTIVE_REPLANNED_STATUS)
            self.assertTrue(_provider_generation_retry_authorized(entries[correction_id]))
            self.assertTrue(_runnable(correction, entries))
            if media_type == "VIDEO":
                self.assertEqual(correction["motion_risk_analysis"], epoch1_request_before["motion_risk_analysis"])
                self.assertEqual(correction["corrective_motion_evidence"]["scope"], "CONTINUITY_ONLY")
                self.assertIn("One visible action only", correction["prompt"])
                self.assertIn("Physically causal motion", correction["prompt"])
                validate_generation_requests(
                    read_json(paths.artifact_path("output/generation_requests.json")),
                    read_json(paths.artifact_path("output/media_plan.json")),
                    read_json(paths.artifact_path("output/continuity_bible.json")),
                )
            self.assertEqual(
                _resolve_current_canonical_descendant(paths, config.project_id, self.ROOT, requests, entries),
                correction_id,
            )
            self.assertIsNone(_first_invalid_request_replacement(paths, config.project_id, entries, requests))

            again = qc_corrective_replan(
                runtime.root, config.project_id, epoch1_id,
                reason="idempotent operation retry", router=router)
            self.assertTrue(again["idempotent"])
            self.assertEqual(again["correction_request_id"], correction_id)
            self.assertEqual(len(router.calls), 1)

    def test_sh_0006_image_correction_preserves_image_support(self):
        self._assert_sh_0006_append_only_correction("IMAGE")

    def test_sh_0006_video_correction_preserves_approved_motion_evidence(self):
        self._assert_sh_0006_append_only_correction("VIDEO")

    def test_correction_fails_closed_without_confirmed_current_qc_rejection(self):
        mutations = {
            "unconfirmed attribution": lambda entry: entry["attempts"][0].update({"attribution_state": "UNCERTAIN"}),
            "latest review approved": lambda entry: entry["quality_reviews"].append({
                "status": "APPROVED", "failure_class": None, "report": {}}),
            "not current terminal state": lambda entry: entry.update({"status": "QC_PENDING"}),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                runtime, config, paths = self._project(root)
                manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
                entry = next(item for item in manifest["requests"] if item["request_id"] == self.ROOT)
                mutate(entry)
                atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
                before_requests = read_json(paths.artifact_path("output/generation_requests.json"))
                router = _FixtureRouter()
                with self.assertRaisesRegex(Exception, "QC_CORRECTIVE_REPLAN_NOT_ELIGIBLE"):
                    qc_corrective_replan(
                        runtime.root, config.project_id, self.ROOT,
                        reason="must fail before semantic replanning", router=router)
                self.assertEqual(router.calls, [])
                self.assertEqual(read_json(paths.artifact_path("output/generation_requests.json")), before_requests)


if __name__ == "__main__":
    unittest.main()

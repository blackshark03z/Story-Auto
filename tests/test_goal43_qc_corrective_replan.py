from __future__ import annotations

import copy
import tempfile
import unittest
from unittest.mock import patch

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.gemini_qc import MOTION_PLAN_VERSION
from story_auto.core.planning.qc_corrective import validate_qc_corrective_intent
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
    supersede_invalid_pending_qc_corrective_child,
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


class _ConflictingReferenceRouter(_FixtureRouter):
    """Models the pre-fix Gemini result that retained the lantern-room reference."""
    def reason(self, **kwargs):
        self.calls.append(kwargs)
        value = {
            "subject": "Elias Venn",
            "action": "continues examining the sealed official envelope and runs his thumb over the unbroken wax seal",
            "location": "the dim kitchen inside Marrow Bay Lighthouse",
            "composition_intent": "direct continuation from sh_0006 part 1 at the same kitchen table",
            "continuity_requirements": ["continue the exact moment from sh_0006 part 1"],
            "exclusions": ["no lantern room", "no great lighthouse lens", "no ocean-facing gallery"],
            "selected_reference_entity_ids": ["char_elias_venn"],
            "semantic_delta": ["locked the scene to the dim kitchen"],
            "reference_selection_rationale": "incorrectly retained the character reference",
        }
        validator = kwargs.get("acceptance_validator")
        if validator:
            validator(value)
        return ReasoningResult(value, "gemini-3.6-flash", "key-fixture", "project-fixture", False, 0, 1, "e" * 64)


class _FullReplanRouter(_FixtureRouter):
    """Fixture for a temporal-rejected VIDEO that must receive fresh mechanics."""
    def reason(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("task") == "motion_planning":
            value = {
                "start_state": "Elias holds the official sealed letter at chest height in the dim kitchen",
                "end_state": "Elias has lowered the sealed letter while remaining in the dim kitchen",
                "meaningful_actions": ["Elias slowly lowers the official sealed letter"],
                "interaction_objects": ["official sealed letter"],
                "hand_object_contact": "Elias keeps both hands on the letter throughout the slow lowering motion",
                "action_dependencies": ["the letter stays in Elias's hands"],
                "physical_complexity": "LOW",
                "anatomy_risk": "LOW",
                "looping_risk": "LOW",
                "atomic_clips": [{
                    "start_state": "Elias holds the official sealed letter at chest height in the dim kitchen",
                    "action": "Elias slowly lowers the official sealed letter",
                    "end_state": "the sealed letter rests lower in Elias's hands",
                    "natural_stillness": "Elias pauses naturally after lowering the letter",
                }],
            }
        else:
            value = {
                "subject": "Elias Venn",
                "action": "Elias slowly lowers the official sealed letter in quiet reflection",
                "location": "the dim kitchen inside Marrow Bay Lighthouse",
                "composition_intent": "direct continuation in the same dim kitchen scene",
                "continuity_requirements": [
                    "direct continuation from the preceding kitchen shot",
                    "Elias remains with the official sealed letter",
                ],
                "exclusions": [
                    "no lantern room",
                    "no great lighthouse lens",
                    "no ocean-facing gallery or tower/gallery relocation",
                ],
                "selected_reference_entity_ids": [],
                "semantic_delta": [
                    "restored the dim kitchen continuation",
                    "restored the required slow lowering action",
                    "removed the conflicting lantern-room reference",
                ],
                "reference_selection_rationale": "No available reference is compatible with the dim kitchen.",
            }
        validator = kwargs.get("acceptance_validator")
        if validator:
            validator(value)
        return ReasoningResult(value, "gemini-3.6-flash", "key-fixture", "project-fixture", False, 0, 1,
                               "d" * 64)


class _ParaphrasingLockedCoreRouter(_FullReplanRouter):
    """Returns a plausible but wrong whole-shot rewrite to prove core overlay."""
    def reason(self, **kwargs):
        if kwargs.get("task") == "motion_planning":
            return super().reason(**kwargs)
        self.calls.append(kwargs)
        value = {
            "subject": "a weathered lighthouse keeper",
            "action": "reflects on an unfamiliar document without a required hand action",
            "location": "the ocean-facing gallery beside the great lantern lens",
            "composition_intent": "a new gallery tableau",
            "continuity_requirements": ["an unrelated moment in a different room"],
            "exclusions": ["no sudden cuts"],
            "selected_reference_entity_ids": ["char_elias_venn"],
            "semantic_delta": ["proposed an alternate gallery staging"],
            "reference_selection_rationale": "incorrectly selected the gallery-biased character reference",
        }
        validator = kwargs.get("acceptance_validator")
        if validator:
            validator(value)
        return ReasoningResult(value, "gemini-3.6-flash", "key-fixture", "project-fixture", False, 0, 1,
                               "p" * 64)


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
            candidates = router.calls[0]["prompt"]
            self.assertIn("Elias Venn in the lantern room beside the lighthouse lens and ocean gallery", candidates)
            self.assertIn("provider_reference_capacity", candidates)

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

    def test_sh_0007_temporal_rejection_uses_full_replan_and_never_attaches_conflicting_reference(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, media_type="VIDEO")
            requests_data = read_json(paths.artifact_path("output/generation_requests.json"))
            char_reference, request = requests_data["requests"]
            prop_reference = copy.deepcopy(char_reference)
            prop_reference.update({
                "request_id": "req_prop_letter_reference", "fingerprint": "prop-reference-fingerprint",
                "reference_type": "PROP_REFERENCE", "entity_id": "prop_letter",
                "prompt": "Official sealed letter under the dim kitchen brass clock",
            })
            location_reference = copy.deepcopy(char_reference)
            location_reference.update({
                "request_id": "req_kitchen_reference", "fingerprint": "kitchen-reference-fingerprint",
                "reference_type": "LOCATION_REFERENCE", "entity_id": "loc_marrow_bay_lighthouse",
                "prompt": "Marrow Bay Lighthouse kitchen with a brass clock",
            })
            request.update({
                "shot_id": "sh_0007",
                "prompt": "Elias holds the letter elevated near chest level and remains still in broad lighthouse context.",
                "reference_asset_ids": ["char_elias_venn", "prop_letter", "loc_marrow_bay_lighthouse"],
                "depends_on": [char_reference["request_id"], prop_reference["request_id"], location_reference["request_id"]],
            })
            requests_data["requests"] = [char_reference, prop_reference, location_reference, request]
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), requests_data)
            continuity = read_json(paths.artifact_path("output/continuity_bible.json"))
            continuity["locations"][0]["constraints"] = ["sh_0007 continues in the dim kitchen inside Marrow Bay Lighthouse"]
            continuity["props"] = [{"entity_id": "prop_letter", "name": "official sealed letter",
                                    "constraints": ["the letter remains sealed in Elias's hands"]}]
            atomic_write_json(paths.artifact_path("output/continuity_bible.json"), continuity)
            shot_plan = read_json(paths.artifact_path("output/shot_plan.json"))
            shot_plan["shots"][0].update({
                "shot_id": "sh_0007",
                "action": "Elias slowly lowers the official sealed letter as he stands still in quiet reflection.",
                "prop_ids": ["prop_letter"],
                "composition_intent": "direct continuation in the dim kitchen from sh_0006",
            })
            preceding = copy.deepcopy(shot_plan["shots"][0])
            preceding.update({
                "shot_id": "sh_0006", "start": 32.0, "end": 40.0,
                "action": "Elias examines the official sealed letter in the dim kitchen.",
                "camera_intent": "medium framing against the dim kitchen window",
                "composition_intent": "dim kitchen continuity before sh_0007",
            })
            shot_plan["shots"] = [preceding, shot_plan["shots"][0]]
            atomic_write_json(paths.artifact_path("output/shot_plan.json"), shot_plan)
            media_plan = read_json(paths.artifact_path("output/media_plan.json"))
            media_plan["shots"][0].update({"shot_id": "sh_0007", "selected_request_id": self.ROOT})
            atomic_write_json(paths.artifact_path("output/media_plan.json"), media_plan)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            root_entry = next(item for item in manifest["requests"] if item["request_id"] == self.ROOT)
            root_entry.update({"media_type": "VIDEO", "failure_class": "REJECT_BACKGROUND", "quality_reviews": []})
            root_entry["selected_asset"].update({
                "temporal_qc": "REJECTED",
                "temporal_reviews": [{"report": {"state": "REJECT_BACKGROUND", "eligible": False}}],
            })
            for reference in (prop_reference, location_reference):
                manifest["requests"].append({
                    "request_id": reference["request_id"], "request_identity_sha256": reference["fingerprint"],
                    "related_identity": reference["entity_id"], "media_type": "IMAGE", "provider": "google_flow",
                    "prompt_sha256": reference["fingerprint"], "reference_asset_hashes": [], "attempts": [],
                    "provider_submissions": 1, "status": "SUCCEEDED",
                    "selected_asset": {"path": f"assets/image/{reference['request_id']}.png", "sha256": "e" * 64},
                })
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            before = copy.deepcopy(root_entry)

            router = _FullReplanRouter()
            result = qc_corrective_replan(runtime.root, config.project_id, self.ROOT,
                                          reason="full replan after temporal background rejection", router=router)
            self.assertEqual(len(router.calls), 2)
            self.assertIn("adjacent_scene_continuity", router.calls[0]["prompt"])
            self.assertIn("dim kitchen inside Marrow Bay Lighthouse", router.calls[0]["prompt"])
            self.assertIn('"required_atomic_clip_count": 1', router.calls[1]["prompt"])
            correction_id = result["correction_request_id"]
            entries = {item["request_id"]: item for item in read_json(
                paths.artifact_path("output/generation_manifest.json"))["requests"]}
            correction = next(item for item in read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
                              if item["request_id"] == correction_id)
            lowered = correction["prompt"].lower()
            self.assertEqual(correction["media_type"], "VIDEO")
            self.assertIn("dim kitchen", lowered)
            self.assertIn("slowly lowers the official sealed letter", lowered)
            self.assertNotIn("remain still", lowered.split("one visible action only:", 1)[1].split("end state:", 1)[0])
            self.assertIn("no lantern room", lowered)
            self.assertEqual(correction["reference_asset_ids"], [])
            self.assertEqual(correction["depends_on"], [])
            self.assertEqual(correction["corrective_replan_provenance"]["correction_mode"], "FULL_REPLAN")
            self.assertIn("motion_replan", correction["corrective_replan_provenance"])
            self.assertEqual(correction["corrective_motion_evidence"]["scope"], "FULL_REPLAN")
            self.assertEqual(entries[correction_id]["attempts"], [])
            self.assertEqual(entries[correction_id]["provider_submissions"], 0)
            self.assertEqual(entries[self.ROOT]["attempts"], before["attempts"])
            self.assertEqual(entries[self.ROOT]["selected_asset"], before["selected_asset"])
            self.assertFalse(_provider_generation_retry_authorized(entries[self.ROOT]))
            again = qc_corrective_replan(runtime.root, config.project_id, self.ROOT,
                                         reason="idempotent full-replan retry", router=router)
            self.assertTrue(again["idempotent"])
            self.assertEqual(again["correction_request_id"], correction_id)
            self.assertEqual(len(router.calls), 2)

    def test_full_replan_locks_canonical_core_over_paraphrased_model_rewrite(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, media_type="VIDEO")
            requests_data = read_json(paths.artifact_path("output/generation_requests.json"))
            request = requests_data["requests"][1]
            request.update({"shot_id": "sh_0007", "target_start": 40.0,
                            "target_end": 42.970833, "target_duration": 2.970833})
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), requests_data)
            shot_plan = read_json(paths.artifact_path("output/shot_plan.json"))
            current = shot_plan["shots"][0]
            current.update({
                "shot_id": "sh_0007", "start": 40.0, "end": 42.970833,
                "action": "Elias slowly lowers the official sealed envelope while his thumb stays on the unbroken wax seal",
                "composition_intent": "direct continuation in the dim kitchen from sh_0006",
            })
            preceding = copy.deepcopy(current)
            preceding.update({
                "shot_id": "sh_0006", "start": 32.0, "end": 40.0,
                "action": "Elias examines the official sealed envelope in the dim kitchen.",
                "composition_intent": "dim kitchen continuity before sh_0007",
            })
            shot_plan["shots"] = [preceding, current]
            atomic_write_json(paths.artifact_path("output/shot_plan.json"), shot_plan)
            media_plan = read_json(paths.artifact_path("output/media_plan.json"))
            media_plan["shots"][0].update({"shot_id": "sh_0007", "target_duration": 2.970833})
            atomic_write_json(paths.artifact_path("output/media_plan.json"), media_plan)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            root_entry = next(item for item in manifest["requests"] if item["request_id"] == self.ROOT)
            root_entry.update({"failure_class": "USABLE_TEMPORAL_WINDOW_INVALID", "quality_reviews": []})
            root_entry["selected_asset"].update({
                "temporal_qc": "REJECTED",
                "temporal_reviews": [{"report": {"state": "USABLE_TEMPORAL_WINDOW_INVALID", "eligible": False}}],
                "production_qc": "PENDING",
            })
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)

            router = _ParaphrasingLockedCoreRouter()
            result = qc_corrective_replan(runtime.root, config.project_id, self.ROOT,
                                          reason="lock canonical semantics before corrective mechanics", router=router)
            correction_id = result["correction_request_id"]
            requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
            correction = next(item for item in requests if item["request_id"] == correction_id)
            provenance = correction["corrective_replan_provenance"]
            core = provenance["canonical_locked_core"]
            effective = correction["corrected_semantic_intent"]

            self.assertEqual(core["logical_shot_id"], "sh_0007")
            self.assertEqual(core["subject"], effective["subject"])
            self.assertEqual(core["location"], effective["location"])
            self.assertEqual(core["action"], effective["action"])
            self.assertEqual(core["continuity_requirements"], effective["continuity_requirements"])
            self.assertEqual(core["media_type"], correction["media_type"])
            self.assertEqual(core["target_duration"], correction["target_duration"])
            self.assertIn("dim kitchen", correction["prompt"].lower())
            self.assertIn("no ocean-facing gallery", correction["prompt"].lower())
            self.assertEqual(correction["reference_asset_ids"], [])
            self.assertEqual(correction["depends_on"], [])
            self.assertIn("location", provenance["non_authoritative_locked_core_overrides"])
            self.assertEqual(provenance["non_authoritative_model_output"]["location"],
                             "the ocean-facing gallery beside the great lantern lens")
            entries = {item["request_id"]: item for item in read_json(
                paths.artifact_path("output/generation_manifest.json"))["requests"]}
            self.assertEqual(entries[correction_id]["attempts"], [])
            self.assertEqual(entries[correction_id]["provider_submissions"], 0)
            self.assertFalse(_provider_generation_retry_authorized(entries[self.ROOT]))
            again = qc_corrective_replan(runtime.root, config.project_id, self.ROOT,
                                         reason="idempotent locked-core retry", router=router)
            self.assertTrue(again["idempotent"])
            self.assertEqual(again["correction_request_id"], correction_id)

    def test_short_usable_window_temporal_rejection_is_eligible_for_full_replan(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, media_type="VIDEO")
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            entry = next(item for item in manifest["requests"] if item["request_id"] == self.ROOT)
            entry.update({"failure_class": "USABLE_TEMPORAL_WINDOW_INVALID", "quality_reviews": []})
            entry["selected_asset"].update({
                "temporal_qc": "REJECTED",
                "temporal_reviews": [{"report": {
                    "state": "USABLE_TEMPORAL_WINDOW_INVALID", "eligible": False,
                    "usable_start": 0.0, "usable_end": 2.5,
                }}],
                "production_qc": "PENDING",
            })
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            result = qc_corrective_replan(runtime.root, config.project_id, self.ROOT,
                                          reason="target duration exceeds usable temporal window", router=_FullReplanRouter())
            correction = next(item for item in read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
                              if item["request_id"] == result["correction_request_id"])
            self.assertEqual(correction["corrective_replan_provenance"]["correction_mode"], "FULL_REPLAN")

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

    def test_conflicting_reference_is_removed_before_child_creation(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, media_type="VIDEO")
            router = _ConflictingReferenceRouter()
            result = qc_corrective_replan(
                runtime.root, config.project_id, self.ROOT,
                reason="remove the lantern-room reference", router=router)
            self.assertEqual(len(router.calls), 1)
            requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
            correction = next(item for item in requests if item["request_id"] == result["correction_request_id"])
            self.assertEqual(correction["reference_asset_ids"], [])
            policy = correction["corrective_replan_provenance"]["reference_policy"]
            self.assertEqual(policy["removed_conflicting_reference_entity_ids"], ["char_elias_venn"])

    def test_reference_selection_cannot_exceed_flow_capacity(self):
        value = _FixtureRouter().reason().value
        value["selected_reference_entity_ids"] = ["char_elias_venn", "prop_official_envelope"]
        with self.assertRaisesRegex(Exception, "QC_CORRECTIVE_REPLAN_REFERENCE_CAPACITY_INVALID"):
            validate_qc_corrective_intent(
                value, reference_entity_ids={"char_elias_venn", "prop_official_envelope"}, reference_capacity=1)

    def test_pre_dispatch_supersession_replaces_only_invalid_untouched_corrective_child(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, media_type="VIDEO")
            router = _ConflictingReferenceRouter()
            # Recreate the exact historical defect under a narrow test-only
            # bypass, then verify the recovery path itself is fail-closed.
            with patch("story_auto.providers.flow.service._require_valid_corrective_reference_policy",
                       return_value={"reference_capacity": 1,
                                     "selected_reference_entity_ids": ["char_elias_venn"],
                                     "effective_reference_entity_ids": ["char_elias_venn"],
                                     "conflicts": []}):
                bad = qc_corrective_replan(
                    runtime.root, config.project_id, self.ROOT,
                    reason="historical pre-fix bad corrective child", router=router)
            old_id = bad["correction_request_id"]
            before_request = copy.deepcopy(next(item for item in read_json(
                paths.artifact_path("output/generation_requests.json"))["requests"] if item["request_id"] == old_id))
            before_entry = copy.deepcopy(next(item for item in read_json(
                paths.artifact_path("output/generation_manifest.json"))["requests"] if item["request_id"] == old_id))

            # This operation is available only before any provider boundary.
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            blocked_entry = next(item for item in manifest["requests"] if item["request_id"] == old_id)
            blocked_entry["attempts"] = [{"attempt": 1, "status": "SUBMITTED"}]
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            with self.assertRaisesRegex(Exception, "QC_CORRECTIVE_PRE_DISPATCH_SUPERSESSION_NOT_ELIGIBLE"):
                supersede_invalid_pending_qc_corrective_child(
                    runtime.root, config.project_id, old_id, reason="must reject provider-bound child")
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
                **manifest,
                "requests": [before_entry if item["request_id"] == old_id else item for item in manifest["requests"]],
            })

            result = supersede_invalid_pending_qc_corrective_child(
                runtime.root, config.project_id, old_id, reason="remove forbidden effective reference")
            new_id = result["replacement_request_id"]
            self.assertFalse(result["idempotent"])
            self.assertEqual(result["effective_references"], [])
            self.assertEqual(result["reference_capacity"], 1)
            requests = read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
            entries = {item["request_id"]: item for item in read_json(
                paths.artifact_path("output/generation_manifest.json"))["requests"]}
            replacement = next(item for item in requests if item["request_id"] == new_id)
            self.assertNotIn(old_id, {item["request_id"] for item in requests})
            self.assertEqual((replacement["reference_asset_ids"], replacement["depends_on"]), ([], []))
            self.assertTrue(_runnable(replacement, entries))
            self.assertEqual(entries[old_id]["attempts"], before_entry["attempts"])
            self.assertEqual(entries[old_id]["provider_submissions"], before_entry.get("provider_submissions", 0))
            self.assertEqual(entries[old_id]["selected_asset"], before_entry["selected_asset"])
            transaction = read_json(next(paths.artifact_path(
                "output/qc_corrective_pre_dispatch_supersession_transactions").glob("*.prepared.json")))
            self.assertEqual(transaction["superseded_request"], before_request)
            self.assertEqual(_resolve_current_canonical_descendant(
                paths, config.project_id, self.ROOT, requests, entries), new_id)
            self.assertIsNone(_first_invalid_request_replacement(paths, config.project_id, entries, requests))
            again = supersede_invalid_pending_qc_corrective_child(
                runtime.root, config.project_id, old_id, reason="idempotent retry")
            self.assertTrue(again["idempotent"])
            self.assertEqual(again["replacement_request_id"], new_id)


if __name__ == "__main__":
    unittest.main()

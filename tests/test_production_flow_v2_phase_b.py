from __future__ import annotations

import hashlib
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from story_auto.application import OperatorService
from story_auto.application.production_coordinator import ProductionCoordinator
from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project, load_project
from story_auto.core.visual import NATURALNESS_QC_FIELDS
from story_auto.providers.flow import apply_auto_accept_policy
from story_auto.providers.flow.service import _canonical_locked_corrective_core
from story_auto.providers.llm import ReasoningResult


class _PassingAutomaticQCRouter:
    def __init__(self):
        self.calls = []

    def reason(self, **kwargs):
        self.calls.append(kwargs)
        value = {
            "results": {field: "PASS" for field in NATURALNESS_QC_FIELDS},
            "visible_provider_watermark": False,
            "alignment_classification": "PASS_DIRECT",
            "confidence": "HIGH",
            "observed": "The generated image directly depicts the requested narrated moment.",
            "contradictions": [],
        }
        return ReasoningResult(value, "gemini-fixture", "key-fixture", "project-fixture",
                               False, 0, 1, "a" * 64)


def _fixture(app: OperatorService, project_id: str, policy: str, count: int = 2):
    app.create_project(project_id=project_id, render_mode="full_image", settings={"qc_policy": policy},
                       content="# Policy fixture\n\n## Narration\n\nProvider-free visual evidence.")
    paths, _ = app._project(project_id)
    asset = paths.artifact_path("assets/selected.png")
    asset.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1280, 720), "navy").save(asset, "PNG")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    requests, entries = [], []
    for number in range(count):
        request_id = f"req_qc_{number:03d}"
        fingerprint = hashlib.sha256(request_id.encode()).hexdigest()
        request = {"request_id": request_id, "fingerprint": fingerprint, "purpose": "SHOT",
                   "shot_id": f"sh_{number:04d}", "media_type": "IMAGE", "provider": "google_flow", "prompt": "fixture"}
        entry = {"request_id": request_id, "request_identity_sha256": fingerprint,
                 "related_identity": request["shot_id"], "media_type": "IMAGE", "provider": "google_flow",
                 "status": "QC_PENDING", "failure_class": None,
                 "attempts": [{"attempt": 1, "status": "SUCCEEDED", "attribution_state": "CONFIRMED",
                               "asset_path": "assets/selected.png", "asset_sha256": digest}],
                 "selected_asset": {"path": "assets/selected.png", "sha256": digest, "attempt": 1,
                                    "production_qc": "PENDING"}}
        requests.append(request); entries.append(entry)
    atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": requests})
    atomic_write_json(paths.artifact_path("output/shot_plan.json"), {"shots": [
        {"shot_id": item["shot_id"], "action": "Provider-free fixture moment.",
         "source_text": "Provider-free fixture moment.", "atmospheric": False}
        for item in requests
    ]})
    atomic_write_json(paths.artifact_path("output/generation_manifest.json"),
                      {"schema_version": "story-auto-generation-manifest/1.0.0", "project_id": project_id, "requests": entries})
    return paths


class PhaseBQualityPolicyTests(unittest.TestCase):
    def test_new_projects_persist_auto_default_and_legacy_projects_keep_manual_effective_policy(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            app.create_project(project_id="prj_default", content="# Default\n\n## Narration\n\nText.")
            paths, config = app._project("prj_default")
            self.assertEqual(config.settings["qc_policy"], "AUTO_ACCEPT")
            legacy = create_project(RuntimeLayout.from_root(root), ProjectConfig("prj_legacy", render_mode="full_image", settings={}), "# Legacy\n\n## Narration\n\nText.")
            project = read_json(legacy.project_file); project["settings"].pop("qc_policy")
            atomic_write_json(legacy.project_file, project)
            self.assertEqual(app.query_qc_status("prj_legacy")["policy"], "MANUAL_REVIEW")
            self.assertNotIn("qc_policy", read_json(legacy.project_file)["settings"])

    def test_auto_accept_records_system_policy_decisions_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root); paths = _fixture(app, "prj_auto", "AUTO_ACCEPT", 42)
            router = _PassingAutomaticQCRouter()
            first = app.apply_qc_policy("prj_auto", router=router)
            saved = read_json(paths.artifact_path("output/generation_manifest.json"))
            self.assertEqual((first["accepted_assets"], first["provider_dispatch_delta"], first["ineligible_assets"]), (42, 0, []))
            self.assertTrue(all(item["status"] == "SUCCEEDED" and item["selected_asset"]["production_qc"] == "AUTO_ACCEPTED" for item in saved["requests"]))
            decision = saved["requests"][0]["quality_reviews"][-1]
            self.assertEqual((decision["decision"], decision["disposition"], decision["actor"], decision["policy"]),
                             ("ACCEPT", "AUTO_ACCEPTED", "SYSTEM", "AUTO_ACCEPT"))
            self.assertEqual((decision["automated_quality_evaluation"]["model"],
                              saved["requests"][0]["selected_asset"]["alignment_classification"]),
                             ("gemini-fixture", "PASS_DIRECT"))
            self.assertEqual(len(router.calls), 42)
            self.assertEqual(app.query_qc_status("prj_auto")["status"], "COMPLETE")
            second = app.apply_qc_policy("prj_auto", router=router)
            self.assertEqual((second["accepted_assets"], second["already_auto_accepted_assets"]), (0, 42))
            self.assertEqual(len(router.calls), 42)
            self.assertEqual(read_json(paths.artifact_path("output/generation_manifest.json")), saved)

    def test_auto_accept_never_accepts_failed_ambiguous_missing_or_wrong_type_assets(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root); paths = _fixture(app, "prj_auto_negative", "AUTO_ACCEPT", 4)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            manifest["requests"][0]["selected_asset"]["path"] = "assets/missing.png"
            wrong_type = paths.artifact_path("assets/wrong-type.txt"); wrong_type.write_text("not an image", encoding="utf-8")
            manifest["requests"][1]["selected_asset"].update({"path": "assets/wrong-type.txt", "sha256": hashlib.sha256(wrong_type.read_bytes()).hexdigest()})
            manifest["requests"][2].update({"status": "FAILED_RETRYABLE", "failure_class": "FLOW_TIMEOUT"})
            manifest["requests"][3].update({"status": "AMBIGUOUS", "failure_class": "OUTPUT_ATTRIBUTION_AMBIGUOUS"})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            router = _PassingAutomaticQCRouter()
            result = app.apply_qc_policy("prj_auto_negative", router=router)
            saved = read_json(paths.artifact_path("output/generation_manifest.json"))
            self.assertEqual(result["accepted_assets"], 0)
            self.assertEqual(saved["requests"][0]["selected_asset"]["production_qc"], "PENDING")
            self.assertEqual(saved["requests"][1]["selected_asset"]["production_qc"], "PENDING")
            self.assertEqual((saved["requests"][2]["status"], saved["requests"][3]["status"]), ("FAILED_RETRYABLE", "AMBIGUOUS"))
            self.assertEqual(router.calls, [])

    def test_auto_accept_rejects_a_gemini_naturalness_failure_without_provider_dispatch(self):
        class RejectingRouter(_PassingAutomaticQCRouter):
            def reason(self, **kwargs):
                result = super().reason(**kwargs)
                result.value["results"]["AI_POLISH"] = "FAIL"
                result.value["observed"] = "Visible synthetic facial treatment."
                return result

        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root); paths = _fixture(app, "prj_auto_reject", "AUTO_ACCEPT", 1)
            result = app.apply_qc_policy("prj_auto_reject", router=RejectingRouter())
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((result["accepted_assets"], result["rejected_assets"], result["provider_dispatch_delta"]),
                             (0, 1, 0))
            self.assertEqual((entry["status"], entry["failure_class"], entry["selected_asset"]["production_qc"]),
                             ("FAILED_RETRYABLE", "NATURALNESS_QC_REJECTED", "REJECTED"))
            self.assertEqual(entry["quality_reviews"][-1]["selected_asset_sha256"],
                             entry["selected_asset"]["sha256"])

    def test_auto_accept_qc_rejection_becomes_bounded_automatic_corrective_recovery(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root); paths = _fixture(app, "prj_auto_recovery", "AUTO_ACCEPT", 1)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            entry = manifest["requests"][0]
            selected = entry["selected_asset"]
            entry["attempts"][0].update({"dispatch_confirmation_state":"CONFIRMED", "dispatch_confirmed":True})
            entry.update({"status":"FAILED_RETRYABLE", "failure_class":"NATURALNESS_QC_REJECTED"})
            selected["production_qc"] = "REJECTED"
            entry["quality_reviews"] = [{
                "status":"REJECTED", "failure_class":"NATURALNESS_QC_REJECTED",
                "selected_asset_path":selected["path"], "selected_asset_sha256":selected["sha256"],
            }]
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            state = app.production_query("prj_auto_recovery")
            self.assertEqual(
                (state["recovery"]["status"], state["recovery"]["reason_code"],
                 state["recovery"]["requires_owner_decision"],
                 state["recovery"]["provider_dispatches_per_continue"]),
                ("RECOVERY_READY", "AUTO_QC_CORRECTIVE_REPLAN_READY", False, 1),
            )

    def test_visual_operation_compiles_auto_qc_correction_before_generation(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            _fixture(app, "prj_auto_recovery", "AUTO_ACCEPT", 1)
            state = {
                "active_stage":"VISUALS",
                "recovery":{"status":"RECOVERY_READY", "reason_code":"AUTO_QC_CORRECTIVE_REPLAN_READY",
                            "affected_request_id":"req_rejected"},
                "stages":{"VISUALS":{"status":"RECOVERY_READY"}, "PLAN":{"status":"COMPLETE"}},
            }
            calls = []
            with (patch.object(app, "production_query", return_value=state),
                  patch.object(app, "generate", side_effect=lambda project_id: calls.append(("generate", project_id)) or {"ok":True}),
                  patch("story_auto.application.operator.qc_corrective_replan",
                        side_effect=lambda runtime_root, project_id, request_id, **kwargs:
                            calls.append(("corrective", project_id, request_id)))):
                result = app._run_visuals_for_production("prj_auto_recovery")
            self.assertEqual(result, {"ok":True})
            self.assertEqual(calls, [
                ("corrective", "prj_auto_recovery", "req_rejected"),
                ("generate", "prj_auto_recovery"),
            ])

    def test_auto_qc_correction_keeps_abstract_shot_runnable_without_a_location(self):
        locked_core = _canonical_locked_corrective_core(
            {
                "media_type": "IMAGE",
                "target_start": 100.0,
                "target_end": 105.0,
                "target_duration": 5.0,
            },
            shot={
                "shot_id": "sh_abstract_outro",
                "scene_id": "sc_outro",
                "subject": "A reflective closing moment",
                "action": "The narration resolves into a quiet final thought.",
                "location_id": None,
                "prop_ids": [],
            },
            entities={},
            scene_continuity={},
        )

        self.assertEqual(
            locked_core["location"],
            "a neutral, text-free cinematic setting consistent with the narrated moment",
        )
        self.assertIn(
            "no readable words, letters, logos, screens, signs, title cards, captions, or interface elements",
            locked_core["canonical_exclusions"],
        )

    def test_auto_accept_keeps_asset_pending_when_gemini_report_is_invalid(self):
        class InvalidRouter(_PassingAutomaticQCRouter):
            def reason(self, **kwargs):
                result = super().reason(**kwargs)
                result.value["results"].pop("AI_POLISH")
                return result

        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root); paths = _fixture(app, "prj_auto_uncertain", "AUTO_ACCEPT", 1)
            before = read_json(paths.artifact_path("output/generation_manifest.json"))
            with self.assertRaisesRegex(Exception, "GEMINI_QC_UNCERTAIN"):
                app.apply_qc_policy("prj_auto_uncertain", router=InvalidRouter())
            self.assertEqual(read_json(paths.artifact_path("output/generation_manifest.json")), before)

    def test_manual_review_pauses_then_batch_accepts_exact_assets_without_duplicate_decisions(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root); paths = _fixture(app, "prj_manual", "MANUAL_REVIEW", 2)
            pending = app.query_qc_status("prj_manual")
            self.assertEqual((pending["status"], pending["requires_owner_decision"], pending["pending_review"]), ("BLOCKED", True, 2))
            first = app.accept_selected_assets("prj_manual", {"req_qc_000", "req_qc_001"}, "Owner approved the selected batch.")
            saved = read_json(paths.artifact_path("output/generation_manifest.json"))
            self.assertEqual((first["accepted_assets"], first["provider_dispatch_delta"]), (2, 0))
            self.assertEqual(saved["quality_batches"][-1]["asset_set"], [
                {"request_id": "req_qc_000", "path": "assets/selected.png", "sha256": saved["requests"][0]["selected_asset"]["sha256"]},
                {"request_id": "req_qc_001", "path": "assets/selected.png", "sha256": saved["requests"][1]["selected_asset"]["sha256"]},
            ])
            self.assertEqual(app.query_qc_status("prj_manual")["status"], "COMPLETE")
            replay = app.accept_selected_assets("prj_manual", {"req_qc_000", "req_qc_001"}, "Owner approved the selected batch.")
            self.assertEqual(replay["accepted_assets"], 0)
            self.assertEqual(read_json(paths.artifact_path("output/generation_manifest.json")), saved)

    def test_coordinator_runs_automatic_quality_but_manual_policy_returns_owner_decision(self):
        auto_states = iter([
            {"pipeline_status": "READY", "active_stage": "QUALITY", "stages": {}},
            {"pipeline_status": "READY", "active_stage": "RENDER", "stages": {}},
            {"pipeline_status": "COMPLETE", "active_stage": "RENDER", "stages": {}},
        ])
        calls = []
        coordinator = ProductionCoordinator(lambda _: next(auto_states), {"quality": lambda _: calls.append("quality") or {"accepted_assets": 2, "provider_dispatch_delta": 0}, "render": lambda _: calls.append("render")})
        self.assertEqual(coordinator.run_until("prj_auto")["outcome"], "FINAL_VIDEO_COMPLETE")
        self.assertEqual(calls, ["quality", "render"])
        manual = {"pipeline_status": "OWNER_DECISION_REQUIRED", "active_stage": "QUALITY", "stages": {}}
        coordinator = ProductionCoordinator(lambda _: manual, {"quality": lambda _: self.fail("manual policy must not run automatically")})
        self.assertEqual(coordinator.run_until("prj_manual")["outcome"], "OWNER_DECISION_REQUIRED")

    def test_coordinator_auto_approves_validated_plans_only_for_automatic_policy(self):
        automatic = iter([
            {"pipeline_status": "OWNER_DECISION_REQUIRED", "active_stage": "PLAN",
             "quality": {"policy": "AUTO_ACCEPT"},
             "stages": {"PLAN": {"status": "BLOCKED"}},
             "evidence": [{"path": "output/generation_requests.json", "present": False}]},
            {"pipeline_status": "OWNER_DECISION_REQUIRED", "active_stage": "PLAN",
             "quality": {"policy": "AUTO_ACCEPT"},
             "stages": {"PLAN": {"status": "BLOCKED"}},
             "evidence": [{"path": "output/generation_requests.json", "present": False}, {"path": "output/review_state.json", "present": True}]},
            {"pipeline_status": "OWNER_DECISION_REQUIRED", "active_stage": "PLAN",
             "quality": {"policy": "AUTO_ACCEPT"},
             "stages": {"PLAN": {"status": "BLOCKED"}},
             "evidence": [{"path": "output/generation_requests.json", "present": True}]},
            {"pipeline_status": "COMPLETE", "active_stage": "RENDER", "stages": {}},
        ])
        calls = []
        coordinator = ProductionCoordinator(
            lambda _: next(automatic),
            {"approve_plan": lambda _: calls.append("approve_plan"),
             "plan": lambda _: calls.append("plan"),
             "approve_shots": lambda _: calls.append("approve_shots")},
        )
        result = coordinator.run_until("prj_auto_plan")
        self.assertEqual((result["outcome"], result["invoked_stages"], calls),
                         ("FINAL_VIDEO_COMPLETE", ["approve_plan", "plan", "approve_shots"], ["approve_plan", "plan", "approve_shots"]))

    def test_coordinator_compiles_directly_when_story_plan_is_already_approved(self):
        automatic = iter([
            {"pipeline_status": "OWNER_DECISION_REQUIRED", "active_stage": "PLAN",
             "quality": {"policy": "AUTO_ACCEPT"},
             "stages": {"PLAN": {"status": "BLOCKED"}},
             "planning": {"story_plan_approved": True, "visual_plan_approved": False},
             "evidence": [{"path": "output/generation_requests.json", "present": False}]},
            {"pipeline_status": "OWNER_DECISION_REQUIRED", "active_stage": "PLAN",
             "quality": {"policy": "AUTO_ACCEPT"},
             "stages": {"PLAN": {"status": "BLOCKED"}},
             "planning": {"story_plan_approved": False, "visual_plan_approved": False},
             "evidence": [{"path": "output/generation_requests.json", "present": True}]},
            {"pipeline_status": "COMPLETE", "active_stage": "RENDER", "stages": {}},
        ])
        calls = []
        coordinator = ProductionCoordinator(
            lambda _: next(automatic),
            {"approve_plan": lambda _: self.fail("approved story plan must not be approved again"),
             "plan": lambda _: calls.append("plan"),
             "approve_shots": lambda _: calls.append("approve_shots")},
        )
        result = coordinator.run_until("prj_auto_approved_story")
        self.assertEqual((result["outcome"], result["invoked_stages"], calls),
                         ("FINAL_VIDEO_COMPLETE", ["plan", "approve_shots"], ["plan", "approve_shots"]))

    def test_auto_accept_compiled_requests_continue_without_an_owner_plan_stop(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            _fixture(app, "prj_unapproved_compiled", "AUTO_ACCEPT", 1)
            state = app.production_query("prj_unapproved_compiled")
            self.assertEqual((state["pipeline_status"], state["stages"]["PLAN"]["status"]),
                             ("READY", "BLOCKED"))

    def test_manual_review_compiled_requests_remain_an_owner_plan_stop(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            _fixture(app, "prj_manual_unapproved_compiled", "MANUAL_REVIEW", 1)
            state = app.production_query("prj_manual_unapproved_compiled")
            self.assertEqual((state["pipeline_status"], state["active_stage"], state["stages"]["PLAN"]["status"]),
                             ("OWNER_DECISION_REQUIRED", "PLAN", "BLOCKED"))

    def test_operator_coordinator_auto_accepts_then_continues_to_render_without_provider_dispatch(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root); paths = _fixture(app, "prj_auto_coordinator", "AUTO_ACCEPT", 2)
            for name in ("content_manifest.json", "alignment.json", "story_timeline.json", "continuity_bible.json", "media_plan.json", "render_plan.json"):
                atomic_write_json(paths.artifact_path(f"output/{name}"), {"fixture": name})
            atomic_write_json(paths.artifact_path("output/review_state.json"), {
                "plan_approval": {"status": "APPROVED", "bound_hashes": {
                    name: sha256_file(paths.artifact_path(f"output/{filename}"))
                    for name, filename in (("timeline", "story_timeline.json"), ("continuity", "continuity_bible.json"),
                                           ("shot_plan", "shot_plan.json"), ("media_plan", "media_plan.json"))
                }}
            })
            renders = []
            def render(_project_id):
                renders.append(_project_id)
                accepted = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"]
                self.assertEqual(len(accepted), 2)
                self.assertTrue(all(item["selected_asset"]["production_qc"] == "AUTO_ACCEPTED" for item in accepted))
                from tests.final_output_fixture import complete_final
                return complete_final(paths)
            router = _PassingAutomaticQCRouter()
            with (patch.object(app, "render", side_effect=render),
                  patch("story_auto.application.operator.apply_auto_accept_policy",
                        side_effect=lambda runtime_root, project_id, **_kwargs: apply_auto_accept_policy(
                            runtime_root, project_id, router=router))):
                result = app.run_to_final("prj_auto_coordinator")
            self.assertEqual((result["outcome"], result["invoked_stages"], renders),
                             ("FINAL_VIDEO_COMPLETE", ["quality", "render"], ["prj_auto_coordinator"]))
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            self.assertTrue(all(item["selected_asset"]["production_qc"] == "AUTO_ACCEPTED" for item in manifest["requests"]))

    def test_reserved_ai_review_is_serializable_but_not_runnable(self):
        with tempfile.TemporaryDirectory() as root:
            app = OperatorService(root)
            app.create_project(project_id="prj_ai", settings={"qc_policy": "AI_REVIEW"}, content="# AI\n\n## Narration\n\nText.")
            self.assertEqual(app.query_qc_status("prj_ai")["policy"], "AI_REVIEW")
            with self.assertRaisesRegex(Exception, "AI_REVIEW_UNSUPPORTED"):
                app.apply_qc_policy("prj_ai")
            changed = app.set_qc_policy("prj_ai", "MANUAL_REVIEW")
            self.assertEqual(changed["policy"], "MANUAL_REVIEW")
            self.assertEqual(app.query_qc_status("prj_ai")["policy"], "MANUAL_REVIEW")


if __name__ == "__main__":
    unittest.main()

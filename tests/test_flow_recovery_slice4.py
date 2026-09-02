"""Offline Slice 4 recovery projection and Continue Production regressions."""
from __future__ import annotations

import threading
import tempfile
import unittest
import socket
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from story_auto.application import OperatorService
from story_auto.application.production_coordinator import ProductionCoordinator
from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project, load_project
from story_auto.core.project.production_state import ProductionStateReconciler
from story_auto.core.project import lock as lock_module
from story_auto.providers.flow.service import execute_generation, FlowExecutor
from story_auto.providers.flow.session import FlowCapabilities


def _request(request_id: str = "shot_01") -> dict:
    return {
        "request_id": request_id, "fingerprint": request_id, "purpose": "SHOT",
        "shot_id": request_id, "media_type": "IMAGE", "prompt": "synthetic",
        "depends_on": [], "provider": "google_flow", "execution_tier": "STANDARD_PRODUCTION",
    }


def _terminal(family: str) -> dict:
    return {
        "attempt": 1, "status": "FAILED_RETRYABLE", "dispatch_confirmed": True,
        "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED",
        "terminal_evidence": [{"authoritative": True, "failure_family": family,
                                "exact_attribution_confirmed": True}],
    }


class Slice4Fixture:
    @staticmethod
    def project(root: str, entry: dict | None = None, *, final: bool = False):
        runtime = RuntimeLayout.from_root(root)
        paths = create_project(runtime, ProjectConfig("prj_slice4"), "# Slice 4\n\n## Narration\n\nFixture.")
        for name in ("content_manifest.json", "alignment.json", "story_timeline.json", "continuity_bible.json", "shot_plan.json", "media_plan.json"):
            atomic_write_json(paths.artifact_path(f"output/{name}"), {"fixture": name})
        atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {"status": "APPROVED"}})
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": [_request()]})
        if entry is not None:
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
                "schema_version": "story-auto-generation-manifest/1.0.0", "project_id": paths.project_id,
                "requests": [entry],
            })
        if final:
            paths.artifact_path("output/final.mp4").write_bytes(b"valid final")
        return runtime, paths

    @staticmethod
    def state(runtime, paths) -> dict:
        _paths, config = load_project(runtime, paths.project_id)
        return ProductionStateReconciler().reconcile(paths, config).to_dict()

    @staticmethod
    def operator(root: str, *, entry: dict | None = None):
        """Create one approved request and a validated fake Flow connection."""
        app = OperatorService(root)
        app.flow_connections.save_validated_candidate({
            "status": "CONNECTED", "project_url": "https://labs.google/fx/tools/flow/slice4",
            "project_identity": "https://labs.google/fx/tools/flow/slice4",
            "observed_capabilities": {"IMAGE": True, "VIDEO": True,
                                      "REFERENCE_IMAGE": True, "FRAME_VIDEO": True},
        })
        app.create_project(project_id="prj_slice4", render_mode="full_image",
                           content="# Slice 4\n\n## Narration\n\nFixture.")
        paths, _config = app._project("prj_slice4")
        for name in ("content_manifest.json", "alignment.json", "story_timeline.json", "continuity_bible.json", "shot_plan.json", "media_plan.json"):
            atomic_write_json(paths.artifact_path(f"output/{name}"), {"fixture": name})
        atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {"status": "APPROVED"}})
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": [_request()]})
        if entry is not None:
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
                "schema_version": "story-auto-generation-manifest/1.0.0", "project_id": paths.project_id,
                "requests": [entry],
            })
        return app, paths


class _FakeFlow:
    """Offline provider boundary double; its call count is the safety oracle."""
    def __init__(self, *, entered: threading.Event | None = None, release: threading.Event | None = None):
        self.calls: list[str] = []
        self.entered = entered
        self.release = release

    def __call__(self, request, _refs, destination):
        self.calls.append(request["request_id"])
        if self.entered:
            self.entered.set()
        if self.release:
            self.release.wait(2)
        destination.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1280, 720), "navy").save(destination, "PNG")
        return destination


class ProductionRecoveryProjectionTests(unittest.TestCase):
    def test_live_continue_holding_project_lock_projects_running(self):
        with tempfile.TemporaryDirectory() as root:
            app, paths = Slice4Fixture.operator(root)
            entered, release = threading.Event(), threading.Event()
            provider = _FakeFlow(entered=entered, release=release)
            original_generate = app.generate
            app.generate = lambda project_id: original_generate(
                project_id, executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), provider),
                max_requests=1,
            )
            worker = threading.Thread(target=lambda: app.continue_production(paths.project_id))
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(app.production_query(paths.project_id)["pipeline_status"], "RUNNING")
            finally:
                release.set(); worker.join(3)

    def test_stale_generating_and_running_marker_without_live_lock_is_not_running(self):
        entry = {"request_id": "shot_01", "status": "GENERATING", "provider_submissions": 1,
                 "attempts": [{"attempt": 1, "status": "GENERATING", "dispatch_confirmed": True,
                               "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED"}]}
        with tempfile.TemporaryDirectory() as root:
            runtime, paths = Slice4Fixture.project(root, entry)
            state = Slice4Fixture.state(runtime, paths)
            state["run"] = {"run_id": "run_stale", "status": "RUNNING"}
            atomic_write_json(paths.artifact_path("output/production_state.json"), state)
            state = Slice4Fixture.state(runtime, paths)
            self.assertNotEqual(state["pipeline_status"], "RUNNING")

    def test_dead_stale_lock_is_not_live_work_evidence(self):
        entry = {"request_id": "shot_01", "status": "GENERATING", "provider_submissions": 1,
                 "attempts": [{"attempt": 1, "status": "GENERATING", "dispatch_confirmed": True,
                               "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED"}]}
        with tempfile.TemporaryDirectory() as root:
            runtime, paths = Slice4Fixture.project(root, entry)
            state = Slice4Fixture.state(runtime, paths)
            state["run"] = {"run_id": "run_stale", "status": "RUNNING"}
            atomic_write_json(paths.artifact_path("output/production_state.json"), state)
            atomic_write_json(runtime.locks / f"{paths.project_id}.lock", {
                "project_id": paths.project_id, "pid": 999999, "hostname": socket.gethostname(), "created_at": 0,
            })
            with patch.object(lock_module, "_process_liveness", return_value=False):
                state = Slice4Fixture.state(runtime, paths)
            self.assertNotEqual(state["pipeline_status"], "RUNNING")

    def test_legacy_selected_asset_requires_real_bytes(self):
        entry = {"request_id": "shot_01", "status": "QC_PENDING", "attempts": [],
                 "selected_asset": {"path": "assets/legacy.png"}}
        with tempfile.TemporaryDirectory() as root:
            runtime, paths = Slice4Fixture.project(root, entry)
            asset = paths.artifact_path("assets/legacy.png")
            asset.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1280, 720), "green").save(asset, "PNG")
            self.assertEqual(Slice4Fixture.state(runtime, paths)["recovery"]["status"], "COMPLETE")
            asset.unlink()
            state = Slice4Fixture.state(runtime, paths)
            self.assertNotEqual(state["recovery"]["status"], "COMPLETE")
            self.assertEqual(state["pipeline_status"], "NEEDS_ATTENTION")
            self.assertEqual((state["quality"]["technical_passed"], state["quality"]["pending_review"]), (0, 0))

    def test_recovery_matrix_projects_durable_evidence_without_status_only_running(self):
        cases = {
            "synthetic_active_field": ({"request_id": "shot_01", "status": "GENERATING", "provider_submissions": 1,
                        "attempts": [{"attempt": 1, "status": "GENERATING", "dispatch_confirmed": True,
                                      "provider_progress_active": True,
                                      "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED"}]}, "NEEDS_ATTENTION", True, 0),
            "stale_generating": ({"request_id": "shot_01", "status": "GENERATING", "provider_submissions": 1,
                                  "attempts": [{"attempt": 1, "status": "GENERATING", "dispatch_confirmed": True,
                                                "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED"}]}, "NEEDS_ATTENTION", True, 0),
            "successful_asset_missing_without_raw": ({"request_id": "shot_01", "status": "SUCCEEDED", "attempts": [],
                                                        "selected_asset": {"path": "assets/missing.png", "sha256": "x",
                                                                           "source_provider_attempt": 1}}, "NEEDS_ATTENTION", True, 0),
            "pre_dispatch": ({"request_id": "shot_01", "status": "FAILED_RETRYABLE", "provider_submissions": 0,
                              "attempts": [{"attempt": 1, "status": "NOT_DISPATCHED", "dispatch_confirmed": False,
                                            "provider_execution_state": "NOT_STARTED",
                                            "attribution_state": "NOT_ATTEMPTED",
                                            "dispatch_confirmation_state": "PRE_DISPATCH_FAILURE",
                                            "provider_settings": {"activation": {"input_dispatched": False,
                                                                                   "proof": "PROCESS_INTERRUPTED_BEFORE_PROVIDER_SETUP"}}}]}, "RECOVERY_READY", False, 1),
            "terminal_transient": ({"request_id": "shot_01", "status": "FAILED_RETRYABLE", "provider_submissions": 1,
                                    "attempts": [_terminal("PROVIDER_TERMINAL_TRANSIENT")]}, "RECOVERY_READY", False, 1),
            "rate_limit": ({"request_id": "shot_01", "status": "FAILED_RETRYABLE", "provider_submissions": 1,
                            "attempts": [_terminal("PROVIDER_RATE_LIMIT")]}, "RECOVERY_READY", False, 1),
            "policy": ({"request_id": "shot_01", "status": "FAILED_RETRYABLE", "provider_submissions": 1,
                         "attempts": [_terminal("PROVIDER_POLICY_BLOCK")]}, "NEEDS_ATTENTION", True, 0),
            "auth": ({"request_id": "shot_01", "status": "AUTH_REQUIRED", "attempts": []}, "BLOCKED", False, 0),
            "credit": ({"request_id": "shot_01", "status": "CREDIT_BLOCKED", "attempts": []}, "BLOCKED", False, 0),
            "terminal_unknown": ({"request_id": "shot_01", "status": "FAILED_RETRYABLE", "provider_submissions": 1,
                                  "attempts": [_terminal("PROVIDER_TERMINAL_UNKNOWN")]}, "NEEDS_ATTENTION", True, 0),
            "dispatch_uncertain": ({"request_id": "shot_01", "status": "FAILED_RETRYABLE", "provider_submissions": 1,
                                    "attempts": [{"attempt": 1, "status": "FAILED_RETRYABLE", "dispatch_confirmed": False,
                                                  "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED",
                                                  "failure_class": "FLOW_DISPATCH_UNCERTAIN"}]}, "NEEDS_ATTENTION", True, 0),
            "dispatch_ambiguous": ({"request_id": "shot_01", "status": "AMBIGUOUS", "provider_submissions": 1,
                                    "attempts": [{"attempt": 1, "status": "AMBIGUOUS",
                                                  "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED"}]}, "NEEDS_ATTENTION", True, 0),
        }
        for name, (entry, expected, owner, dispatches) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                runtime, paths = Slice4Fixture.project(root, entry)
                state = Slice4Fixture.state(runtime, paths)
                self.assertEqual(state["recovery"]["status"], expected)
                self.assertEqual(state["pipeline_status"], expected)
                self.assertEqual(state["recovery"]["requires_owner_decision"], owner)
                self.assertEqual(state["recovery"]["provider_dispatches_per_continue"], dispatches)

    def test_failed_retryable_without_authority_is_never_running(self):
        entry = {"request_id": "shot_01", "status": "FAILED_RETRYABLE", "provider_submissions": 1,
                 "attempts": [{"attempt": 1, "status": "FAILED_RETRYABLE", "dispatch_confirmed": False}]}
        with tempfile.TemporaryDirectory() as root:
            runtime, paths = Slice4Fixture.project(root, entry)
            state = Slice4Fixture.state(runtime, paths)
            self.assertEqual((state["pipeline_status"], state["stages"]["VISUALS"]["status"]),
                             ("NEEDS_ATTENTION", "NEEDS_ATTENTION"))

    def test_complete_requires_a_valid_final_output(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths = Slice4Fixture.project(root, final=True)
            state = Slice4Fixture.state(runtime, paths)
            self.assertEqual((state["pipeline_status"], state["recovery"]["status"]), ("COMPLETE", "COMPLETE"))

    def test_cached_projection_rebuilds_when_selected_asset_disappears(self):
        with tempfile.TemporaryDirectory() as root:
            app, paths = Slice4Fixture.operator(root)
            raw_rel, selected_rel = "assets/image/shot_01/raw.png", "assets/image/shot_01/clean.png"
            raw, selected = paths.artifact_path(raw_rel), paths.artifact_path(selected_rel)
            raw.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1280, 720), "navy").save(raw, "PNG")
            Image.new("RGB", (1280, 720), "green").save(selected, "PNG")
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
                "schema_version": "story-auto-generation-manifest/1.0.0", "project_id": paths.project_id,
                "requests": [{"request_id": "shot_01", "request_identity_sha256": "shot_01", "media_type": "IMAGE",
                              "status": "QC_PENDING", "selected_asset": {"path": selected_rel, "sha256": sha256_file(selected),
                                                                           "source_provider_attempt": 1},
                              "attempts": [{"attempt": 1, "status": "SUCCEEDED", "asset_path": raw_rel,
                                            "asset_sha256": sha256_file(raw), "attribution_state": "CONFIRMED",
                                            "production_image_postprocess_required": True}]}],
            })
            self.assertEqual(app.production_query(paths.project_id)["recovery"]["status"], "COMPLETE")
            selected.unlink()
            state = app.production_query(paths.project_id)
            self.assertEqual((state["recovery"]["status"], state["recovery"]["provider_dispatches_per_continue"]),
                             ("RECOVERY_READY", 0))


class ContinueProductionTests(unittest.TestCase):
    def test_continue_stops_at_attention_or_blocked_boundary_without_visual_call(self):
        for status in ("NEEDS_ATTENTION", "BLOCKED", "RUNNING"):
            with self.subTest(status=status):
                state = {"pipeline_status": status, "active_stage": "VISUALS", "recovery": {"status": status},
                         "stages": {"VISUALS": {"status": status}}}
                calls = []
                coordinator = ProductionCoordinator(lambda _: state, {"visuals": lambda _: calls.append("visuals")})
                result = coordinator.run_until("prj_slice4")
                self.assertEqual((result["outcome"], calls), (status, []))

    def test_continue_safe_recovery_uses_slice3_once_and_appends_one_attempt(self):
        with tempfile.TemporaryDirectory() as root:
            app, paths = Slice4Fixture.operator(root)
            provider = _FakeFlow()
            original_generate = app.generate
            app.generate = lambda project_id: original_generate(
                project_id, executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), provider),
                max_requests=1,
            )
            result = app.continue_production(paths.project_id)
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual(provider.calls, ["shot_01"])
            self.assertEqual((result["invoked_stages"].count("visuals"), entry["provider_submissions"], len(entry["attempts"])),
                             (1, 1, 1))

    def test_continue_preserves_completed_visual_and_dispatches_only_recoverable_one(self):
        with tempfile.TemporaryDirectory() as root:
            app, paths = Slice4Fixture.operator(root)
            first_asset = paths.artifact_path("assets/image/shot_01/accepted.png")
            first_asset.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1280, 720), "green").save(first_asset, "PNG")
            first_sha = sha256_file(first_asset)
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),
                              {"requests": [_request("shot_01"), _request("shot_02")]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
                "schema_version": "story-auto-generation-manifest/1.0.0", "project_id": paths.project_id,
                "requests": [
                    {"request_id": "shot_01", "request_identity_sha256": "shot_01", "media_type": "IMAGE",
                     "status": "SUCCEEDED", "attempts": [{"attempt": 1, "status": "SUCCEEDED"}],
                     "selected_asset": {"path": "assets/image/shot_01/accepted.png", "sha256": first_sha,
                                        "production_qc": "AUTO_ACCEPTED"}},
                    {"request_id": "shot_02", "request_identity_sha256": "shot_02", "media_type": "IMAGE",
                     "status": "NOT_DISPATCHED", "provider_submissions": 0,
                     "attempts": [{"attempt": 1, "status": "NOT_DISPATCHED", "dispatch_confirmed": False,
                                   "provider_execution_state": "NOT_STARTED", "attribution_state": "NOT_ATTEMPTED",
                                   "dispatch_confirmation_state": "PRE_DISPATCH_FAILURE",
                                   "provider_settings": {"activation": {"input_dispatched": False,
                                                                        "proof": "PROCESS_INTERRUPTED_BEFORE_PROVIDER_SETUP"}}}]},
                ],
            })
            provider = _FakeFlow()
            original_generate = app.generate
            app.generate = lambda project_id: original_generate(
                project_id, executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), provider),
                max_requests=2,
            )
            result = app.continue_production(paths.project_id)
            entries = {item["request_id"]: item for item in read_json(paths.artifact_path("output/generation_manifest.json"))["requests"]}
            self.assertEqual((provider.calls, result["invoked_stages"].count("visuals")), (["shot_02"], 1))
            self.assertEqual((sha256_file(first_asset), entries["shot_01"]["selected_asset"]["sha256"],
                              entries["shot_01"]["selected_asset"]["production_qc"]),
                             (first_sha, first_sha, "AUTO_ACCEPTED"))

    def test_concurrent_and_repeat_continue_never_cross_provider_boundary_twice(self):
        with tempfile.TemporaryDirectory() as root:
            app, paths = Slice4Fixture.operator(root)
            entered, release = threading.Event(), threading.Event()
            provider = _FakeFlow(entered=entered, release=release)
            original_generate = app.generate
            app.generate = lambda project_id: original_generate(
                project_id, executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), provider),
                max_requests=1,
            )
            first = threading.Thread(target=lambda: app.continue_production(paths.project_id))
            first.start()
            self.assertTrue(entered.wait(2))
            second = app.continue_production(paths.project_id)
            release.set(); first.join(3)
            third = app.continue_production(paths.project_id)
            self.assertEqual((provider.calls, second["invoked_stages"], third["invoked_stages"]),
                             (["shot_01"], [], []))

    def test_continue_ambiguous_policy_and_auth_are_provider_free(self):
        cases = {
            "ambiguous": {"request_id": "shot_01", "status": "AMBIGUOUS", "provider_submissions": 1,
                          "attempts": [{"attempt": 1, "status": "AMBIGUOUS",
                                        "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED"}]},
            "policy": {"request_id": "shot_01", "status": "FAILED_RETRYABLE", "provider_submissions": 1,
                       "attempts": [_terminal("PROVIDER_POLICY_BLOCK")]},
            "auth": {"request_id": "shot_01", "status": "AUTH_REQUIRED", "attempts": []},
        }
        for name, entry in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                app, paths = Slice4Fixture.operator(root, entry=entry)
                app.generate = lambda _project_id: self.fail("Continue must not activate the provider")
                result = app.continue_production(paths.project_id)
                self.assertEqual(result["invoked_stages"], [])

    def test_continue_repairs_preserved_raw_asset_without_provider_dispatch(self):
        with tempfile.TemporaryDirectory() as root:
            app, paths = Slice4Fixture.operator(root)
            raw_rel = "assets/image/shot_01/attempt_001_raw.png"
            raw = paths.artifact_path(raw_rel)
            raw.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1280, 720), "navy").save(raw, "PNG")
            entry = {
                "request_id": "shot_01", "request_identity_sha256": "shot_01", "media_type": "IMAGE",
                "status": "FAILED_RETRYABLE", "failure_class": "FLOW_IMAGE_DERIVATIVE_INVALID",
                "selected_asset": {"path": "assets/image/shot_01/attempt_001_clean.png",
                                   "source_provider_attempt": 1},
                "attempts": [{"attempt": 1, "status": "SUCCEEDED", "asset_path": raw_rel,
                              "asset_sha256": sha256_file(raw), "attribution_state": "CONFIRMED",
                              "production_image_postprocess_required": True,
                              "metadata": {"width": 1280, "height": 720}}],
            }
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
                "schema_version": "story-auto-generation-manifest/1.0.0", "project_id": paths.project_id,
                "requests": [entry],
            })
            provider = _FakeFlow()
            original_generate = app.generate
            app.generate = lambda project_id: original_generate(
                project_id, executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), provider),
                max_requests=1,
            )
            state = app.production_query(paths.project_id)
            result = app.continue_production(paths.project_id)
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((state["recovery"]["status"], state["recovery"]["provider_dispatches_per_continue"], provider.calls),
                             ("RECOVERY_READY", 0, []))
            self.assertIn("visuals", result["invoked_stages"])
            self.assertEqual((entry["status"], entry["selected_asset"]["source_provider_attempt"]), ("QC_PENDING", 1))

    def test_canonical_slice3_executor_remains_the_only_continue_provider_route(self):
        service_source = Path(__file__).parents[1] / "story_auto" / "providers" / "flow" / "service.py"
        operator_source = Path(__file__).parents[1] / "story_auto" / "application" / "operator.py"
        service = service_source.read_text(encoding="utf-8")
        operator = operator_source.read_text(encoding="utf-8")
        self.assertIn("RecoveryExecutionGate(", service)
        self.assertIn("return self.generate(project_id)", operator)
        self.assertNotIn("executor.run(", operator)


class Slice4FrontendMappingTests(unittest.TestCase):
    def test_frontend_working_indicator_uses_backend_recovery_projection_only(self):
        source = (Path(__file__).parents[1] / "story_auto" / "ui" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("backendProductionWorking", source)
        self.assertIn("RECOVERING", source)
        self.assertIn("RECOVERY_READY", source)
        self.assertNotIn("FAILED_RETRYABLE", source)


if __name__ == "__main__":
    unittest.main()

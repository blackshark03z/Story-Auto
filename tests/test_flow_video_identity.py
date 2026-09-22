from __future__ import annotations

import tempfile
import unittest
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.response_model import FlowObservedIdentity
from story_auto.providers.flow.live import (
    DispatchEvidenceTracker,
    LiveFlowGenerator,
    recoverable_new_response_identity,
    recoverable_response_identity_delta,
    response_identity_set_fingerprint,
)
from story_auto.providers.flow.service import (
    FlowError,
    FlowExecutor,
    _confirm_executor_attribution,
    _persist_observed_video_identity_before_acquisition,
    _persist_video_recovery_checkpoint_after_acceptance,
    _record_attempt_provider_state,
    reconcile_unresolved_flow_attempt,
)
from story_auto.providers.flow.session import FlowRuntime, FlowSessionError
from story_auto.providers.flow.video_acquisition import FlowObservedVideoAcquirer
from story_auto.providers.flow.video_identity import (
    load_attempt_video_identity,
    persist_attempt_video_identity,
)


PROJECT_IDENTITY = "11111111-2222-3333-4444-555555555555"
OTHER_PROJECT = "99999999-2222-3333-4444-555555555555"
IDENTITY = FlowObservedIdentity(
    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    PROJECT_IDENTITY,
    "99999999-8888-7777-6666-555555555555",
)
OTHER_IDENTITY = FlowObservedIdentity(
    "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
    PROJECT_IDENTITY,
    "88888888-7777-6666-5555-444444444444",
)
THIRD_IDENTITY = FlowObservedIdentity(
    "cccccccc-dddd-eeee-ffff-000000000000",
    PROJECT_IDENTITY,
    "77777777-6666-5555-4444-333333333333",
)


class FlowVideoIdentityBindingTests(unittest.TestCase):
    def make_project(
        self,
        root: str,
        *,
        media_type: str = "VIDEO",
        dispatch_confirmed: bool = True,
        provider_execution_state: str = "PROVIDER_BOUNDARY_ENTERED",
    ):
        runtime = RuntimeLayout.from_root(root)
        project_id = "prj_video_identity"
        settings = {
            "provider_binding": {
                "flow": {
                    "state": "BOUND",
                    "project_url": f"https://flow.google.com/project/{PROJECT_IDENTITY}",
                    "project_identity": PROJECT_IDENTITY,
                    "created_for_story_project_id": project_id,
                    "project_name": "StoryAuto_video_identity",
                    "activation_state": "STARTED",
                    "created_at": "2026-09-20T00:00:00+00:00",
                }
            }
        }
        paths = create_project(runtime, ProjectConfig(project_id, settings=settings))
        request = {
            "request_id": "req_video",
            "fingerprint": "video-fingerprint",
            "purpose": "SHOT",
            "media_type": media_type,
            "prompt": "bounded fixture",
            "depends_on": [],
            "provider": "google_flow",
        }
        entry = {
            "request_id": "req_video",
            "request_identity_sha256": "video-fingerprint",
            "media_type": media_type,
            "status": "GENERATING",
            "attempts": [
                {
                    "attempt": 1,
                    "status": "SUBMITTED",
                    "provider_execution_state": provider_execution_state,
                    "dispatch_confirmed": dispatch_confirmed,
                }
            ],
        }
        atomic_write_json(
            paths.artifact_path("output/generation_requests.json"), {"requests": [request]},
        )
        atomic_write_json(
            paths.artifact_path("output/generation_manifest.json"),
            {
                "schema_version": "story-auto-generation-manifest/1.0.0",
                "project_id": project_id,
                "requests": [entry],
            },
        )
        return runtime, paths, project_id

    def test_persists_and_loads_exact_attempt_identity(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths, project_id = self.make_project(root)
            bound = persist_attempt_video_identity(
                runtime.root, project_id, "req_video", 1, IDENTITY,
            )
            loaded = load_attempt_video_identity(runtime.root, project_id, "req_video", 1)
            self.assertEqual(loaded, bound)
            self.assertEqual(loaded.observed_identity, IDENTITY)
            attempt = read_json(
                paths.artifact_path("output/generation_manifest.json")
            )["requests"][0]["attempts"][0]
            self.assertEqual(
                attempt["flow_observed_video_identity"]["binding_sha256"],
                bound.binding_sha256,
            )

    def test_same_identity_is_idempotent_and_conflict_preserves_first_binding(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths, project_id = self.make_project(root)
            first = persist_attempt_video_identity(
                runtime.root, project_id, "req_video", 1, IDENTITY,
            )
            second = persist_attempt_video_identity(
                runtime.root, project_id, "req_video", 1, IDENTITY,
            )
            self.assertEqual(second, first)
            with self.assertRaises(FlowSessionError) as caught:
                persist_attempt_video_identity(
                    runtime.root, project_id, "req_video", 1, OTHER_IDENTITY,
                )
            self.assertEqual(caught.exception.failure_class, "FLOW_VIDEO_IDENTITY_CONFLICT")
            saved = read_json(paths.artifact_path("output/generation_manifest.json"))
            self.assertEqual(
                saved["requests"][0]["attempts"][0]["flow_observed_video_identity"]
                ["binding_sha256"],
                first.binding_sha256,
            )

    def test_wrong_project_identity_fails_before_manifest_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths, project_id = self.make_project(root)
            before = paths.artifact_path("output/generation_manifest.json").read_bytes()
            wrong = FlowObservedIdentity(
                IDENTITY.component_1, OTHER_PROJECT, IDENTITY.component_3,
            )
            with self.assertRaises(FlowSessionError) as caught:
                persist_attempt_video_identity(
                    runtime.root, project_id, "req_video", 1, wrong,
                )
            self.assertEqual(caught.exception.failure_class, "FLOW_PROJECT_MISMATCH")
            self.assertEqual(
                paths.artifact_path("output/generation_manifest.json").read_bytes(), before,
            )

    def test_requires_video_and_confirmed_provider_boundary(self):
        cases = [
            {"media_type": "IMAGE"},
            {"dispatch_confirmed": False},
            {"provider_execution_state": "NOT_STARTED"},
        ]
        for number, kwargs in enumerate(cases):
            with self.subTest(case=number), tempfile.TemporaryDirectory() as root:
                runtime, paths, project_id = self.make_project(root, **kwargs)
                before = paths.artifact_path("output/generation_manifest.json").read_bytes()
                with self.assertRaises(FlowSessionError):
                    persist_attempt_video_identity(
                        runtime.root, project_id, "req_video", 1, IDENTITY,
                    )
                self.assertEqual(
                    paths.artifact_path("output/generation_manifest.json").read_bytes(), before,
                )

    def test_missing_binding_blocks_canonical_acquisition(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, _paths, project_id = self.make_project(root)
            acquirer = FlowObservedVideoAcquirer(
                FlowRuntime(
                    runtime.flow_profile,
                    "http://127.0.0.1:9222",
                    f"https://flow.google.com/project/{PROJECT_IDENTITY}",
                    PROJECT_IDENTITY,
                ),
                object(),
            )
            with self.assertRaises(FlowSessionError) as caught:
                acquirer.acquire_persisted(
                    runtime.root,
                    project_id,
                    "req_video",
                    1,
                    Path(root) / "must-not-exist.mp4",
                )
            self.assertEqual(
                caught.exception.failure_class, "FLOW_VIDEO_IDENTITY_NOT_PERSISTED",
            )

    def test_canonical_acquisition_uses_only_reloaded_binding(self):
        class RecordingAcquirer(FlowObservedVideoAcquirer):
            def __init__(self, runtime):
                super().__init__(runtime, object())
                self.target = None

            def acquire(self, target, destination, *, timeout_ms=45_000):
                self.target = target
                return {
                    "acquisition_version": "fixture",
                    "identity": target.identity,
                    "path": str(destination),
                }

        with tempfile.TemporaryDirectory() as root:
            runtime, _paths, project_id = self.make_project(root)
            bound = persist_attempt_video_identity(
                runtime.root, project_id, "req_video", 1, IDENTITY,
            )
            acquirer = RecordingAcquirer(
                FlowRuntime(
                    runtime.flow_profile,
                    "http://127.0.0.1:9222",
                    f"https://flow.google.com/project/{PROJECT_IDENTITY}",
                    PROJECT_IDENTITY,
                )
            )
            result = acquirer.acquire_persisted(
                runtime.root,
                project_id,
                "req_video",
                1,
                Path(root) / "fixture.mp4",
            )
            self.assertEqual(acquirer.target, IDENTITY)
            self.assertEqual(result["identity_binding_sha256"], bound.binding_sha256)
            self.assertEqual(
                (result["story_project_id"], result["request_id"], result["attempt"]),
                (project_id, "req_video", 1),
            )

    def test_tampered_binding_blocks_acquisition(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths, project_id = self.make_project(root)
            persist_attempt_video_identity(
                runtime.root, project_id, "req_video", 1, IDENTITY,
            )
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            manifest["requests"][0]["attempts"][0]["flow_observed_video_identity"][
                "component_3"
            ] = OTHER_IDENTITY.component_3
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            with self.assertRaises(FlowSessionError) as caught:
                load_attempt_video_identity(runtime.root, project_id, "req_video", 1)
            self.assertEqual(
                caught.exception.failure_class, "FLOW_VIDEO_IDENTITY_BINDING_INVALID",
            )

    def test_state_regression_after_binding_blocks_canonical_load(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths, project_id = self.make_project(root)
            persist_attempt_video_identity(
                runtime.root, project_id, "req_video", 1, IDENTITY,
            )
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            manifest["requests"][0]["attempts"][0]["dispatch_confirmed"] = False
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            with self.assertRaises(FlowSessionError) as caught:
                load_attempt_video_identity(runtime.root, project_id, "req_video", 1)
            self.assertEqual(
                caught.exception.failure_class,
                "FLOW_VIDEO_IDENTITY_BINDING_PRECONDITION_FAILED",
            )

    def test_active_flow_project_must_match_persisted_identity(self):
        class MustNotAcquire(FlowObservedVideoAcquirer):
            def acquire(self, *_args, **_kwargs):
                raise AssertionError("raw acquisition must not start")

        with tempfile.TemporaryDirectory() as root:
            runtime, _paths, project_id = self.make_project(root)
            persist_attempt_video_identity(
                runtime.root, project_id, "req_video", 1, IDENTITY,
            )
            acquirer = MustNotAcquire(
                FlowRuntime(
                    runtime.flow_profile,
                    "http://127.0.0.1:9222",
                    f"https://flow.google.com/project/{OTHER_PROJECT}",
                    OTHER_PROJECT,
                ),
                object(),
            )
            with self.assertRaises(FlowSessionError) as caught:
                acquirer.acquire_persisted(
                    runtime.root,
                    project_id,
                    "req_video",
                    1,
                    Path(root) / "must-not-exist.mp4",
                )
            self.assertEqual(caught.exception.failure_class, "FLOW_PROJECT_MISMATCH")

    def test_invalid_attempt_collection_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths, project_id = self.make_project(root)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            manifest["requests"][0]["attempts"] = None
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
            with self.assertRaises(FlowSessionError) as caught:
                persist_attempt_video_identity(
                    runtime.root, project_id, "req_video", 1, IDENTITY,
                )
            self.assertEqual(
                caught.exception.failure_class, "FLOW_VIDEO_IDENTITY_BINDING_INVALID",
            )

    def test_service_commits_identity_before_acquisition_callback_returns(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths, project_id = self.make_project(root)
            manifest_path = paths.artifact_path("output/generation_manifest.json")
            manifest = read_json(manifest_path)
            request = read_json(
                paths.artifact_path("output/generation_requests.json")
            )["requests"][0]
            attempt = manifest["requests"][0]["attempts"][0]
            generator = SimpleNamespace(
                dispatch_confirmed=False,
                last_settings={
                    "dispatch_confirmation_state": "UNCERTAIN",
                    "composer_transition_seen": True,
                    "activation": {
                        "input_dispatched": True,
                        "trusted_click_seen": True,
                        "activation_verified": True,
                        "provider_acceptance_transition": True,
                    },
                    "attribution_state": "PENDING",
                },
            )
            bound = _persist_observed_video_identity_before_acquisition(
                paths=paths,
                manifest=manifest,
                request=request,
                attempt=attempt,
                generator=generator,
                project_identity=PROJECT_IDENTITY,
                identity=IDENTITY,
            )
            persisted = read_json(manifest_path)["requests"][0]["attempts"][0]
            self.assertTrue(persisted["dispatch_confirmed"])
            self.assertEqual(
                persisted["flow_observed_video_identity"]["binding_sha256"],
                bound.binding_sha256,
            )
            self.assertEqual(
                persisted["dispatch_confirmation_signal"],
                "passive_response_identity_bound",
            )

    def test_service_refuses_identity_before_causal_dispatch_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            _runtime, paths, _project_id = self.make_project(root)
            manifest_path = paths.artifact_path("output/generation_manifest.json")
            before = manifest_path.read_bytes()
            manifest = read_json(manifest_path)
            request = read_json(
                paths.artifact_path("output/generation_requests.json")
            )["requests"][0]
            attempt = manifest["requests"][0]["attempts"][0]
            generator = SimpleNamespace(
                dispatch_confirmed=False,
                last_settings={
                    "dispatch_confirmation_state": "UNCERTAIN",
                    "composer_transition_seen": True,
                    "activation": {
                        "input_dispatched": True,
                        "trusted_click_seen": True,
                        "activation_verified": False,
                        "provider_acceptance_transition": True,
                    },
                },
            )
            with self.assertRaises(FlowSessionError) as caught:
                _persist_observed_video_identity_before_acquisition(
                    paths=paths,
                    manifest=manifest,
                    request=request,
                    attempt=attempt,
                    generator=generator,
                    project_identity=PROJECT_IDENTITY,
                    identity=IDENTITY,
                )
            self.assertEqual(
                caught.exception.failure_class,
                "FLOW_VIDEO_IDENTITY_BINDING_PRECONDITION_FAILED",
            )
            self.assertEqual(manifest_path.read_bytes(), before)

    def test_service_rolls_back_in_memory_binding_when_atomic_write_fails(self):
        with tempfile.TemporaryDirectory() as root:
            _runtime, paths, _project_id = self.make_project(root)
            manifest_path = paths.artifact_path("output/generation_manifest.json")
            before_bytes = manifest_path.read_bytes()
            manifest = read_json(manifest_path)
            request = read_json(
                paths.artifact_path("output/generation_requests.json")
            )["requests"][0]
            attempt = manifest["requests"][0]["attempts"][0]
            before_attempt = dict(attempt)
            generator = SimpleNamespace(
                dispatch_confirmed=False,
                last_settings={
                    "dispatch_confirmation_state": "UNCERTAIN",
                    "composer_transition_seen": True,
                    "activation": {
                        "input_dispatched": True,
                        "trusted_click_seen": True,
                        "activation_verified": True,
                        "provider_acceptance_transition": True,
                    },
                },
            )
            with patch(
                "story_auto.providers.flow.service.atomic_write_json",
                side_effect=OSError("fixture write failure"),
            ):
                with self.assertRaises(OSError):
                    _persist_observed_video_identity_before_acquisition(
                        paths=paths,
                        manifest=manifest,
                        request=request,
                        attempt=attempt,
                        generator=generator,
                        project_identity=PROJECT_IDENTITY,
                        identity=IDENTITY,
                    )
            self.assertEqual(attempt, before_attempt)
            self.assertEqual(manifest_path.read_bytes(), before_bytes)

    def test_service_persists_recovery_checkpoint_after_provider_acceptance(self):
        with tempfile.TemporaryDirectory() as root:
            _runtime, paths, _project_id = self.make_project(
                root, dispatch_confirmed=False,
            )
            manifest_path = paths.artifact_path("output/generation_manifest.json")
            manifest = read_json(manifest_path)
            request = read_json(
                paths.artifact_path("output/generation_requests.json")
            )["requests"][0]
            attempt = manifest["requests"][0]["attempts"][0]
            generator = SimpleNamespace(
                last_settings={
                    "dispatch_confirmation_state": "AWAITING_ATTRIBUTION",
                    "composer_transition_seen": True,
                    "flow_response_identity_baseline_count": 2,
                    "pre_dispatch_baseline_fingerprint": "a" * 64,
                    "activation": {
                        "input_dispatched": True,
                        "trusted_click_seen": True,
                        "activation_verified": True,
                        "provider_acceptance_transition": True,
                    },
                },
            )
            _persist_video_recovery_checkpoint_after_acceptance(
                paths=paths,
                manifest=manifest,
                request=request,
                attempt=attempt,
                generator=generator,
            )
            persisted = read_json(manifest_path)["requests"][0]["attempts"][0]
            self.assertEqual(
                persisted["video_recovery_checkpoint"]["state"],
                "PROVIDER_ACCEPTED_AWAITING_OUTPUT",
            )
            self.assertFalse(
                persisted["video_recovery_checkpoint"]["retry_authorized"],
            )
            self.assertEqual(
                persisted["provider_settings"]["pre_dispatch_baseline_fingerprint"],
                "a" * 64,
            )
            self.assertEqual(
                persisted["provider_settings"]["flow_response_identity_baseline_count"],
                2,
            )
            self.assertFalse(persisted["dispatch_confirmed"])

    def test_service_refuses_unproven_recovery_checkpoint(self):
        with tempfile.TemporaryDirectory() as root:
            _runtime, paths, _project_id = self.make_project(
                root, dispatch_confirmed=False,
            )
            manifest_path = paths.artifact_path("output/generation_manifest.json")
            before = manifest_path.read_bytes()
            manifest = read_json(manifest_path)
            request = read_json(
                paths.artifact_path("output/generation_requests.json")
            )["requests"][0]
            attempt = manifest["requests"][0]["attempts"][0]
            generator = SimpleNamespace(last_settings={
                "composer_transition_seen": True,
                "flow_response_identity_baseline_count": 2,
                "pre_dispatch_baseline_fingerprint": "a" * 64,
                "activation": {
                    "input_dispatched": True,
                    "trusted_click_seen": True,
                    "activation_verified": False,
                    "provider_acceptance_transition": True,
                },
            })
            with self.assertRaises(FlowSessionError) as caught:
                _persist_video_recovery_checkpoint_after_acceptance(
                    paths=paths,
                    manifest=manifest,
                    request=request,
                    attempt=attempt,
                    generator=generator,
                )
            self.assertEqual(
                caught.exception.failure_class,
                "FLOW_VIDEO_RECOVERY_CHECKPOINT_INVALID",
            )
            self.assertEqual(manifest_path.read_bytes(), before)

    def test_recovery_checkpoint_rolls_back_when_atomic_write_fails(self):
        with tempfile.TemporaryDirectory() as root:
            _runtime, paths, _project_id = self.make_project(
                root, dispatch_confirmed=False,
            )
            manifest_path = paths.artifact_path("output/generation_manifest.json")
            before_bytes = manifest_path.read_bytes()
            manifest = read_json(manifest_path)
            request = read_json(
                paths.artifact_path("output/generation_requests.json")
            )["requests"][0]
            attempt = manifest["requests"][0]["attempts"][0]
            before_attempt = dict(attempt)
            generator = SimpleNamespace(last_settings={
                "composer_transition_seen": True,
                "flow_response_identity_baseline_count": 2,
                "pre_dispatch_baseline_fingerprint": "a" * 64,
                "activation": {
                    "input_dispatched": True,
                    "trusted_click_seen": True,
                    "activation_verified": True,
                    "provider_acceptance_transition": True,
                },
            })
            with patch(
                "story_auto.providers.flow.service.atomic_write_json",
                side_effect=OSError("fixture write failure"),
            ):
                with self.assertRaises(OSError):
                    _persist_video_recovery_checkpoint_after_acceptance(
                        paths=paths,
                        manifest=manifest,
                        request=request,
                        attempt=attempt,
                        generator=generator,
                    )
            self.assertEqual(attempt, before_attempt)
            self.assertEqual(manifest_path.read_bytes(), before_bytes)

    def test_executor_installs_and_clears_pre_acquisition_binding_seam(self):
        events = []

        class Capabilities:
            @staticmethod
            def require(media_type, has_reference):
                events.append(("capability", media_type, has_reference))

        class Generator:
            dispatch_confirmed = False

            def set_before_provider_boundary(self, callback):
                self.before_provider = callback

            def set_before_video_acquisition(self, callback):
                self.before_acquisition = callback

            def __call__(self, _request, _refs, _destination):
                self.before_provider()
                events.append("provider_boundary")
                self.dispatch_confirmed = True
                return self.before_acquisition(IDENTITY)

        generator = Generator()
        result = FlowExecutor(Capabilities(), generator).run(
            {"media_type": "VIDEO"},
            ["reference.png"],
            Path("unused.mp4"),
            before_provider_boundary=lambda: events.append("persisted_boundary"),
            before_video_acquisition=lambda identity: (
                events.append(("persisted_identity", identity)), "bound"
            )[1],
        )
        self.assertEqual(result, "bound")
        self.assertEqual(
            events,
            [
                ("capability", "VIDEO", True),
                "persisted_boundary",
                "provider_boundary",
                ("persisted_identity", IDENTITY),
            ],
        )
        self.assertIsNone(generator.before_provider)
        self.assertIsNone(generator.before_acquisition)

    def test_executor_installs_acceptance_checkpoint_before_acquisition(self):
        events = []

        class Capabilities:
            @staticmethod
            def require(_media_type, _has_reference):
                pass

        class Generator:
            def set_before_provider_boundary(self, callback):
                self.before_provider = callback

            def set_after_provider_acceptance(self, callback):
                self.after_acceptance = callback

            def set_before_video_acquisition(self, callback):
                self.before_acquisition = callback

            def __call__(self, _request, _refs, _destination):
                self.before_provider()
                self.after_acceptance()
                return self.before_acquisition(IDENTITY)

        generator = Generator()
        result = FlowExecutor(Capabilities(), generator).run(
            {"media_type": "VIDEO"},
            ["reference.png"],
            Path("unused.mp4"),
            before_provider_boundary=lambda: events.append("provider_boundary"),
            after_provider_acceptance=lambda: events.append("acceptance_checkpoint"),
            before_video_acquisition=lambda identity: (
                events.append(("identity_checkpoint", identity)), "bound"
            )[1],
        )
        self.assertEqual(result, "bound")
        self.assertEqual(events, [
            "provider_boundary",
            "acceptance_checkpoint",
            ("identity_checkpoint", IDENTITY),
        ])
        self.assertIsNone(generator.before_provider)
        self.assertIsNone(generator.after_acceptance)
        self.assertIsNone(generator.before_acquisition)

    def test_executor_attribution_accepts_only_matching_response_binding(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths, project_id = self.make_project(root)
            bound = persist_attempt_video_identity(
                runtime.root, project_id, "req_video", 1, IDENTITY,
            )
            attempt = read_json(
                paths.artifact_path("output/generation_manifest.json")
            )["requests"][0]["attempts"][0]
            identity = f"response-binding:{bound.binding_sha256}"
            generator = SimpleNamespace(
                last_settings={
                    "dispatch_confirmation_state": "CONFIRMED",
                    "flow_observed_video_identity_binding_sha256": bound.binding_sha256,
                    "attribution_state": "CONFIRMED",
                    "attribution_method": "passive_response_identity_binding",
                    "attribution_method_version": "flow-observed-video-binding/1.0.0",
                    "attributed_provider_identity": {"identity": identity},
                    "attribution_confirmation_timestamp": "2026-09-20T00:00:01+00:00",
                }
            )
            _record_attempt_provider_state(attempt, generator)
            _confirm_executor_attribution(attempt, generator)
            self.assertEqual(
                attempt["attribution_events"][-1]["provider_identity"],
                {"identity": identity},
            )
            generator.last_settings[
                "flow_observed_video_identity_binding_sha256"
            ] = "0" * 64
            with self.assertRaises(FlowError) as caught:
                _confirm_executor_attribution(attempt, generator)
            self.assertEqual(
                caught.exception.failure_class, "FLOW_VIDEO_IDENTITY_BINDING_INVALID",
            )

    def test_live_response_path_persists_before_acquiring_bytes(self):
        events = []

        class Observer:
            @staticmethod
            def identities():
                return {IDENTITY}

        class Acquirer:
            def __init__(self, _runtime, _observer):
                pass

            @staticmethod
            def acquire(identity, destination):
                events.append(("acquire", identity))
                return {
                    "path": str(destination),
                    "acquisition_version": "fixture-acquisition/1.0.0",
                }

        dispatch = DispatchEvidenceTracker()
        activation = {
            "input_dispatched": True,
            "trusted_click_seen": True,
            "activation_verified": True,
            "provider_acceptance_transition": True,
        }
        generator = LiveFlowGenerator(
            FlowRuntime(Path("profile"), "cdp", "url", PROJECT_IDENTITY)
        )
        generator.last_settings = {}
        generator.set_before_video_acquisition(
            lambda identity: (
                events.append(("persist", identity)),
                SimpleNamespace(binding_sha256="b" * 64),
            )[1]
        )
        with patch("story_auto.providers.flow.live.FlowObservedVideoAcquirer", Acquirer):
            result = generator._try_response_identity_video(
                Observer(), set(), dispatch, activation, True, Path("result.mp4"),
            )
        self.assertEqual(result, Path("result.mp4"))
        self.assertEqual(events, [("persist", IDENTITY), ("acquire", IDENTITY)])
        self.assertEqual(
            generator.last_settings["flow_observed_video_identity_binding_sha256"],
            "b" * 64,
        )
        self.assertEqual(
            generator.last_settings["candidate_acquisition_state"], "RESOLVED",
        )

    def test_passive_identity_baseline_stabilizes_without_dom_card_authority(self):
        class Observer:
            observed_response_count = 1

            @staticmethod
            def identities():
                return {IDENTITY}

        generator = LiveFlowGenerator(
            FlowRuntime(Path("profile"), "cdp", "url", PROJECT_IDENTITY)
        )
        tick = iter(index * 0.5 for index in range(100))
        with patch(
            "story_auto.providers.flow.live.time.monotonic",
            side_effect=lambda: next(tick),
        ), patch("story_auto.providers.flow.live.time.sleep"):
            baseline = generator._stable_response_identity_set(Observer())
        self.assertEqual(baseline, {IDENTITY})

    def test_timeout_recovery_proves_one_exact_addition_from_sealed_baseline(self):
        baseline = {IDENTITY, OTHER_IDENTITY}
        fingerprint = response_identity_set_fingerprint(baseline)
        self.assertEqual(
            recoverable_new_response_identity(
                baseline_fingerprint=fingerprint,
                baseline_count=2,
                current=baseline | {THIRD_IDENTITY},
            ),
            THIRD_IDENTITY,
        )
        self.assertIsNone(
            recoverable_new_response_identity(
                baseline_fingerprint=fingerprint,
                baseline_count=2,
                current=baseline | {THIRD_IDENTITY, FlowObservedIdentity(
                    "dddddddd-eeee-ffff-0000-111111111111",
                    PROJECT_IDENTITY,
                    "66666666-5555-4444-3333-222222222222",
                )},
            )
        )

    def test_timeout_recovery_can_prove_unique_bounded_multi_identity_delta(self):
        baseline = {IDENTITY, OTHER_IDENTITY}
        fourth = FlowObservedIdentity(
            "dddddddd-eeee-ffff-0000-111111111111",
            PROJECT_IDENTITY,
            "66666666-5555-4444-3333-222222222222",
        )
        self.assertEqual(
            recoverable_response_identity_delta(
                baseline_fingerprint=response_identity_set_fingerprint(baseline),
                baseline_count=2,
                current=baseline | {THIRD_IDENTITY, fourth},
            ),
            {THIRD_IDENTITY, fourth},
        )
        self.assertIsNone(
            recoverable_response_identity_delta(
                baseline_fingerprint=response_identity_set_fingerprint(baseline),
                baseline_count=2,
                current=baseline | {THIRD_IDENTITY, fourth},
                maximum_additions=1,
            )
        )
        self.assertIsNone(
            recoverable_new_response_identity(
                baseline_fingerprint="0" * 64,
                baseline_count=2,
                current=baseline | {THIRD_IDENTITY},
            )
        )

    def test_timeout_recovery_refuses_combinatorial_identity_search(self):
        current = {
            FlowObservedIdentity(
                f"{index:08x}-0000-0000-0000-000000000000",
                PROJECT_IDENTITY,
                f"{index:08x}-1111-1111-1111-111111111111",
            )
            for index in range(318)
        }
        self.assertIsNone(
            recoverable_response_identity_delta(
                baseline_fingerprint="0" * 64,
                baseline_count=316,
                current=current,
            )
        )

    def test_live_response_path_never_acquires_without_persistence_callback(self):
        class Observer:
            @staticmethod
            def identities():
                return {IDENTITY}

        dispatch = DispatchEvidenceTracker()
        activation = {
            "input_dispatched": True,
            "trusted_click_seen": True,
            "activation_verified": True,
            "provider_acceptance_transition": True,
        }
        generator = LiveFlowGenerator(
            FlowRuntime(Path("profile"), "cdp", "url", PROJECT_IDENTITY)
        )
        generator.last_settings = {}
        with self.assertRaises(FlowError) as caught:
            generator._try_response_identity_video(
                Observer(), set(), dispatch, activation, True,
                Path("must-not-exist.mp4"),
            )
        self.assertEqual(
            caught.exception.failure_class,
            "FLOW_VIDEO_IDENTITY_BINDING_PRECONDITION_FAILED",
        )

    def test_mid_generation_checkpoint_reconciles_without_generate(self):
        baseline = {IDENTITY, OTHER_IDENTITY}
        settings = {
            "activation": {
                "input_dispatched": True,
                "trusted_click_seen": True,
                "activation_verified": True,
                "provider_acceptance_transition": True,
            },
            "composer_transition_seen": True,
            "pre_dispatch_baseline_fingerprint": response_identity_set_fingerprint(
                baseline,
            ),
            "flow_response_identity_baseline_count": len(baseline),
        }
        attempt = {
            "attempt": 1,
            "status": "SUBMITTED",
            "provider_execution_state": "PROVIDER_BOUNDARY_ENTERED",
            "dispatch_confirmed": False,
            "provider_settings": settings,
            "video_recovery_checkpoint": {
                "state": "PROVIDER_ACCEPTED_AWAITING_OUTPUT",
                "retry_authorized": False,
            },
        }
        calls = []

        class Observer:
            def __init__(self, _runtime):
                pass

            def start(self):
                calls.append("observer_start")

            def close(self):
                calls.append("observer_close")

            @staticmethod
            def resolve_urls(_urls):
                return {THIRD_IDENTITY}

        class Page:
            def command(self, method, _params):
                calls.append(method)

            @staticmethod
            def evaluate(_script):
                return ["thumbnail"]

            def close(self):
                calls.append("page_close")

        class Acquirer:
            def __init__(self, _runtime, _observer):
                pass

            @staticmethod
            def acquire(identity, destination):
                calls.append(("acquire", identity))
                return {
                    "path": str(destination),
                    "acquisition_version": "fixture-acquisition/1.0.0",
                }

        generator = LiveFlowGenerator(
            FlowRuntime(Path("profile"), "cdp", "url", PROJECT_IDENTITY)
        )
        generator.set_before_video_acquisition(
            lambda identity: (
                calls.append(("persist", identity)),
                SimpleNamespace(binding_sha256="b" * 64),
            )[1]
        )
        with patch.object(
            generator, "_verify_persisted_poll_evidence", return_value={},
        ), patch.object(
            generator, "_stable_response_identity_set",
            return_value=baseline | {THIRD_IDENTITY},
        ), patch(
            "story_auto.providers.flow.live.FlowPassiveResponseObserver", Observer,
        ), patch(
            "story_auto.providers.flow.live.CdpPage.open", return_value=Page(),
        ), patch(
            "story_auto.providers.flow.live.FlowObservedVideoAcquirer", Acquirer,
        ):
            result = generator.reconcile(
                {"media_type": "VIDEO"}, attempt, Path("recovered.mp4"),
            )
        self.assertEqual(result["state"], "CONFIRMED_OUTPUT")
        self.assertEqual(result["evidence"]["dispatch_confirmation_signal"],
                         "passive_response_identity_recovered")
        self.assertEqual(calls.count("Page.reload"), 1)
        self.assertEqual(
            [item for item in calls if isinstance(item, tuple)],
            [("persist", THIRD_IDENTITY), ("acquire", THIRD_IDENTITY)],
        )

    def test_bound_identity_crash_window_finalizes_same_canonical_attempt(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, paths, project_id = self.make_project(root)
            bound = persist_attempt_video_identity(
                runtime.root, project_id, "req_video", 1, IDENTITY,
            )
            manifest_path = paths.artifact_path("output/generation_manifest.json")
            manifest = read_json(manifest_path)
            entry = manifest["requests"][0]
            attempt = entry["attempts"][0]
            entry.update({
                "status": "FAILED_RETRYABLE",
                "failure_class": "FLOW_VIDEO_ACQUISITION_FAILED",
                "provider_submissions": 1,
            })
            attempt.update({
                "status": "FAILED_RETRYABLE",
                "failure_class": "FLOW_VIDEO_ACQUISITION_FAILED",
                "provider_settings": {
                    "composer_transition_seen": True,
                    "activation": {
                        "input_dispatched": True,
                        "trusted_click_seen": True,
                        "activation_verified": True,
                        "provider_acceptance_transition": True,
                    },
                },
            })
            atomic_write_json(manifest_path, manifest)
            calls = []

            class Observer:
                def __init__(self, _runtime):
                    pass

                def start(self):
                    calls.append("observer_start")

                def close(self):
                    calls.append("observer_close")

            class Page:
                def command(self, method, _params):
                    calls.append(method)

                def close(self):
                    calls.append("page_close")

            class Acquirer:
                def __init__(self, _runtime, _observer):
                    pass

                @staticmethod
                def acquire(identity, destination):
                    calls.append(("acquire", identity))
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(b"exact-bound-fixture-video")
                    return {
                        "path": str(destination),
                        "acquisition_version": "fixture-acquisition/1.0.0",
                    }

            generator = LiveFlowGenerator(
                FlowRuntime(
                    Path("profile"), "cdp",
                    f"https://flow.google.com/project/{PROJECT_IDENTITY}",
                    PROJECT_IDENTITY,
                )
            )
            metadata = {
                "sha256": hashlib.sha256(b"exact-bound-fixture-video").hexdigest(),
                "duration_seconds": 8.0,
                "width": 1280,
                "height": 720,
                "codec": "h264",
                "container": "mp4",
                "audio_present": True,
            }
            with patch.object(
                generator, "_verify_persisted_poll_evidence", return_value={},
            ), patch.object(
                generator, "_stable_response_identity_set", return_value={IDENTITY},
            ), patch(
                "story_auto.providers.flow.live.FlowPassiveResponseObserver", Observer,
            ), patch(
                "story_auto.providers.flow.live.CdpPage.open", return_value=Page(),
            ), patch(
                "story_auto.providers.flow.live.FlowObservedVideoAcquirer", Acquirer,
            ), patch(
                "story_auto.providers.flow.service.validate_video", return_value=metadata,
            ):
                result = reconcile_unresolved_flow_attempt(
                    runtime.root,
                    project_id,
                    "req_video",
                    executor=FlowExecutor(SimpleNamespace(), generator),
                )
            self.assertTrue(result["released"])
            self.assertEqual(result["status"], "SUCCEEDED")
            final = read_json(manifest_path)["requests"][0]
            self.assertEqual(final["provider_submissions"], 1)
            self.assertEqual(len(final["attempts"]), 1)
            self.assertEqual(
                final["attempts"][0]["flow_observed_video_identity"]["binding_sha256"],
                bound.binding_sha256,
            )
            self.assertEqual(final["selected_asset"]["sha256"], metadata["sha256"])
            self.assertEqual(calls.count("Page.reload"), 1)
            self.assertEqual(
                [item for item in calls if isinstance(item, tuple)],
                [("acquire", IDENTITY)],
            )

    def test_live_response_path_waits_for_causal_dispatch_confirmation(self):
        class Observer:
            @staticmethod
            def identities():
                return {IDENTITY}

        generator = LiveFlowGenerator(
            FlowRuntime(Path("profile"), "cdp", "url", PROJECT_IDENTITY)
        )
        generator.last_settings = {}
        calls = []
        generator.set_before_video_acquisition(lambda identity: calls.append(identity))
        result = generator._try_response_identity_video(
            Observer(), set(), DispatchEvidenceTracker(), {
                "input_dispatched": True,
                "trusted_click_seen": True,
                "activation_verified": False,
                "provider_acceptance_transition": True,
            }, True, Path("must-not-exist.mp4"),
        )
        self.assertIsNone(result)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()

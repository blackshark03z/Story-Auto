"""Creation boundary regressions; no live providers or canonical runtime."""
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from story_auto.application.operator import OperatorService
from story_auto.core.artifacts import read_json
from story_auto.providers.flow.project_binding import FlowProjectBindingError, FlowProjectBindingService, LiveFlowProjects
from story_auto.providers.flow.project_binding import canonical_project
from story_auto.providers.flow.connection import normalize_project_url
from story_auto.providers.flow.project_surface import list_agrees_with_dom, observed_project_list
from story_auto.providers.flow.session import FlowCapabilities, FlowSessionError
from tests import test_flow_project_binding as fixtures
from tests.test_flow_project_binding import FakeProjects, validated


PROJECT = "prj_1234567890abcdef"


class BoundaryProjects(FakeProjects):
    failure = None
    after_activation = False

    def create_project_with_activation(self, name, before_activation):
        if self.failure and not self.after_activation:
            raise self.failure
        before_activation()
        result = super().create_project(name)
        self.matches.append(result)
        if self.failure:
            raise self.failure
        return result


class FlowProjectActivationTests(unittest.TestCase):
    def make_project(self, root):
        return fixtures.FlowProjectBindingTests().make_project(root)

    def binding(self, runtime):
        return read_json(runtime.projects / PROJECT / "project.json")["settings"]["provider_binding"]["flow"]

    def test_pre_activation_discovery_failure_remains_retryable(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, service = self.make_project(root)
            adapter = BoundaryProjects()
            adapter.failure = FlowProjectBindingError("FLOW_HOST_MIGRATED_RETRY_REQUIRED")
            with self.assertRaises(FlowProjectBindingError):
                service.ensure(PROJECT, adapter)
            binding = self.binding(runtime)
            self.assertEqual(binding["activation_state"], "NOT_ATTEMPTED")
            self.assertNotIn("activation_started_at", binding)
            self.assertEqual(binding["last_setup_failure"], "FLOW_HOST_MIGRATED_RETRY_REQUIRED")
            self.assertEqual(binding["last_setup_failure_phase"], "PRE_ACTIVATION")
            self.assertEqual(adapter.created, [])
            adapter.failure = None
            self.assertEqual(service.ensure(PROJECT, adapter)["state"], "BOUND")
            self.assertEqual(len(adapter.created), 1)

    def test_post_activation_timeout_reconciles_after_service_restart(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, service = self.make_project(root)
            adapter = BoundaryProjects()
            adapter.failure = FlowSessionError("FLOW_CDP_COMMAND_TIMEOUT")
            adapter.after_activation = True
            with self.assertRaises(FlowSessionError):
                service.ensure(PROJECT, adapter)
            self.assertEqual(self.binding(runtime)["activation_state"], "STARTED")
            restarted = FlowProjectBindingService(runtime, service.connections)
            self.assertEqual(restarted.ensure(PROJECT, adapter)["state"], "BOUND")
            self.assertEqual(len(adapter.created), 1)

    def test_unknown_outcome_without_match_never_creates_again(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, service = self.make_project(root)
            adapter = BoundaryProjects()
            adapter.failure = FlowSessionError("FLOW_CDP_COMMAND_TIMEOUT")
            adapter.after_activation = True
            with self.assertRaises(FlowSessionError): service.ensure(PROJECT, adapter)
            adapter.matches.clear()
            for _ in range(2):
                with self.assertRaisesRegex(FlowProjectBindingError, "RECONCILIATION_REQUIRED"):
                    service.ensure(PROJECT, adapter)
            self.assertEqual(len(adapter.created), 1)
            self.assertEqual(self.binding(runtime)["last_setup_failure"], "FLOW_PROJECT_CREATION_RECONCILIATION_REQUIRED")

    def test_auth_during_create_preparation_persists_exact_product_state(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, service = self.make_project(root)
            adapter = BoundaryProjects()
            adapter.failure = FlowSessionError("FLOW_AUTH_REQUIRED")
            with self.assertRaises(FlowSessionError): service.ensure(PROJECT, adapter)
            self.assertEqual(self.binding(runtime)["activation_state"], "NOT_ATTEMPTED")
            self.assertEqual(service.connections.connection_for_project(PROJECT)[1]["status"], "AUTH_REQUIRED")
            self.assertEqual(adapter.created, [])

    def test_application_creation_ensures_binding_before_return(self):
        with tempfile.TemporaryDirectory() as root, patch("story_auto.application.operator._validate_new_project_narrator"):
            adapter = BoundaryProjects()
            app = OperatorService(root, flow_projects=adapter)
            app.flow_connections.save_validated_candidate(validated())
            before = app.runtime.flow_connection_file.read_bytes()
            result = app.create_project(project_id=PROJECT, render_mode="full_image", content="# Story\n\n## Narration\n\nA test story.")
            self.assertEqual(result["flow_connection"]["status"], "CONNECTED")
            self.assertEqual(self.binding(app.runtime)["state"], "BOUND")
            self.assertEqual(len(adapter.created), 1)
            self.assertEqual(app.runtime.flow_connection_file.read_bytes(), before)

    def test_generation_reopens_bound_project_before_live_preflight_and_dispatch(self):
        with tempfile.TemporaryDirectory() as root, patch("story_auto.application.operator._validate_new_project_narrator"):
            adapter = BoundaryProjects()
            app = OperatorService(root, flow_projects=adapter)
            app.flow_connections.save_validated_candidate(validated())
            app.create_project(project_id=PROJECT, render_mode="full_image",
                               content="# Story\n\n## Narration\n\nA test story.")
            connection, _ = app.flow_connections.connection_for_project(
                PROJECT, required_capabilities=["IMAGE"])
            events = []

            def ensure(*_args):
                events.append("exact_project_opened")
                return canonical_project(self.binding(app.runtime))

            def inspect(*_args):
                self.assertEqual(events, ["exact_project_opened"])
                events.append("live_preflight")
                return FlowCapabilities(True, True, True, True, True, True)

            def execute(*_args, **_kwargs):
                self.assertEqual(events, ["exact_project_opened", "live_preflight"])
                events.append("execute")
                return {"new_submissions": 0}

            with patch.object(app.flow_project_bindings, "ensure", side_effect=ensure), \
                 patch.object(app.flow_connections, "connection_for_project",
                              return_value=(connection, {"status":"CONNECTED"})), \
                 patch.object(app.flow_connections, "runtime_for_connection",
                              return_value=SimpleNamespace()), \
                 patch.object(app, "_flow_capabilities_for_project", return_value=["IMAGE"]), \
                 patch("story_auto.application.operator.preflight", side_effect=inspect), \
                 patch("story_auto.application.operator.LiveFlowGenerator", return_value=object()), \
                 patch("story_auto.application.operator.execute_generation", side_effect=execute):
                app.generate(PROJECT, request_ids={"req_01"}, max_requests=1)
            self.assertEqual(events, ["exact_project_opened", "live_preflight", "execute"])

    def test_missing_global_connection_does_not_silently_skip_setup(self):
        with tempfile.TemporaryDirectory() as root, patch("story_auto.application.operator._validate_new_project_narrator"):
            adapter = BoundaryProjects()
            app = OperatorService(root, flow_projects=adapter)
            app.create_project(project_id=PROJECT, render_mode="full_image")
            self.assertEqual(self.binding(app.runtime)["state"], "BOUND")
            self.assertEqual(len(adapter.created), 1)

    def test_live_adapter_marks_boundary_only_immediately_before_click(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, service = self.make_project(root)
            adapter = LiveFlowProjects(runtime)
            adapter.find_projects = lambda name: []
            adapter.last_list_evidence = {"observed_at":"2026-09-05T00:00:00Z", "projects":[]}
            adapter._confirm_saved_title = lambda provider: None
            adapter._wait_project = lambda page: "https://flow.google.com/project/one"
            adapter._set_title = lambda page, name: None
            adapter.open_project = FakeProjects().open_project
            test = self

            class Page:
                clicks = 0
                def evaluate(self, expression):
                    test.assertEqual(test.binding(runtime)["activation_state"], "NOT_ATTEMPTED")
                    return "https://flow.google.com/" if expression == "location.href" else [{"x":10,"y":20}]
                def command(self, method, params=None): pass
                def click(self, x, y):
                    test.assertEqual(test.binding(runtime)["activation_state"], "STARTED")
                    self.clicks += 1
                def close(self): pass

            page = Page()
            adapter._page = lambda: page
            self.assertEqual(service.ensure(PROJECT, adapter)["state"], "BOUND")
            self.assertEqual(page.clicks, 1)

    def test_application_failure_returns_saved_identity_and_precise_setup_failure(self):
        with tempfile.TemporaryDirectory() as root, patch("story_auto.application.operator._validate_new_project_narrator"):
            adapter = BoundaryProjects()
            adapter.failure = FlowSessionError("FLOW_AUTH_REQUIRED")
            app = OperatorService(root, flow_projects=adapter)
            result = app.create_project(project_id=PROJECT, render_mode="full_image")
            self.assertEqual(result["project_id"], PROJECT)
            self.assertEqual(result["flow_setup"]["failure_class"], "FLOW_AUTH_REQUIRED")
            self.assertEqual(result["flow_connection"]["status"], "AUTH_REQUIRED")
            self.assertEqual(adapter.created, [])

    def test_creation_identity_survives_open_failure_and_retry(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, service = self.make_project(root)
            adapter = BoundaryProjects()
            original_open = adapter.open_project
            adapter.open_project = lambda *a: (_ for _ in ()).throw(FlowSessionError("FLOW_CDP_UNAVAILABLE"))
            with self.assertRaises(FlowSessionError): service.ensure(PROJECT, adapter)
            self.assertEqual(self.binding(runtime)["state"], "CREATED")
            self.assertEqual(self.binding(runtime)["project_identity"], "new-one")
            adapter.open_project = original_open
            self.assertEqual(service.ensure(PROJECT, adapter)["state"], "BOUND")
            self.assertEqual(len(adapter.created), 1)

    def test_current_host_url_and_identity_are_canonical(self):
        value = canonical_project({"project_name":"StoryAuto_current", "project_identity":"abc-123",
                                   "project_url":"https://flow.google.com/project/abc-123/"})
        self.assertEqual(value, {"project_name":"StoryAuto_current", "project_identity":"abc-123",
                                 "project_url":"https://flow.google.com/project/abc-123"})
        self.assertEqual(normalize_project_url(value["project_url"]), value["project_url"])
        with self.assertRaisesRegex(Exception, "FLOW_URL_INVALID"):
            normalize_project_url("https://flow.google.com/about")

    def test_observed_current_list_response_must_agree_with_complete_grid(self):
        import json
        provider_rows = [["abc-123", ["StoryAuto_current", None, [123, 456]]]]
        envelope = [["wrb.fr", "UpteDb", json.dumps([provider_rows]), None, None, None, "generic"]]
        rows = observed_project_list(")]}'\n\n1\n" + json.dumps(envelope))
        self.assertEqual(rows[0]["project_identity"], "abc-123")
        self.assertEqual(rows[0]["created_at_epoch_seconds"], 123)
        dom = {"ready":True, "items":1,
               "rows":[{"project_name":"StoryAuto_current",
                         "project_url":"https://flow.google.com/project/abc-123"}]}
        self.assertTrue(list_agrees_with_dom(rows, dom))
        self.assertFalse(list_agrees_with_dom(rows, {**dom, "items":2}))

    def test_current_host_receipt_persists_identity_before_name_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, service = self.make_project(root)

            class ReceiptProjects(FakeProjects):
                create_calls = 0
                def create_project_with_receipt(self, name, before_activation, record_created):
                    self.create_calls += 1
                    before_activation({"project_ids":["existing"], "observed_at":"2026-09-05T00:00:00Z"})
                    created = {"project_name":name, "project_url":"https://flow.google.com/project/new-current",
                               "project_identity":"new-current"}
                    record_created(created)
                    pending = self_test.binding(runtime)
                    self_test.assertEqual((pending["state"], pending["name_confirmation_pending"]), ("CREATED", True))
                    return created

            self_test = self
            adapter = ReceiptProjects()
            bound = service.ensure(PROJECT, adapter)
            self.assertEqual((bound["state"], bound["project_url"], bound["project_identity"]),
                             ("BOUND", "https://flow.google.com/project/new-current", "new-current"))
            self.assertEqual(bound["activation_baseline_project_ids"], ["existing"])
            self.assertEqual(adapter.create_calls, 1)

    def test_restart_after_click_uses_unique_baseline_delta_without_second_create(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, service = self.make_project(root)

            class CrashProjects(FakeProjects):
                create_calls = 0
                def create_project_with_receipt(self, name, before_activation, record_created):
                    self.create_calls += 1
                    before_activation({"project_ids":["existing"], "observed_at":"2026-09-05T00:00:00Z"})
                    raise FlowSessionError("FLOW_CDP_COMMAND_TIMEOUT")
                def reconcile_started(self, binding):
                    return {"project_name":binding["project_name"],
                            "project_url":"https://flow.google.com/project/delta-one",
                            "project_identity":"delta-one"}

            adapter = CrashProjects()
            with self.assertRaises(FlowSessionError):
                service.ensure(PROJECT, adapter)
            self.assertEqual(self.binding(runtime)["activation_baseline_project_ids"], ["existing"])
            restarted = FlowProjectBindingService(runtime, service.connections)
            self.assertEqual(restarted.ensure(PROJECT, adapter)["project_identity"], "delta-one")
            self.assertEqual(adapter.create_calls, 1)


if __name__ == "__main__": unittest.main()

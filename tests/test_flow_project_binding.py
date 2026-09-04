from __future__ import annotations

import tempfile
import unittest

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.connection import FlowConnectionService
from story_auto.providers.flow.live import _resolve_pre_dispatch_provider_model
from story_auto.providers.flow.service import FlowError
from story_auto.providers.flow.project_binding import (
    FlowProjectBindingError,
    FlowProjectBindingService,
    LiveFlowProjects,
    managed_flow_settings,
)


def validated(url="https://labs.google/fx/vi/tools/flow/project/legacy"):
    return {
        "status": "CONNECTED",
        "project_url": url,
        "project_identity": url,
        "observed_capabilities": {
            "IMAGE": True,
            "VIDEO": True,
            "REFERENCE_IMAGE": True,
            "FRAME_VIDEO": True,
        },
    }


class FakeProjects:
    def __init__(self, matches=()):
        self.matches = list(matches)
        self.created = []
        self.opened = []

    def find_projects(self, name):
        return [item for item in self.matches if item["project_name"] == name]

    def create_project(self, name):
        self.created.append(name)
        return {
            "project_name": name,
            "project_url": "https://labs.google/fx/vi/tools/flow/project/new-one",
            "project_identity": "new-one",
        }

    def open_project(self, project_url, project_identity, project_name):
        self.opened.append((project_url, project_identity, project_name))
        return {
            "project_name": project_name,
            "project_url": project_url,
            "project_identity": project_identity,
        }


class FlowProjectBindingTests(unittest.TestCase):
    def make_project(self, root, project_id="prj_1234567890abcdef"):
        runtime = RuntimeLayout.from_root(root)
        create_project(runtime, ProjectConfig(project_id, render_mode="full_image",
                                               settings=managed_flow_settings({}, project_id)))
        connections = FlowConnectionService(runtime)
        connections.save_validated_candidate(validated())
        return runtime, FlowProjectBindingService(runtime, connections)

    def test_new_managed_project_persists_intent_then_binds_exact_created_project(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, service = self.make_project(root)
            before = read_json(runtime.projects / "prj_1234567890abcdef" / "project.json")
            self.assertEqual(before["settings"]["provider_binding"]["flow"]["state"], "CREATE_INTENT")
            adapter = FakeProjects()
            binding = service.ensure("prj_1234567890abcdef", adapter)
            self.assertEqual((binding["state"], binding["project_name"], len(adapter.created)),
                             ("BOUND", "StoryAuto_1234567890ab", 1))
            self.assertEqual(binding["project_identity"], "new-one")

    def test_bound_restart_reopens_exact_project_and_never_creates(self):
        with tempfile.TemporaryDirectory() as root:
            _runtime, service = self.make_project(root)
            first = FakeProjects()
            binding = service.ensure("prj_1234567890abcdef", first)
            restarted = FakeProjects()
            same = service.ensure("prj_1234567890abcdef", restarted)
            self.assertEqual(same, binding)
            self.assertEqual(restarted.created, [])
            self.assertEqual(restarted.opened, [(binding["project_url"], "new-one", binding["project_name"])])

    def test_crash_after_activation_reconciles_one_exact_name_without_duplicate_create(self):
        with tempfile.TemporaryDirectory() as root:
            _runtime, service = self.make_project(root)
            service.mark_activation_started("prj_1234567890abcdef")
            match = {
                "project_name": "StoryAuto_1234567890ab",
                "project_url": "https://labs.google/fx/vi/tools/flow/project/recovered",
                "project_identity": "recovered",
            }
            adapter = FakeProjects([match])
            binding = service.ensure("prj_1234567890abcdef", adapter)
            self.assertEqual((binding["state"], binding["project_identity"], adapter.created),
                             ("BOUND", "recovered", []))

    def test_crash_with_no_or_multiple_exact_matches_fails_closed_without_create(self):
        for matches in ([], [
            {"project_name": "StoryAuto_1234567890ab", "project_url": "https://labs.google/fx/vi/tools/flow/project/a", "project_identity": "a"},
            {"project_name": "StoryAuto_1234567890ab", "project_url": "https://labs.google/fx/vi/tools/flow/project/b", "project_identity": "b"},
        ]):
            with self.subTest(count=len(matches)), tempfile.TemporaryDirectory() as root:
                _runtime, service = self.make_project(root)
                service.mark_activation_started("prj_1234567890abcdef")
                adapter = FakeProjects(matches)
                with self.assertRaisesRegex(FlowProjectBindingError, "FLOW_PROJECT_CREATION_RECONCILIATION_REQUIRED"):
                    service.ensure("prj_1234567890abcdef", adapter)
                self.assertEqual(adapter.created, [])

    def test_wrong_active_project_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            _runtime, service = self.make_project(root)
            adapter = FakeProjects()
            service.ensure("prj_1234567890abcdef", adapter)
            adapter.open_project = lambda *_: {
                "project_name": "StoryAuto_1234567890ab",
                "project_url": "https://labs.google/fx/vi/tools/flow/project/wrong",
                "project_identity": "wrong",
            }
            with self.assertRaisesRegex(FlowProjectBindingError, "FLOW_PROJECT_BINDING_MISMATCH"):
                service.ensure("prj_1234567890abcdef", adapter)
            self.assertEqual(adapter.created, ["StoryAuto_1234567890ab"])

    def test_managed_binding_composes_project_identity_without_changing_global_legacy_record(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, service = self.make_project(root)
            service.ensure("prj_1234567890abcdef", FakeProjects())
            connection, status = service.connections.connection_for_project("prj_1234567890abcdef", required_capabilities=["IMAGE"])
            self.assertEqual((status["status"], connection.project_identity), ("CONNECTED", "new-one"))
            self.assertEqual(service.connections.get_current_connection().project_identity,
                             "https://labs.google/fx/vi/tools/flow/project/legacy")

    def test_live_open_project_preserves_exact_active_project_without_navigation(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = RuntimeLayout.from_root(root)
            adapter = LiveFlowProjects(runtime)
            url = "https://labs.google/fx/vi/tools/flow/project/exact-one"
            name = "StoryAuto_exactone"

            class FakePage:
                def __init__(self): self.commands = []
                def evaluate(self, expression):
                    return url if expression == "location.href" else name
                def command(self, method, params=None):
                    self.commands.append((method, params))
                    if method == "Page.navigate": raise AssertionError("exact active project must not navigate")
                    return {}
                def close(self): pass

            page = FakePage()
            adapter._page = lambda: page
            observed = adapter.open_project(url, "exact-one", name)
            self.assertEqual(observed, {"project_name": name, "project_url": url, "project_identity": "exact-one"})
            self.assertEqual(page.commands, [])

    def test_known_empty_managed_project_can_supply_one_empty_provider_model_baseline(self):
        resolved, authority = _resolve_pre_dispatch_provider_model(
            [None, None, None], historical_records=[], history_seed=[], allow_known_empty=True)
        self.assertEqual(resolved, [[], [], []])
        self.assertEqual(authority, "AUTO_MANAGED_BOUND_PROJECT_WITH_NO_PRIOR_DISPATCH")
        for history, allowed in (([{"card_id": "old"}], True), ([], False)):
            with self.subTest(history=bool(history), allowed=allowed):
                with self.assertRaises(FlowError):
                    _resolve_pre_dispatch_provider_model(
                        [None, None, None], historical_records=history, history_seed=[],
                        allow_known_empty=allowed)


if __name__ == "__main__":
    unittest.main()

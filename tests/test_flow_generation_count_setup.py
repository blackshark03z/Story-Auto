"""Focused no-provider regression coverage for Flow generation-count preparation."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from story_auto.providers.flow.live import LiveFlowGenerator
from story_auto.providers.flow.settings import resolve_settings


class _FlowCountDom:
    """A provider-UI double: settings calls are distinct from Generate submissions."""

    def __init__(self, *, image_count: int = 4, video_count: int = 4):
        self.counts = {"IMAGE": image_count, "VIDEO": video_count}
        self.inspections: list[str] = []
        self.mutations: list[tuple[str, int]] = []
        self.request_settings: list[str] = []
        self.submissions = 0

    def inspect_generation_count(self, media_type: str) -> int:
        self.inspections.append(media_type)
        return self.counts[media_type]

    def configure_generation_count(self, media_type: str, count: int) -> None:
        self.mutations.append((media_type, count))
        self.counts[media_type] = count

    def apply_request_settings(self, settings):
        self.request_settings.append(settings.media_type)
        return {"actual_output_count": self.counts[settings.media_type]}


def _runtime(project_identity: str = "flow-project-a"):
    return SimpleNamespace(
        profile="runtime/browser/flow-profile",
        cdp_url="http://127.0.0.1:9222",
        project_url="https://labs.google/fx/tools/flow/project-a",
        project_identity=project_identity,
    )


def _settings(media_type: str):
    return resolve_settings({"media_type": media_type, "output_count": 1})


class FlowGenerationCountSetupTests(unittest.TestCase):
    def test_fresh_unknown_image_state_configures_and_verifies_one_once(self):
        generator, dom = LiveFlowGenerator(_runtime()), _FlowCountDom(image_count=4)

        result = generator.ensure_generation_count(dom, _settings("IMAGE"))

        self.assertEqual(dom.mutations, [("IMAGE", 1)])
        self.assertEqual(dom.inspections, ["IMAGE", "IMAGE"])
        self.assertEqual((result["actual_output_count"], result["generation_count_preparation"]),
                         (1, "CONFIGURED_AND_VERIFIED"))
        self.assertEqual(result["generation_count_setup"], {
            "ui_inspections": 2,
            "ui_mutations": 1,
        })
        self.assertEqual(dom.submissions, 0)

    def test_same_session_second_image_request_reuses_evidence_without_reopening_setup(self):
        generator, dom = LiveFlowGenerator(_runtime()), _FlowCountDom(image_count=4)

        generator.ensure_generation_count(dom, _settings("IMAGE"))
        result = generator.ensure_generation_count(dom, _settings("IMAGE"))

        self.assertEqual(dom.mutations, [("IMAGE", 1)])
        self.assertEqual(dom.inspections, ["IMAGE", "IMAGE"])
        self.assertEqual(result["generation_count_preparation"], "REUSED_VERIFIED_EVIDENCE")
        self.assertEqual(result["generation_count_setup"], {
            "ui_inspections": 0,
            "ui_mutations": 0,
        })

    def test_same_session_request_settings_are_not_reopened_when_their_identity_matches(self):
        generator, dom = LiveFlowGenerator(_runtime()), _FlowCountDom(image_count=1)

        generator.ensure_request_settings(dom, _settings("IMAGE"))
        generator.ensure_request_settings(dom, _settings("IMAGE"))

        self.assertEqual(dom.request_settings, ["IMAGE"])

    def test_same_session_video_setup_is_also_idempotent(self):
        generator, dom = LiveFlowGenerator(_runtime()), _FlowCountDom(video_count=3)

        first = generator.ensure_generation_count(dom, _settings("VIDEO"))
        second = generator.ensure_generation_count(dom, _settings("VIDEO"))

        self.assertEqual(dom.mutations, [("VIDEO", 1)])
        self.assertEqual(dom.inspections, ["VIDEO", "VIDEO"])
        self.assertEqual((first["actual_output_count"], second["generation_count_preparation"]),
                         (1, "REUSED_VERIFIED_EVIDENCE"))

    def test_provider_observed_reset_invalidates_evidence_then_reconfigures_once(self):
        generator, dom = LiveFlowGenerator(_runtime()), _FlowCountDom(image_count=4)
        generator.ensure_generation_count(dom, _settings("IMAGE"))
        dom.counts["IMAGE"] = 2

        current = generator.record_observed_generation_count("IMAGE", 2)
        result = generator.ensure_generation_count(dom, _settings("IMAGE"))

        self.assertFalse(current)
        self.assertEqual(dom.mutations, [("IMAGE", 1), ("IMAGE", 1)])
        self.assertEqual(result["generation_count_preparation"], "CONFIGURED_AND_VERIFIED")

    def test_different_flow_project_identity_never_reuses_old_evidence(self):
        dom = _FlowCountDom(image_count=4)
        generator = LiveFlowGenerator(_runtime("flow-project-a"))

        generator.ensure_generation_count(dom, _settings("IMAGE"))
        dom.counts["IMAGE"] = 4
        generator.runtime = _runtime("flow-project-b")
        generator.ensure_generation_count(dom, _settings("IMAGE"))

        self.assertEqual(dom.mutations, [("IMAGE", 1), ("IMAGE", 1)])

    def test_image_video_change_only_prepares_the_media_type_that_needs_it(self):
        generator, dom = LiveFlowGenerator(_runtime()), _FlowCountDom(image_count=4, video_count=3)

        generator.ensure_generation_count(dom, _settings("IMAGE"))
        generator.ensure_generation_count(dom, _settings("VIDEO"))
        generator.ensure_generation_count(dom, _settings("IMAGE"))

        self.assertEqual(dom.mutations, [("IMAGE", 1), ("VIDEO", 1)])
        self.assertEqual(dom.inspections, ["IMAGE", "IMAGE", "VIDEO", "VIDEO"])

    def test_repeated_matching_observation_never_mutates_provider_ui(self):
        generator, dom = LiveFlowGenerator(_runtime()), _FlowCountDom(image_count=1)

        first = generator.ensure_generation_count(dom, _settings("IMAGE"))
        second = generator.ensure_generation_count(dom, _settings("IMAGE"))

        self.assertEqual(dom.mutations, [])
        self.assertEqual(dom.inspections, ["IMAGE"])
        self.assertEqual((first["generation_count_preparation"], second["generation_count_preparation"]),
                         ("VERIFIED_CURRENT", "REUSED_VERIFIED_EVIDENCE"))
        self.assertEqual(dom.submissions, 0)

    def test_setup_observation_and_reconfiguration_create_no_submission_accounting(self):
        generator, dom = LiveFlowGenerator(_runtime()), _FlowCountDom(image_count=4, video_count=2)

        generator.ensure_generation_count(dom, _settings("IMAGE"))
        generator.ensure_generation_count(dom, _settings("VIDEO"))
        dom.counts["IMAGE"] = 3
        generator.record_observed_generation_count("IMAGE", 3)
        generator.ensure_generation_count(dom, _settings("IMAGE"))

        self.assertEqual(dom.submissions, 0)
        self.assertEqual(dom.mutations, [("IMAGE", 1), ("VIDEO", 1), ("IMAGE", 1)])


if __name__ == "__main__":
    unittest.main()

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.planning.service import (PlanningError, _timeline_acceptance,
    _timeline_schema, _resolve_timeline, validate_timeline, run_planning_stages)
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.application.production_queries import ProductionQueries
from story_auto.application.production_coordinator import ProductionCoordinator
from story_auto.providers.llm import LLMRequest, LLMResponse, GeminiReasoningRouter, RoutedGeminiProvider


def alignment(count):
    return {"duration_seconds": count, "segments": [{"segment_id": f"cue_{i:04d}",
        "start": i - 1, "end": i, "text": f"Cue {i}. "} for i in range(1, count + 1)]}


def grouping(*groups):
    return {"groups": [{"segment_ids": list(ids), "story_role": "story_beat", "summary": "A beat."} for ids in groups]}


class Provider:
    def __init__(self, outputs):
        self.outputs, self.calls = outputs, []

    def generate_structured(self, request):
        self.calls.append(request)
        if request.stage == "continuity":
            value = {"style": {}, "characters": [], "locations": [], "props": []}
        else:
            value = deepcopy(self.outputs[min(len(self.calls) - 1, len(self.outputs) - 1)])
        return LLMResponse(value, request.model, request.request_id, 1, 1, {})


class TimelineRecoveryTests(unittest.TestCase):
    def test_real_continue_entry_repairs_missing_story_plan_before_visual_compilation(self):
        from story_auto.application import OperatorService
        with tempfile.TemporaryDirectory() as root:
            runtime = RuntimeLayout.from_root(root)
            paths = create_project(runtime, ProjectConfig("prj_entry", render_mode="full_image",
                settings={"qc_policy": "MANUAL_REVIEW", "llm": {"provider": "gemini", "model": "fixture"}}),
                "## Narration\n\nSaved narration.")
            atomic_write_json(paths.artifact_path("output/alignment.json"), alignment(5))
            atomic_write_json(paths.artifact_path("output/content_manifest.json"), {"fixture": True})
            app = OperatorService(root)
            provider = Provider([grouping(["cue_0001", "cue_0005"])])
            with patch("story_auto.core.planning.service._default_provider", return_value=provider), \
                 patch.object(app, "start_or_resume", side_effect=AssertionError("Source must be reused")), \
                 patch.object(app, "generate", side_effect=AssertionError("No media dispatch")), \
                 patch.object(app, "plan_visuals", side_effect=AssertionError("Story review comes first")):
                result = app.continue_production(paths.project_id)
            self.assertEqual(result["outcome"], "OWNER_DECISION_REQUIRED")
            self.assertEqual(result["invoked_stages"], ["plan"])
            self.assertEqual(len(provider.calls), 2)  # timeline + continuity
            self.assertTrue(app.planning_review(paths.project_id)["story_timeline"])

    def accept(self, value, count=5):
        canonical = alignment(count)
        _timeline_acceptance("prj_fixture", canonical, "fixture")(value)
        timeline = _resolve_timeline("prj_fixture", canonical, value, {"direct_input_hashes": {"alignment_sha256": "fixture"}})
        validate_timeline(timeline, canonical)
        self.assertEqual([i for s in timeline["scenes"] for i in s["narration_segment_ids"]],
                         [s["segment_id"] for s in canonical["segments"]])
        return value

    def test_exact_353_cue_interior_omission(self):
        ids = [s["segment_id"] for s in alignment(353)["segments"]]
        value = grouping(ids[:274], [i for i in ids[274:290] if i != "cue_0289"], ids[290:])
        self.accept(value, 353)
        self.assertIn("cue_0289", value["groups"][1]["segment_ids"])

    def test_boundary_omission_is_ambiguous(self):
        value = grouping(["cue_0001", "cue_0002"], ["cue_0004", "cue_0005"])
        original = deepcopy(value)
        with self.assertRaisesRegex(PlanningError, "cue_0003"):
            self.accept(value)
        self.assertEqual(value, original)

    def test_duplicate_within_group_has_unique_owner(self):
        self.accept(grouping(["cue_0001", "cue_0001", "cue_0002"], ["cue_0003", "cue_0004", "cue_0005"]))

    def test_out_of_order_groups_and_ids(self):
        self.accept(grouping(["cue_0005", "cue_0004"], ["cue_0003", "cue_0001", "cue_0002"]))

    def test_multiple_interior_gaps_have_unique_owner(self):
        self.accept(grouping(["cue_0001", "cue_0005"]))

    def test_unknown_id_is_never_dropped(self):
        value = grouping(["cue_0001", "cue_9999", "cue_0005"])
        original = deepcopy(value)
        with self.assertRaisesRegex(PlanningError, "cue_9999"):
            self.accept(value)
        self.assertEqual(value, original)

    def test_interleaving_or_conflicting_assignments_rejected(self):
        for value in (grouping(["cue_0001", "cue_0003"], ["cue_0002", "cue_0004", "cue_0005"]),
                      grouping(["cue_0001", "cue_0002"], ["cue_0002", "cue_0005"])):
            original = deepcopy(value)
            with self.assertRaises(PlanningError): self.accept(value)
            self.assertEqual(value, original)

    def test_valid_output_unchanged(self):
        value = grouping([s["segment_id"] for s in alignment(5)["segments"]])
        original = deepcopy(value)
        self.accept(value)
        self.assertEqual(value, original)

    def routed(self, root, outputs):
        provider = Provider(outputs)
        router = GeminiReasoningRouter(cache_dir=Path(root)/"cache", ledger_path=Path(root)/"ledger.json",
            credentials=[("fixture", "fixture-key", "fixture-project")], provider_factory=lambda keys: provider)
        request = LLMRequest("fixture", "Group these canonical cues", _timeline_schema(), {}, "fixture", "story_timeline",
            acceptance_validator=_timeline_acceptance("prj_fixture", alignment(5), "fixture"), acceptance_max_rejections=2)
        return router, provider, request

    def test_conflicting_output_retries_with_exact_feedback_and_existing_fallback(self):
        bad = grouping(["cue_0001", "cue_0002"], ["cue_0002", "cue_0005"])
        good = grouping([s["segment_id"] for s in alignment(5)["segments"]])
        with tempfile.TemporaryDirectory() as root:
            router, provider, request = self.routed(root, [bad, good])
            self.assertEqual(RoutedGeminiProvider(router).generate_structured(request).value, good)
            self.assertEqual(len(provider.calls), 2)
            self.assertIn('"missing": ["cue_0003", "cue_0004"]', provider.calls[1].prompt)
            self.assertNotEqual(provider.calls[0].model, provider.calls[1].model)

    def test_legacy_poisoned_cache_rejected_each_continue_and_bound(self):
        bad = grouping(["cue_0001"], ["cue_0003", "cue_0004", "cue_0005"])
        with tempfile.TemporaryDirectory() as root:
            router, provider, request = self.routed(root, [bad])
            # Seed exactly the legacy schema-success cache, with no semantic validator.
            from dataclasses import replace
            RoutedGeminiProvider(router).generate_structured(replace(request, acceptance_validator=None))
            provider.calls.clear()
            for _ in range(2):
                with self.assertRaises(PlanningError): RoutedGeminiProvider(router).generate_structured(request)
            self.assertEqual(len(provider.calls), 4)
            cached = read_json(next((Path(root)/"cache").glob("*.json")))
            self.assertEqual(cached["semantic_acceptance"]["status"], "REJECTED")
            statuses = [x["status"] for x in read_json(Path(root)/"ledger.json")["requests"]]
            self.assertEqual(statuses.count("SUCCEEDED"), 1)  # Only the seeded legacy event.
            self.assertEqual(statuses.count("FAILED"), 2)

    def test_legacy_interior_gap_cache_repaired_without_provider_call(self):
        with tempfile.TemporaryDirectory() as root:
            router, provider, request = self.routed(root, [grouping(["cue_0001", "cue_0005"])])
            from dataclasses import replace
            RoutedGeminiProvider(router).generate_structured(replace(request, acceptance_validator=None))
            provider.calls.clear()
            result = RoutedGeminiProvider(router).generate_structured(request)
            self.accept(result.value)
            self.assertEqual(provider.calls, [])
            cached = read_json(next((Path(root)/"cache").glob("*.json")))
            self.assertEqual(cached["semantic_acceptance"]["status"], "REPAIRED")
            self.assertIn("original_value", cached)

    def test_failed_continue_survives_restart_then_recovers_without_source_or_flow(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = RuntimeLayout.from_root(root)
            paths = create_project(runtime, ProjectConfig("prj_recovery", render_mode="full_image",
                settings={"qc_policy": "MANUAL_REVIEW", "llm": {"provider": "gemini", "model": "fixture"}}),
                "## Narration\n\nSaved narration.")
            for name, value in (("alignment.json", alignment(5)), ("content_manifest.json", {"fixture": True})):
                atomic_write_json(paths.artifact_path("output/" + name), value)
            protected = [paths.content_file, paths.artifact_path("output/alignment.json"), paths.artifact_path("output/content_manifest.json")]
            before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in protected]
            bad = Provider([grouping(["cue_0001"], ["cue_0003", "cue_0004", "cue_0005"])])
            queries = ProductionQueries(runtime)
            operations = {"plan": lambda pid: run_planning_stages(root, pid, provider=bad),
                          "visuals": lambda pid: self.fail("No Flow or media allowed"),
                          "prepare": lambda pid: self.fail("No Source/Timing regeneration allowed")}
            coordinator = ProductionCoordinator(queries.production_query, operations, queries.record_run, queries.record_planning_failure)
            for _ in range(2):
                result = coordinator.run_until(paths.project_id)
                self.assertEqual(result["outcome"], "SAFETY_BLOCKED")
                state = ProductionQueries(runtime).production_query(paths.project_id)
                self.assertEqual(state["pipeline_status"], "SAFETY_BLOCKED")
                self.assertEqual(state["blocker"]["reason_code"], "STORY_TIMELINE_INVALID")
                self.assertEqual(state["next_action"]["label"], "Retry planning")
            self.assertEqual(len(bad.calls), 4)
            self.assertFalse(paths.artifact_path("output/story_timeline.json").exists())
            good = Provider([grouping([s["segment_id"] for s in alignment(5)["segments"]])])
            operations["plan"] = lambda pid: run_planning_stages(root, pid, provider=good)
            result = coordinator.run_until(paths.project_id)
            self.assertEqual(result["outcome"], "OWNER_DECISION_REQUIRED")
            self.assertEqual([call.stage for call in good.calls], ["story_timeline", "continuity"])
            self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in protected])
            self.assertNotIn("failure", ProductionQueries(runtime).production_query(paths.project_id)["run"])

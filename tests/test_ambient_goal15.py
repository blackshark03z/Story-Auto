from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_auto.application import OperatorService
from story_auto.core.artifacts import atomic_write_json, sha256_file
from story_auto.core.planning import (compile_ambient_shot_plan,
                                      compile_generation_requests,
                                      compile_media_plan,
                                      run_visual_planning_stages)
from story_auto.core.planning.service import PlanningError
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.visual import (
    AMBIENT_IMAGE_PROMPT_INTERNAL_TARGET,
    DEFAULT_VISUAL_POLICY,
    FLOW_IMAGE_PROMPT_HARD_LIMIT,
    AmbientVisualBriefBudgetError,
    ambient_prompt_directive,
    compile_ambient_image_prompt,
)
from tests.test_ambient_story import NoVisualProvider, planning_fixture


FIXTURE = Path(__file__).parent / "fixtures" / "scipio_trial_a_visual_regression.json"


def alternating_fixture(count: int) -> tuple[dict, dict]:
    patterns = (
        ("climax", "The hero achieves a decisive victory."),
        ("rising action", "Formal charges and an accusation place the hero under pressure."),
        ("falling action", "The hero withdrew from public life and died."),
        ("confrontation", "The hero confronts opposing authority in public."),
    )
    scenes = []
    for index in range(count):
        role, summary = patterns[index % len(patterns)]
        scenes.append({
            "scene_id":f"scn_{index + 1:04d}", "start":float(index * 10), "end":float((index + 1) * 10),
            "narration_segment_ids":[f"seg_{index + 1:04d}"], "story_role":role,
            "summary":summary, "entity_ids":["char_hero"],
        })
    timeline = {"schema_version":"story-auto-story-timeline/1.0.0","project_id":"prj_budget",
                "alignment_sha256":"a" * 64,"scenes":scenes,"review_status":"VALIDATED"}
    continuity = {"schema_version":"story-auto-continuity-bible/1.0.0","project_id":"prj_budget","style":{},
                  "characters":[{"entity_id":"char_hero","name":"The Hero","facts":{},"visual_design":{},"constraints":["stable identity"]}],
                  "locations":[],"props":[],"review_status":"VALIDATED"}
    return timeline, continuity


def compile_plan(style: str, count: int) -> dict:
    timeline, continuity = alternating_fixture(count)
    return compile_ambient_shot_plan("prj_budget",timeline,continuity,style,
                                     timeline_sha256="a" * 64,continuity_sha256="b" * 64)


class AmbientBudgetAndMergeContractTests(unittest.TestCase):
    def test_quiet_verdict_preferred_budget_is_soft_and_hard_max_is_enforced(self):
        soft = compile_plan("quiet_verdict", 6)
        self.assertEqual(soft["asset_budget"], {
            "preferred_min":2,"preferred_max":5,"hard_max":8,"planned_images":6,
            "budget_exception_reason":"SEMANTIC_STATE_INCOMPATIBILITY",
        })
        with self.assertRaisesRegex(PlanningError,"AMBIENT_CHAPTER_HARD_MAX_EXCEEDED"):
            compile_plan("quiet_verdict", 9)

    def test_hidden_mastery_preferred_budget_is_soft_and_hard_max_is_enforced(self):
        soft = compile_plan("hidden_mastery", 8)
        self.assertEqual(soft["asset_budget"], {
            "preferred_min":4,"preferred_max":7,"hard_max":10,"planned_images":8,
            "budget_exception_reason":"SEMANTIC_STATE_INCOMPATIBILITY",
        })
        with self.assertRaisesRegex(PlanningError,"AMBIENT_CHAPTER_HARD_MAX_EXCEEDED"):
            compile_plan("hidden_mastery", 11)

    def test_supportive_anchor_can_span_compatible_locations(self):
        timeline, continuity = alternating_fixture(2)
        timeline["scenes"][0].update({"story_role":"backstory","summary":"The hero begins a demanding ascent.","entity_ids":["char_hero","loc_north"]})
        timeline["scenes"][1].update({"story_role":"rising action","summary":"The hero continues the same demanding ascent.","entity_ids":["char_hero","loc_south"]})
        continuity["locations"] = [
            {"entity_id":"loc_north","name":"Northern port","facts":{},"visual_design":{},"constraints":[]},
            {"entity_id":"loc_south","name":"Southern port","facts":{},"visual_design":{},"constraints":[]},
        ]
        plan = compile_ambient_shot_plan("prj_supportive",timeline,continuity,"quiet_verdict",
                                         timeline_sha256="a" * 64,continuity_sha256="b" * 64)
        self.assertEqual(len(plan["shots"]),1)
        self.assertEqual(plan["shots"][0]["visual_anchor_kind"],"SUPPORTIVE")
        self.assertIn("does not claim to depict every narrated event",plan["shots"][0]["long_anchor_justification"])

    def test_action_accusation_and_retirement_do_not_merge(self):
        plan = compile_plan("quiet_verdict",3)
        self.assertEqual([shot["narrative_function"] for shot in plan["shots"]],
                         ["ACCOMPLISHMENT","ACCUSATION","RETIREMENT_DEATH"])


class AmbientPromptBudgetContractTests(unittest.TestCase):
    def _brief(self) -> dict:
        return {
            "visual_anchor":"A stable protagonist remains under quiet institutional scrutiny",
            "visual_anchor_kind":"SUPPORTIVE","dominant_subject":"The stable protagonist",
            "dominant_environment":"A restrained civic chamber","dominant_state":"Quiet scrutiny without literal event reenactment",
            "important_object_or_motif":"A sealed ledger with a unique optional motif phrase",
            "continuity_requirements":["Preserve the same face, age, and restrained dark wardrobe"],
            "composition_intent":"Clear subject hierarchy and negative space for subtitles",
            "optional_supporting_context":"OPTIONAL-CONTEXT " + "supporting detail " * 35,
        }

    def test_optional_detail_compacts_before_required_identity_style_and_safety(self):
        brief = self._brief()
        prompt = compile_ambient_image_prompt(brief,dict(DEFAULT_VISUAL_POLICY),
                                               style_directive=ambient_prompt_directive("quiet_verdict"))
        self.assertLessEqual(len(prompt),AMBIENT_IMAGE_PROMPT_INTERNAL_TARGET)
        self.assertIn(brief["dominant_subject"],prompt)
        self.assertIn("Ambient style",prompt)
        self.assertIn("bottom-right provider-mark safe area",prompt)
        self.assertNotIn("OPTIONAL-CONTEXT",prompt)

    def test_irreducible_required_brief_fails_without_raw_truncation(self):
        brief = self._brief()
        brief["dominant_subject"] = "required-identity " * 300
        with self.assertRaises(AmbientVisualBriefBudgetError) as caught:
            compile_ambient_image_prompt(brief,dict(DEFAULT_VISUAL_POLICY),
                                         style_directive=ambient_prompt_directive("quiet_verdict"))
        self.assertEqual(caught.exception.failure_class,"AMBIENT_VISUAL_BRIEF_OVER_BUDGET")
        self.assertIn("required-identity",brief["dominant_subject"])

    def test_long_narrative_summary_is_not_compiled_into_visual_prompt(self):
        timeline, continuity = alternating_fixture(1)
        marker = "EVENT-INVENTORY-MUST-NOT-ENTER-PROMPT"
        timeline["scenes"][0].update({"story_role":"thematic analysis","summary":f"{marker} " + "many narrated facts " * 150})
        plan = compile_ambient_shot_plan("prj_summary",timeline,continuity,"quiet_verdict",
                                         timeline_sha256="a" * 64,continuity_sha256="b" * 64)
        settings={"hook_seconds":55,"motion_spike_threshold":8,"overrides":{},"max_attempts":2,
                  "aspect_ratio":"16:9","large_batch_request_threshold":20,"provider_video_clip_seconds":8.0,
                  "ambient_style":"quiet_verdict"}
        media=compile_media_plan("prj_summary",plan,"ambient_story",settings)
        requests=compile_generation_requests("prj_summary",plan,media,continuity,settings,ambient_style="quiet_verdict")
        shot_request=next(item for item in requests["requests"] if item["purpose"]=="SHOT")
        self.assertIn(marker,plan["shots"][0]["narrative_summary"])
        self.assertNotIn(marker,shot_request["prompt"])
        self.assertLessEqual(len(shot_request["prompt"]),FLOW_IMAGE_PROMPT_HARD_LIMIT)


class AmbientFailureAndReviewStateTests(unittest.TestCase):
    def test_stale_ambient_visual_policy_rebuilds_descendants_only(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=RuntimeLayout.from_root(root)
            config=ProjectConfig("prj_invalidation",render_mode="ambient_story",settings={
                "ambient_style":"quiet_verdict","llm":{"provider":"gemini","model":"gemini-3.5-flash"},
                "media":{"max_attempts":2},
            })
            paths=create_project(runtime,config,"# Preserve\n\n## Narration\n\nApproved narration remains unchanged.\n")
            alignment,timeline,continuity=planning_fixture(config.project_id)
            for name,value in (("alignment",alignment),("story_timeline",timeline),("continuity_bible",continuity)):
                atomic_write_json(paths.artifact_path(f"output/{name}.json"),value)
            paths.artifact_path("output/voice.wav").write_bytes(b"stable kokoro fixture")
            atomic_write_json(paths.artifact_path("output/audio_manifest.json"),{"provider":"kokoro_local","duration_seconds":70.0})
            provider=NoVisualProvider()
            self.assertEqual(run_visual_planning_stages(runtime.root,config.project_id,provider=provider),("RUN","RUN","RUN"))
            upstream={name:sha256_file(paths.artifact_path(name)) for name in (
                "content.md","output/voice.wav","output/audio_manifest.json","output/alignment.json",
                "output/story_timeline.json","output/continuity_bible.json",
            )}
            for stage in ("shot_plan","media_plan","generation_requests"):
                checkpoint=paths.artifact_path(f"output/.checkpoints/{stage}.json")
                state=json.loads(checkpoint.read_text(encoding="utf-8"))
                state["fingerprint"]="stale-goal13-policy-fingerprint"
                state["producer_version"]="story-auto-ambient-policy/1.0.0"
                atomic_write_json(checkpoint,state)
            self.assertEqual(run_visual_planning_stages(runtime.root,config.project_id,provider=provider),("RUN","RUN","RUN"))
            self.assertEqual({name:sha256_file(paths.artifact_path(name)) for name in upstream},upstream)
            self.assertEqual(provider.calls,0)

    def test_prompt_budget_failure_is_pre_provider_and_surfaces_truthful_state(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=RuntimeLayout.from_root(root)
            config=ProjectConfig("prj_failure",render_mode="ambient_story",settings={
                "ambient_style":"quiet_verdict","llm":{"provider":"gemini","model":"gemini-3.5-flash"},
                "media":{"max_attempts":2},
            })
            paths=create_project(runtime,config,"# Failure\n\n## Narration\n\nApproved narration.\n")
            alignment,timeline,continuity=planning_fixture(config.project_id)
            for name,value in (("alignment",alignment),("story_timeline",timeline),("continuity_bible",continuity)):
                atomic_write_json(paths.artifact_path(f"output/{name}.json"),value)
            paths.artifact_path("output/voice.wav").write_bytes(b"preserved audio fixture")
            paths.artifact_path("output/final.mp4").write_bytes(b"stale downstream fixture")
            audio_hash=sha256_file(paths.artifact_path("output/voice.wav"))
            alignment_hash=sha256_file(paths.artifact_path("output/alignment.json"))
            provider=NoVisualProvider()
            with patch("story_auto.core.planning.service.compile_ambient_image_prompt",
                       side_effect=AmbientVisualBriefBudgetError("dominant_subject",1400,1100)):
                with self.assertRaisesRegex(PlanningError,"AMBIENT_VISUAL_BRIEF_OVER_BUDGET"):
                    run_visual_planning_stages(runtime.root,config.project_id,provider=provider)
            self.assertEqual(provider.calls,0)
            self.assertFalse(paths.artifact_path("output/generation_requests.json").exists())
            self.assertEqual(sha256_file(paths.artifact_path("output/voice.wav")),audio_hash)
            self.assertEqual(sha256_file(paths.artifact_path("output/alignment.json")),alignment_hash)
            app=OperatorService(root)
            snapshot=app.snapshot(config.project_id)
            review=app.review_overview(config.project_id)
            self.assertEqual(snapshot["blocked"][0],"VISUAL_PLANNING_REGENERATION_REQUIRED")
            self.assertEqual(snapshot["current_activity"],"Visual planning needs to be regenerated.")
            self.assertIsNone(snapshot["final_path"])
            self.assertEqual(next(item["status"] for item in review["quality"] if item["label"]=="Visual match"),"Not available yet")
            self.assertEqual(next(item["status"] for item in review["quality"] if item["label"]=="Final render"),"Waiting")
            self.assertEqual(review["issues"][0]["technical_code"],"AMBIENT_VISUAL_BRIEF_OVER_BUDGET")

    def test_visual_match_requires_selected_generated_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            app=OperatorService(root)
            created=app.create_project(project_id="prj_visual_evidence",content="# Evidence\n\n## Narration\n\nApproved narration.\n")
            paths,_=app._project(created["project_id"])
            status=lambda: next(item["status"] for item in app.review_overview(created["project_id"])["quality"] if item["label"]=="Visual match")
            self.assertEqual(status(),"Not checked")
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),{"requests":[
                {"request_id":"shot_1","purpose":"SHOT","shot_id":"sh_0001","media_type":"IMAGE","prompt":"bounded"}
            ]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"requests":[]})
            self.assertEqual(status(),"Pending")
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"requests":[
                {"request_id":"shot_1","status":"SUCCEEDED","selected_asset":{"path":"output/generated.png","sha256":"a" * 64}}
            ]})
            self.assertEqual(status(),"Passed")


class ScipioAmbientRegressionTests(unittest.TestCase):
    def test_real_trial_fixture_compiles_corrected_bounded_image_requests(self):
        fixture=json.loads(FIXTURE.read_text(encoding="utf-8"))
        evidence,timeline,continuity=fixture["evidence"],fixture["timeline"],fixture["continuity"]
        plan=compile_ambient_shot_plan(evidence["project_id"],timeline,continuity,"quiet_verdict",
                                       timeline_sha256="a" * 64,continuity_sha256="b" * 64)
        boundaries=[(shot["start"],shot["end"]) for shot in plan["shots"]]
        self.assertEqual(boundaries,[
            (0.0,19.65),(19.65,95.15),(95.15,130.0125),(130.0125,227.9),
            (227.9,278.9875),(278.9875,322.7),(322.7,414.1),(414.1,467.975),
        ])
        self.assertEqual(plan["asset_budget"]["budget_exception_reason"],"SEMANTIC_STATE_INCOMPATIBILITY")
        settings={"hook_seconds":55,"motion_spike_threshold":8,"overrides":{},"max_attempts":2,
                  "aspect_ratio":"16:9","large_batch_request_threshold":20,"provider_video_clip_seconds":8.0,
                  "ambient_style":"quiet_verdict"}
        media=compile_media_plan(evidence["project_id"],plan,"ambient_story",settings)
        requests=compile_generation_requests(evidence["project_id"],plan,media,continuity,settings,ambient_style="quiet_verdict")
        self.assertEqual(sum(item["purpose"]=="SHOT" for item in requests["requests"]),8)
        self.assertTrue(all(item["media_type"]=="IMAGE" for item in requests["requests"]))
        self.assertLessEqual(max(len(item["prompt"]) for item in requests["requests"]),FLOW_IMAGE_PROMPT_HARD_LIMIT)
        self.assertEqual(requests["guardrail_estimate"]["required_video_requests"],0)

        live=Path(__file__).parents[1] / "runtime" / "projects" / evidence["project_id"]
        if live.is_dir():
            self.assertEqual(sha256_file(live / "content.md"),evidence["content_sha256"])
            self.assertEqual(sha256_file(live / "output" / "voice.wav"),evidence["audio_sha256"])
            self.assertEqual(sha256_file(live / "output" / "alignment.json"),evidence["alignment_sha256"])
            alignment=json.loads((live / "output" / "alignment.json").read_text(encoding="utf-8"))
            self.assertEqual((alignment["duration_seconds"],len(alignment["segments"])),
                             (evidence["duration_seconds"],evidence["alignment_segments"]))

    def test_generic_planner_contains_no_trial_specific_rules(self):
        source=(Path(__file__).parents[1] / "story_auto" / "core" / "planning" / "ambient.py").read_text(encoding="utf-8").lower()
        for story_term in ("scipio","zama","spain","warlords"):
            self.assertNotIn(story_term,source)


if __name__ == "__main__":
    unittest.main()

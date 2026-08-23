from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from story_auto.core.artifacts import read_json
from story_auto.core.gemini_qc import (MOTION_PLAN_VERSION, MOTION_SCHEMA,
                                       GeminiQCError, plan_motion,
                                       validate_motion_plan)
from story_auto.providers.llm.gemini import LLMResponse
from story_auto.providers.llm.router import HARD_MODELS, GeminiReasoningRouter


INTENT = {
    "action": "reaches for the door and opens it",
    "subject": "A fictional caretaker",
    "location": "a quiet corridor",
}


def motion_plan(*, valid: bool) -> dict:
    clips = [{
        "start_state": "hand lowered",
        "action": "reaches for the door and opens it" if not valid else "hand reaches the door handle",
        "end_state": "hand rests on handle",
        "natural_stillness": "brief contact pause",
    }]
    if valid:
        clips.append({
            "start_state": "hand rests on handle",
            "action": "door opens once",
            "end_state": "door remains open",
            "natural_stillness": "settles without looping",
            "direction_sensitive": True,
            "ordered_action_steps": ["hand contacts handle", "door opens"],
            "progression_checkpoints": ["door closed", "door open"],
            "movement_direction": "door closed -> open",
            "forbidden_motion": ["door closes", "object moves before contact", "reverse progression"],
        })
        clips[0].update({
            "direction_sensitive": True,
            "ordered_action_steps": ["hand approaches handle", "hand contacts handle"],
            "progression_checkpoints": ["hand lowered", "hand at handle"],
            "movement_direction": "hand toward handle",
            "forbidden_motion": ["hand moves away", "object moves before contact", "reverse progression"],
        })
    return {
        "start_state": clips[0]["start_state"],
        "end_state": clips[-1]["end_state"],
        "meaningful_actions": ["reaches for the door", "opens the door"],
        "interaction_objects": ["door"],
        "hand_object_contact": "hand contacts handle before movement",
        "action_dependencies": ["contact before opening"],
        "physical_complexity": "HIGH",
        "anatomy_risk": "MEDIUM",
        "looping_risk": "LOW",
        "atomic_clips": clips,
    }


class SequencedProvider:
    def __init__(self, values: list[dict], calls: list[str]) -> None:
        self.values = values
        self.calls = calls

    def generate_structured(self, request):
        self.calls.append(request.model)
        value = self.values.pop(0) if len(self.values) > 1 else self.values[0]
        return LLMResponse(value, request.model, request.request_id, 1, 1, {})


def make_router(directory: str, values: list[dict]):
    calls: list[str] = []
    router = GeminiReasoningRouter(
        cache_dir=Path(directory) / "cache",
        ledger_path=Path(directory) / "ledger.json",
        credentials=[("secret-fixture", "key-fixture", "project-fixture")],
        provider_factory=lambda _keys: SequencedProvider(values, calls),
    )
    return router, calls


def motion_prompt() -> str:
    return ("Decompose this production VIDEO intent into physically plausible cinematic states. "
            "Default to one meaningful action per generated clip. Split high-risk contact mechanics "
            "with cuts. Natural stillness is valid. Return JSON only. Intent:\n" +
            json.dumps(INTENT, ensure_ascii=False, sort_keys=True))


def test_accepted_motion_result_caches_and_reuses_without_provider_call():
    with tempfile.TemporaryDirectory() as directory:
        router, calls = make_router(directory, [motion_plan(valid=True)])
        first_value, first = plan_motion(router, INTENT)
        second_value, second = plan_motion(router, INTENT)

        assert first_value == second_value
        assert not first.cache_hit and first.request_count == 1
        assert second.cache_hit and second.request_count == 0
        assert len(calls) == 1


def test_domain_rejected_provider_result_is_not_cached_and_next_bounded_attempt_wins():
    with tempfile.TemporaryDirectory() as directory:
        invalid, valid = motion_plan(valid=False), motion_plan(valid=True)
        router, calls = make_router(directory, [invalid, valid])

        value, result = plan_motion(router, INTENT)
        cached_value, cached = plan_motion(router, INTENT)

        assert value == valid == cached_value
        assert result.request_count == 2 and result.fallback_count == 1
        assert cached.cache_hit and cached.request_count == 0
        assert calls == list(HARD_MODELS[:2])
        cache_files = list((Path(directory) / "cache").glob("*.json"))
        assert len(cache_files) == 1
        assert read_json(cache_files[0])["value"] == valid
        ledger = read_json(Path(directory) / "ledger.json")
        assert [(item["status"], item.get("failure_class")) for item in ledger["requests"]] == [
            ("REJECTED", "HIGH_RISK_ACTION_NOT_DECOMPOSED"), ("SUCCEEDED", None),
        ]


def test_trial_b_style_legacy_poison_is_bypassed_without_manual_cache_delete():
    with tempfile.TemporaryDirectory() as directory:
        invalid, valid = motion_plan(valid=False), motion_plan(valid=True)
        router, calls = make_router(directory, [invalid, valid])

        poisoned = router.reason(
            task="motion_planning", prompt=motion_prompt(), schema=MOTION_SCHEMA, tier="HARD",
            prompt_version="motion-planner/1.0.0", schema_version="story-auto-motion-plan/1.0.0",
        )
        with pytest.raises(GeminiQCError, match="HIGH_RISK_ACTION_NOT_DECOMPOSED"):
            validate_motion_plan(poisoned.value, original_action=INTENT["action"])
        cache_path = Path(directory) / "cache" / f"{poisoned.input_hash}.json"
        assert cache_path.is_file() and read_json(cache_path)["value"] == invalid

        recomputed_value, recomputed = plan_motion(router, INTENT)
        reused_value, reused = plan_motion(router, INTENT)

        assert recomputed_value == valid == reused_value
        assert not recomputed.cache_hit and recomputed.request_count == 1
        assert reused.cache_hit and reused.request_count == 0
        assert len(calls) == 2
        assert cache_path.is_file() and read_json(cache_path)["value"] == invalid
        assert len(list((Path(directory) / "cache").glob("*.json"))) == 2
        ledger = read_json(Path(directory) / "ledger.json")
        assert not any(item["status"] == "REJECTED" and item.get("source") == "CACHE"
                       for item in ledger["requests"])


def test_all_domain_rejections_keep_existing_hard_router_bound_and_canonical_failure():
    with tempfile.TemporaryDirectory() as directory:
        router, calls = make_router(directory, [motion_plan(valid=False)])

        with pytest.raises(GeminiQCError, match="HIGH_RISK_ACTION_NOT_DECOMPOSED"):
            plan_motion(router, INTENT)

        assert calls == list(HARD_MODELS)
        assert not (Path(directory) / "cache").exists()
        assert all(item["status"] != "SUCCEEDED"
                   for item in read_json(Path(directory) / "ledger.json")["requests"])

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from story_auto.core.gemini_qc import (GeminiQCError, combine_temporal_qc, compile_flow_motion_prompt,
    is_high_risk, sample_dense_frames, validate_hook_plan, validate_motion_plan, validate_usable_window)


def beat(start, end, info, action, risk="LOW"):
    return {"start": start, "end": end, "new_information": info, "active_subject": "Julian",
            "action": action, "location": "academy", "important_props": [], "visual_function": info,
            "emotional_function": "tension", "similarity_to_previous": 0.1, "repetition_risk": risk}


def temporal(state, defects=None, start=0, end=8):
    return {"state": state, "confidence": "HIGH", "dimensions": {}, "defects": defects or [],
            "usable_start": start, "usable_end": end}


def test_hook_semantic_repetition_detects_same_information_despite_camera_change():
    plan = {"beats": [beat(0, 4, "Julian hears piano", "listens in corridor"),
                      beat(4, 8, "Julian hears piano", "listens in corridor profile")]}
    with pytest.raises(GeminiQCError, match="HOOK_SEMANTIC_REPETITION"):
        validate_hook_plan(plan, start=0, end=8, max_similarity=.5)


def test_distinct_hook_information_passes():
    plan = {"beats": [beat(0, 4, "empty academy interrupted by eight notes", "Julian freezes"),
                      beat(4, 8, "locked grand scheduled for disposal", "red notice rests on piano")]}
    validate_hook_plan(plan, start=0, end=8)


def test_high_risk_motion_requires_atomic_decomposition():
    assert is_high_risk("walks to the door and opens the handle")
    plan = {"meaningful_actions": ["walk", "reach", "open"], "atomic_clips": [{"start_state":"far", "action":"walk", "end_state":"near", "natural_stillness":"pause"}]}
    with pytest.raises(GeminiQCError, match="HIGH_RISK_ACTION_NOT_DECOMPOSED"):
        validate_motion_plan(plan, original_action="walks to door and opens it")


def test_flow_prompt_is_deterministic_bounded_and_contact_safe():
    clip = {"start_state":"hand away from handle", "action":"hand approaches and rests on handle",
            "end_state":"hand resting on handle; door closed", "natural_stillness":"one breath"}
    prompt = compile_flow_motion_prompt(subject="fictional conductor", location="academy corridor", clip=clip, duration=4)
    assert "One visible action only" in prompt and "before they move" in prompt and "no reset" in prompt


def test_usable_window_validation():
    validate_usable_window(0, 3.5, duration=8, target_duration=3)
    with pytest.raises(GeminiQCError, match="USABLE_TEMPORAL_WINDOW_INVALID"):
        validate_usable_window(3.5, 8, duration=8, target_duration=5)


def test_deterministic_temporal_gate_overrides_gemini_pass_on_severe_defect():
    severe = [{"class":"LIMB_INTEGRITY", "severity":"SEVERE", "start":1, "end":2, "evidence":"detached hand"}]
    with pytest.raises(GeminiQCError, match="TEMPORAL_HARD_GATE_CONTRADICTION"):
        combine_temporal_qc(temporal("PASS_TEMPORAL", severe), temporal("PASS_TEMPORAL"), duration=8, target_duration=8)


@pytest.mark.parametrize("state", ["REJECT_ACTION_LOGIC", "REJECT_ANATOMY", "REJECT_LOOP", "REJECT_IDENTITY", "REJECT_BACKGROUND"])
def test_temporal_rejection_states_are_ineligible(state):
    result = combine_temporal_qc(temporal(state), temporal("PASS_TEMPORAL"), duration=8, target_duration=8)
    assert result["state"] == state and not result["eligible"]


def test_valid_usable_window_is_selected_deterministically():
    result = combine_temporal_qc(temporal("PASS_WITH_USABLE_WINDOW", start=0, end=4),
                                 temporal("PASS_TEMPORAL", start=0, end=8), duration=8, target_duration=3.5)
    assert result["eligible"] and result["usable_end"] == 4


def test_dense_frame_sampling_is_bounded(ffmpeg_test_video):
    with tempfile.TemporaryDirectory() as tmp:
        frames = sample_dense_frames(ffmpeg_test_video, Path(tmp), risk="HIGH", duration=1, max_frames=5)
        assert 1 <= len(frames) <= 5 and all(Path(x["path"]).is_file() for x in frames)


@pytest.fixture
def ffmpeg_test_video(tmp_path):
    import subprocess
    path = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=navy:s=320x180:r=10:d=1",
                    "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)
    return path

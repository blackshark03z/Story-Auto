from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from story_auto.providers.llm.router import ReasoningResult

from story_auto.core.gemini_qc import (GeminiQCError, combine_temporal_qc, compile_flow_motion_prompt,
    classify_motion_action, is_direction_sensitive, is_high_risk, sample_dense_frames, temporal_video_qc,
    validate_hook_plan, validate_motion_plan, validate_usable_window)


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
            "end_state":"hand resting on handle; door closed", "natural_stillness":"one breath",
            "direction_sensitive":True, "action_family":"CONTACT", "ordered_action_steps":["APPROACH", "CONTACT"],
            "progression_checkpoints":["AWAY", "CONTACT"], "movement_direction":"CONTACT_THEN_OBJECT_MOTION",
            "forbidden_motion":["OBJECT_BEFORE_CONTACT", "REVERSE_DIRECTION"]}
    prompt = compile_flow_motion_prompt(subject="fictional conductor", location="academy corridor", clip=clip, duration=4)
    assert "One visible action only" in prompt and "before they move" in prompt and "Required ordered action sequence" in prompt and "no reset" in prompt


def directional_clip(action="ascends the staircase"):
    return {"start_state":"lower stair position, body oriented upward", "action":action,
            "end_state":"upper landing, higher position", "natural_stillness":"settles at the landing",
            "direction_sensitive":True, "action_family":"ASCENT",
            "ordered_action_steps":["LOWER", "MIDDLE", "UPPER"],
            "progression_checkpoints":["LOWER", "MIDDLE", "UPPER"], "movement_direction":"ASCENDING",
            "forbidden_motion":["BACKWARD_MOTION", "DESCENDING", "REVERSE_DIRECTION"]}


def descent_clip():
    return {"start_state":"upper landing", "action":"descends the staircase", "end_state":"lower stair position",
            "natural_stillness":"settles at the bottom", "direction_sensitive":True, "action_family":"DESCENT",
            "ordered_action_steps":["UPPER", "MIDDLE", "LOWER"], "progression_checkpoints":["UPPER", "MIDDLE", "LOWER"],
            "movement_direction":"DESCENDING", "forbidden_motion":["BACKWARD_MOTION", "ASCENDING", "REVERSE_DIRECTION"]}


def test_stair_ascent_contract_rejects_reverse_trajectory_and_accepts_forward_progression():
    valid = directional_clip()
    validate_motion_plan({"meaningful_actions":["ascend stairs"], "atomic_clips":[valid]}, original_action=valid["action"])
    reversed_clip = directional_clip()
    reversed_clip["movement_direction"] = "DESCENDING"
    with pytest.raises(GeminiQCError, match="MOTION_DIRECTIONAL_TRAJECTORY_INVALID"):
        validate_motion_plan({"meaningful_actions":["ascend stairs"], "atomic_clips":[reversed_clip]}, original_action=reversed_clip["action"])
    descent = descent_clip()
    validate_motion_plan({"meaningful_actions":["descend stairs"], "atomic_clips":[descent]}, original_action=descent["action"])
    descent["movement_direction"] = "ASCENDING"
    with pytest.raises(GeminiQCError, match="MOTION_DIRECTIONAL_TRAJECTORY_INVALID"):
        validate_motion_plan({"meaningful_actions":["descend stairs"], "atomic_clips":[descent]}, original_action=descent["action"])


def test_pickup_and_sit_contracts_reject_reversed_causal_order():
    pickup = {"start_state":"hand away from cup", "action":"picks up the cup", "end_state":"cup lifted",
              "natural_stillness":"holds still", "direction_sensitive":True, "action_family":"PICK_UP",
              "ordered_action_steps":["APPROACH", "CONTACT", "LIFT"],
              "progression_checkpoints":["HAND_AWAY", "CONTACT", "CUP_RAISED"], "movement_direction":"UP_AFTER_CONTACT",
              "forbidden_motion":["OBJECT_BEFORE_CONTACT", "REVERSE_ORDER"]}
    validate_motion_plan({"meaningful_actions":["pick up cup"], "atomic_clips":[pickup]}, original_action=pickup["action"])
    pickup["ordered_action_steps"] = ["LIFT", "APPROACH", "CONTACT"]
    with pytest.raises(GeminiQCError, match="MOTION_ORDERED_ACTION_STEPS_INVALID"):
        validate_motion_plan({"meaningful_actions":["pick up cup"], "atomic_clips":[pickup]}, original_action=pickup["action"])
    sit = {"start_state":"standing", "action":"sits down in chair", "end_state":"seated", "natural_stillness":"settles",
           "direction_sensitive":True, "action_family":"SIT", "ordered_action_steps":["STANDING", "LOWERING", "SEATED"],
           "progression_checkpoints":["STANDING", "LOWERING", "SEATED"], "movement_direction":"SIT_DOWN",
           "forbidden_motion":["REVERSE_ORDER"]}
    validate_motion_plan({"meaningful_actions":["sit"], "atomic_clips":[sit]}, original_action=sit["action"])
    sit["ordered_action_steps"] = ["SEATED", "LOWERING", "STANDING"]
    with pytest.raises(GeminiQCError, match="MOTION_ORDERED_ACTION_STEPS_INVALID"):
        validate_motion_plan({"meaningful_actions":["sit"], "atomic_clips":[sit]}, original_action=sit["action"])


def test_non_directional_still_motion_remains_unconstrained():
    clip = {"start_state":"still", "action":"observes the quiet corridor", "end_state":"still", "natural_stillness":"one breath"}
    validate_motion_plan({"meaningful_actions":["observe"], "atomic_clips":[clip]}, original_action=clip["action"])
    assert "Required ordered action sequence" not in compile_flow_motion_prompt(subject="caretaker", location="corridor", clip=clip, duration=4)


@pytest.mark.parametrize("action", ["walks down the corridor", "moves up the road", "sitting quietly by the fireplace",
                                    "standing near the window", "door remains open", "window is closed",
                                    "passes through the doorway", "gives a nervous glance", "leaves the letter on the table",
                                    "reaches the landing", "climbs into the car", "understands the warning",
                                    "the situation remains tense", "stands still on the stairs", "carries a ladder across the yard",
                                    "rests a hand at the side"])
def test_phrase_aware_classifier_rejects_lexical_false_positives(action):
    clip = {"start_state":"still", "action":action, "end_state":"still", "natural_stillness":"one breath"}
    assert classify_motion_action(action) == "NONE"
    assert not is_direction_sensitive(action)
    validate_motion_plan({"meaningful_actions":[action], "atomic_clips":[clip]}, original_action=action)
    assert "Required ordered action sequence" not in compile_flow_motion_prompt(subject="caretaker", location="yard", clip=clip, duration=4)


def test_canonical_action_families_cover_toward_pickup_sit_and_stand():
    assert classify_motion_action("hands the envelope to the guard") == "HANDOFF"
    toward = {"start_state":"at the gate", "action":"walks toward the door", "end_state":"at the door", "natural_stillness":"pauses",
              "direction_sensitive":True, "action_family":"TOWARD", "ordered_action_steps":["ORIGIN", "TARGET"], "progression_checkpoints":["ORIGIN", "TARGET"],
              "movement_direction":"TOWARD_TARGET", "forbidden_motion":["REVERSE_DIRECTION"]}
    validate_motion_plan({"meaningful_actions":["walk toward door"], "atomic_clips":[toward]}, original_action=toward["action"])
    stand = {"start_state":"seated", "action":"stands up from the chair", "end_state":"standing", "natural_stillness":"balances",
             "direction_sensitive":True, "action_family":"STAND", "ordered_action_steps":["SEATED", "RISING", "STANDING"],
             "progression_checkpoints":["SEATED", "RISING", "STANDING"], "movement_direction":"STAND_UP",
             "forbidden_motion":["REVERSE_ORDER"]}
    validate_motion_plan({"meaningful_actions":["stand"], "atomic_clips":[stand]}, original_action=stand["action"])
    stand["ordered_action_steps"] = ["STANDING", "RISING", "SEATED"]
    with pytest.raises(GeminiQCError, match="MOTION_ORDERED_ACTION_STEPS_INVALID"):
        validate_motion_plan({"meaningful_actions":["stand"], "atomic_clips":[stand]}, original_action=stand["action"])


def test_structured_action_family_covers_remaining_canonical_actions():
    def clip(action, family, direction, steps, checkpoints, forbidden):
        return {"start_state":"start", "action":action, "end_state":"end", "natural_stillness":"settles",
                "direction_sensitive":True, "action_family":family, "movement_direction":direction,
                "ordered_action_steps":steps, "progression_checkpoints":checkpoints, "forbidden_motion":forbidden}
    cases = [
        clip("walks away from the gate", "AWAY", "AWAY_FROM_TARGET", ["ORIGIN", "AWAY"], ["ORIGIN", "AWAY"], ["REVERSE_DIRECTION"]),
        clip("walks from the gate to the car", "FROM_TO", "FROM_TO_DESTINATION", ["ORIGIN", "DESTINATION"], ["ORIGIN", "DESTINATION"], ["REVERSE_DIRECTION"]),
        clip("puts down the cup", "PUT_DOWN", "DOWN_AFTER_CONTACT", ["CONTACT", "LOWER", "RELEASE"], ["HELD", "SURFACE"], ["OBJECT_BEFORE_CONTACT", "REVERSE_ORDER"]),
        clip("opens the door", "OPEN", "OPENING", ["CONTACT", "OPEN"], ["CLOSED", "OPEN"], ["REVERSE_DIRECTION"]),
        clip("closes the window", "CLOSE", "CLOSING", ["CONTACT", "CLOSE"], ["OPEN", "CLOSED"], ["REVERSE_DIRECTION"]),
        clip("hands the envelope to the guard", "HANDOFF", "TRANSFER_TO_RECIPIENT", ["CONTACT", "TRANSFER"], ["HELD", "RECIPIENT"], ["REVERSE_DIRECTION"]),
        clip("reaches for the handle", "CONTACT", "CONTACT_THEN_OBJECT_MOTION", ["APPROACH", "CONTACT"], ["AWAY", "CONTACT"], ["REVERSE_DIRECTION"]),
        clip("enters the room", "ENTER", "ENTERING", ["OUTSIDE", "INSIDE"], ["OUTSIDE", "INSIDE"], ["REVERSE_DIRECTION"]),
        clip("exits the room", "EXIT", "EXITING", ["INSIDE", "OUTSIDE"], ["INSIDE", "OUTSIDE"], ["REVERSE_DIRECTION"]),
    ]
    for item in cases:
        validate_motion_plan({"meaningful_actions":[item["action"]], "atomic_clips":[item]}, original_action=item["action"])
    turn = clip("turns", "TURN_MOVE", "TURN_THEN_FORWARD", ["TURN", "MOVE"], ["FACING_OLD", "FACING_NEW"], ["REVERSE_DIRECTION"])
    move = clip("moves forward", "TURN_MOVE", "TURN_THEN_FORWARD", ["TURN", "MOVE"], ["FACING_OLD", "FACING_NEW"], ["REVERSE_DIRECTION"])
    validate_motion_plan({"meaningful_actions":["turn", "move"], "atomic_clips":[turn, move]}, original_action="turns then moves forward")


@pytest.mark.parametrize(("action", "family", "direction"), [
    ("enters the room", "ENTER", "ENTERING"), ("exits the room", "EXIT", "EXITING"),
    ("walks toward the gate", "TOWARD", "TOWARD_TARGET"), ("walks away from the gate", "AWAY", "AWAY_FROM_TARGET"),
    ("walks from the gate to the car", "FROM_TO", "FROM_TO_DESTINATION"), ("turns", "TURN_MOVE", "TURN_THEN_FORWARD"),
])
def test_arbitrary_steps_and_checkpoints_reject_for_every_review_probe(action, family, direction):
    invalid = {"start_state":"start", "action":action, "end_state":"end", "natural_stillness":"settles",
               "direction_sensitive":True, "action_family":family, "movement_direction":direction,
               "ordered_action_steps":["BANANA", "MOON"], "progression_checkpoints":["X", "Y"],
               "forbidden_motion":["REVERSE_DIRECTION"]}
    with pytest.raises(GeminiQCError, match="MOTION_ORDERED_ACTION_STEPS_INVALID"):
        validate_motion_plan({"meaningful_actions":[action], "atomic_clips":[invalid]}, original_action=action)


@pytest.mark.parametrize(("action", "family", "direction", "steps", "forbidden"), [
    ("opens the door", "OPEN", "OPENING", ["CONTACT", "OPEN"], ["REVERSE_DIRECTION"]),
    ("hands the envelope to the guard", "HANDOFF", "TRANSFER_TO_RECIPIENT", ["CONTACT", "TRANSFER"], ["REVERSE_DIRECTION"]),
])
def test_valid_steps_with_arbitrary_checkpoints_reject(action, family, direction, steps, forbidden):
    invalid = {"start_state":"start", "action":action, "end_state":"end", "natural_stillness":"settles",
               "direction_sensitive":True, "action_family":family, "movement_direction":direction,
               "ordered_action_steps":steps, "progression_checkpoints":["X", "Y"], "forbidden_motion":forbidden}
    with pytest.raises(GeminiQCError, match="MOTION_DIRECTIONAL_PROGRESSION_INVALID"):
        validate_motion_plan({"meaningful_actions":[action], "atomic_clips":[invalid]}, original_action=action)


def test_structured_family_can_pass_when_text_inference_is_none_but_contradiction_fails_closed():
    implicit_ascent = {"start_state":"lower", "action":"follows the documented route", "end_state":"upper",
                       "natural_stillness":"settles", "direction_sensitive":True, "action_family":"ASCENT",
                       "ordered_action_steps":["LOWER", "MIDDLE", "UPPER"], "progression_checkpoints":["LOWER", "MIDDLE", "UPPER"],
                       "movement_direction":"ASCENDING", "forbidden_motion":["BACKWARD_MOTION", "DESCENDING", "REVERSE_DIRECTION"]}
    assert classify_motion_action(implicit_ascent["action"]) == "NONE"
    validate_motion_plan({"meaningful_actions":["route"], "atomic_clips":[implicit_ascent]}, original_action=implicit_ascent["action"])
    contradictory = dict(implicit_ascent, action="ascends the staircase", action_family="DESCENT",
                         ordered_action_steps=["UPPER", "MIDDLE", "LOWER"], progression_checkpoints=["UPPER", "MIDDLE", "LOWER"],
                         movement_direction="DESCENDING", forbidden_motion=["BACKWARD_MOTION", "ASCENDING", "REVERSE_DIRECTION"])
    with pytest.raises(GeminiQCError, match="MOTION_ACTION_FAMILY_CONTRADICTION"):
        validate_motion_plan({"meaningful_actions":["ascend"], "atomic_clips":[contradictory]}, original_action=contradictory["action"])


def test_complex_directional_action_requires_atomic_decomposition():
    clip = directional_clip("turns then ascends the staircase")
    with pytest.raises(GeminiQCError, match="HIGH_RISK_ACTION_NOT_DECOMPOSED"):
        validate_motion_plan({"meaningful_actions":["turn", "ascend"], "atomic_clips":[clip]}, original_action=clip["action"])


def test_usable_window_validation():
    validate_usable_window(0, 3.5, duration=8, target_duration=3)
    with pytest.raises(GeminiQCError, match="USABLE_TEMPORAL_WINDOW_INVALID"):
        validate_usable_window(3.5, 8, duration=8, target_duration=5)


def test_deterministic_temporal_gate_overrides_gemini_pass_on_severe_defect():
    severe = [{"class":"LIMB_INTEGRITY", "severity":"SEVERE", "start":1, "end":2, "evidence":"detached hand"}]
    with pytest.raises(GeminiQCError, match="TEMPORAL_HARD_GATE_CONTRADICTION"):
        combine_temporal_qc(temporal("PASS_TEMPORAL", severe), temporal("PASS_TEMPORAL"), duration=8, target_duration=8)


def test_temporal_qc_maps_directional_or_contact_progression_failures_to_action_logic_rejection():
    contract = directional_clip()
    reverse = temporal("PASS_TEMPORAL")
    reverse["dimensions"] = {"MOVEMENT_DIRECTION":"SEVERE", "CHECKPOINT_PROGRESSION":"MAJOR"}
    result = combine_temporal_qc(reverse, temporal("PASS_TEMPORAL"), duration=8, target_duration=8, motion_contract=contract)
    assert result["state"] == "REJECT_ACTION_LOGIC" and not result["eligible"]
    contact = temporal("PASS_TEMPORAL")
    contact["dimensions"] = {"CAUSAL_CONTACT_ORDER":"MAJOR"}
    result = combine_temporal_qc(temporal("PASS_TEMPORAL"), contact, duration=8, target_duration=8, motion_contract=contract)
    assert result["state"] == "REJECT_ACTION_LOGIC" and not result["eligible"]


@pytest.mark.parametrize("state", ["REJECT_ACTION_LOGIC", "REJECT_ANATOMY", "REJECT_LOOP", "REJECT_IDENTITY", "REJECT_BACKGROUND"])
def test_temporal_rejection_states_are_ineligible(state):
    result = combine_temporal_qc(temporal(state), temporal("PASS_TEMPORAL"), duration=8, target_duration=8)
    assert result["state"] == state and not result["eligible"]


def test_valid_usable_window_is_selected_deterministically():
    result = combine_temporal_qc(temporal("PASS_WITH_USABLE_WINDOW", start=0, end=4),
                                 temporal("PASS_TEMPORAL", start=0, end=8), duration=8, target_duration=3.5)
    assert result["eligible"] and result["usable_end"] == 4


def test_short_usable_window_becomes_terminal_temporal_rejection_without_weakening_validation():
    result = combine_temporal_qc(
        temporal("PASS_TEMPORAL", start=0, end=8),
        temporal("PASS_WITH_USABLE_WINDOW", start=0, end=2.5),
        duration=8,
        target_duration=2.970833,
    )
    assert result["state"] == "USABLE_TEMPORAL_WINDOW_INVALID"
    assert not result["eligible"]
    with pytest.raises(GeminiQCError, match="USABLE_TEMPORAL_WINDOW_INVALID"):
        validate_usable_window(0, 2.5, duration=8, target_duration=2.970833)


def test_temporal_false_positive_review_epoch_changes_both_qc_cache_identities(tmp_path):
    class Router:
        def __init__(self): self.calls=[]
        def reason(self, **kwargs):
            self.calls.append(kwargs)
            return ReasoningResult(temporal("PASS_TEMPORAL"),"fixture","key","project",False,0,1,
                                   f"hash-{len(self.calls)}")
    video=tmp_path / "video.mp4"; video.write_bytes(b"video")
    frame=tmp_path / "frame.jpg"; frame.write_bytes(b"frame")
    frames=[{"index":1,"timestamp":.5,"path":str(frame),"sha256":"x"*64}]
    router=Router()
    temporal_video_qc(router,video=video,intent={"shot_id":"sh_0007"},frames=frames,duration=8,target_duration=3,
                      review_epoch="epoch-a")
    temporal_video_qc(router,video=video,intent={"shot_id":"sh_0007"},frames=frames,duration=8,target_duration=3,
                      review_epoch="epoch-b")
    assert len(router.calls)==4
    assert router.calls[0]["prompt"] != router.calls[2]["prompt"]
    assert router.calls[0]["prompt_version"] != router.calls[2]["prompt_version"]


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

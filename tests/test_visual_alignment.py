from story_auto.core.visual_alignment import classify_semantic_alignment


def test_mandatory_entity_contradiction_is_mismatch():
    expected = {"characters": ["daniel"], "mandatory_characters": ["daniel"], "props": ["piano"]}
    observed = {"characters": ["unrelated violinist"], "props": ["violin"]}
    assert classify_semantic_alignment(expected, observed) == "MISMATCH"


def test_explicit_atmospheric_review_can_pass():
    assert classify_semantic_alignment({"atmospheric": True}, {"classification": "PASS_ATMOSPHERIC"}) == "PASS_ATMOSPHERIC"


def test_unplanned_atmospheric_label_is_mismatch():
    assert classify_semantic_alignment({"atmospheric": False}, {"classification": "PASS_ATMOSPHERIC"}) == "MISMATCH"


def test_narration_action_contradiction_is_mismatch_even_with_claimed_pass():
    expected = {"characters": ["daniel"], "action": "repairs piano mechanism"}
    observed = {"classification": "PASS_DIRECT", "characters": ["daniel"],
                "action": "plays violin", "action_compatible": False}
    assert classify_semantic_alignment(expected, observed) == "MISMATCH"


def test_location_or_critical_prop_contradiction_is_mismatch():
    expected = {"location": "recital hall", "props": ["rubbish bag"]}
    assert classify_semantic_alignment(expected, {"location_compatible": False}) == "MISMATCH"
    assert classify_semantic_alignment(expected, {"critical_props_present": False}) == "MISMATCH"

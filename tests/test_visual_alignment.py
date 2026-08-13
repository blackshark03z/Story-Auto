from story_auto.core.visual_alignment import classify_semantic_alignment


def test_mandatory_entity_contradiction_is_mismatch():
    expected = {"characters": ["daniel"], "props": ["piano"]}
    observed = {"characters": ["unrelated violinist"], "props": ["violin"]}
    assert classify_semantic_alignment(expected, observed) == "MISMATCH"


def test_explicit_atmospheric_review_can_pass():
    assert classify_semantic_alignment({}, {"classification": "PASS_ATMOSPHERIC"}) == "PASS_ATMOSPHERIC"

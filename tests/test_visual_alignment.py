from story_auto.core.visual_alignment import build_shot_mapping_audit, classify_semantic_alignment


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


def _audit_for_hashes(hashes):
    shots = [{"shot_id": f"sh_{index:04d}", "start": float(index - 1), "end": float(index),
              "narration_segment_ids": [f"seg_{index}"]} for index in range(1, len(hashes) + 1)]
    requests = [{"request_id": f"req_{index}", "purpose": "SHOT", "shot_id": shot["shot_id"],
                 "prompt": "story-specific intent"} for index, shot in enumerate(shots, 1)]
    manifest = [{"request_id": request["request_id"], "selected_asset": {
        "path": f"assets/{request['request_id']}.png", "sha256": asset_hash, "attempt": 1,
        "alignment_classification": "PASS_DIRECT"}} for request, asset_hash in zip(requests, hashes)]
    segments = [{"segment_id": shot["shot_id"], "shot_id": shot["shot_id"], "target_start": shot["start"],
                 "target_end": shot["end"], "source_asset": manifest[index]["selected_asset"]["path"],
                 "source_hash": hashes[index], "source_media_type": "IMAGE",
                 "provenance": {"request_id": requests[index]["request_id"]}}
                for index, shot in enumerate(shots)]
    return build_shot_mapping_audit(
        alignment={"segments": [{"segment_id": f"seg_{index}", "text": "Narration"}
                                  for index in range(1, len(hashes) + 1)]},
        shot_plan={"shots": shots}, media_plan={"shots": []}, generation_requests={"requests": requests},
        generation_manifest={"requests": manifest}, render_plan={"segments": segments})


def test_clean_complete_alignment_audit_passes_without_owner_review():
    audit = _audit_for_hashes(["a" * 64])
    assert audit["acceptance"] == "PASS"
    assert audit["metrics"]["mismatch_count"] == 0


def test_cross_shot_asset_reuse_requires_review():
    audit = _audit_for_hashes(["a" * 64, "a" * 64])
    assert audit["acceptance"] == "REVIEW_REQUIRED"
    assert audit["root_cause"] == "UNPLANNED_CROSS_SHOT_REUSE"

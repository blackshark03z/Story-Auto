from __future__ import annotations

import unittest

from story_auto.providers.flow.attribution import RequestAttributionTracker, surface_fingerprint
from story_auto.providers.flow.live import records_for_media


def record(card: str, asset: str | None = None, *, media_type="IMAGE", state="READY", timestamp=None):
    value = {"card_id": card, "asset_id": asset, "media_type": media_type,
             "state": state, "url": f"https://provider.invalid/{asset}" if asset else None}
    if timestamp is not None:
        value["timestamp"] = timestamp
    return value


class FlowAttributionTests(unittest.TestCase):
    def test_pre_dispatch_baseline_excludes_stale_outputs_from_delta(self):
        stale = record("tile-old", "asset-old")
        tracker = RequestAttributionTracker([stale], media_type="IMAGE", expected_count=1)
        observation = tracker.observe([stale])
        self.assertEqual((observation.state, observation.candidate_delta_count), ("WAITING", 0))
        self.assertEqual(surface_fingerprint([stale]), surface_fingerprint([dict(stale, timestamp="later")]))

    def test_preexisting_asset_rewrapped_in_new_tile_is_still_stale(self):
        baseline = [record("tile-old", "asset-same")]
        tracker = RequestAttributionTracker(baseline, media_type="IMAGE", expected_count=1)
        observation = tracker.observe([record("tile-new-wrapper", "asset-same")])
        self.assertEqual((observation.state, observation.candidate_delta_count), ("WAITING", 0))

    def test_one_unique_provider_tile_asset_lineage_requires_stability(self):
        stale = record("tile-old", "asset-old")
        current = [stale, record("tile-request", "asset-request")]
        tracker = RequestAttributionTracker([stale], media_type="IMAGE", expected_count=1)
        self.assertEqual(tracker.observe(current).state, "CANDIDATE")
        self.assertEqual(tracker.observe(current).state, "CANDIDATE")
        confirmed = tracker.observe(current)
        self.assertEqual(confirmed.state, "CONFIRMED")
        self.assertEqual(confirmed.candidate["asset_id"], "asset-request")
        self.assertNotIn("url", confirmed.candidate_identities[0])

    def test_six_candidate_delta_is_ambiguous_and_never_selects_newest(self):
        candidates = [record(f"tile-{index}", f"asset-{index}", timestamp=1000 + index)
                      for index in range(6)]
        tracker = RequestAttributionTracker([], media_type="IMAGE", expected_count=1)
        observation = tracker.observe(candidates)
        self.assertEqual((observation.state, observation.candidate_delta_count), ("AMBIGUOUS", 6))
        self.assertIsNone(observation.candidate)

    def test_timestamp_proximity_cannot_resolve_competing_candidates(self):
        tracker = RequestAttributionTracker([], media_type="IMAGE", expected_count=1)
        observation = tracker.observe([
            record("tile-near", "asset-near", timestamp=1.001),
            record("tile-newest", "asset-newest", timestamp=1.002),
        ])
        self.assertEqual(observation.state, "AMBIGUOUS")
        self.assertIsNone(observation.candidate)

    def test_transient_candidate_is_not_accepted_before_competitor_arrives(self):
        tracker = RequestAttributionTracker([], media_type="IMAGE", expected_count=1)
        self.assertEqual(tracker.observe([record("tile-a", "asset-a")]).state, "CANDIDATE")
        observation = tracker.observe([
            record("tile-a", "asset-a"), record("tile-b", "asset-b")
        ])
        self.assertEqual(observation.state, "AMBIGUOUS")
        self.assertIsNone(observation.candidate)

    def test_placeholder_lineage_can_quarantine_foreign_output(self):
        tracker = RequestAttributionTracker([], media_type="IMAGE", expected_count=1)
        self.assertEqual(tracker.observe([record("tile-job", state="PENDING")]).state, "WAITING")
        current = [record("tile-job", "asset-owned"), record("tile-foreign", "asset-foreign")]
        tracker.observe(current)
        tracker.observe(current)
        confirmed = tracker.observe(current)
        self.assertEqual(confirmed.state, "CONFIRMED")
        self.assertEqual(confirmed.candidate["asset_id"], "asset-owned")
        self.assertEqual(confirmed.foreign_candidate_identities[0]["asset_id"], "asset-foreign")

    def test_image_and_reference_image_use_same_identity_contract(self):
        current = [record("tile-image", "asset-image")]
        ordinary = RequestAttributionTracker([], media_type="IMAGE", expected_count=1)
        reference = RequestAttributionTracker([], media_type="IMAGE", expected_count=1)
        for _ in range(3):
            ordinary_result = ordinary.observe(current)
            reference_result = reference.observe(current)
        self.assertEqual(ordinary_result, reference_result)
        self.assertEqual(reference_result.state, "CONFIRMED")

    def test_video_surface_ignores_thumbnail_and_preserves_video_identity(self):
        records = [
            record("video-card", "video-asset", media_type="VIDEO"),
            record("video-card", "thumb-asset", media_type="VIDEO_THUMBNAIL"),
        ]
        self.assertEqual([item["asset_id"] for item in records_for_media(records, "VIDEO")], ["video-asset"])
        tracker = RequestAttributionTracker([], media_type="VIDEO", expected_count=1)
        for _ in range(3):
            observation = tracker.observe(records)
        self.assertEqual((observation.state, observation.candidate["asset_id"]), ("CONFIRMED", "video-asset"))


if __name__ == "__main__":
    unittest.main()

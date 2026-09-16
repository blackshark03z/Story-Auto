from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from story_auto.core.artifacts import atomic_write_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.visual.hybrid_body import (apply_pexels_search_result, adopt_pexels_stock_video,
    build_hybrid_body_plan, hybrid_body_view, semantic_stock_query)
from story_auto.core.visual.opening_builder import configure_opening_builder
from story_auto.providers.pexels import PexelsClient, PexelsError, cached_video_search, select_candidate
from story_auto.providers.pexels.service import resolve_pexels_stock_slot


FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def candidate(asset_id: int, rank: int, *, duration: float = 12.0, width: int = 1920, height: int = 1080):
    return {
        "provider": "pexels", "provider_asset_id": str(asset_id), "provider_rank": rank,
        "duration_seconds": duration, "width": width, "height": height,
        "page_url": f"https://www.pexels.com/video/{asset_id}/",
        "creator": {"id": f"u{asset_id}", "name": f"Creator {asset_id}", "url": f"https://www.pexels.com/@c{asset_id}/"},
        "video_files": [{"file_id": f"f{asset_id}", "quality": "hd", "file_type": "video/mp4",
                         "width": width, "height": height, "fps": 30.0,
                         "link": f"https://videos.pexels.com/video-files/{asset_id}.mp4"}],
        "attribution": {"provider": "Pexels", "provider_url": "https://www.pexels.com/",
                        "creator_name": f"Creator {asset_id}", "creator_url": f"https://www.pexels.com/@c{asset_id}/",
                        "source_url": f"https://www.pexels.com/video/{asset_id}/",
                        "text": f"Video by Creator {asset_id} on Pexels"},
    }


class PexelsClientTests(unittest.TestCase):
    def test_search_contract_normalizes_provenance_and_rate_limits(self):
        observed = {}
        def fetch(url, headers, timeout):
            observed.update({"url": url, "headers": dict(headers), "timeout": timeout})
            payload = {"page": 1, "per_page": 24, "total_results": 1, "videos": [{
                "id": 101, "width": 1920, "height": 1080, "duration": 11,
                "url": "https://www.pexels.com/video/101/",
                "user": {"id": 9, "name": "Jane", "url": "https://www.pexels.com/@jane/"},
                "video_files": [{"id": 501, "quality": "hd", "file_type": "video/mp4",
                                 "width": 1920, "height": 1080, "fps": 30,
                                 "link": "https://videos.pexels.com/video-files/101.mp4"}],
            }]}
            return 200, {"X-Ratelimit-Limit": "20000", "X-Ratelimit-Remaining": "19999",
                         "X-Ratelimit-Reset": "1790000000"}, json.dumps(payload).encode()
        result = PexelsClient(key="test-key", fetch=fetch).search_videos("misty mountain", per_page=24)
        self.assertEqual(observed["headers"]["Authorization"], "test-key")
        self.assertIn("/v1/videos/search?", observed["url"])
        self.assertIn("query=misty+mountain", observed["url"])
        self.assertEqual(result["rate_limit"], {"limit": 20000, "remaining": 19999, "reset": 1790000000})
        self.assertEqual(result["videos"][0]["provider_asset_id"], "101")
        self.assertEqual(result["videos"][0]["attribution"]["creator_name"], "Jane")
        self.assertNotIn("test-key", json.dumps(result))

    def test_cached_search_uses_same_response_inside_24h(self):
        with tempfile.TemporaryDirectory() as root:
            calls = []
            def fetch(url, headers, timeout):
                calls.append(url)
                return 200, {}, json.dumps({"total_results": 0, "videos": []}).encode()
            client = PexelsClient(key="k", fetch=fetch)
            first = cached_video_search(root, client, "forest night", now_epoch=1000)
            second = cached_video_search(root, client, "forest   night", now_epoch=1100)
            self.assertFalse(first["cache_hit"])
            self.assertTrue(second["cache_hit"])
            self.assertEqual(len(calls), 1)

    def test_selection_is_deterministic_relevant_and_avoids_used_assets(self):
        result = {"query": "forest night", "videos": [candidate(i, i) for i in range(1, 10)]}
        first = select_candidate(result, slot_id="BODY_0004", used_asset_ids=set(), target_duration=7,
                                 target_width=1920, target_height=1080)
        second = select_candidate(result, slot_id="BODY_0004", used_asset_ids=set(), target_duration=7,
                                  target_width=1920, target_height=1080)
        self.assertEqual(first["provider_asset_id"], second["provider_asset_id"])
        self.assertLessEqual(first["provider_rank"], 8)
        replacement = select_candidate(result, slot_id="BODY_0004", used_asset_ids={first["provider_asset_id"]},
                                       target_duration=7, target_width=1920, target_height=1080)
        self.assertNotEqual(first["provider_asset_id"], replacement["provider_asset_id"])


class HybridBodyPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = RuntimeLayout.from_root(self.temp.name).ensure()
        self.project_id = "prj_hybrid_body"
        self.paths = create_project(self.runtime, ProjectConfig(self.project_id, render_mode="hybrid_hook",
            settings={"render": {"width": 320, "height": 180, "fps": 24, "pixel_format": "yuv420p"}}))
        configure_opening_builder(self.runtime.root, self.project_id,
            shared_context="Same protagonist and dawn mountain continuity.", slot_specs=[
                {"duration_seconds": 6, "purpose": "hook", "prompt": "opening one"},
                {"duration_seconds": 6, "purpose": "development", "prompt": "opening two"},
                {"duration_seconds": 6, "purpose": "transition", "prompt": "opening three"},
            ])
        segments = []
        for index in range(10):
            start, end = index * 6.0, (index + 1) * 6.0
            segments.append({"segment_id": f"seg_{index}", "start": start, "end": end,
                             "text": f"Nhân vật đi qua khu rừng sương mù vào ban đêm cảnh {index}."})
        atomic_write_json(self.paths.artifact_path("output/alignment.json"),
                          {"duration_seconds": 60.0, "segments": segments})

    def tearDown(self):
        self.temp.cleanup()

    def _search_result(self, query: str):
        return {"provider": "pexels", "query": query, "locale": "vi-VN", "cache_key": "c" * 64,
                "cache_hit": False, "rate_limit": {"limit": 20000, "remaining": 19990, "reset": 1790000000},
                "videos": [candidate(201, 1), candidate(202, 2), candidate(203, 3)]}

    def test_body_recipe_is_exact_nonoverlapping_and_semantic(self):
        plan = build_hybrid_body_plan(self.runtime.root, self.project_id)
        self.assertEqual(plan["opening_end_seconds"], 18.0)
        self.assertEqual(plan["slots"][0]["start"], 18.0)
        self.assertEqual(plan["slots"][-1]["end"], 60.0)
        for prior, current in zip(plan["slots"], plan["slots"][1:]):
            self.assertAlmostEqual(prior["end"], current["start"], places=5)
        kinds = [slot["visual_type"] for slot in plan["slots"]]
        self.assertEqual(kinds[:4], ["IMAGE", "IMAGE", "IMAGE", "STOCK_VIDEO"])
        stock = next(slot for slot in plan["slots"] if slot["visual_type"] == "STOCK_VIDEO")
        self.assertGreaterEqual(stock["target_duration"], 5.0)
        self.assertLessEqual(stock["target_duration"], 10.0)
        self.assertEqual(stock["fallback_policy"], "IMAGE")
        self.assertTrue(stock["provider_query"])
        self.assertIn("rừng", stock["provider_query"])

    def test_stock_selection_persists_provenance_rate_limit_and_no_duplicate(self):
        plan = build_hybrid_body_plan(self.runtime.root, self.project_id)
        stock_slots = [item for item in plan["slots"] if item["visual_type"] == "STOCK_VIDEO"]
        first = stock_slots[0]
        selected = apply_pexels_search_result(self.runtime.root, self.project_id, first["slot_id"],
                                              self._search_result(first["provider_query"]))
        selected_slot = next(item for item in selected["slots"] if item["slot_id"] == first["slot_id"])
        self.assertEqual(selected_slot["status"], "SELECTED")
        self.assertEqual(selected_slot["attribution"]["provider"], "Pexels")
        self.assertEqual(selected_slot["search_observation"]["rate_limit"]["remaining"], 19990)
        if len(stock_slots) > 1:
            second = stock_slots[1]
            updated = apply_pexels_search_result(self.runtime.root, self.project_id, second["slot_id"],
                                                 self._search_result(second["provider_query"]))
            ids = [item["provider_selection"]["provider_asset_id"] for item in updated["slots"]
                   if isinstance(item.get("provider_selection"), dict)]
            self.assertEqual(len(ids), len(set(ids)))

    @unittest.skipUnless(FFMPEG, "Hybrid stock normalization requires ffmpeg and ffprobe")
    def test_resolve_stock_slot_searches_once_downloads_once_and_then_reuses_hash_bound_asset(self):
        plan = build_hybrid_body_plan(self.runtime.root, self.project_id)
        stock = next(item for item in plan["slots"] if item["visual_type"] == "STOCK_VIDEO")
        calls = {"search": 0, "download": 0}
        def fetch(url, headers, timeout):
            calls["search"] += 1
            payload = {"total_results": 1, "videos": [{
                "id": 301, "width": 1920, "height": 1080, "duration": 12,
                "url": "https://www.pexels.com/video/301/",
                "user": {"id": 3, "name": "Stock Creator", "url": "https://www.pexels.com/@stock/"},
                "video_files": [{"id": 901, "quality": "hd", "file_type": "video/mp4",
                                 "width": 1920, "height": 1080, "fps": 30,
                                 "link": "https://videos.pexels.com/video-files/301.mp4"}],
            }]}
            return 200, {"X-Ratelimit-Remaining": "19999"}, json.dumps(payload).encode()
        def download(url, destination, max_bytes):
            calls["download"] += 1
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            "color=c=black:s=640x360:r=30:d=10", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-an", str(destination)], check=True)
        client = PexelsClient(key="fake", fetch=fetch)
        first = resolve_pexels_stock_slot(self.runtime.root, self.project_id, stock["slot_id"],
                                          client=client, downloader=download, now_epoch=1000)
        bound = next(item for item in first["slots"] if item["slot_id"] == stock["slot_id"])
        self.assertEqual(bound["status"], "READY")
        self.assertEqual(bound["provider_selection"]["provider_asset_id"], "301")
        second = resolve_pexels_stock_slot(self.runtime.root, self.project_id, stock["slot_id"],
                                           client=client, downloader=download, now_epoch=1100)
        self.assertEqual(calls, {"search": 1, "download": 1})
        self.assertEqual(next(item for item in second["slots"] if item["slot_id"] == stock["slot_id"])["status"], "READY")

    @unittest.skipUnless(FFMPEG, "Hybrid stock normalization requires ffmpeg and ffprobe")
    def test_selected_stock_download_is_normalized_silent_and_hash_bound(self):
        plan = build_hybrid_body_plan(self.runtime.root, self.project_id)
        stock = next(item for item in plan["slots"] if item["visual_type"] == "STOCK_VIDEO")
        apply_pexels_search_result(self.runtime.root, self.project_id, stock["slot_id"],
                                   self._search_result(stock["provider_query"]))
        source = Path(self.temp.name) / "pexels_source.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=darkgreen:s=640x360:r=30:d=10", "-f", "lavfi", "-i",
                        "sine=frequency=330:sample_rate=48000:duration=10", "-shortest", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True)
        value = adopt_pexels_stock_video(self.runtime.root, self.project_id, stock["slot_id"], source)
        bound = next(item for item in value["slots"] if item["slot_id"] == stock["slot_id"])
        self.assertEqual(bound["status"], "READY")
        self.assertTrue(bound["normalized_asset"]["audio_stripped"])
        self.assertEqual((bound["normalized_asset"]["width"], bound["normalized_asset"]["height"]), (320, 180))
        self.assertAlmostEqual(bound["normalized_asset"]["duration_seconds"], stock["target_duration"], delta=.08)
        normalized = self.paths.artifact_path(bound["normalized_asset"]["path"])
        audio = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                                "stream=codec_type", "-of", "csv=p=0", str(normalized)],
                               capture_output=True, text=True, check=True)
        self.assertEqual(audio.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from PIL import Image

from story_auto.core.artifacts import atomic_write_json, sha256_file
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.render.media import probe_media
from story_auto.core.visual.hybrid_body import (adopt_hybrid_body_image, adopt_pexels_stock_video,
    apply_pexels_search_result, build_hybrid_body_plan)
from story_auto.core.visual.hybrid_render import hybrid_preview_readiness, hybrid_preview_view, render_hybrid_preview
from story_auto.core.visual.opening_builder import configure_opening_builder, import_opening_clip, opening_builder_view


FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


@unittest.skipUnless(FFMPEG, "Hybrid mixed render requires ffmpeg and ffprobe")
class HybridVisualMixedRenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = RuntimeLayout.from_root(self.temp.name).ensure()
        self.project_id = "prj_hybrid_mixed"
        self.paths = create_project(self.runtime, ProjectConfig(self.project_id, render_mode="hybrid_hook",
            settings={
                "render": {"width": 320, "height": 180, "fps": 10, "pixel_format": "yuv420p",
                           "subtitle_style": {"width": 28, "font_name": "Arial", "font_size": 24,
                                              "margin_left": 20, "margin_right": 20}},
                "hybrid_visual": {"audio_visualizer": True},
            }))
        narration = self.paths.artifact_path("assets/audio/narration.wav")
        narration.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=440:sample_rate=48000:duration=36", "-c:a", "pcm_s16le", str(narration)], check=True)
        segments = [{"segment_id": f"seg_{index}", "start": index * 6.0, "end": (index + 1) * 6.0,
                     "text": f"Cảnh kể chuyện trong khu rừng sương mù đoạn {index}."} for index in range(6)]
        atomic_write_json(self.paths.artifact_path("output/alignment.json"), {
            "duration_seconds": 36.0, "audio_path": "assets/audio/narration.wav",
            "audio_sha256": sha256_file(narration), "segments": segments,
        })
        configure_opening_builder(self.runtime.root, self.project_id,
            shared_context="Same protagonist, natural cinematic dawn lighting.", slot_specs=[
                {"duration_seconds": 7.5, "purpose": "hook", "prompt": "opening clip one"},
                {"duration_seconds": 7.5, "purpose": "transition", "prompt": "opening clip two"},
            ])
        for index, slot_id in enumerate(("OPENING_O1", "OPENING_O2"), start=1):
            source = Path(self.temp.name) / f"opening_{index}.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            f"color=c={'navy' if index == 1 else 'teal'}:s=640x360:r=12:d=8", "-f", "lavfi", "-i",
                            "sine=frequency=880:sample_rate=48000:duration=8", "-shortest", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True)
            import_opening_clip(self.runtime.root, self.project_id, slot_id, source, original_filename=source.name)
        self.body = build_hybrid_body_plan(self.runtime.root, self.project_id,
                                           image_slot_seconds=4.0, images_per_block=3, stock_slot_seconds=5.0)

    def tearDown(self):
        self.temp.cleanup()

    def _image(self, name: str, color: tuple[int, int, int]) -> Path:
        path = Path(self.temp.name) / name
        Image.new("RGB", (640, 360), color).save(path)
        return path

    def _bind_body_assets(self, *, stock_as_fallback: bool = False) -> None:
        image_slots = [item for item in self.body["slots"] if item["visual_type"] == "IMAGE"]
        for index, slot in enumerate(image_slots, start=1):
            adopt_hybrid_body_image(self.runtime.root, self.project_id, slot["slot_id"],
                                    self._image(f"image_{index}.png", (20 * index, 30, 80)),
                                    original_filename=f"image_{index}.png")
        stock = next(item for item in self.body["slots"] if item["visual_type"] == "STOCK_VIDEO")
        if stock_as_fallback:
            adopt_hybrid_body_image(self.runtime.root, self.project_id, stock["slot_id"],
                                    self._image("stock_fallback.png", (80, 40, 20)),
                                    original_filename="stock_fallback.png", as_stock_fallback=True)
            return
        search_result = {"provider": "pexels", "query": stock["provider_query"], "locale": "vi-VN",
                         "cache_key": "d" * 64, "cache_hit": False,
                         "rate_limit": {"limit": 20000, "remaining": 19999, "reset": 1790000000},
                         "videos": [{"provider": "pexels", "provider_asset_id": "501", "provider_rank": 1,
                            "duration_seconds": 6.0, "width": 1920, "height": 1080,
                            "page_url": "https://www.pexels.com/video/501/",
                            "creator": {"id": "9", "name": "Creator", "url": "https://www.pexels.com/@creator/"},
                            "video_files": [{"file_id": "901", "quality": "hd", "file_type": "video/mp4",
                                             "width": 1920, "height": 1080, "fps": 30.0,
                                             "link": "https://videos.pexels.com/video-files/501.mp4"}],
                            "attribution": {"provider": "Pexels", "provider_url": "https://www.pexels.com/",
                                            "creator_name": "Creator", "creator_url": "https://www.pexels.com/@creator/",
                                            "source_url": "https://www.pexels.com/video/501/",
                                            "text": "Video by Creator on Pexels"}}]}
        apply_pexels_search_result(self.runtime.root, self.project_id, stock["slot_id"], search_result)
        source = Path(self.temp.name) / "stock.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=darkgreen:s=640x360:r=15:d=6", "-f", "lavfi", "-i",
                        "sine=frequency=220:sample_rate=48000:duration=6", "-shortest", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True)
        adopt_pexels_stock_video(self.runtime.root, self.project_id, stock["slot_id"], source)

    def test_readiness_requires_body_assets_and_accepts_image_stock_fallback(self):
        opening = opening_builder_view(self.runtime.root, self.project_id)
        self.assertTrue(opening["ready"])
        before = hybrid_preview_readiness(self.runtime.root, self.project_id)
        self.assertFalse(before["ready"])
        self.assertTrue(any(item["reason"] == "IMAGE_REQUIRED" for item in before["missing"]))
        self._bind_body_assets(stock_as_fallback=True)
        after = hybrid_preview_readiness(self.runtime.root, self.project_id)
        self.assertTrue(after["ready"])

    def test_mixed_preview_preserves_master_tracks_across_video_image_stock_image(self):
        self._bind_body_assets(stock_as_fallback=False)
        manifest = render_hybrid_preview(self.runtime.root, self.project_id)
        self.assertEqual(manifest["status"], "READY")
        self.assertEqual(manifest["source_video_audio"], "MUTED_BY_CONTRACT")
        self.assertTrue(manifest["audio_visualizer"]["enabled"])
        self.assertEqual(manifest["narration"]["sha256"], sha256_file(self.paths.artifact_path("assets/audio/narration.wav")))
        kinds = [item["source_kind"] for item in manifest["timeline"]]
        self.assertEqual(kinds[:2], ["OPENING_VIDEO", "OPENING_VIDEO"])
        self.assertEqual(kinds[2:6], ["IMAGE", "IMAGE", "IMAGE", "STOCK_VIDEO"])
        self.assertEqual(kinds[-1], "IMAGE")
        transitions = [item["transition"]["type"] for item in manifest["timeline"]]
        self.assertIn("CROSSFADE", transitions)
        self.assertIn("CUT", transitions)
        self.assertEqual(manifest["timeline"][-1]["transition"]["type"], "CUT")
        for prior, current in zip(manifest["timeline"], manifest["timeline"][1:]):
            self.assertAlmostEqual(prior["end"], current["start"], places=5)
        self.assertAlmostEqual(manifest["timeline"][-1]["end"], 36.0, places=5)
        output = self.paths.artifact_path(manifest["preview_path"])
        meta = probe_media(output)
        self.assertAlmostEqual(meta["duration_seconds"], 36.0, delta=.12)
        self.assertEqual(len(meta["audio"]), 1)
        self.assertTrue(self.paths.artifact_path(manifest["subtitles"]["srt"]).is_file())
        self.assertTrue(self.paths.artifact_path(manifest["subtitles"]["ass"]).is_file())
        self.assertFalse(self.paths.artifact_path("output/final.mp4").exists())
        view = hybrid_preview_view(self.runtime.root, self.project_id)
        self.assertTrue(view["preview_ready"])


if __name__ == "__main__":
    unittest.main()

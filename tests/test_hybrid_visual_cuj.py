from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
import os
import json

from PIL import Image, ImageDraw

from story_auto.application.operator import OperatorService
from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.audio import TimedSpan, build_alignment
from story_auto.core.content import narration_hash
from story_auto.core.planning import run_planning_stages
from story_auto.providers.llm import LLMResponse
from story_auto.providers.flow.service import FlowExecutor, execute_generation
from story_auto.providers.flow.session import FlowCapabilities
from story_auto.ui.server import create_server
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.visual.hybrid_body import hybrid_body_view, sync_hybrid_body_generated_images
from story_auto.core.visual.opening_builder import import_opening_clip, opening_builder_view


FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


class HybridPlanningGemini:
    name = "gemini"
    def generate_structured(self, request):
        if request.stage == "story_timeline":
            value = {"groups": [{
                "segment_ids": [f"seg_{index:04d}" for index in range(1, 7)],
                "story_role": "setup",
                "summary": "A cultivator crosses a misty mountain.",
                "entity_ids": [],
            }]}
        else:
            value = {"style": {"id": "cinematic", "negative_constraints": ["no text overlays"]},
                     "characters": [], "locations": [], "props": []}
        return LLMResponse(value, request.model, request.request_id, 1, 3,
                           {"promptTokenCount": 10, "candidatesTokenCount": 5})


@unittest.skipUnless(FFMPEG, "Hybrid CUJ integration requires ffmpeg and ffprobe")
class HybridVisualCanonicalCUJTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = RuntimeLayout.from_root(self.temp.name).ensure()
        self.project_id = "prj_hybrid_cuj"
        self.paths = create_project(self.runtime, ProjectConfig(self.project_id, render_mode="hybrid_hook", settings={
            "hybrid_visual": {"cuj_enabled": True, "audio_visualizer": True},
            "render": {"width": 320, "height": 180, "fps": 10, "pixel_format": "yuv420p",
                       "subtitle_style": {"width": 28, "font_name": "Arial", "font_size": 24,
                                          "margin_left": 20, "margin_right": 20}},
            "ui": {"input_source": "STORY_CONTENT"},
        }))
        self.service = OperatorService(self.runtime.root)
        narration_texts = [f"A misty mountain story beat {i}." for i in range(6)]
        narration_text = " ".join(narration_texts)
        self.paths.content_file.write_text("## Narration\n\n" + narration_text + "\n", encoding="utf-8")
        atomic_write_json(self.paths.artifact_path("output/content_manifest.json"), {
            "schema_version": "test", "narration_sha256": narration_hash(narration_text),
        })
        narration = self.paths.artifact_path("assets/audio/narration.wav")
        narration.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=440:sample_rate=48000:duration=36", "-c:a", "pcm_s16le", str(narration)], check=True)
        spans = [TimedSpan(text + (" " if index < 5 else ""), index * 6.0, (index + 1) * 6.0)
                 for index, text in enumerate(narration_texts)]
        alignment = build_alignment(project_id=self.project_id, audio_path="assets/audio/narration.wav",
                                    audio_sha256=sha256_file(narration), narration_sha256=narration_hash(narration_text),
                                    duration_seconds=36.0, source="fixture", spans=spans)
        atomic_write_json(self.paths.artifact_path("output/alignment.json"), alignment)
        project = read_json(self.paths.project_file)
        project["settings"]["llm"] = {"provider": "gemini", "model": "gemini-3.5-flash", "max_attempts": 2}
        atomic_write_json(self.paths.project_file, project)
        run_planning_stages(self.runtime.root, self.project_id, provider=HybridPlanningGemini())

    def tearDown(self):
        self.temp.cleanup()

    def _import_opening(self) -> None:
        opening = opening_builder_view(self.runtime.root, self.project_id)
        self.assertEqual(len(opening["slots"]), 3)
        for index, slot in enumerate(opening["slots"], 1):
            source = Path(self.temp.name) / f"opening_{index}.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            f"color=c={'navy' if index == 1 else 'teal'}:s=640x360:r=12:d=6.2",
                            "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=6.2",
                            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True)
            import_opening_clip(self.runtime.root, self.project_id, slot["slot_id"], source,
                                original_filename=source.name)

    def _simulate_flow_body_images(self) -> None:
        requests = read_json(self.paths.artifact_path("output/generation_requests.json"))["requests"]
        calls = []
        def generate(request, refs, target):
            calls.append(request["request_id"])
            target.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGB", (1280, 720), (30 + len(calls) * 20, 40, 90))
            draw = ImageDraw.Draw(image)
            if len(calls) % 2:
                draw.rectangle((40, 80, 500, 640), fill=(230, 220, 60))
            else:
                draw.rectangle((780, 80, 1240, 640), fill=(40, 220, 210))
            image.save(target, "PNG")
            return target
        executor = FlowExecutor(FlowCapabilities(True, True, True, True, True, True), generate)
        request_ids = {request["request_id"] for request in requests}
        result = execute_generation(self.runtime.root, self.project_id, executor=executor, execute=True,
                                    request_ids=request_ids, production_batch=True)
        self.assertEqual(result["new_submissions"], len(requests))
        self.assertEqual(set(calls), request_ids)
        sync_hybrid_body_generated_images(self.runtime.root, self.project_id)
        body = hybrid_body_view(self.runtime.root, self.project_id)
        self.assertTrue(all(isinstance(slot.get("source_asset"), dict)
                            for slot in body["slots"] if slot["visual_type"] == "IMAGE"))

    def test_run_to_final_stops_only_for_manual_opening_then_continues_to_canonical_final(self):
        first = self.service.run_to_final(self.project_id)
        self.assertEqual(first["outcome"], "OWNER_DECISION_REQUIRED")
        state = self.service.production_query(self.project_id)
        self.assertEqual(state["active_stage"], "VISUALS")
        self.assertEqual(state["blocker"]["reason_code"], "HYBRID_OPENING_CLIPS_REQUIRED")
        self.assertEqual(state["next_action"]["action"], "focus_opening_builder")
        self.assertEqual([state["stages"][name]["status"] for name in ("SOURCE", "TIMING", "PLAN")],
                         ["COMPLETE", "COMPLETE", "COMPLETE"])
        opening = opening_builder_view(self.runtime.root, self.project_id)
        self.assertEqual(opening["opening_duration_seconds"], 18.0)
        review = read_json(self.paths.artifact_path("output/review_state.json"))
        self.assertEqual(review["plan_approval"]["status"], "APPROVED")
        self.assertEqual(len(read_json(self.paths.artifact_path("output/generation_requests.json"))["requests"]),
                         len([slot for slot in hybrid_body_view(self.runtime.root, self.project_id)["slots"]
                              if slot["visual_type"] == "IMAGE"]))

        self._import_opening()
        self._simulate_flow_body_images()
        resumed = self.service.continue_production(self.project_id)
        self.assertEqual(resumed["outcome"], "FINAL_VIDEO_COMPLETE")
        state = self.service.production_query(self.project_id)
        self.assertEqual(state["pipeline_status"], "COMPLETE")
        self.assertTrue(all(state["stages"][name]["status"] == "COMPLETE"
                            for name in ("SOURCE", "TIMING", "PLAN", "VISUALS", "QUALITY", "RENDER")))
        self.assertTrue(self.paths.artifact_path("output/final.mp4").is_file())
        manifest = read_json(self.paths.artifact_path("output/final_manifest.json"))
        self.assertEqual(manifest["schema_version"], "story-auto-hybrid-final/1.0.0")
        self.assertEqual(manifest["render_mode"], "hybrid_hook")
        self.assertEqual(manifest["source_video_audio"], "MUTED_BY_CONTRACT")
        self.assertTrue(manifest["audio_visualizer"]["enabled"])
        self.assertEqual(len(manifest["streams"]["audio"]), 1)
        self.assertAlmostEqual(manifest["duration_seconds"], float(read_json(self.paths.artifact_path("output/alignment.json"))["duration_seconds"]), delta=.12)
        self.assertEqual(manifest["final_sha256"], sha256_file(self.paths.artifact_path("output/final.mp4")))
        self.assertEqual(manifest["input_hashes"]["alignment"], sha256_file(self.paths.artifact_path("output/alignment.json")))
        kinds = [item["source_kind"] for item in manifest["timeline"]]
        self.assertEqual(kinds[:3], ["OPENING_VIDEO", "OPENING_VIDEO", "OPENING_VIDEO"])
        self.assertIn("STOCK_IMAGE_FALLBACK", kinds)
        self.assertFalse(self.paths.artifact_path("output/hybrid_quality.json").stat().st_size == 0)

        # Completed output stays on disk, but cannot represent changed inputs.
        final_hash = sha256_file(self.paths.artifact_path("output/final.mp4"))
        for relative in ("assets/audio/narration.wav", "output/hybrid_subtitles.srt",
                         "output/hybrid_subtitles.ass", "content.md", "project.json"):
            with self.subTest(changed_final_input=relative):
                target = self.paths.artifact_path(relative)
                before = target.read_bytes()
                try:
                    if relative == "project.json":
                        config = read_json(target)
                        config["settings"]["hybrid_visual"]["audio_visualizer"] = False
                        atomic_write_json(target, config)
                    else:
                        target.write_bytes(before + b" changed")
                    self.assertNotEqual(self.service.production_query(self.project_id)["pipeline_status"], "COMPLETE")
                    self.assertIsNone(self.service.project_workspace(self.project_id)["final_path"])
                finally:
                    target.write_bytes(before)
                self.assertEqual(self.service.production_query(self.project_id)["pipeline_status"], "COMPLETE")
                self.assertEqual(sha256_file(self.paths.artifact_path("output/final.mp4")), final_hash)

        replacement = Path(self.temp.name) / "opening_replacement.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=purple:s=640x360:r=12:d=6.2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-an", str(replacement)], check=True)
        import_opening_clip(self.runtime.root, self.project_id, "OPENING_O1", replacement,
                            original_filename=replacement.name)
        stale = self.service.production_query(self.project_id)
        self.assertNotEqual(stale["pipeline_status"], "COMPLETE")
        self.assertEqual(stale["active_stage"], "QUALITY")
        self.assertEqual(stale["stages"]["RENDER"]["status"], "NOT_STARTED")

    def test_browser_cuj_imports_opening_then_continues_to_final(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as probe:
            chrome = Path(probe.chromium.executable_path)
        if not chrome.is_file():
            self.skipTest("Playwright Chromium is not installed for the browser CUJ")

        first = self.service.run_to_final(self.project_id)
        self.assertEqual(first["outcome"], "OWNER_DECISION_REQUIRED")
        self._simulate_flow_body_images()
        opening_files = []
        for index in range(1, 4):
            source = Path(self.temp.name) / f"browser_opening_{index}.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            f"color=c={'navy' if index == 1 else 'teal' if index == 2 else 'purple'}:s=640x360:r=12:d=6.2",
                            "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000:duration=6.2",
                            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True)
            opening_files.append(source)

        server = create_server(self.runtime.root, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=str(chrome))
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{server.server_address[1]}")
                card = page.locator(".project-card", has_text=self.project_id).first
                card.get_by_role("button", name="View project", exact=True).click()
                page.get_by_text("Opening Builder", exact=False).first.wait_for(timeout=5000)
                self.assertIn("Import opening clips", page.locator("body").inner_text())
                for index, source in enumerate(opening_files, 1):
                    page.locator(f'input[data-opening-import="OPENING_O{index}"]').set_input_files(str(source))
                    page.get_by_text("READY", exact=True).nth(index - 1).wait_for(timeout=10000)
                page.get_by_role("button", name="Continue production", exact=True).click()
                page.get_by_role("link", name="Open final video", exact=True).wait_for(timeout=30000)
                self.assertIn("COMPLETE", page.locator("body").inner_text().upper())
                page.wait_for_function("document.querySelector('video.video-frame')?.readyState >= 2")
                media = page.locator("video.video-frame").evaluate("v => ({duration:v.duration,width:v.videoWidth,height:v.videoHeight})")
                self.assertAlmostEqual(media["duration"], 36, delta=.12)
                self.assertEqual((media["width"], media["height"]), (320,180))
                destination = os.environ.get("STORY_AUTO_CUJ_EVIDENCE_DIR")
                if destination:
                    evidence = Path(destination); evidence.mkdir(parents=True, exist_ok=True)
                    for name, width, height in (("desktop",1366,768),("narrow",760,820)):
                        page.set_viewport_size({"width":width,"height":height})
                        page.screenshot(path=str(evidence / f"hybrid-real-final-{name}.png"), full_page=True)
                    (evidence / "hybrid-real-final.json").write_text(json.dumps({
                        "fixture":"real local render; fake planning/Flow; manual opening fixtures; no providers",
                        "project_id":self.project_id, "media":media,
                        "final_sha256":sha256_file(self.paths.artifact_path("output/final.mp4")),
                        "manifest_sha256":sha256_file(self.paths.artifact_path("output/final_manifest.json")),
                    }, indent=2), encoding="utf-8")
                browser.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(5)
        self.assertEqual(self.service.production_query(self.project_id)["pipeline_status"], "COMPLETE")

    def test_browser_new_video_wizard_exposes_hybrid_visual(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as probe:
            chrome = Path(probe.chromium.executable_path)
        if not chrome.is_file():
            self.skipTest("Playwright Chromium is not installed for the browser CUJ")
        server = create_server(self.runtime.root, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=str(chrome))
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{server.server_address[1]}")
                page.locator("#newVideoTop").click()
                page.get_by_role("button", name="Continue", exact=True).click()
                page.locator("#contentInput").fill("# Hybrid Browser\n\n## Narration\n\nA short story for the Hybrid Visual creation journey.")
                page.get_by_role("button", name="Continue", exact=True).click()
                hybrid = page.locator('input[name="format"][value="hybrid_hook"]')
                hybrid.wait_for(timeout=5000)
                self.assertTrue(hybrid.is_enabled())
                hybrid.check()
                surface = page.locator("#wizardContent").inner_text()
                self.assertIn("HYBRID VISUAL", surface)
                self.assertIn("15-20s opening video", surface)
                policy = page.locator("#hybridOpeningProviderPolicy")
                policy.wait_for(timeout=5000)
                self.assertEqual(policy.input_value(), "AUTO")
                policy.select_option("ELYUM")
                self.assertEqual(policy.input_value(), "ELYUM")
                self.assertIn("never auto-spend", page.locator("#wizardContent").inner_text())
                self.assertNotIn("Coming soon", surface)
                browser.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(5)

    def test_project_flag_is_required_before_hybrid_enters_canonical_pipeline(self):
        project = read_json(self.paths.project_file)
        project["settings"]["hybrid_visual"]["cuj_enabled"] = False
        atomic_write_json(self.paths.project_file, project)
        state = self.service.production_query(self.project_id)
        self.assertEqual(state["pipeline_status"], "FEATURE_NOT_AVAILABLE")


if __name__ == "__main__":
    unittest.main()

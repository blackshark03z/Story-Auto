from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
import threading
import os
import json
from unittest.mock import patch

from story_auto.application.operator import OperatorService
from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.visual.opening_builder import configure_opening_builder, import_opening_clip
from story_auto.providers.elyum_seedance.client import ElyumSeedanceError
from story_auto.ui.server import create_server
from story_auto.providers.elyum_seedance.opening import (
    generate_elyum_opening_preview,
    keep_elyum_opening_preview,
    preflight_elyum_opening_slot,
    kill_elyum_opening_preview,
    review_elyum_opening_preview,
)

MODEL = "seedance-test-t2v"


def _video(destination: Path, color: str = "navy") -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
        f"color=c={color}:s=640x360:r=24:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(destination)
    ], check=True)


class FakeElyum:
    provider = "elyum_seedance"
    def __init__(self, *, ambiguous_create=False, ambiguous_keep=False, estimate=20, balance=100):
        self.ambiguous_create = ambiguous_create; self.ambiguous_keep = ambiguous_keep
        self.estimate = estimate; self.balance = balance
        self.make_calls = 0; self.keep_calls = 0; self.kill_calls = 0; self.client_refs = []
    def readiness(self): return {"status":"READY","provider_id":self.provider}
    def account_balance(self): return self.balance
    def seedance_model_ids(self): return [MODEL, "seedance-too-expensive"]
    def estimate_video(self, *, model, duration, mode, resolution=None):
        self.last_estimate = (model, duration, mode, resolution)
        return 120 if model == "seedance-too-expensive" else self.estimate
    def make_video(self, **kwargs):
        self.make_calls += 1; self.client_refs.append(kwargs["client_ref"]); self.last_make = kwargs
        if self.ambiguous_create and self.make_calls == 1:
            raise ElyumSeedanceError("IDEMPOTENT_REPLAY_REQUIRED", dispatch_state="RECONCILE_BY_CLIENT_REF")
        return "elyum-job-1", {"jobId":"elyum-job-1"}
    def wait(self, job_id, **kwargs): return {"jobId":job_id,"status":"preview","genId":"elyum-gen-1","url":"https://example.invalid/preview.mp4","unlockCredits":20}
    def gen_id(self, result): return result.get("genId")
    def execution_state(self, result): return result.get("status")
    def preview_urls(self, result): return [result["url"]] if result.get("url") else []
    def unlock_credits(self, result): return result.get("unlockCredits")
    def keep(self, gen_id):
        self.keep_calls += 1
        if self.ambiguous_keep: raise ElyumSeedanceError("PROVIDER_TRANSIENT")
        return {"genId":gen_id,"downloadUrl":"https://example.invalid/original.mp4"}
    def downloadable_urls(self, result): return [result["downloadUrl"]] if result.get("downloadUrl") else []
    def kill(self, gen_id, **kwargs): self.kill_calls += 1; self.last_kill=(gen_id,kwargs); return {"status":"killed"}


class ElyumHybridOpeningTests(unittest.TestCase):
    def _project(self, root: str):
        runtime = RuntimeLayout.from_root(root).ensure()
        create_project(runtime, ProjectConfig("prj_elyum_opening", render_mode="hybrid_hook", settings={"render":{"width":320,"height":180,"fps":24,"pixel_format":"yuv420p"}}))
        configure_opening_builder(root, "prj_elyum_opening", shared_context="One stable protagonist.", slot_specs=[
            {"duration_seconds":6,"purpose":"Hook","prompt":"A cinematic hook."},
            {"duration_seconds":6,"purpose":"Develop","prompt":"Continue naturally."},
            {"duration_seconds":6,"purpose":"Bridge","prompt":"Bridge into the story."},
        ])
        return runtime
    @staticmethod
    def _fetch(_url: str, destination: Path): _video(destination, "navy")
    @staticmethod
    def _fetch_original(_url: str, destination: Path): _video(destination, "teal")

    def test_slot_preflight_is_read_only_and_persists_models_cost_and_balance(self):
        with tempfile.TemporaryDirectory() as root:
            self._project(root); client=FakeElyum(estimate=20,balance=100)
            view=preflight_elyum_opening_slot(root,"prj_elyum_opening","OPENING_O1",client=client,resolution="480p")
            preflight=view["slots"][0]["elyum_preflight"]
            self.assertEqual(preflight["status"],"READY"); self.assertEqual(preflight["balance"],100)
            self.assertEqual(preflight["provider_duration_seconds"],6); self.assertEqual(preflight["resolution"],"480p")
            self.assertEqual(preflight["models"],[
                {"model_id":MODEL,"estimate_credits":20,"affordable":True,"credential_slot":1,"balance":100},
                {"model_id":"seedance-too-expensive","estimate_credits":120,"affordable":False,"credential_slot":1,"balance":100},
            ])
            self.assertEqual(client.make_calls,0)

    def test_preview_preflight_and_t2v_contract(self):
        with tempfile.TemporaryDirectory() as root:
            self._project(root); client=FakeElyum()
            view=generate_elyum_opening_preview(root,"prj_elyum_opening","OPENING_O1",model=MODEL,client=client,preview_fetcher=self._fetch)
            gen=view["slots"][0]["api_generation"]
            self.assertEqual(gen["status"],"PREVIEW_READY"); self.assertFalse(view["slots"][0]["asset_ready"])
            self.assertEqual(client.last_estimate,(MODEL,6,"t2v","480p")); self.assertEqual(client.last_make["mode"],"t2v"); self.assertFalse(client.last_make["audio"])
            self.assertEqual(gen["provider_submissions"],1); self.assertEqual(gen["provider_job_id"],"elyum-job-1")

    def test_ambiguous_create_replays_exact_same_client_ref(self):
        with tempfile.TemporaryDirectory() as root:
            self._project(root); client=FakeElyum(ambiguous_create=True)
            first=generate_elyum_opening_preview(root,"prj_elyum_opening","OPENING_O1",model=MODEL,client=client,preview_fetcher=self._fetch)
            self.assertEqual(first["slots"][0]["api_generation"]["status"],"AMBIGUOUS")
            second=generate_elyum_opening_preview(root,"prj_elyum_opening","OPENING_O1",model=MODEL,client=client,preview_fetcher=self._fetch)
            self.assertEqual(client.make_calls,2); self.assertEqual(len(set(client.client_refs)),1)
            self.assertEqual(second["slots"][0]["api_generation"]["status"],"PREVIEW_READY")
            self.assertEqual(second["slots"][0]["api_generation"]["provider_submissions"],1)

    def test_accept_keep_binds_same_opening_slot(self):
        with tempfile.TemporaryDirectory() as root:
            self._project(root); client=FakeElyum()
            generate_elyum_opening_preview(root,"prj_elyum_opening","OPENING_O1",model=MODEL,client=client,preview_fetcher=self._fetch)
            reviewed=review_elyum_opening_preview(root,"prj_elyum_opening","OPENING_O1",decision="ACCEPT",reason="Use this preview")
            self.assertEqual(reviewed["slots"][0]["api_generation"]["status"],"KEEP_REQUIRED")
            with self.assertRaises(ElyumSeedanceError): keep_elyum_opening_preview(root,"prj_elyum_opening","OPENING_O1",client=client)
            kept=keep_elyum_opening_preview(root,"prj_elyum_opening","OPENING_O1",client=client,confirm_spend=True,output_fetcher=self._fetch_original)
            slot=kept["slots"][0]
            self.assertTrue(slot["asset_ready"]); self.assertEqual(slot["api_generation"]["status"],"SUCCEEDED")
            self.assertEqual(slot["source_asset"]["provider"],"elyum_seedance"); self.assertEqual(client.keep_calls,1)

    def test_reject_kill_preserves_manual_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            runtime=self._project(root); client=FakeElyum()
            generate_elyum_opening_preview(root,"prj_elyum_opening","OPENING_O1",model=MODEL,client=client,preview_fetcher=self._fetch)
            review_elyum_opening_preview(root,"prj_elyum_opening","OPENING_O1",decision="REJECT",reason="Motion is wrong")
            killed=kill_elyum_opening_preview(root,"prj_elyum_opening","OPENING_O1",reason="Motion is wrong",client=client,confirm_kill=True)
            self.assertEqual(killed["slots"][0]["api_generation"]["status"],"KILLED"); self.assertEqual(client.kill_calls,1)
            manual=runtime.temp/"manual.mp4"; _video(manual,"red")
            final=import_opening_clip(root,"prj_elyum_opening","OPENING_O1",manual,original_filename="manual.mp4")
            self.assertTrue(final["slots"][0]["asset_ready"]); self.assertEqual(final["slots"][0]["api_generation"]["status"],"KILLED")

    def test_keep_ambiguous_is_never_automatically_retried(self):
        with tempfile.TemporaryDirectory() as root:
            self._project(root); client=FakeElyum(ambiguous_keep=True)
            generate_elyum_opening_preview(root,"prj_elyum_opening","OPENING_O1",model=MODEL,client=client,preview_fetcher=self._fetch)
            review_elyum_opening_preview(root,"prj_elyum_opening","OPENING_O1",decision="ACCEPT",reason="Accept")
            result=keep_elyum_opening_preview(root,"prj_elyum_opening","OPENING_O1",client=client,confirm_spend=True,output_fetcher=self._fetch_original)
            self.assertEqual(result["slots"][0]["api_generation"]["status"],"KEEP_AMBIGUOUS"); self.assertEqual(client.keep_calls,1)
            with self.assertRaises(ElyumSeedanceError): keep_elyum_opening_preview(root,"prj_elyum_opening","OPENING_O1",client=client,confirm_spend=True,output_fetcher=self._fetch_original)
            self.assertEqual(client.keep_calls,1)

    def test_cost_block_has_canonical_no_dispatch(self):
        with tempfile.TemporaryDirectory() as root:
            self._project(root); client=FakeElyum(estimate=45)
            result=generate_elyum_opening_preview(root,"prj_elyum_opening","OPENING_O1",model=MODEL,client=client,max_credits=44,preview_fetcher=self._fetch)
            gen=result["slots"][0]["api_generation"]
            self.assertEqual(gen["status"],"COST_BLOCKED"); self.assertEqual(client.make_calls,0); self.assertEqual(gen["provider_submissions"],0)


    def test_browser_surface_exposes_elyum_consequence_states_without_spend(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as probe:
            chrome = Path(probe.chromium.executable_path)
        if not chrome.is_file():
            self.skipTest("Playwright Chromium is not installed")

        with tempfile.TemporaryDirectory() as root:
            runtime = RuntimeLayout.from_root(root).ensure()
            paths = create_project(runtime, ProjectConfig("prj_elyum_browser", render_mode="hybrid_hook", settings={
                "hybrid_visual": {"cuj_enabled": True},
                "render": {"width": 320, "height": 180, "fps": 24, "pixel_format": "yuv420p"},
            }))
            paths.content_file.write_text("# Elyum Browser\n\n## Narration\n\nA stable opening.\n", encoding="utf-8")
            configure_opening_builder(root, "prj_elyum_browser", shared_context="One stable protagonist.", slot_specs=[
                {"duration_seconds": 6, "purpose": "Hook", "prompt": "A cinematic hook."},
                {"duration_seconds": 6, "purpose": "Develop", "prompt": "Continue naturally."},
                {"duration_seconds": 6, "purpose": "Bridge", "prompt": "Bridge into the story."},
            ])
            manifest_path = paths.artifact_path("output/opening_manifest.json")

            def set_slot(*, preflight=None, generation=None):
                manifest = read_json(manifest_path)
                slot = manifest["slots"][0]
                if preflight is None:
                    slot.pop("elyum_preflight", None)
                else:
                    slot["elyum_preflight"] = preflight
                if generation is None:
                    slot.pop("api_generation", None)
                else:
                    slot["api_generation"] = generation
                atomic_write_json(manifest_path, manifest)

            configured = {"configured": True, "status": "CONFIGURED", "models": [], "balance": None}
            with patch.object(OperatorService, "elyum_connection_status", return_value=configured):
                server = create_server(root, port=0)
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                try:
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True, executable_path=str(chrome))
                        page = browser.new_page(); page.goto(f"http://127.0.0.1:{server.server_address[1]}")
                        page.locator('[data-open-project="prj_elyum_browser"]').click()
                        page.get_by_role("button", name="Check Elyum options", exact=True).first.wait_for(timeout=5000)

                        set_slot(preflight={"status":"READY","balance":100,"resolution":"480p","models":[{"model_id":MODEL,"estimate_credits":20,"affordable":True}]})
                        page.reload(); page.locator('[data-open-project="prj_elyum_browser"]').click()
                        page.get_by_role("button", name="Generate Elyum preview", exact=True).first.wait_for(timeout=5000)

                        base_generation = {"provider":"elyum_seedance","provider_model":MODEL,"provider_submissions":1,"unlock_credits":20}
                        set_slot(generation={**base_generation,"status":"PREVIEW_READY","preview_asset":{"path":"assets/opening/preview.mp4","sha256":"fixture"}})
                        page.reload(); page.locator('[data-open-project="prj_elyum_browser"]').click()
                        page.get_by_role("button", name="Accept preview", exact=True).wait_for(timeout=5000)
                        o1_card = page.locator("article.choice").filter(has_text="OPENING_O1").first
                        self.assertEqual(o1_card.get_by_text("Import clip", exact=True).count(), 0)

                        set_slot(generation={**base_generation,"status":"KEEP_REQUIRED"})
                        page.reload(); page.locator('[data-open-project="prj_elyum_browser"]').click()
                        page.get_by_role("button", name="Keep & use · 20 credits", exact=True).wait_for(timeout=5000)

                        set_slot(generation={**base_generation,"status":"KEEP_ACQUISITION_REQUIRED","keep_confirmed":True})
                        page.reload(); page.locator('[data-open-project="prj_elyum_browser"]').click()
                        recover = page.get_by_role("button", name="Recover kept video", exact=True)
                        recover.wait_for(timeout=5000)
                        self.assertEqual(page.locator('[data-opening-import="OPENING_O1"]').count(), 0)
                        self.assertEqual(page.locator('[data-opening-elyum-keep="OPENING_O1"]').count(), 0)
                        with patch.object(OperatorService, "keep_elyum_opening", return_value={"status":"fixture recovered"}) as acquire:
                            recover.click()
                            page.wait_for_function("state.busy === false")
                            acquire.assert_called_once_with("prj_elyum_browser", slot_id="OPENING_O1", confirm_spend=False)
                        destination = os.environ.get("STORY_AUTO_CUJ_EVIDENCE_DIR")
                        if destination:
                            evidence = Path(destination); evidence.mkdir(parents=True, exist_ok=True)
                            for name, width, height in (("desktop",1366,768),("narrow",760,820)):
                                page.set_viewport_size({"width":width,"height":height})
                                page.evaluate("window.scrollTo({top:0,left:0,behavior:'instant'})")
                                page.screenshot(path=str(evidence / f"opening-acquire-{name}.png"), full_page=True)
                                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                            (evidence / "opening-acquire.json").write_text(json.dumps({
                                "fixture":"isolated local server; acquisition service mocked; no providers",
                                "action":"keep_elyum_opening", "confirm_spend":False,
                                "viewports":[[1366,768],[760,820]],
                            }, indent=2), encoding="utf-8")

                        set_slot(generation={**base_generation,"status":"PREVIEW_REJECTED"})
                        page.reload(); page.locator('[data-open-project="prj_elyum_browser"]').click()
                        page.get_by_role("button", name="Kill & release hold", exact=True).wait_for(timeout=5000)
                        browser.close()
                finally:
                    server.shutdown(); server.server_close(); thread.join(5)


if __name__ == "__main__": unittest.main()

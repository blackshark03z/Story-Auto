from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.visual.opening_builder import configure_opening_builder, import_opening_clip
from story_auto.providers.elyum_seedance.client import ElyumSeedanceError
from story_auto.providers.elyum_seedance.opening import (
    generate_elyum_opening_preview,
    keep_elyum_opening_preview,
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
    def estimate_video(self, *, model, duration, mode, resolution=None):
        self.last_estimate = (model, duration, mode, resolution); return self.estimate
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


if __name__ == "__main__": unittest.main()
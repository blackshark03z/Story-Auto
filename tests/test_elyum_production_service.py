from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from PIL import Image

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.full_video_continuity import FullVideoContinuityError, bind_initial_anchor
from story_auto.core.full_video_provider import full_video_provider_snapshot
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.elyum_seedance import ElyumSeedanceError
from story_auto.providers.elyum_seedance.service import (ElyumProductionError, execute_elyum_generation,
    keep_elyum_preview, kill_elyum_preview, review_elyum_preview)


FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


class FakeElyumClient:
    provider = "elyum_seedance"

    def __init__(self, *, balance=100, estimate=44, make_outcomes=None, wait_outcomes=None, on_make=None,
                 keep_outcome=None, kill_outcome=None, job_status_outcome=None):
        self.balance = balance
        self.estimate = estimate
        self.make_outcomes = list(make_outcomes or [("job_prod_1", {})])
        self.wait_outcomes = list(wait_outcomes or [{"status": "done", "genId": "gen_prod_1",
                                                      "url": "https://elyum.invalid/preview.mp4", "unlockCredits": 20}])
        self.on_make = on_make
        self.keep_outcome = {"status": "kept", "videoUrl": "https://elyum.invalid/final.mp4"} if keep_outcome is None else keep_outcome
        self.kill_outcome = {"status": "killed"} if kill_outcome is None else kill_outcome
        self.job_status_outcome = job_status_outcome or {"status": "done", "videoUrl": "https://elyum.invalid/final.mp4"}
        self.upload_calls = 0
        self.make_calls = []
        self.wait_calls = []
        self.keep_calls = 0
        self.kill_calls = 0
        self.job_status_calls = 0

    def readiness(self):
        return {"status": "READY", "reason_code": None}

    def account_balance(self):
        return self.balance

    def estimate_video(self, *, model, duration, mode):
        self.last_estimate = (model, duration, mode)
        return self.estimate

    def upload_file(self, path):
        self.upload_calls += 1
        self.last_upload_sha = sha256_file(Path(path))
        return "https://elyum.invalid/reference.png"

    def make_video(self, **kwargs):
        self.make_calls.append(dict(kwargs))
        if self.on_make:
            self.on_make(kwargs)
        outcome = self.make_outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def wait(self, job_id, *, timeout_seconds=50, thumbnails=True):
        self.wait_calls.append(job_id)
        outcome = self.wait_outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @staticmethod
    def gen_id(result):
        return result.get("genId")

    @staticmethod
    def execution_state(result):
        return result.get("status")

    @staticmethod
    def preview_urls(result):
        return [result["url"]] if result.get("url") else []

    @staticmethod
    def unlock_credits(result):
        return result.get("unlockCredits")

    @staticmethod
    def downloadable_urls(result):
        if not isinstance(result, dict):
            return []
        value = result.get("videoUrl") or result.get("url")
        return [value] if isinstance(value, str) and value else []

    def keep(self, *_args, **_kwargs):
        self.keep_calls += 1
        if isinstance(self.keep_outcome, Exception):
            raise self.keep_outcome
        return self.keep_outcome

    def kill(self, *_args, **_kwargs):
        self.kill_calls += 1
        if isinstance(self.kill_outcome, Exception):
            raise self.kill_outcome
        return self.kill_outcome

    def job_status(self, *_args, **_kwargs):
        self.job_status_calls += 1
        if isinstance(self.job_status_outcome, Exception):
            raise self.job_status_outcome
        return self.job_status_outcome


@unittest.skipUnless(FFMPEG, "FFmpeg integration requires ffmpeg and ffprobe")
class ElyumProductionServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = RuntimeLayout.from_root(self.temp.name).ensure()
        self.paths = create_project(self.runtime, ProjectConfig(
            "prj_elyum_prod", render_mode="full_video_ai",
            settings={"full_video_provider": "elyum_seedance",
                      "elyum": {"model": "seedance-2-fast-i2v", "resolution": "480p",
                                "provider_duration_seconds": 4, "max_credits": 44}},
        ))
        self.request = {"request_id": "req_first", "purpose": "SHOT", "shot_id": "sh_0001",
                        "media_type": "VIDEO", "requirement": "REQUIRED", "provider": "elyum_seedance",
                        "prompt": "A restrained slow push-in.", "fingerprint": "a" * 64,
                        "target_start": 0.0, "target_end": 4.0, "target_duration": 4.0,
                        "part_index": 1, "part_count": 1, "aspect_ratio": "16:9"}
        self.requests = {"schema_version": "story-auto-generation-requests/1.0.0",
                         "project_id": "prj_elyum_prod", "prompt_version": "test",
                         "full_video_provider_snapshot": full_video_provider_snapshot({"full_video_provider": "elyum_seedance"}),
                         "requests": [self.request]}
        atomic_write_json(self.paths.artifact_path("output/generation_requests.json"), self.requests)
        anchor = Path(self.temp.name) / "anchor.png"
        Image.new("RGB", (320, 180), (30, 50, 70)).save(anchor)
        bind_initial_anchor(self.runtime.root, "prj_elyum_prod", "run_prod", "req_first", anchor,
                            source_provenance="TEST_CANONICAL_ANCHOR")
        self.preview_fixture = self.paths.artifact_path("preview_fixture.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=navy:s=320x180:r=10:d=4", "-an", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(self.preview_fixture)], check=True)

    def tearDown(self):
        self.temp.cleanup()

    def _fetch(self, _url, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.preview_fixture, destination)

    def _manifest(self):
        return read_json(self.paths.artifact_path("output/generation_manifest.json"))

    def _preview_ready(self, client=None):
        active = client or FakeElyumClient()
        result = execute_elyum_generation(self.runtime.root, "prj_elyum_prod", run_id="run_prod", client=active,
                                          dispatch_authorized=True, preview_fetcher=self._fetch)
        self.assertEqual(result["status"], "PREVIEW_READY")
        return active

    def test_dispatch_requires_explicit_authority(self):
        client = FakeElyumClient()
        with self.assertRaises(ElyumProductionError) as caught:
            execute_elyum_generation(self.runtime.root, "prj_elyum_prod", run_id="run_prod", client=client,
                                     preview_fetcher=self._fetch)
        self.assertEqual(caught.exception.failure_class, "ELYUM_PRODUCTION_DISPATCH_NOT_AUTHORIZED")
        self.assertEqual(client.upload_calls, 0)
        self.assertEqual(client.make_calls, [])

    def test_success_persists_reference_and_client_identity_before_make_and_stops_at_locked_preview(self):
        def on_make(_kwargs):
            manifest = self._manifest()
            attempt = manifest["requests"][0]["attempts"][0]
            self.assertEqual(attempt["status"], "PRE_DISPATCH")
            self.assertEqual(attempt["continuity_reference"]["run_id"], "run_prod")
            self.assertTrue(attempt["continuity_reference"]["reference_sha256"])
            self.assertTrue(attempt["client_ref"].startswith("story-auto-prod-"))
            self.assertTrue(attempt["provider_reference_url"].startswith("https://elyum.invalid/"))
            self.assertNotIn("provider_job_id", attempt)

        client = FakeElyumClient(on_make=on_make)
        result = execute_elyum_generation(
            self.runtime.root, "prj_elyum_prod", run_id="run_prod", client=client,
            dispatch_authorized=True, preview_fetcher=self._fetch,
        )
        self.assertEqual(result["status"], "PREVIEW_READY")
        self.assertEqual((result["new_submissions"], result["resumed_tasks"]), (1, 0))
        self.assertEqual((client.upload_calls, len(client.make_calls), len(client.wait_calls), client.keep_calls), (1, 1, 1, 0))
        manifest = self._manifest(); entry = manifest["requests"][0]; attempt = entry["attempts"][0]
        self.assertEqual(entry["status"], "PREVIEW_READY")
        self.assertEqual(entry["provider_submissions"], 1)
        self.assertEqual(attempt["provider_job_id"], "job_prod_1")
        self.assertEqual(attempt["gen_id"], "gen_prod_1")
        self.assertTrue(attempt["preview_asset"]["locked"])
        self.assertNotIn("selected_asset", entry)
        with self.assertRaises(FullVideoContinuityError) as caught:
            anchor2 = Path(self.temp.name) / "anchor2.png"
            Image.new("RGB", (320, 180), (90, 40, 20)).save(anchor2)
            bind_initial_anchor(self.runtime.root, "prj_elyum_prod", "run_prod", "req_first", anchor2,
                                source_provenance="CHANGED")
        self.assertEqual(caught.exception.failure_class, "CONTINUITY_TARGET_ALREADY_DISPATCHED")

    def test_ambiguous_create_replays_same_client_ref_without_reupload_or_new_attempt(self):
        transient = ElyumSeedanceError("IDEMPOTENT_REPLAY_REQUIRED", "PROVIDER_TRANSIENT",
                                       dispatch_state="RECONCILE_BY_CLIENT_REF")
        client = FakeElyumClient(make_outcomes=[transient, ("job_prod_1", {})])
        first = execute_elyum_generation(self.runtime.root, "prj_elyum_prod", run_id="run_prod", client=client,
                                         dispatch_authorized=True, preview_fetcher=self._fetch)
        self.assertEqual(first["status"], "REPLAY_SAME_CLIENT_REF")
        manifest = self._manifest(); first_ref = manifest["requests"][0]["attempts"][0]["client_ref"]
        second = execute_elyum_generation(self.runtime.root, "prj_elyum_prod", run_id="run_prod", client=client,
                                          dispatch_authorized=True, preview_fetcher=self._fetch)
        self.assertEqual(second["status"], "PREVIEW_READY")
        self.assertEqual(client.upload_calls, 1)
        self.assertEqual(len(client.make_calls), 2)
        self.assertEqual({item["client_ref"] for item in client.make_calls}, {first_ref})
        self.assertEqual(len(self._manifest()["requests"][0]["attempts"]), 1)

    def test_known_job_wait_failure_resumes_same_job_without_second_make(self):
        transient = ElyumSeedanceError("PROVIDER_TRANSIENT")
        client = FakeElyumClient(wait_outcomes=[transient, {"status": "done", "genId": "gen_prod_1",
                                                             "url": "https://elyum.invalid/preview.mp4", "unlockCredits": 20}])
        first = execute_elyum_generation(self.runtime.root, "prj_elyum_prod", run_id="run_prod", client=client,
                                         dispatch_authorized=True, preview_fetcher=self._fetch)
        self.assertEqual(first["status"], "WAIT_UNAVAILABLE")
        second = execute_elyum_generation(self.runtime.root, "prj_elyum_prod", run_id="run_prod", client=client,
                                          dispatch_authorized=True, preview_fetcher=self._fetch)
        self.assertEqual(second["status"], "PREVIEW_READY")
        self.assertEqual(len(client.make_calls), 1)
        self.assertEqual(client.wait_calls, ["job_prod_1", "job_prod_1"])
        self.assertEqual(second["resumed_tasks"], 1)

    def test_credit_block_is_read_only_and_creates_no_attempt(self):
        client = FakeElyumClient(balance=30, estimate=44)
        result = execute_elyum_generation(self.runtime.root, "prj_elyum_prod", run_id="run_prod", client=client,
                                          dispatch_authorized=True, preview_fetcher=self._fetch)
        self.assertEqual(result["status"], "CREDIT_BLOCKED")
        self.assertEqual((client.upload_calls, len(client.make_calls), len(client.wait_calls)), (0, 0, 0))
        entry = self._manifest()["requests"][0]
        self.assertEqual(entry["attempts"], [])
        self.assertEqual(entry["preflight_events"][-1]["balance"], 30)

    def test_new_run_cannot_reuse_preview_bound_to_prior_run(self):
        client = FakeElyumClient()
        first = execute_elyum_generation(self.runtime.root, "prj_elyum_prod", run_id="run_prod", client=client,
                                         dispatch_authorized=True, preview_fetcher=self._fetch)
        self.assertEqual(first["status"], "PREVIEW_READY")
        with self.assertRaises(ElyumProductionError) as caught:
            execute_elyum_generation(self.runtime.root, "prj_elyum_prod", run_id="run_new", client=client,
                                     dispatch_authorized=True, preview_fetcher=self._fetch)
        self.assertEqual(caught.exception.failure_class, "ELYUM_CONTINUITY_SNAPSHOT_MISMATCH")
        self.assertEqual(len(client.make_calls), 1)

    def test_owner_accept_creates_keep_boundary_and_keep_is_single_spend_then_idempotent(self):
        client = self._preview_ready()
        before_waits = len(client.wait_calls)
        reviewed = review_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first",
                                        decision="ACCEPT", reason="Owner accepts exact locked preview")
        self.assertEqual(reviewed["status"], "KEEP_REQUIRED")
        boundary = execute_elyum_generation(self.runtime.root, "prj_elyum_prod", run_id="run_prod", client=client,
                                            dispatch_authorized=True, preview_fetcher=self._fetch)
        self.assertEqual(boundary["status"], "KEEP_REQUIRED")
        self.assertEqual(len(client.wait_calls), before_waits)
        with self.assertRaises(ElyumProductionError) as caught:
            keep_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first", client=client,
                               output_fetcher=self._fetch)
        self.assertEqual(caught.exception.failure_class, "ELYUM_KEEP_CONFIRMATION_REQUIRED")
        kept = keep_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first", client=client,
                                  confirm_spend=True, output_fetcher=self._fetch)
        self.assertEqual(kept["status"], "SUCCEEDED")
        self.assertEqual(client.keep_calls, 1)
        entry = self._manifest()["requests"][0]
        self.assertEqual(entry["selected_asset"]["production_qc"], "OWNER_ACCEPTED")
        self.assertEqual(entry["selected_asset"]["source_preview_sha256"], reviewed["preview_sha256"])
        again = keep_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first", client=client,
                                   confirm_spend=True, output_fetcher=self._fetch)
        self.assertTrue(again["idempotent"])
        self.assertEqual(client.keep_calls, 1)

    def test_missing_clean_output_recovers_acquisition_without_second_keep(self):
        client = self._preview_ready()
        review_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first",
                             decision="ACCEPT", reason="Owner accepts preview")
        kept = keep_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first", client=client,
                                  confirm_spend=True, output_fetcher=self._fetch)
        self.assertEqual(kept["status"], "SUCCEEDED")
        self.paths.artifact_path(kept["path"]).unlink()
        boundary = execute_elyum_generation(self.runtime.root, "prj_elyum_prod", run_id="run_prod", client=client,
                                            dispatch_authorized=True, preview_fetcher=self._fetch)
        self.assertEqual(boundary["status"], "KEEP_ACQUISITION_REQUIRED")
        self.assertEqual(client.keep_calls, 1)
        recovered = keep_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first", client=client,
                                       output_fetcher=self._fetch)
        self.assertEqual(recovered["status"], "SUCCEEDED")
        self.assertEqual(client.keep_calls, 1)

    def test_keep_success_with_acquisition_failure_retries_download_only(self):
        client = self._preview_ready()
        review_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first",
                             decision="ACCEPT", reason="Owner accepts preview")
        def fail_fetch(_url, _destination):
            raise RuntimeError("offline fixture acquisition failure")
        first = keep_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first", client=client,
                                   confirm_spend=True, output_fetcher=fail_fetch)
        self.assertEqual(first["status"], "KEEP_ACQUISITION_REQUIRED")
        self.assertEqual(client.keep_calls, 1)
        second = keep_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first", client=client,
                                    output_fetcher=self._fetch)
        self.assertEqual(second["status"], "SUCCEEDED")
        self.assertEqual(client.keep_calls, 1)

    def test_ambiguous_keep_is_never_retried_automatically(self):
        transient = ElyumSeedanceError("PROVIDER_TRANSIENT")
        client = self._preview_ready(FakeElyumClient(keep_outcome=transient))
        review_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first",
                             decision="ACCEPT", reason="Owner accepts preview")
        first = keep_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first", client=client,
                                   confirm_spend=True, output_fetcher=self._fetch)
        self.assertEqual(first["status"], "KEEP_AMBIGUOUS")
        self.assertEqual(client.keep_calls, 1)
        with self.assertRaises(ElyumProductionError) as caught:
            keep_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first", client=client,
                               confirm_spend=True, output_fetcher=self._fetch)
        self.assertEqual(caught.exception.failure_class, "ELYUM_KEEP_OUTCOME_AMBIGUOUS")
        self.assertEqual(client.keep_calls, 1)

    def test_reject_then_explicit_kill_is_single_consequence_and_no_redispatch(self):
        client = self._preview_ready()
        reviewed = review_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first",
                                        decision="REJECT", reason="Owner rejects visible drift")
        self.assertEqual(reviewed["status"], "PREVIEW_REJECTED")
        with self.assertRaises(ElyumProductionError) as caught:
            kill_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first", client=client,
                               reason="Rejected preview")
        self.assertEqual(caught.exception.failure_class, "ELYUM_KILL_CONFIRMATION_REQUIRED")
        killed = kill_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first", client=client,
                                    confirm_kill=True, reason="Rejected preview")
        self.assertEqual(killed["status"], "KILLED")
        self.assertEqual(client.kill_calls, 1)
        before_make = len(client.make_calls)
        boundary = execute_elyum_generation(self.runtime.root, "prj_elyum_prod", run_id="run_prod", client=client,
                                            dispatch_authorized=True, preview_fetcher=self._fetch)
        self.assertEqual(boundary["status"], "KILLED")
        self.assertEqual(len(client.make_calls), before_make)
        again = kill_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first", client=client,
                                   confirm_kill=True, reason="Rejected preview")
        self.assertTrue(again["idempotent"])
        self.assertEqual(client.kill_calls, 1)

    def test_ambiguous_kill_is_never_retried_automatically(self):
        transient = ElyumSeedanceError("PROVIDER_TRANSIENT")
        client = self._preview_ready(FakeElyumClient(kill_outcome=transient))
        review_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first",
                             decision="REJECT", reason="Owner rejects preview")
        first = kill_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first", client=client,
                                   confirm_kill=True, reason="Rejected preview")
        self.assertEqual(first["status"], "KILL_AMBIGUOUS")
        self.assertEqual(client.kill_calls, 1)
        with self.assertRaises(ElyumProductionError) as caught:
            kill_elyum_preview(self.runtime.root, "prj_elyum_prod", "req_first", client=client,
                               confirm_kill=True, reason="Rejected preview")
        self.assertEqual(caught.exception.failure_class, "ELYUM_KILL_OUTCOME_AMBIGUOUS")
        self.assertEqual(client.kill_calls, 1)


if __name__ == "__main__":
    unittest.main()

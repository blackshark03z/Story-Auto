from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from PIL import Image

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.full_video_continuity import bind_initial_anchor, bind_previous_accepted_frame
from story_auto.core.full_video_provider import full_video_provider_snapshot
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.render import probe_media, run_render_stages
from story_auto.providers.elyum_seedance import ElyumSeedanceError
from story_auto.providers.elyum_seedance.service import (
    authorize_elyum_replacement,
    execute_elyum_generation,
    keep_elyum_preview,
    kill_elyum_preview,
    review_elyum_preview,
)


FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


class _UatElyumClient:
    provider = "elyum_seedance"

    def __init__(self, *, balance=100, estimate=44, job_id="job_uat", gen_id="gen_uat",
                 preview_url="https://elyum.invalid/preview.mp4",
                 final_url="https://elyum.invalid/final.mp4", wait_transient=False):
        self.balance = balance
        self.estimate = estimate
        self.job_id = job_id
        self.gen_id_value = gen_id
        self.preview_url = preview_url
        self.final_url = final_url
        self.wait_transient = wait_transient
        self.upload_calls = 0
        self.make_calls: list[dict] = []
        self.wait_calls: list[str] = []
        self.keep_calls = 0
        self.kill_calls = 0

    def readiness(self):
        return {"status": "READY", "reason_code": None}

    def account_balance(self):
        return self.balance

    def estimate_video(self, *, model, duration, mode):
        return self.estimate

    def upload_file(self, _path):
        self.upload_calls += 1
        return "https://elyum.invalid/reference.png"

    def make_video(self, **kwargs):
        self.make_calls.append(dict(kwargs))
        return self.job_id, {"jobId": self.job_id}

    def wait(self, job_id, *, timeout_seconds=50, thumbnails=True):
        self.wait_calls.append(job_id)
        if self.wait_transient:
            self.wait_transient = False
            raise ElyumSeedanceError("PROVIDER_TRANSIENT")
        return {"status": "done", "genId": self.gen_id_value,
                "url": self.preview_url, "unlockCredits": 20}

    def keep(self, _gen_id, *, index=0):
        self.keep_calls += 1
        return {"status": "kept", "videoUrl": self.final_url}

    def kill(self, _gen_id, *, index=0, reason=None):
        self.kill_calls += 1
        return {"status": "killed"}

    def job_status(self, _job_id, *, thumbnails=True):
        return {"status": "done", "videoUrl": self.final_url}

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
        value = result.get("videoUrl") if isinstance(result, dict) else None
        return [value] if value else []


@unittest.skipUnless(FFMPEG, "Goal 54 Slice F UAT requires ffmpeg and ffprobe")
class Goal54SliceFOfflineUatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = RuntimeLayout.from_root(self.temp.name).ensure()
        self.config = ProjectConfig(
            "prj_goal54_uat", render_mode="full_video_ai",
            settings={
                "qc_policy": "MANUAL_REVIEW",
                "full_video_provider": "elyum_seedance",
                "elyum": {"model": "seedance-2-fast-i2v", "resolution": "480p",
                          "provider_duration_seconds": 4, "max_credits": 44},
                "render": {"width": 320, "height": 180, "fps": 10},
            },
        )
        self.paths = create_project(self.runtime, self.config, "# Goal 54 UAT\n\n## Narration\n\nTwo-shot bounded UAT.")
        self.run_id = "run_goal54_uat"
        audio_rel = "assets/audio/narration.wav"
        audio = self.paths.artifact_path(audio_rel)
        audio.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=520:sample_rate=48000:duration=8", "-c:a", "pcm_s16le", str(audio)], check=True)
        atomic_write_json(self.paths.artifact_path("output/alignment.json"), {
            "audio_path": audio_rel, "duration_seconds": 8.0,
            "segments": [
                {"segment_id": "seg_1", "start": 0.0, "end": 4.0, "text": "First shot."},
                {"segment_id": "seg_2", "start": 4.0, "end": 8.0, "text": "Second shot."},
            ],
        })
        atomic_write_json(self.paths.artifact_path("output/shot_plan.json"), {
            "shots": [{"shot_id": "sh_0001", "start": 0.0, "end": 4.0},
                      {"shot_id": "sh_0002", "start": 4.0, "end": 8.0}],
        })
        atomic_write_json(self.paths.artifact_path("output/media_plan.json"), {
            "render_mode": "full_video_ai",
            "shots": [
                {"shot_id": "sh_0001", "media_type": "VIDEO", "requirement": "REQUIRED", "fallback_policy": "BLOCK", "image_motion_policy": "NONE"},
                {"shot_id": "sh_0002", "media_type": "VIDEO", "requirement": "REQUIRED", "fallback_policy": "BLOCK", "image_motion_policy": "NONE"},
            ],
        })
        self.requests = [
            {"request_id": "req_1", "purpose": "SHOT", "shot_id": "sh_0001", "media_type": "VIDEO",
             "requirement": "REQUIRED", "provider": "elyum_seedance", "prompt": "Shot one slow push.",
             "fingerprint": "1" * 64, "part_index": 1, "part_count": 1,
             "target_start": 0.0, "target_end": 4.0, "target_duration": 4.0, "aspect_ratio": "16:9"},
            {"request_id": "req_2", "purpose": "SHOT", "shot_id": "sh_0002", "media_type": "VIDEO",
             "requirement": "REQUIRED", "provider": "elyum_seedance", "prompt": "Shot two continuous motion.",
             "fingerprint": "2" * 64, "part_index": 1, "part_count": 1,
             "target_start": 4.0, "target_end": 8.0, "target_duration": 4.0, "aspect_ratio": "16:9"},
        ]
        atomic_write_json(self.paths.artifact_path("output/generation_requests.json"), {
            "schema_version": "story-auto-generation-requests/1.0.0", "project_id": self.config.project_id,
            "prompt_version": "goal54-uat", "full_video_provider_snapshot": full_video_provider_snapshot(self.config.settings),
            "requests": self.requests,
        })
        anchor = Path(self.temp.name) / "anchor.png"
        Image.new("RGB", (320, 180), (40, 60, 80)).save(anchor)
        bind_initial_anchor(self.runtime.root, self.config.project_id, self.run_id, "req_1", anchor,
                            source_provenance="GOAL54_SLICE_F_UAT_CANONICAL_ANCHOR")
        self.video1 = Path(self.temp.name) / "video1.mp4"
        self.video2 = Path(self.temp.name) / "video2.mp4"
        for path, color in ((self.video1, "navy"), (self.video2, "maroon")):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            f"color=c={color}:s=320x180:r=10:d=4.05", "-an", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", str(path)], check=True)

    def tearDown(self):
        self.temp.cleanup()

    def _fetch(self, url: str, destination: Path):
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = self.video2 if "2" in url or "replacement" in url else self.video1
        shutil.copyfile(source, destination)

    def test_two_shot_offline_uat_covers_recovery_replacement_continuity_and_final_render(self):
        first_client = _UatElyumClient(job_id="job_1", gen_id="gen_1",
                                       preview_url="https://elyum.invalid/preview1.mp4",
                                       final_url="https://elyum.invalid/final1.mp4", wait_transient=True)
        first = execute_elyum_generation(self.runtime.root, self.config.project_id, run_id=self.run_id,
                                         request_ids={"req_1"}, client=first_client, dispatch_authorized=True,
                                         preview_fetcher=self._fetch)
        self.assertEqual(first["status"], "WAIT_UNAVAILABLE")
        self.assertEqual(len(first_client.make_calls), 1)

        # Simulate app/process reload: a new client instance must resume the exact saved job.
        reloaded_client = _UatElyumClient(job_id="job_unused", gen_id="gen_1",
                                          preview_url="https://elyum.invalid/preview1.mp4",
                                          final_url="https://elyum.invalid/final1.mp4")
        resumed = execute_elyum_generation(self.runtime.root, self.config.project_id, run_id=self.run_id,
                                           request_ids={"req_1"}, client=reloaded_client, dispatch_authorized=True,
                                           preview_fetcher=self._fetch)
        self.assertEqual(resumed["status"], "PREVIEW_READY")
        self.assertEqual((reloaded_client.upload_calls, len(reloaded_client.make_calls)), (0, 0))
        self.assertEqual(reloaded_client.wait_calls, ["job_1"])
        review_elyum_preview(self.runtime.root, self.config.project_id, "req_1",
                             decision="ACCEPT", reason="UAT shot 1 continuity is acceptable")
        kept1 = keep_elyum_preview(self.runtime.root, self.config.project_id, "req_1",
                                   client=reloaded_client, confirm_spend=True, output_fetcher=self._fetch)
        self.assertEqual(kept1["status"], "SUCCEEDED")
        self.assertEqual(reloaded_client.keep_calls, 1)

        continuity2 = bind_previous_accepted_frame(self.runtime.root, self.config.project_id, self.run_id, "req_2")
        self.assertEqual(continuity2["source_request_id"], "req_1")
        self.assertTrue(continuity2["reference_sha256"])

        # Read-only cost failure must happen before provider upload/create and remain recoverable.
        poor_client = _UatElyumClient(balance=30, estimate=44)
        blocked = execute_elyum_generation(self.runtime.root, self.config.project_id, run_id=self.run_id,
                                           request_ids={"req_2"}, client=poor_client, dispatch_authorized=True,
                                           preview_fetcher=self._fetch)
        self.assertEqual(blocked["status"], "CREDIT_BLOCKED")
        self.assertEqual((poor_client.upload_calls, len(poor_client.make_calls)), (0, 0))

        second_client = _UatElyumClient(job_id="job_2a", gen_id="gen_2a",
                                        preview_url="https://elyum.invalid/preview2.mp4",
                                        final_url="https://elyum.invalid/final2.mp4")
        second = execute_elyum_generation(self.runtime.root, self.config.project_id, run_id=self.run_id,
                                          request_ids={"req_2"}, client=second_client, dispatch_authorized=True,
                                          preview_fetcher=self._fetch)
        self.assertEqual(second["status"], "PREVIEW_READY")
        review_elyum_preview(self.runtime.root, self.config.project_id, "req_2",
                             decision="REJECT", reason="UAT intentionally exercises replacement boundary")
        killed = kill_elyum_preview(self.runtime.root, self.config.project_id, "req_2", client=second_client,
                                    confirm_kill=True, reason="UAT rejected preview")
        self.assertEqual(killed["status"], "KILLED")
        before_replacement = read_json(self.paths.artifact_path("output/generation_manifest.json"))["requests"][1]
        self.assertEqual((before_replacement["provider_submissions"], len(before_replacement["attempts"])), (1, 1))

        authorized = authorize_elyum_replacement(self.runtime.root, self.config.project_id, "req_2",
                                                 reason="UAT explicit one-shot replacement", confirm_replace=True)
        self.assertEqual(authorized["status"], "REPLACEMENT_AUTHORIZED")
        replacement_client = _UatElyumClient(job_id="job_2b", gen_id="gen_2b",
                                             preview_url="https://elyum.invalid/replacement2.mp4",
                                             final_url="https://elyum.invalid/final2.mp4")
        replacement = execute_elyum_generation(self.runtime.root, self.config.project_id, run_id=self.run_id,
                                               request_ids={"req_2"}, client=replacement_client, dispatch_authorized=True,
                                               preview_fetcher=self._fetch)
        self.assertEqual(replacement["status"], "PREVIEW_READY")
        review_elyum_preview(self.runtime.root, self.config.project_id, "req_2",
                             decision="ACCEPT", reason="UAT replacement is acceptable")
        kept2 = keep_elyum_preview(self.runtime.root, self.config.project_id, "req_2",
                                   client=replacement_client, confirm_spend=True, output_fetcher=self._fetch)
        self.assertEqual(kept2["status"], "SUCCEEDED")

        manifest = read_json(self.paths.artifact_path("output/generation_manifest.json"))
        by_id = {entry["request_id"]: entry for entry in manifest["requests"]}
        self.assertEqual((by_id["req_1"]["provider_submissions"], len(by_id["req_1"]["attempts"])), (1, 1))
        self.assertEqual((by_id["req_2"]["provider_submissions"], len(by_id["req_2"]["attempts"])), (2, 2))
        self.assertNotEqual(by_id["req_2"]["attempts"][0]["client_ref"], by_id["req_2"]["attempts"][1]["client_ref"])
        self.assertEqual(by_id["req_2"]["attempts"][1]["replacement_of_attempt"], 1)
        for request_id in ("req_1", "req_2"):
            selected = by_id[request_id]["selected_asset"]
            self.assertEqual(selected["production_qc"], "OWNER_ACCEPTED")
            self.assertEqual(sha256_file(self.paths.artifact_path(selected["path"])), selected["sha256"])
            self.assertEqual(selected["source_preview_sha256"], by_id[request_id]["attempts"][-1]["preview_review"]["preview_sha256"])

        rendered = run_render_stages(self.runtime.root, self.config.project_id)
        self.assertEqual(rendered["actions"]["final_render"], "RUN")
        final_path = self.paths.artifact_path("output/final.mp4")
        self.assertTrue(final_path.is_file())
        media = probe_media(final_path)
        self.assertEqual((media["video"]["width"], media["video"]["height"]), (320, 180))
        self.assertEqual(len(media["audio"]), 1)
        self.assertGreaterEqual(float(media["duration_seconds"]), 7.8)
        frozen_manifest_sha = sha256_file(self.paths.artifact_path("output/generation_manifest.json"))
        second_render = run_render_stages(self.runtime.root, self.config.project_id)
        self.assertEqual(second_render["actions"]["final_render"], "SKIP")
        self.assertEqual(sha256_file(self.paths.artifact_path("output/generation_manifest.json")), frozen_manifest_sha)


if __name__ == "__main__":
    unittest.main()

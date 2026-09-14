from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from PIL import Image

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.full_video_continuity import (FullVideoContinuityError, begin_continuity_run,
    bind_initial_anchor, bind_previous_accepted_frame, reconcile_continuity_run,
    resolve_continuity_reference)
from story_auto.core.full_video_provider import full_video_provider_snapshot
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project


FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


class FullVideoContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = RuntimeLayout.from_root(self.temp.name).ensure()
        self.paths = create_project(self.runtime, ProjectConfig("prj_continuity", render_mode="full_video_ai"))
        self.requests = {
            "schema_version": "story-auto-generation-requests/1.0.0",
            "project_id": "prj_continuity",
            "prompt_version": "test",
            "full_video_provider_snapshot": full_video_provider_snapshot({"full_video_provider": "elyum_seedance"}),
            "requests": [
                self._request("req_first", "a" * 64, 0.0, 4.0, 1),
                self._request("req_second", "b" * 64, 4.0, 8.0, 2),
            ],
        }
        atomic_write_json(self.paths.artifact_path("output/generation_requests.json"), self.requests)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _request(request_id, fingerprint, start, end, part):
        return {"request_id": request_id, "purpose": "SHOT", "shot_id": f"sh_{part:04d}",
                "media_type": "VIDEO", "provider": "elyum_seedance", "fingerprint": fingerprint,
                "target_start": start, "target_end": end, "target_duration": end - start,
                "part_index": 1, "part_count": 1}

    def _anchor(self, name="anchor.png"):
        path = Path(self.temp.name) / name
        Image.new("RGB", (320, 180), (40, 60, 80)).save(path)
        return path

    def _video(self, relative, color="navy"):
        path = self.paths.artifact_path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"color=c={color}:s=320x180:r=10:d=4", "-an", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(path)], check=True)
        return path

    def _accepted_manifest(self, video_path):
        relative = video_path.relative_to(self.paths.root).as_posix()
        return {"schema_version": "story-auto-generation-manifest/1.0.0", "project_id": "prj_continuity",
                "requests": [{"request_id": "req_first", "request_identity_sha256": "a" * 64,
                    "related_identity": "sh_0001", "media_type": "VIDEO", "provider": "elyum_seedance",
                    "status": "SUCCEEDED", "provider_submissions": 1, "attempts": [{"attempt": 1, "status": "SUCCEEDED"}],
                    "selected_asset": {"path": relative, "sha256": sha256_file(video_path), "attempt": 1,
                                       "source_provider_attempt": 1, "production_qc": "OWNER_ACCEPTED"}}]}

    def test_initial_anchor_is_exact_run_scoped_and_idempotent(self):
        anchor = self._anchor()
        started = begin_continuity_run(self.runtime.root, "prj_continuity", "run_alpha")
        self.assertEqual(started["status"], "STARTED")
        first = bind_initial_anchor(self.runtime.root, "prj_continuity", "run_alpha", "req_first", anchor,
                                    source_provenance="OWNER_CANONICAL_ANCHOR")
        second = bind_initial_anchor(self.runtime.root, "prj_continuity", "run_alpha", "req_first", anchor,
                                     source_provenance="OWNER_CANONICAL_ANCHOR")
        self.assertEqual(first["source_kind"], "INITIAL_ANCHOR")
        self.assertEqual(first["source_provenance"], "OWNER_CANONICAL_ANCHOR")
        self.assertEqual(first["reference_sha256"], sha256_file(anchor))
        self.assertTrue(second["idempotent"])
        begin_continuity_run(self.runtime.root, "prj_continuity", "run_beta")
        with self.assertRaises(FullVideoContinuityError) as caught:
            resolve_continuity_reference(self.runtime.root, "prj_continuity", "run_beta", "req_first")
        self.assertEqual(caught.exception.failure_class, "CONTINUITY_REFERENCE_MISSING")
        resolved = resolve_continuity_reference(self.runtime.root, "prj_continuity", "run_alpha", "req_first")
        self.assertEqual(resolved["run_id"], "run_alpha")

    def test_same_run_cannot_silently_cross_generation_request_snapshot(self):
        begin_continuity_run(self.runtime.root, "prj_continuity", "run_alpha")
        value = read_json(self.paths.artifact_path("output/generation_requests.json"))
        value["requests"][0]["prompt"] = "changed plan"
        atomic_write_json(self.paths.artifact_path("output/generation_requests.json"), value)
        with self.assertRaises(FullVideoContinuityError) as caught:
            begin_continuity_run(self.runtime.root, "prj_continuity", "run_alpha")
        self.assertEqual(caught.exception.failure_class, "CONTINUITY_RUN_PLAN_MISMATCH")

    def test_initial_anchor_is_first_request_only_and_late_binding_is_blocked(self):
        anchor = self._anchor()
        with self.assertRaises(FullVideoContinuityError) as caught:
            bind_initial_anchor(self.runtime.root, "prj_continuity", "run_alpha", "req_second", anchor,
                                source_provenance="OWNER_CANONICAL_ANCHOR")
        self.assertEqual(caught.exception.failure_class, "CONTINUITY_INITIAL_ANCHOR_TARGET_INVALID")
        manifest = {"schema_version": "story-auto-generation-manifest/1.0.0", "project_id": "prj_continuity",
                    "requests": [{"request_id": "req_first", "provider_submissions": 1,
                                  "attempts": [{"attempt": 1, "provider_job_id": "job_1", "dispatch_confirmed": True}]}]}
        atomic_write_json(self.paths.artifact_path("output/generation_manifest.json"), manifest)
        with self.assertRaises(FullVideoContinuityError) as caught:
            bind_initial_anchor(self.runtime.root, "prj_continuity", "run_alpha", "req_first", anchor,
                                source_provenance="OWNER_CANONICAL_ANCHOR")
        self.assertEqual(caught.exception.failure_class, "CONTINUITY_TARGET_ALREADY_DISPATCHED")

    @unittest.skipUnless(FFMPEG, "FFmpeg integration requires ffmpeg and ffprobe")
    def test_previous_owner_accepted_video_yields_hash_bound_frame_and_rejection_invalidates_it(self):
        video = self._video("assets/video/req_first/attempt_001.mp4")
        atomic_write_json(self.paths.artifact_path("output/generation_manifest.json"), self._accepted_manifest(video))
        bound = bind_previous_accepted_frame(self.runtime.root, "prj_continuity", "run_alpha", "req_second")
        self.assertEqual(bound["source_request_id"], "req_first")
        self.assertEqual(bound["frame_timestamp_seconds"], 3.5)
        self.assertEqual(bound["source_quality_state"], "OWNER_ACCEPTED")
        self.assertTrue(self.paths.artifact_path(bound["reference_path"]).is_file())
        resolved = resolve_continuity_reference(self.runtime.root, "prj_continuity", "run_alpha", "req_second")
        self.assertEqual(resolved["reference_sha256"], bound["reference_sha256"])

        manifest = read_json(self.paths.artifact_path("output/generation_manifest.json"))
        manifest["requests"][0]["status"] = "FAILED_RETRYABLE"
        manifest["requests"][0]["selected_asset"]["production_qc"] = "REJECTED"
        atomic_write_json(self.paths.artifact_path("output/generation_manifest.json"), manifest)
        with self.assertRaises(FullVideoContinuityError) as caught:
            resolve_continuity_reference(self.runtime.root, "prj_continuity", "run_alpha", "req_second")
        self.assertEqual(caught.exception.failure_class, "CONTINUITY_SOURCE_NOT_ACCEPTED")
        reconciled = reconcile_continuity_run(self.runtime.root, "prj_continuity", "run_alpha")
        self.assertEqual(reconciled["status"], "INVALIDATED")
        state = read_json(self.paths.artifact_path("output/full_video_continuity.json"))
        self.assertEqual(state["runs"]["run_alpha"]["bindings"]["req_second"][-1]["status"], "INVALIDATED")

    @unittest.skipUnless(FFMPEG, "FFmpeg integration requires ffmpeg and ffprobe")
    def test_replacement_can_rebind_before_target_dispatch_but_not_after(self):
        first_video = self._video("assets/video/req_first/attempt_001.mp4", "navy")
        atomic_write_json(self.paths.artifact_path("output/generation_manifest.json"), self._accepted_manifest(first_video))
        first = bind_previous_accepted_frame(self.runtime.root, "prj_continuity", "run_alpha", "req_second")

        replacement = self._video("assets/video/req_first/attempt_002.mp4", "red")
        manifest = self._accepted_manifest(replacement)
        manifest["requests"][0]["selected_asset"]["attempt"] = 2
        manifest["requests"][0]["selected_asset"]["source_provider_attempt"] = 2
        atomic_write_json(self.paths.artifact_path("output/generation_manifest.json"), manifest)
        second = bind_previous_accepted_frame(self.runtime.root, "prj_continuity", "run_alpha", "req_second")
        self.assertEqual(second["binding_revision"], 2)
        self.assertNotEqual(first["reference_sha256"], second["reference_sha256"])
        state = read_json(self.paths.artifact_path("output/full_video_continuity.json"))
        self.assertEqual(state["runs"]["run_alpha"]["bindings"]["req_second"][0]["status"], "SUPERSEDED")

        third_video = self._video("assets/video/req_first/attempt_003.mp4", "green")
        manifest = self._accepted_manifest(third_video)
        manifest["requests"][0]["selected_asset"]["attempt"] = 3
        manifest["requests"].append({"request_id": "req_second", "provider_submissions": 1,
                                     "attempts": [{"attempt": 1, "provider_job_id": "provider_job_2",
                                                   "dispatch_confirmed": True}]})
        atomic_write_json(self.paths.artifact_path("output/generation_manifest.json"), manifest)
        with self.assertRaises(FullVideoContinuityError) as caught:
            bind_previous_accepted_frame(self.runtime.root, "prj_continuity", "run_alpha", "req_second")
        self.assertEqual(caught.exception.failure_class, "CONTINUITY_TARGET_ALREADY_DISPATCHED")

    @unittest.skipUnless(FFMPEG, "FFmpeg integration requires ffmpeg and ffprobe")
    def test_plan_change_marks_old_run_stale_instead_of_reusing_frame(self):
        video = self._video("assets/video/req_first/attempt_001.mp4")
        atomic_write_json(self.paths.artifact_path("output/generation_manifest.json"), self._accepted_manifest(video))
        bind_previous_accepted_frame(self.runtime.root, "prj_continuity", "run_alpha", "req_second")
        value = read_json(self.paths.artifact_path("output/generation_requests.json"))
        value["requests"][1]["fingerprint"] = "c" * 64
        atomic_write_json(self.paths.artifact_path("output/generation_requests.json"), value)
        result = reconcile_continuity_run(self.runtime.root, "prj_continuity", "run_alpha")
        self.assertEqual(result["status"], "STALE_PLAN")
        with self.assertRaises(FullVideoContinuityError) as caught:
            resolve_continuity_reference(self.runtime.root, "prj_continuity", "run_alpha", "req_second")
        self.assertEqual(caught.exception.failure_class, "CONTINUITY_RUN_PLAN_MISMATCH")


if __name__ == "__main__":
    unittest.main()

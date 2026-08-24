from __future__ import annotations

import tempfile
import unittest
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.render.plan import resolve_render_plan
from story_auto.core.visual.quality import MediaQualityError, validate_production_qc
from story_auto.providers.flow.postprocess import (
    FlowImagePostprocessError,
    FlowVideoPostprocessError,
    process_flow_image,
    process_flow_video,
    supported_profiles,
)
from story_auto.providers.flow.service import (
    FlowError,
    FlowExecutor,
    adopt_exact_flow_recovery,
    adopt_manual_recovery,
    execute_generation,
    invalidate_asset_attribution,
    queue_regeneration,
    create_local_video_mark_removal,
    reconcile_local_assets,
    reuse_exact_flow_asset,
    review_production_asset,
)
from story_auto.providers.flow.session import FlowCapabilities


QC_FIELDS = (
    "SKIN_REALISM", "LIGHTING_NATURALISM", "MATERIAL_REALISM",
    "COMPOSITION_NATURALISM", "AI_POLISH", "CONTINUITY", "TECHNICAL_VALIDITY",
)


def _report(*, visible=False):
    return {"results": {key: "PASS" for key in QC_FIELDS},
            "visible_provider_watermark": visible, "reviewer": "test operator"}


class FlowImagePostprocessTests(unittest.TestCase):
    def _project(self, root, requests):
        runtime = RuntimeLayout.from_root(root)
        config = ProjectConfig("prj_flow_postprocess")
        paths = create_project(runtime, config)
        atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {"status": "APPROVED"}})
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": requests})
        return runtime, config, paths

    @staticmethod
    def _request(request_id="ref", *, purpose="REFERENCE", depends_on=None, media_type="IMAGE"):
        return {"request_id": request_id, "fingerprint": request_id + "-identity", "purpose": purpose,
                "shot_id": "sh_0001" if purpose == "SHOT" else None, "media_type": media_type,
                "prompt": request_id, "depends_on": depends_on or [], "provider": "google_flow",
                "output_count": 1, "execution_tier": "STANDARD_PRODUCTION"}

    @staticmethod
    def _write_flow_image(path: Path, *, variant=0, size=(1280, 720)):
        image = Image.new("RGB", size, (35 + variant * 20, 65, 95))
        draw = ImageDraw.Draw(image)
        step = 19 + variant * 7
        for offset in range(0, size[0], step):
            draw.line((offset, 0, (offset + 300 + variant * 31) % size[0], size[1]),
                      fill=(100 + variant * 30, 130, 80), width=3)
        if size == (1280, 720):
            draw.polygon([(1160, 573), (1187, 599), (1160, 625), (1133, 599)], fill="white")
        elif size == (1376, 768):
            draw.polygon([(1278, 644), (1307, 671), (1278, 698), (1249, 671)], fill="white")
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, "PNG")

    @classmethod
    def _write_flow_video(cls, path: Path, *, size=(1280, 720)):
        poster = path.with_suffix(".source.png")
        cls._write_flow_image(poster, size=size)
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-i", str(poster),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-t", "2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
        ], check=True)
        poster.unlink()

    def _executor(self, calls, *, size=(1280, 720)):
        def generate(request, refs, path):
            calls.append((request["request_id"], list(refs)))
            self._write_flow_image(path, variant=len(calls) - 1, size=size)
            return path
        return FlowExecutor(FlowCapabilities(True, True, True, True, True, True), generate)

    def _video_executor(self, calls, *, size=(1280, 720)):
        def generate(request, refs, path):
            calls.append((request["request_id"], list(refs)))
            self._write_flow_video(path, size=size)
            return path
        return FlowExecutor(FlowCapabilities(True, True, True, True, True, True), generate)

    def test_supported_profiles_create_distinct_valid_derivatives(self):
        self.assertEqual(set(supported_profiles()), {"flow-sparkle-1280x720-v1", "flow-sparkle-1376x768-v1"})
        with tempfile.TemporaryDirectory() as root:
            for size in ((1280, 720), (1376, 768)):
                raw = Path(root) / f"raw-{size[0]}.png"
                clean = Path(root) / f"clean-{size[0]}.png"
                self._write_flow_image(raw, size=size)
                raw_before = sha256_file(raw)
                result = process_flow_image(raw, clean)
                self.assertEqual(sha256_file(raw), raw_before)
                self.assertNotEqual(result["source_sha256"], result["output_sha256"])
                self.assertEqual((result["output_metadata"]["width"], result["output_metadata"]["height"]), size)
                self.assertEqual(len(result["mask_sha256"]), 64)

    def test_supported_video_profile_creates_a_distinct_valid_derivative(self):
        with tempfile.TemporaryDirectory() as root:
            raw = Path(root) / "raw.mp4"; clean = Path(root) / "clean.mp4"
            self._write_flow_video(raw)
            raw_before = sha256_file(raw)
            result = process_flow_video(raw, clean)
            self.assertEqual(sha256_file(raw), raw_before)
            self.assertNotEqual(result["source_sha256"], result["output_sha256"])
            self.assertEqual((result["output_metadata"]["width"], result["output_metadata"]["height"]), (1280, 720))
            self.assertLess(abs(result["output_metadata"]["duration_seconds"] - result["source_metadata"]["duration_seconds"]), .05)
            self.assertEqual(result["processor_name"], "flow-video-removelogo")

    def test_production_image_preserves_raw_and_selects_lineaged_derivative(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, [self._request()])
            calls = []
            result = execute_generation(runtime.root, config.project_id, executor=self._executor(calls), execute=True)
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            attempt, selected, processing = entry["attempts"][0], entry["selected_asset"], entry["postprocess_attempts"][0]
            self.assertEqual(result["new_submissions"], 1)
            self.assertEqual((attempt["status"], processing["status"], entry["status"]), ("SUCCEEDED", "SUCCEEDED", "QC_PENDING"))
            self.assertNotEqual(attempt["asset_path"], selected["path"])
            self.assertNotEqual(attempt["asset_sha256"], selected["sha256"])
            self.assertEqual((selected["source_provider_attempt"], selected["source_sha256"]), (1, attempt["asset_sha256"]))
            self.assertEqual(sha256_file(paths.artifact_path(attempt["asset_path"])), attempt["asset_sha256"])

    def test_production_video_preserves_raw_and_selects_clean_lineaged_derivative(self):
        with tempfile.TemporaryDirectory() as root:
            request = self._request("video", purpose="SHOT", media_type="VIDEO")
            request["motion_risk_analysis"] = {"anatomy_risk": "LOW"}
            runtime, config, paths = self._project(root, [request])
            calls = []
            result = execute_generation(runtime.root, config.project_id, executor=self._video_executor(calls), execute=True)
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            attempt, selected, processing = entry["attempts"][0], entry["selected_asset"], entry["video_postprocess_attempts"][0]
            self.assertEqual(result["new_submissions"], 1)
            self.assertEqual((attempt["status"], processing["status"], entry["status"]), ("SUCCEEDED", "SUCCEEDED", "QC_PENDING"))
            self.assertTrue(attempt["production_video_postprocess_required"])
            self.assertNotEqual((attempt["asset_path"], attempt["asset_sha256"]), (selected["path"], selected["sha256"]))
            self.assertEqual((selected["source_provider_attempt"], selected["source_sha256"], selected["temporal_qc"]),
                             (1, attempt["asset_sha256"], "PENDING"))
            self.assertEqual(sha256_file(paths.artifact_path(attempt["asset_path"])), attempt["asset_sha256"])

    def test_missing_derivative_rebuilds_locally_without_provider_submission(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, [self._request()])
            calls = []; executor = self._executor(calls)
            execute_generation(runtime.root, config.project_id, executor=executor, execute=True)
            unchanged = execute_generation(runtime.root, config.project_id, executor=executor, execute=True)
            self.assertEqual((unchanged["new_submissions"], len(calls)), (0, 1))
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            paths.artifact_path(entry["selected_asset"]["path"]).unlink()
            self.assertEqual(reconcile_local_assets(runtime.root, config.project_id), {"ref"})
            result = execute_generation(runtime.root, config.project_id, executor=executor, execute=True)
            repaired = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((result["new_submissions"], len(calls), len(repaired["attempts"])), (0, 1, 1))
            self.assertEqual(repaired["postprocess_attempts"][-1]["status"], "SUCCEEDED")
            self.assertTrue(paths.artifact_path(repaired["selected_asset"]["path"]).is_file())

    def test_unsupported_geometry_fails_closed_and_retries_only_local_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, [self._request()])
            calls = []; executor = self._executor(calls, size=(640, 480))
            first = execute_generation(runtime.root, config.project_id, executor=executor, execute=True)
            queue_regeneration(runtime.root, config.project_id, "ref", reason="operator retry")
            second = execute_generation(runtime.root, config.project_id, executor=executor, execute=True)
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((first["new_submissions"], second["new_submissions"], len(calls)), (0, 0, 1))
            self.assertEqual((entry["attempts"][0]["status"], len(entry["attempts"])), ("SUCCEEDED", 1))
            self.assertEqual(entry["failure_class"], "FLOW_IMAGE_POSTPROCESS_UNSUPPORTED_GEOMETRY")
            self.assertEqual(len(entry["postprocess_attempts"]), 2)
            self.assertEqual(entry["operator_actions"][-1]["action"], "RETRY_LOCAL_POSTPROCESS")
            self.assertNotIn("selected_asset", entry)

    def test_manual_recovery_preserves_raw_and_selects_clean_derivative(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, [self._request()])
            def timeout(*_):
                raise FlowError("FLOW_TIMEOUT")
            execute_generation(runtime.root, config.project_id,
                               executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), timeout),
                               execute=True)
            recovered = Path(root) / "recovered.png"; self._write_flow_image(recovered)
            raw_sha = sha256_file(recovered)
            selected = adopt_exact_flow_recovery(runtime.root, config.project_id, "ref", recovered,
                                                 provider_identity={"asset_id": "operator-observed-flow-tile"},
                                                 evidence="exact visible Flow result", settings={"source": "operator"})
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            attempt = entry["attempts"][-1]
            self.assertEqual((attempt["status"], attempt["asset_sha256"]), ("SUCCEEDED", raw_sha))
            self.assertNotEqual(selected["sha256"], raw_sha)
            self.assertEqual(selected["source_sha256"], raw_sha)

    def test_wrong_mapping_is_invalidated_without_deleting_raw_or_clean_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, [self._request()])
            execute_generation(runtime.root, config.project_id, executor=self._executor([]), execute=True)
            entry = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            raw_path = paths.artifact_path(entry["attempts"][0]["asset_path"])
            clean_path = paths.artifact_path(entry["selected_asset"]["path"])
            raw_sha, clean_sha = sha256_file(raw_path), sha256_file(clean_path)
            event = invalidate_asset_attribution(runtime.root, config.project_id, "ref")
            repaired = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            self.assertEqual((sha256_file(raw_path), sha256_file(clean_path)), (raw_sha, clean_sha))
            self.assertEqual((event["reason"], repaired["failure_class"]),
                             ("OUTPUT_ATTRIBUTION_INVALID", "OUTPUT_ATTRIBUTION_INVALID"))
            self.assertEqual(repaired["attempts"][0]["attribution_status"], "INVALIDATED")
            self.assertNotIn("selected_asset", repaired)

    def test_reference_dependency_receives_clean_selected_derivative(self):
        with tempfile.TemporaryDirectory() as root:
            requests = [self._request(), self._request("shot", purpose="SHOT", depends_on=["ref"])]
            runtime, config, paths = self._project(root, requests)
            calls = []; executor = self._executor(calls)
            execute_generation(runtime.root, config.project_id, executor=executor, execute=True, request_ids={"ref"})
            review_production_asset(runtime.root, config.project_id, "ref", _report())
            execute_generation(runtime.root, config.project_id, executor=executor, execute=True, request_ids={"shot"})
            entries = {item["request_id"]: item for item in read_json(paths.artifact_path("output/generation_manifest.json"))["requests"]}
            selected = entries["ref"]["selected_asset"]
            self.assertEqual(Path(calls[1][1][0]), paths.artifact_path(selected["path"]))
            self.assertEqual(entries["shot"]["reference_asset_hashes"], [selected["sha256"]])
            self.assertNotEqual(selected["sha256"], entries["ref"]["attempts"][0]["asset_sha256"])

    def test_exact_reuse_accepts_raw_to_derivative_lineage_and_requires_fresh_qc(self):
        with tempfile.TemporaryDirectory() as root:
            runtime, config, paths = self._project(root, [self._request()])
            execute_generation(runtime.root, config.project_id, executor=self._executor([]), execute=True)
            requests = read_json(paths.artifact_path("output/generation_requests.json"))
            requests["requests"].append(self._request("revised", purpose="SHOT"))
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), requests)
            selected = reuse_exact_flow_asset(runtime.root, config.project_id, "ref", "revised",
                                              attribution="reuse clean exact image under revised intent")
            self.assertEqual(selected["production_qc"], "PENDING")
            self.assertEqual(selected["source_lineage"]["lineage_kind"], "RAW_TO_DERIVATIVE")

    def test_visible_provider_watermark_rejects_every_media_type(self):
        for media_type in ("IMAGE", "VIDEO"):
            with self.subTest(media_type=media_type), self.assertRaises(MediaQualityError) as error:
                validate_production_qc(_report(visible=True), provider="google_flow", media_type=media_type)
            self.assertEqual(error.exception.failure_class, "VISIBLE_PROVIDER_WATERMARK")

    def test_video_mark_removal_is_one_bounded_local_derivative(self):
        with tempfile.TemporaryDirectory() as root:
            request = self._request("video", purpose="SHOT", media_type="VIDEO")
            runtime, config, paths = self._project(root, [request])
            rel = "assets/video/video/attempt_001.mp4"; source = paths.artifact_path(rel)
            self._write_flow_video(source); digest = sha256_file(source)
            from story_auto.providers.flow.validation import validate_video
            metadata = validate_video(source)
            rejection = {"reviewed_at": "2026-08-24T00:00:00+00:00", "status": "REJECTED",
                         "failure_class": "VISIBLE_PROVIDER_WATERMARK", "report": _report(visible=True),
                         "selected_asset_path": rel, "selected_asset_sha256": digest}
            selected = {"path": rel, "sha256": digest, "attempt": 1, "metadata": metadata,
                        "production_qc": "REJECTED"}
            entry = {"request_id": "video", "request_identity_sha256": request["fingerprint"],
                     "media_type": "VIDEO", "provider": "google_flow", "status": "FAILED_RETRYABLE",
                     "failure_class": "VISIBLE_PROVIDER_WATERMARK", "provider_submissions": 1,
                     "attempts": [{"attempt": 1, "status": "SUCCEEDED", "attribution_state": "CONFIRMED",
                                   "asset_path": rel, "asset_sha256": digest}], "selected_asset": selected,
                     "quality_reviews": [rejection]}
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),
                              {"schema_version": "story-auto-generation-manifest/1.0.0",
                               "project_id": config.project_id, "requests": [entry]})
            result = create_local_video_mark_removal(runtime.root, config.project_id, "video",
                                                     expected_source_sha256=digest)
            saved = read_json(paths.artifact_path("output/generation_manifest.json"))["requests"][0]
            derived = saved["selected_asset"]
            self.assertEqual((saved["provider_submissions"], len(saved["attempts"]), saved["status"]), (1, 1, "QC_PENDING"))
            self.assertEqual((derived["parent_asset_sha256"], derived["production_qc"], derived["temporal_qc"]),
                             (digest, "PENDING", "PENDING"))
            self.assertEqual(saved["video_mark_removals"][0]["source_selected_asset"], selected)
            self.assertEqual(result["provider_submissions"], 1)
            self.assertTrue(paths.artifact_path(derived["path"]).is_file())
            with self.assertRaisesRegex(FlowError, "VIDEO_MARK_REMOVAL_NOT_ELIGIBLE"):
                create_local_video_mark_removal(runtime.root, config.project_id, "video",
                                                expected_source_sha256=digest)

    def test_render_plan_resolves_exact_clean_selected_path_and_hash(self):
        with tempfile.TemporaryDirectory() as root:
            request = self._request("shot", purpose="SHOT")
            runtime, config, paths = self._project(root, [request])
            execute_generation(runtime.root, config.project_id, executor=self._executor([]), execute=True)
            report = _report(); report["alignment_classification"] = "PASS_DIRECT"
            review_production_asset(runtime.root, config.project_id, "shot", report)
            manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
            selected = manifest["requests"][0]["selected_asset"]
            plan = resolve_render_plan(
                project_id=config.project_id, project_root=paths.root, render_mode="hybrid_hook",
                alignment={"duration_seconds": 2.0},
                shot_plan={"shots": [{"shot_id": "sh_0001", "start": 0.0, "end": 2.0}]},
                media_plan={"shots": [{"shot_id": "sh_0001", "media_type": "IMAGE",
                                         "requirement": "REQUIRED", "fallback_policy": "BLOCK"}]},
                generation_requests={"requests": [request]}, generation_manifest=manifest,
            )
            self.assertEqual((plan["segments"][0]["source_asset"], plan["segments"][0]["source_hash"]),
                             (selected["path"], selected["sha256"]))
            self.assertNotEqual(selected["path"], manifest["requests"][0]["attempts"][0]["asset_path"])


if __name__ == "__main__":
    unittest.main()

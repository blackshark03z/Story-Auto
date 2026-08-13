from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from PIL import Image

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.render import (MediaTarget, RenderPlanError, compile_hold, compile_image, compile_video,
                                    compose, probe_media, resolve_render_plan, transition_output_durations,
                                    validate_video, run_render_stages)
from story_auto.core.subtitles import build_subtitles


FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def run(*args: str) -> None:
    subprocess.run(list(args), capture_output=True, text=True, check=True)


@unittest.skipUnless(FFMPEG, "FFmpeg integration requires ffmpeg and ffprobe")
class RenderMediaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_natural_soft_finishing_remains_valid_and_bounded(self) -> None:
        source=self.root/"natural.png"; output=self.root/"natural.mp4"
        Image.new("RGB",(640,360),(180,140,120)).save(source)
        metadata=compile_image(source,output,duration=.5,motion="STATIC",target=MediaTarget(320,180,10),finishing_profile="NATURAL_SOFT")
        self.assertEqual((metadata["video"]["width"],metadata["video"]["height"]),(320,180))

    def image(self, name: str = "source.png") -> Path:
        path = self.root / name
        Image.new("RGB", (640, 480), (31, 72, 110)).save(path)
        return path

    def audio(self, name: str, duration: float, frequency: int) -> Path:
        path = self.root / name
        run("ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
            "-c:a", "pcm_s16le", str(path))
        return path

    def test_image_motion_modes_create_exact_silent_clips(self) -> None:
        target = MediaTarget(320, 180, 10)
        for motion in ("STATIC", "SLOW_PUSH", "SLOW_PAN"):
            output = self.root / f"{motion}.mp4"
            compile_image(self.image(f"{motion}.png"), output, duration=.6, motion=motion, target=target)
            metadata = validate_video(output, target=target, silent=True, expected_duration=.6)
            self.assertEqual(metadata["video"]["pixel_format"], "yuv420p")

    def test_jpeg_payload_with_png_suffix_still_normalizes_pixel_format(self) -> None:
        source = self.root / "flow-image.png"
        Image.new("RGB", (1376, 768), (31, 72, 110)).save(source, format="JPEG")
        output = self.root / "flow-image.mp4"
        metadata = compile_image(source, output, duration=.4, motion="SLOW_PAN", target=MediaTarget(320, 180, 10))
        self.assertEqual(metadata["video"]["pixel_format"], "yuv420p")

    def test_720p_video_normalizes_to_1080p_and_removes_audio(self) -> None:
        source = self.root / "flow-720p.mp4"
        run("ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=navy:s=1280x720:r=30:d=0.5",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source))
        output = self.root / "normalized.mp4"
        metadata = compile_video(source, output, duration=.4, short_policy="BLOCK", target=MediaTarget())
        self.assertEqual((metadata["video"]["width"], metadata["video"]["height"]), (1920, 1080))
        self.assertEqual(metadata["audio"], [])

    def test_hold_and_hybrid_compositor_with_subtitles_and_bgm(self) -> None:
        target = MediaTarget(320, 180, 10)
        segments = [
            {"target_duration": .4, "transition": {"type": "CROSSFADE", "duration": .1}},
            {"target_duration": .4, "transition": {"type": "CROSSFADE", "duration": .1}},
            {"target_duration": .4, "transition": {"type": "CUT", "duration": 0}},
        ]
        compile_durations, final_duration = transition_output_durations(segments)
        clips = []
        for index, duration in enumerate(compile_durations):
            clip = self.root / f"hold-{index}.mp4"
            compile_hold(clip, duration=duration, color=("red", "green", "blue")[index], target=target)
            clips.append(clip)
        alignment = {"duration_seconds": final_duration, "segments": [
            {"start": 0.0, "end": .6, "text": "Readable first subtitle."},
            {"start": .6, "end": 1.2, "text": "Readable second subtitle."},
        ]}
        srt, ass = self.root / "subtitles.srt", self.root / "subtitles.ass"
        build_subtitles(alignment, srt, ass, width=20, font_size=24)
        style_line=next(line for line in ass.read_text(encoding="utf-8").splitlines() if line.startswith("Style: Default"))
        self.assertIn(",90,260,54,1",style_line)
        narration = self.audio("narration.wav", final_duration, 700)
        bgm = self.audio("bgm.wav", .3, 220)
        output = self.root / "final.mp4"
        metadata = compose(clips=clips, segments=segments, narration=narration, output=output,
                           master_duration=final_duration, subtitles_ass=ass, bgm=bgm,
                           bgm_volume=.08, target=target)
        self.assertTrue(srt.read_text(encoding="utf-8").startswith("1\n00:00:00,000"))
        self.assertEqual(len(metadata["audio"]), 1)
        self.assertAlmostEqual(metadata["duration_seconds"], 1.2, delta=.12)

    def test_probe_and_duration_math_reject_invalid_overlap(self) -> None:
        output = self.root / "hold.mp4"
        compile_hold(output, duration=.4, target=MediaTarget(320, 180, 10))
        self.assertEqual(probe_media(output)["video"]["codec"], "h264")
        with self.assertRaisesRegex(Exception, "TRANSITION_TIMING_INVALID"):
            transition_output_durations([{"target_duration": .2, "transition": {"type": "CROSSFADE", "duration": .2}},
                                         {"target_duration": .2, "transition": {"type": "CUT", "duration": 0}}])


class RenderPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.image = self.root / "shot.png"
        Image.new("RGB", (320, 180), (10, 20, 30)).save(self.image)
        self.alignment = {"duration_seconds": 2.0}
        self.shots = {"shots": [{"shot_id": "sh_0001", "start": 0.0, "end": 2.0}]}
        self.requests = {"requests": [{"request_id": "req_image", "purpose": "SHOT", "shot_id": "sh_0001",
                                        "media_type": "IMAGE", "provider": "google_flow"}]}
        self.manifest = {"requests": [{"request_id": "req_image", "status": "SUCCEEDED",
                                        "selected_asset": {"path": "shot.png", "sha256": sha256_file(self.image), "attempt": 1}}]}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_hybrid_resolves_validated_image_with_provenance(self) -> None:
        media = {"shots": [{"shot_id": "sh_0001", "media_type": "IMAGE", "requirement": "REQUIRED",
                             "image_motion_policy": "SLOW_PUSH", "fallback_policy": "BLOCK"}]}
        plan = resolve_render_plan(project_id="prj_test", project_root=self.root, render_mode="hybrid_hook",
                                   alignment=self.alignment, shot_plan=self.shots, media_plan=media,
                                   generation_requests=self.requests, generation_manifest=self.manifest)
        self.assertEqual(plan["segments"][0]["source_hash"], sha256_file(self.image))
        self.assertEqual(plan["segments"][0]["provenance"]["request_id"], "req_image")

    def test_full_video_missing_required_video_blocks_without_slideshow(self) -> None:
        media = {"shots": [{"shot_id": "sh_0001", "media_type": "VIDEO", "requirement": "REQUIRED",
                             "image_motion_policy": "NONE", "fallback_policy": "BLOCK"}]}
        with self.assertRaisesRegex(RenderPlanError, "RENDER_BLOCKED_REQUIRED_VIDEO_MISSING"):
            resolve_render_plan(project_id="prj_test", project_root=self.root, render_mode="full_video_ai",
                                alignment=self.alignment, shot_plan=self.shots, media_plan=media,
                                generation_requests={"requests": []}, generation_manifest={"requests": []})

    def test_missing_required_image_fails_closed_with_shot_asset_class(self) -> None:
        media = {"shots": [{"shot_id": "sh_0001", "media_type": "IMAGE", "requirement": "REQUIRED",
                             "image_motion_policy": "STATIC", "fallback_policy": "BLOCK"}]}
        with self.assertRaisesRegex(RenderPlanError, "RENDER_SHOT_ASSET_UNRESOLVED"):
            resolve_render_plan(project_id="prj_test", project_root=self.root, render_mode="hybrid_hook",
                                alignment=self.alignment, shot_plan=self.shots, media_plan=media,
                                generation_requests=self.requests, generation_manifest={"requests": []})

    def test_reference_asset_cannot_resolve_a_story_shot(self) -> None:
        media = {"shots": [{"shot_id": "sh_0001", "media_type": "IMAGE", "requirement": "REQUIRED",
                             "image_motion_policy": "STATIC", "fallback_policy": "BLOCK"}]}
        requests = {"requests": [{"request_id": "req_ref", "purpose": "REFERENCE", "shot_id": "sh_0001",
                                    "media_type": "IMAGE", "provider": "google_flow"}]}
        manifest = {"requests": [{"request_id": "req_ref", "status": "SUCCEEDED",
                                    "selected_asset": self.manifest["requests"][0]["selected_asset"]}]}
        with self.assertRaisesRegex(RenderPlanError, "RENDER_SHOT_ASSET_UNRESOLVED"):
            resolve_render_plan(project_id="prj_test", project_root=self.root, render_mode="hybrid_hook",
                                alignment=self.alignment, shot_plan=self.shots, media_plan=media,
                                generation_requests=requests, generation_manifest=manifest)

    def test_manifest_reordering_does_not_change_exact_request_resolution(self) -> None:
        other = self.root / "other.png"; Image.new("RGB", (320, 180), "red").save(other)
        media = {"shots": [{"shot_id": "sh_0001", "media_type": "IMAGE", "requirement": "REQUIRED",
                             "image_motion_policy": "STATIC", "fallback_policy": "BLOCK"}]}
        extra = {"request_id": "req_other", "status": "SUCCEEDED",
                 "selected_asset": {"path": "other.png", "sha256": sha256_file(other), "attempt": 1}}
        forward = {"requests": [extra, self.manifest["requests"][0]]}
        reverse = {"requests": list(reversed(forward["requests"]))}
        kwargs = dict(project_id="prj_test", project_root=self.root, render_mode="hybrid_hook",
                      alignment=self.alignment, shot_plan=self.shots, media_plan=media,
                      generation_requests=self.requests)
        self.assertEqual(resolve_render_plan(**kwargs, generation_manifest=forward)["segments"][0]["source_hash"],
                         resolve_render_plan(**kwargs, generation_manifest=reverse)["segments"][0]["source_hash"])

    def test_unplanned_cross_shot_hash_reuse_fails_but_explicit_reuse_passes(self) -> None:
        shots = {"shots": [{"shot_id": "sh_0001", "start": 0.0, "end": 1.0},
                           {"shot_id": "sh_0002", "start": 1.0, "end": 2.0}]}
        requests = {"requests": [{"request_id": f"req_{i}", "purpose": "SHOT", "shot_id": f"sh_000{i}",
                                    "media_type": "IMAGE", "provider": "google_flow"} for i in (1, 2)]}
        manifest = {"requests": [{"request_id": f"req_{i}", "status": "SUCCEEDED",
                                    "selected_asset": {"path": "shot.png", "sha256": sha256_file(self.image), "attempt": 1}}
                                   for i in (1, 2)]}
        base = [{"shot_id": f"sh_000{i}", "media_type": "IMAGE", "requirement": "REQUIRED",
                 "image_motion_policy": "STATIC", "fallback_policy": "BLOCK"} for i in (1, 2)]
        kwargs = dict(project_id="prj_test", project_root=self.root, render_mode="hybrid_hook",
                      alignment=self.alignment, shot_plan=shots, generation_requests=requests,
                      generation_manifest=manifest, settings={"visual_narration_alignment": {"fail_on_unplanned_reuse": True}})
        with self.assertRaisesRegex(RenderPlanError, "VISUAL_NARRATION_ALIGNMENT_MISMATCH"):
            resolve_render_plan(**kwargs, media_plan={"shots": base})
        base[1]["allow_asset_reuse"] = True
        self.assertEqual(len(resolve_render_plan(**kwargs, media_plan={"shots": base})["segments"]), 2)

    def test_explicit_preferred_hold_fallback_is_recorded(self) -> None:
        media = {"shots": [{"shot_id": "sh_0001", "media_type": "VIDEO", "requirement": "PREFERRED",
                             "image_motion_policy": "NONE", "fallback_policy": "HOLD"}]}
        plan = resolve_render_plan(project_id="prj_test", project_root=self.root, render_mode="hybrid_hook",
                                   alignment=self.alignment, shot_plan=self.shots, media_plan=media,
                                   generation_requests={"requests": []}, generation_manifest={"requests": []})
        self.assertEqual(plan["segments"][0]["source_media_type"], "HOLD")
        self.assertTrue(plan["segments"][0]["fallback_resolution"]["used"])

    @unittest.skipUnless(FFMPEG, "multi-video plan requires ffmpeg")
    def test_full_video_multi_part_requests_tile_one_shot_without_stills(self) -> None:
        videos=[]
        for index in (1,2):
            path=self.root/f"part_{index}.mp4"; run("ffmpeg","-y","-f","lavfi","-i",f"color=c=navy:s=320x180:r=10:d=1","-an","-c:v","libx264","-pix_fmt","yuv420p",str(path)); videos.append(path)
        requests={"requests":[{"request_id":f"req_{i}","purpose":"SHOT","shot_id":"sh_0001","media_type":"VIDEO","provider":"google_flow","part_index":i,"part_count":2,"target_start":float(i-1),"target_end":float(i),"target_duration":1.0} for i in (1,2)]}
        manifest={"requests":[{"request_id":f"req_{i}","status":"SUCCEEDED","selected_asset":{"path":f"part_{i}.mp4","sha256":sha256_file(videos[i-1]),"attempt":1}} for i in (1,2)]}
        media={"shots":[{"shot_id":"sh_0001","media_type":"VIDEO","requirement":"REQUIRED","fallback_policy":"BLOCK","image_motion_policy":"NONE"}]}
        plan=resolve_render_plan(project_id="prj_full",project_root=self.root,render_mode="full_video_ai",alignment=self.alignment,shot_plan=self.shots,media_plan=media,generation_requests=requests,generation_manifest=manifest)
        self.assertEqual([item["segment_id"] for item in plan["segments"]],["sh_0001_part_001","sh_0001_part_002"])
        self.assertTrue(all(item["source_media_type"]=="VIDEO" and item["short_video_policy"]=="BLOCK" for item in plan["segments"]))


@unittest.skipUnless(FFMPEG, "FFmpeg integration requires ffmpeg and ffprobe")
class RenderServiceRecoveryTests(unittest.TestCase):
    def test_checkpoint_resume_rebuilds_only_missing_render_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            runtime = RuntimeLayout.from_root(root)
            config = ProjectConfig("prj_render01", settings={
                "render": {"width": 320, "height": 180, "fps": 10, "transition": {"type": "CROSSFADE", "duration": .1}},
                "audio": {"bgm_path": "assets/audio/bgm.wav", "bgm_volume": .08},
            })
            paths = create_project(runtime, config)
            image_rel, video_rel = "assets/image/req_image/attempt_001.png", "assets/video/req_video/attempt_001.mp4"
            image_path, video_path = paths.artifact_path(image_rel), paths.artifact_path(video_rel)
            image_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (640, 480), "navy").save(image_path)
            run("ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=maroon:s=1280x720:r=10:d=0.8",
                "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=0.8",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video_path))
            narration_rel, bgm_rel = "assets/audio/narration.wav", "assets/audio/bgm.wav"
            narration, bgm = paths.artifact_path(narration_rel), paths.artifact_path(bgm_rel)
            narration.parent.mkdir(parents=True, exist_ok=True)
            run("ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=700:sample_rate=48000:duration=1.8",
                "-c:a", "pcm_s16le", str(narration))
            run("ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=200:sample_rate=48000:duration=0.4",
                "-c:a", "pcm_s16le", str(bgm))
            atomic_write_json(paths.artifact_path("output/alignment.json"), {
                "schema_version": "story-auto-alignment/1.0.0", "project_id": config.project_id,
                "audio_path": narration_rel, "audio_sha256": sha256_file(narration), "narration_sha256": "n" * 64,
                "duration_seconds": 1.8, "segments": [
                    {"segment_id": "seg_1", "start": 0.0, "end": .6, "text": "The first scene begins."},
                    {"segment_id": "seg_2", "start": .6, "end": 1.2, "text": "The motion changes."},
                    {"segment_id": "seg_3", "start": 1.2, "end": 1.8, "text": "The scene holds."},
                ]})
            shots = [{"shot_id": f"sh_{index:04d}", "start": (index - 1) * .6, "end": index * .6}
                     for index in range(1, 4)]
            atomic_write_json(paths.artifact_path("output/shot_plan.json"), {"shots": shots})
            atomic_write_json(paths.artifact_path("output/media_plan.json"), {"render_mode": "hybrid_hook", "shots": [
                {"shot_id": "sh_0001", "media_type": "VIDEO", "requirement": "REQUIRED", "fallback_policy": "BLOCK", "image_motion_policy": "NONE"},
                {"shot_id": "sh_0002", "media_type": "IMAGE", "requirement": "REQUIRED", "fallback_policy": "BLOCK", "image_motion_policy": "SLOW_PUSH"},
                {"shot_id": "sh_0003", "media_type": "HOLD", "requirement": "REQUIRED", "fallback_policy": "BLOCK", "image_motion_policy": "NONE"},
            ]})
            atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": [
                {"request_id": "req_video", "purpose": "SHOT", "shot_id": "sh_0001", "media_type": "VIDEO", "provider": "google_flow"},
                {"request_id": "req_image", "purpose": "SHOT", "shot_id": "sh_0002", "media_type": "IMAGE", "provider": "google_flow"},
            ]})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"), {
                "schema_version": "story-auto-generation-manifest/1.0.0", "project_id": config.project_id, "requests": [
                    {"request_id": "req_video", "status": "SUCCEEDED", "selected_asset": {"path": video_rel, "sha256": sha256_file(video_path), "attempt": 1}},
                    {"request_id": "req_image", "status": "SUCCEEDED", "selected_asset": {"path": image_rel, "sha256": sha256_file(image_path), "attempt": 1}},
                ]})
            first = run_render_stages(runtime.root, config.project_id)
            self.assertEqual(first["actions"]["final_render"], "RUN")
            second = run_render_stages(runtime.root, config.project_id)
            self.assertEqual(second["actions"]["final_render"], "SKIP")
            self.assertTrue(all(action == "SKIP" for action in second["actions"]["clips"].values()))
            paths.artifact_path("output/final.mp4").unlink()
            case_a = run_render_stages(runtime.root, config.project_id)
            self.assertEqual(case_a["actions"]["final_render"], "RUN")
            self.assertTrue(all(action == "SKIP" for action in case_a["actions"]["clips"].values()))
            paths.artifact_path("output/scenes/sh_0002.mp4").unlink()
            case_b = run_render_stages(runtime.root, config.project_id)
            self.assertEqual(case_b["actions"]["clips"], {"sh_0001": "SKIP", "sh_0002": "RUN", "sh_0003": "SKIP"})
            self.assertEqual(case_b["actions"]["final_render"], "RUN")
            metadata = probe_media(paths.artifact_path("output/final.mp4"))
            self.assertEqual((metadata["video"]["width"], metadata["video"]["height"]), (320, 180))
            self.assertEqual(len(metadata["audio"]), 1)

    def test_full_video_multi_part_render_resume_and_render_only_invalidation(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            runtime=RuntimeLayout.from_root(root)
            config=ProjectConfig("prj_fullrender01",render_mode="full_video_ai",settings={"render":{"width":320,"height":180,"fps":10}})
            paths=create_project(runtime,config)
            narration_rel="assets/audio/narration.wav"; narration=paths.artifact_path(narration_rel); narration.parent.mkdir(parents=True,exist_ok=True)
            run("ffmpeg","-y","-f","lavfi","-i","sine=frequency=600:sample_rate=48000:duration=2","-c:a","pcm_s16le",str(narration))
            atomic_write_json(paths.artifact_path("output/alignment.json"),{"audio_path":narration_rel,"duration_seconds":2.0,"segments":[{"segment_id":"seg_1","start":0.0,"end":2.0,"text":"A continuous full video scene."}]})
            atomic_write_json(paths.artifact_path("output/shot_plan.json"),{"shots":[{"shot_id":"sh_0001","start":0.0,"end":2.0}]})
            atomic_write_json(paths.artifact_path("output/media_plan.json"),{"render_mode":"full_video_ai","shots":[{"shot_id":"sh_0001","media_type":"VIDEO","requirement":"REQUIRED","fallback_policy":"BLOCK","image_motion_policy":"NONE"}]})
            requests=[]; entries=[]
            for index,color in ((1,"navy"),(2,"maroon")):
                rel=f"assets/video/req_{index}/attempt_001.mp4"; path=paths.artifact_path(rel); path.parent.mkdir(parents=True,exist_ok=True)
                run("ffmpeg","-y","-f","lavfi","-i",f"color=c={color}:s=320x180:r=10:d=1.05","-an","-c:v","libx264","-pix_fmt","yuv420p",str(path))
                requests.append({"request_id":f"req_{index}","purpose":"SHOT","shot_id":"sh_0001","media_type":"VIDEO","provider":"google_flow","part_index":index,"part_count":2,"target_start":float(index-1),"target_end":float(index),"target_duration":1.0})
                entries.append({"request_id":f"req_{index}","status":"SUCCEEDED","selected_asset":{"path":rel,"sha256":sha256_file(path),"attempt":1}})
            atomic_write_json(paths.artifact_path("output/generation_requests.json"),{"requests":requests})
            atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"schema_version":"story-auto-generation-manifest/1.0.0","project_id":config.project_id,"requests":entries})
            provider_state=sha256_file(paths.artifact_path("output/generation_manifest.json"))
            first=run_render_stages(runtime.root,config.project_id); second=run_render_stages(runtime.root,config.project_id)
            self.assertEqual(first["actions"]["clips"],{"sh_0001_part_001":"RUN","sh_0001_part_002":"RUN"})
            self.assertEqual(second["actions"]["clips"],{"sh_0001_part_001":"SKIP","sh_0001_part_002":"SKIP"})
            paths.artifact_path("output/scenes/sh_0001_part_002.mp4").unlink()
            narrow=run_render_stages(runtime.root,config.project_id)
            self.assertEqual(narrow["actions"]["clips"],{"sh_0001_part_001":"SKIP","sh_0001_part_002":"RUN"})
            project=read_json(paths.project_file); project["settings"]["render"]["finishing_profile"]="NATURAL_SOFT"; atomic_write_json(paths.project_file,project)
            changed=run_render_stages(runtime.root,config.project_id)
            self.assertTrue(all(value=="RUN" for value in changed["actions"]["clips"].values()))
            self.assertEqual(sha256_file(paths.artifact_path("output/generation_manifest.json")),provider_state)
            self.assertEqual(read_json(paths.artifact_path("output/render_plan.json"))["render_mode"],"full_video_ai")


if __name__ == "__main__":
    unittest.main()

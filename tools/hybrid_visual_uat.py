"""Reproducible local Hybrid Visual UAT using existing Xianxia evidence assets.

This harness is intentionally provider-free. It exercises the accepted manual
Opening Builder + image/fallback body + mixed compositor path using real visual
assets already present in the Story Auto evidence workspace.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from story_auto.core.artifacts import atomic_write_json, sha256_file
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.render.media import probe_media
from story_auto.core.visual.hybrid_body import adopt_hybrid_body_image, build_hybrid_body_plan
from story_auto.core.visual.hybrid_render import render_hybrid_preview
from story_auto.core.visual.opening_builder import configure_opening_builder, import_opening_clip


NARRATION = """At dawn, the young cultivator returns to the mountain pavilion where her journey first changed. Mist drifts below the wooden railings while the distant waterfall catches the first pale light. She studies the valley in silence, remembering the choices that brought her here. A faint movement in the forest draws her attention, but she does not rush toward it. Instead, she steadies her breathing and follows the old path along the ridge. Each step carries her farther from the safety of the pavilion and closer to the unanswered signal beyond the clouds. Whatever waits ahead, she chooses to meet it with patience rather than fear."""


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def _concat_pair(first: Path, second: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(first), "-i", str(second),
          "-filter_complex", "[0:v]setpts=PTS-STARTPTS[v0];[1:v]setpts=PTS-STARTPTS[v1];[v0][v1]concat=n=2:v=1:a=0[v]",
          "-map", "[v]", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output)])


def _synthesize_sapi(text: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    escaped_text = text.replace("'", "''")
    escaped_output = str(output.resolve()).replace("'", "''")
    command = ("Add-Type -AssemblyName System.Speech; "
               "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
               "$s.SelectVoice('Microsoft Zira Desktop'); $s.Rate=-1; "
               f"$s.SetOutputToWaveFile('{escaped_output}'); $s.Speak('{escaped_text}'); $s.Dispose()")
    _run([r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe", "-NoProfile", "-Command", command])


def _alignment(text: str, duration: float, audio_rel: str, audio_sha: str) -> dict:
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text.strip()) if item.strip()]
    weights = [max(1, len(item.split())) for item in sentences]
    total_weight = sum(weights)
    cursor = 0.0
    segments = []
    for index, (sentence, weight) in enumerate(zip(sentences, weights), start=1):
        end = duration if index == len(sentences) else cursor + duration * weight / total_weight
        segments.append({"segment_id": f"uat_{index:02d}", "start": round(cursor, 6),
                         "end": round(end, 6), "text": sentence})
        cursor = end
    return {"duration_seconds": duration, "audio_path": audio_rel, "audio_sha256": audio_sha,
            "timing_source": "UAT_LOCAL_SAPI_SENTENCE_ALIGNMENT", "segments": segments}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default="../evidence/hybrid_visual_h5_uat/runtime")
    parser.add_argument("--evidence-root", default="../evidence/goal54/xianxia")
    parser.add_argument("--project-id", default="prj_hybrid_xianxia_uat")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    runtime_root = Path(args.runtime_root).resolve()
    evidence_root = Path(args.evidence_root).resolve()
    if args.reset:
        if "hybrid_visual_h5_uat" not in runtime_root.as_posix().lower():
            raise SystemExit("Refusing reset outside the dedicated Hybrid H5 UAT runtime")
        shutil.rmtree(runtime_root, ignore_errors=True)
    required = {
        "x1c": evidence_root / "x1c_kept_clean.mp4",
        "x2": evidence_root / "x2_kept_clean.mp4",
        "x3": evidence_root / "x3_kept_clean.mp4",
        "anchor": evidence_root / "xianxia_anchor_v2.png",
        "frame2": evidence_root / "x2_continuity_frame.png",
        "frame3": evidence_root / "x3_continuity_frame.png",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing UAT evidence assets: {missing}")

    runtime = RuntimeLayout.from_root(runtime_root).ensure()
    paths = create_project(runtime, ProjectConfig(args.project_id, render_mode="hybrid_hook", settings={
        "render": {"width": 1280, "height": 720, "fps": 24, "pixel_format": "yuv420p",
                   "finishing_profile": "NATURAL_SOFT",
                   "subtitle_style": {"width": 38, "font_name": "Arial", "font_size": 38,
                                      "margin_left": 70, "margin_right": 70}},
        "hybrid_visual": {"audio_visualizer": True},
    }))

    narration = paths.artifact_path("assets/audio/narration.wav")
    _synthesize_sapi(NARRATION, narration)
    audio_meta = probe_media(narration)
    alignment = _alignment(NARRATION, float(audio_meta["duration_seconds"]),
                           "assets/audio/narration.wav", sha256_file(narration))
    atomic_write_json(paths.artifact_path("output/alignment.json"), alignment)

    opening_a = runtime.temp / "hybrid_uat_opening_a.mp4"
    opening_b = runtime.temp / "hybrid_uat_opening_b.mp4"
    _concat_pair(required["x1c"], required["x2"], opening_a)
    _concat_pair(required["x2"], required["x3"], opening_b)
    configure_opening_builder(runtime.root, args.project_id,
        shared_context="Young Chinese female cultivator, pale blue-white hanfu, mountain pavilion and mist continuity.",
        slot_specs=[
            {"duration_seconds": 7.5, "purpose": "hook", "prompt": "Use the accepted Xianxia opening motion and character continuity."},
            {"duration_seconds": 7.5, "purpose": "opening transition", "prompt": "Continue the same cultivator and mountain environment without a style reset."},
        ])
    import_opening_clip(runtime.root, args.project_id, "OPENING_O1", opening_a, original_filename="x1c_plus_x2.mp4")
    import_opening_clip(runtime.root, args.project_id, "OPENING_O2", opening_b, original_filename="x2_plus_x3.mp4")

    body = build_hybrid_body_plan(runtime.root, args.project_id, image_slot_seconds=6.0,
                                  images_per_block=3, stock_slot_seconds=7.0)
    image_sources = [required["anchor"], required["frame2"], required["frame3"]]
    image_index = 0
    for slot in body["slots"]:
        if slot["visual_type"] == "IMAGE":
            source = image_sources[image_index % len(image_sources)]
            adopt_hybrid_body_image(runtime.root, args.project_id, slot["slot_id"], source,
                                    original_filename=source.name)
            image_index += 1
        elif slot["visual_type"] == "STOCK_VIDEO":
            source = image_sources[image_index % len(image_sources)]
            adopt_hybrid_body_image(runtime.root, args.project_id, slot["slot_id"], source,
                                    original_filename=source.name, as_stock_fallback=True)
            image_index += 1

    manifest = render_hybrid_preview(runtime.root, args.project_id)
    result = {
        "status": "PASS",
        "project_id": args.project_id,
        "runtime_root": str(runtime_root),
        "preview": str(paths.artifact_path(manifest["preview_path"])),
        "preview_sha256": manifest["preview_sha256"],
        "duration_seconds": manifest["duration_seconds"],
        "narration_sha256": manifest["narration"]["sha256"],
        "timeline_source_kinds": [item["source_kind"] for item in manifest["timeline"]],
        "source_video_audio": manifest["source_video_audio"],
        "waveform_enabled": manifest["audio_visualizer"]["enabled"],
        "release_activation": manifest["release_activation"],
        "visual_sources": {name: {"path": str(path), "sha256": sha256_file(path)} for name, path in required.items()},
    }
    output = runtime_root.parent / "result.json"
    atomic_write_json(output, result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

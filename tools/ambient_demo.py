"""Build two deterministic offline Ambient Story engineering demos.

No provider adapter is imported or called. The fixture exercises the canonical
artifact mapping, image compiler, subtitle/audio path, and common compositor.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from story_auto.core.artifacts import atomic_write_json, sha256_file
from story_auto.core.planning import compile_ambient_shot_plan, compile_generation_requests, compile_media_plan
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.core.render import probe_media, run_render_stages


PROVIDER_CALLS = 0


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=True)


def _audio(path: Path, *, duration: float, frequency: int, volume: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg","-y","-f","lavfi","-i",f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
          "-af",f"volume={volume}","-c:a","pcm_s16le",str(path)])


def _gradient_image(path: Path, *, size: tuple[int, int], colors: tuple[tuple[int, int, int], tuple[int, int, int]],
                    title: str, subtitle: str, accent: tuple[int, int, int], raw_mark: bool) -> None:
    width, height = size
    image = Image.new("RGB", size)
    pixels = image.load()
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(round(colors[0][channel] * (1 - ratio) + colors[1][channel] * ratio) for channel in range(3))
        for x in range(width): pixels[x, y] = color
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((0, height * .66, width, height), fill=(8, 12, 18, 95))
    draw.ellipse((width * .11, height * .20, width * .29, height * .67), fill=(*accent, 210))
    draw.rectangle((width * .20, height * .38, width * .64, height * .64), fill=(230, 224, 210, 42), outline=(255,255,255,55), width=2)
    draw.line((width * .64, height * .38, width * .82, height * .25), fill=(*accent, 140), width=5)
    font = ImageFont.load_default()
    draw.text((30, height - 104), title.upper(), fill=(248,248,246,255), font=font)
    draw.text((30, height - 78), subtitle, fill=(222,226,230,235), font=font)
    if raw_mark:
        x, y = width - 26, height - 24
        draw.line((x-8,y,x+8,y), fill=(255,255,255,255), width=2)
        draw.line((x,y-8,x,y+8), fill=(255,255,255,255), width=2)
        draw.ellipse((x-3,y-3,x+3,y+3), fill=(255,255,255,255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _fixture_spec(style: str) -> dict[str, Any]:
    if style == "quiet_verdict":
        return {"demo_id":"ambient_quiet_verdict_demo","project_id":"prj_ambient_quiet_verdict_demo","hold":12.0,"roles":["incident","point of no return","consequence"],
            "titles":["The hearing begins","The record becomes irreversible","Authority answers to evidence"],
            "colors":[((40,55,70),(15,22,31)),((51,63,76),(20,27,35)),((57,66,72),(24,29,33))],"accent":(112,145,162),"prop":"sealed document"}
    return {"demo_id":"ambient_hidden_mastery_demo","project_id":"prj_ambient_hidden_mastery_demo","hold":10.0,"roles":["incident","escalation","reveal","closure"],
        "titles":["An ordinary technician arrives","The machine refuses every expert","Hidden mastery changes the room","The same tool carries new meaning"],
        "colors":[((92,69,48),(34,25,20)),((108,77,48),(42,29,20)),((122,88,54),(49,35,23)),((102,79,59),(43,34,28))],"accent":(196,142,75),"prop":"precision instrument"}


def _prepare_project(runtime: RuntimeLayout, style: str) -> dict[str, Any]:
    spec = _fixture_spec(style)
    project_root = runtime.projects / spec["project_id"]
    if project_root.exists():
        if project_root.resolve().parent != runtime.projects.resolve(): raise RuntimeError("unsafe demo target")
        shutil.rmtree(project_root)
    duration = spec["hold"] * len(spec["roles"])
    config = ProjectConfig(spec["project_id"], render_mode="ambient_story", settings={
        "ambient_style":style,
        "render":{"width":640,"height":360,"fps":12,"pixel_format":"yuv420p","video_crf":24,
                  "visual_narration_alignment":{"fail_on_unplanned_reuse":True,"require_semantic_qc":True}},
        "audio":{"bgm_path":"assets/audio/bgm.wav","bgm_volume":.05},
    })
    narration_lines = [f"{title}. The narration carries this {role.replace('_',' ')} chapter." for title, role in zip(spec["titles"],spec["roles"])]
    paths = create_project(runtime, config, "# Ambient Story Engineering Demo\n\n## Narration\n\n" + " ".join(narration_lines) + "\n")
    narration_path = paths.artifact_path("assets/audio/narration.wav")
    bgm_path = paths.artifact_path("assets/audio/bgm.wav")
    _audio(narration_path,duration=duration,frequency=520 if style=="quiet_verdict" else 610,volume=.10)
    _audio(bgm_path,duration=4.0,frequency=180 if style=="quiet_verdict" else 220,volume=.035)
    segments, scenes = [], []
    for index, (role, title) in enumerate(zip(spec["roles"], spec["titles"]), 1):
        start, end = (index - 1) * spec["hold"], index * spec["hold"]
        first = f"seg_{index:04d}a"; second = f"seg_{index:04d}b"; middle = start + spec["hold"] / 2
        segments.extend([
            {"segment_id":first,"start":start,"end":middle,"text":title + "."},
            {"segment_id":second,"start":middle,"end":end,"text":f"The narration carries the {role.replace('_',' ')} chapter."},
        ])
        scenes.append({"scene_id":f"scn_{index:04d}","start":start,"end":end,
            "narration_segment_ids":[first,second],"narration_text":narration_lines[index-1],
            "story_role":role,"summary":title,"entity_ids":["char_protagonist","char_counterpart","loc_primary","prop_signature"]})
    alignment = {"schema_version":"story-auto-alignment/1.0.0","project_id":config.project_id,
        "audio_path":"assets/audio/narration.wav","audio_sha256":sha256_file(narration_path),"narration_sha256":"d"*64,
        "duration_seconds":duration,"segments":segments,"source":"offline_engineering_fixture"}
    timeline = {"schema_version":"story-auto-story-timeline/1.0.0","project_id":config.project_id,
        "alignment_sha256":"pending","scenes":scenes,"review_status":"VALIDATED"}
    continuity = {"schema_version":"story-auto-continuity-bible/1.0.0","project_id":config.project_id,"style":{},
        "characters":[
            {"entity_id":"char_protagonist","name":"Mara","facts":{"age":52},"visual_design":{"hair":"dark bob","wardrobe":"charcoal jacket"},"constraints":["same face, age, hair, and jacket"]},
            {"entity_id":"char_counterpart","name":"Counterpart","facts":{},"visual_design":{"wardrobe":"muted formal clothing"},"constraints":["same supporting identity"]},
        ],"locations":[{"entity_id":"loc_primary","name":"Institutional room" if style=="quiet_verdict" else "Working studio","facts":{},"visual_design":{},"constraints":["same architecture"]}],
        "props":[{"entity_id":"prop_signature","name":spec["prop"],"facts":{},"visual_design":{"material":"tactile used surface"},"constraints":["same recurring object"]}],
        "review_status":"VALIDATED"}
    for name, value in (("alignment",alignment),("story_timeline",timeline),("continuity_bible",continuity)):
        atomic_write_json(paths.artifact_path(f"output/{name}.json"), value)
    timeline_sha = sha256_file(paths.artifact_path("output/story_timeline.json")); continuity_sha = sha256_file(paths.artifact_path("output/continuity_bible.json"))
    shot_plan = compile_ambient_shot_plan(config.project_id,timeline,continuity,style,timeline_sha256=timeline_sha,continuity_sha256=continuity_sha)
    settings = {"hook_seconds":0.0,"motion_spike_threshold":8,"overrides":{},"max_attempts":1,"aspect_ratio":"16:9",
        "large_batch_request_threshold":20,"provider_video_clip_seconds":8.0,"ambient_style":style}
    media_plan = compile_media_plan(config.project_id,shot_plan,"ambient_story",settings)
    generation_requests = compile_generation_requests(config.project_id,shot_plan,media_plan,continuity,settings,ambient_style=style)
    atomic_write_json(paths.artifact_path("output/shot_plan.json"),shot_plan)
    atomic_write_json(paths.artifact_path("output/media_plan.json"),media_plan)
    atomic_write_json(paths.artifact_path("output/generation_requests.json"),generation_requests)
    clean_assets: list[tuple[str, str, str, str]] = []
    for index, (title, colors) in enumerate(zip(spec["titles"],spec["colors"]), 1):
        raw_rel=f"assets/image/chapter_{index:02d}/raw.png"; clean_rel=f"assets/image/chapter_{index:02d}/clean.png"
        raw=paths.artifact_path(raw_rel); clean=paths.artifact_path(clean_rel)
        _gradient_image(raw,size=(1280,720),colors=colors,title=title,subtitle=spec["prop"],accent=spec["accent"],raw_mark=True)
        _gradient_image(clean,size=(1280,720),colors=colors,title=title,subtitle=spec["prop"],accent=spec["accent"],raw_mark=False)
        clean_assets.append((raw_rel,sha256_file(raw),clean_rel,sha256_file(clean)))
    entries=[]; chapter=0
    for request in generation_requests["requests"]:
        if request.get("purpose")=="SHOT": chapter += 1
        asset=clean_assets[max(0,chapter-1)]
        entries.append({"request_id":request["request_id"],"media_type":"IMAGE","status":"SUCCEEDED","attempts":[{"attempt":1,"source":"OFFLINE_FIXTURE","provider_submitted":False}],
            "selected_asset":{"path":asset[2],"sha256":asset[3],"attempt":1,"raw_path":asset[0],"raw_sha256":asset[1],
                "alignment_classification":"PASS_DIRECT","naturalness_qc":"PASS","visible_provider_mark":"PASS_CLEAN",
                "postprocess":{"profile":"offline-goal13-clean-derivative","raw_immutable":True}}})
    atomic_write_json(paths.artifact_path("output/generation_manifest.json"),{"schema_version":"story-auto-generation-manifest/1.0.0","project_id":config.project_id,"requests":entries})
    render_result=run_render_stages(runtime.root,config.project_id)
    render_plan=__import__("story_auto.core.artifacts",fromlist=["read_json"]).read_json(paths.artifact_path("output/render_plan.json"))
    presentation={"schema_version":"story-auto-ambient-demo-plan/1.0.0","project_id":config.project_id,"style":style,
        "segments":[{"shot_id":item["shot_id"],"duration":item["target_duration"],"motion":item["image_motion_policy"],
                     "presentation":item["ambient_presentation"],"transition":item["transition"],"source_hash":item["source_hash"]} for item in render_plan["segments"]]}
    presentation_path=paths.artifact_path("output/ambient_presentation_plan.json"); atomic_write_json(presentation_path,presentation)
    final_path=paths.artifact_path("output/final.mp4")
    black=_run(["ffmpeg","-hide_banner","-i",str(final_path),"-vf","blackdetect=d=0.20:pic_th=0.98","-an","-f","null",os.devnull])
    black_frames="black_start:" in (black.stderr or "")
    frame_paths=[]
    for index, segment in enumerate(render_plan["segments"],1):
        frame=paths.artifact_path(f"output/review/frame_{index:02d}.png"); frame.parent.mkdir(parents=True,exist_ok=True)
        timestamp=float(segment["target_start"])+float(segment["target_duration"])/2
        _run(["ffmpeg","-y","-ss",f"{timestamp:.3f}","-i",str(final_path),"-frames:v","1",str(frame)])
        frame_paths.append(frame)
    thumbs=[]
    for path in frame_paths:
        image=Image.open(path).convert("RGB"); image.thumbnail((320,180)); thumbs.append(image.copy())
    sheet=Image.new("RGB",(320*len(thumbs),210),(244,245,247)); draw=ImageDraw.Draw(sheet)
    for index,image in enumerate(thumbs): sheet.paste(image,(index*320,0)); draw.text((index*320+10,188),f"Chapter {index+1}",fill=(20,25,32))
    contact_path=paths.artifact_path("output/ambient_contact_sheet.jpg"); sheet.save(contact_path,quality=90)
    return {"demo_id":spec["demo_id"],"project_id":config.project_id,"style":style,"project_root":str(paths.root),"final_path":str(final_path),
        "contact_sheet":str(contact_path),"render_plan":str(paths.artifact_path("output/render_plan.json")),
        "presentation_plan":str(presentation_path),"duration_seconds":probe_media(final_path)["duration_seconds"],
        "chapter_count":len(render_plan["segments"]),"black_frames":black_frames,"render_actions":render_result["actions"]}


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--runtime-root",default="runtime/goal13_ambient_demos")
    args=parser.parse_args()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"): raise SystemExit("ffmpeg and ffprobe are required")
    runtime=RuntimeLayout.from_root(Path(args.runtime_root)).ensure()
    results=[_prepare_project(runtime,style) for style in ("quiet_verdict","hidden_mastery")]
    summary={"schema_version":"story-auto-goal13-demo-summary/1.0.0","external_provider_calls":PROVIDER_CALLS,
        "status":"PASS" if all(not item["black_frames"] for item in results) and PROVIDER_CALLS==0 else "FAIL","demos":results}
    summary_path=runtime.root/"ambient-demo-summary.json"; atomic_write_json(summary_path,summary)
    print(summary_path.resolve())
    return 0 if summary["status"]=="PASS" else 1


if __name__=="__main__": raise SystemExit(main())

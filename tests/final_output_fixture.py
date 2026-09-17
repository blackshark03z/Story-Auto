"""Small real local render; never dispatches a provider."""
import subprocess
from PIL import Image

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.content import parse_content_markdown, narration_hash
from story_auto.core.render.service import run_render_stages
from story_auto.core.project.model import full_image_motion_spec


def complete_final(paths):
    project = read_json(paths.project_file)
    project["render_mode"] = "full_image"
    project.setdefault("settings", {})["render"] = {"width": 320, "height": 180, "fps": 10}
    atomic_write_json(paths.project_file, project)
    audio_rel = "assets/audio/narration.wav"
    audio = paths.artifact_path(audio_rel)
    audio.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=48000:duration=1", "-c:a", "pcm_s16le", str(audio)], check=True)
    image_rel = "assets/image/fixture.png"
    image = paths.artifact_path(image_rel)
    image.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (640, 360), "navy").save(image)
    text = parse_content_markdown(paths.content_file.read_text(encoding="utf-8")).narration
    documents = {
        "content_manifest": {"fixture": True}, "story_timeline": {"fixture": True}, "continuity_bible": {"fixture": True},
        "alignment": {"audio_path": audio_rel, "duration_seconds": 1.0, "narration_sha256": narration_hash(text),
                      "segments": [{"segment_id": "seg_1", "start": 0.0, "end": 1.0, "text": text}]},
        "shot_plan": {"shots": [{"shot_id": "sh_0001", "start": 0.0, "end": 1.0}]},
        "media_plan": {"render_mode": "full_image", "shots": [{"shot_id": "sh_0001", "media_type": "IMAGE",
                       "requirement": "REQUIRED", "fallback_policy": "BLOCK", "image_motion_policy": "AUTO_CONTINUOUS_ZOOM_IN",
                       "motion_spec": full_image_motion_spec("ZOOM_IN")}]},
        "generation_requests": {"requests": [{"request_id": "req_fixture", "purpose": "SHOT", "shot_id": "sh_0001",
                                               "media_type": "IMAGE", "provider": "google_flow"}]},
        "generation_manifest": {"requests": [{"request_id": "req_fixture", "status": "SUCCEEDED", "attempts": [],
                                              "selected_asset": {"path": image_rel, "sha256": sha256_file(image),
                                                                 "attempt": 1, "production_qc": "AUTO_ACCEPTED"}}]},
    }
    for name, value in documents.items():
        atomic_write_json(paths.artifact_path(f"output/{name}.json"), value)
    atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {
        "status": "APPROVED", "bound_hashes": {
            name: sha256_file(paths.artifact_path(f"output/{filename}.json"))
            for name, filename in (("timeline", "story_timeline"), ("continuity", "continuity_bible"),
                                   ("shot_plan", "shot_plan"), ("media_plan", "media_plan"))}}})
    return run_render_stages(paths.runtime.root, paths.project_id)

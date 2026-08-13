"""Deterministic Goal 08 provider-quality benchmark and anonymous review pack."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import random
import subprocess
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from story_auto.core.artifacts import atomic_write_json, sha256_file
from story_auto.core.visual import DEFAULT_VISUAL_POLICY, compile_image_prompt, compile_video_prompt


SCHEMA = "story-auto-provider-benchmark/1.0.0"
IMAGE_MODELS = ("google_flow_web", "gemini-3.1-flash-image", "gemini-3-pro-image")
VIDEO_MODELS = ("google_flow_web", "gemini-omni-flash-preview", "veo-3.1-generate-preview")
IMAGE_DIMENSIONS = (
    "SKIN_REALISM", "FACE_NATURALNESS", "HAIR_REALISM", "MATERIAL_REALISM",
    "LIGHTING_NATURALISM", "COLOR_NATURALISM", "COMPOSITION_NATURALISM",
    "REFERENCE_IDENTITY", "PROP_CONTINUITY", "ENVIRONMENT_REALISM", "AI_POLISH",
    "OVERALL_PRODUCTION_QUALITY",
)
VIDEO_DIMENSIONS = IMAGE_DIMENSIONS + (
    "TEMPORAL_CONSISTENCY", "FACE_STABILITY", "HAND_BODY_STABILITY", "MOTION_NATURALNESS",
    "CAMERA_PHYSICS", "BACKGROUND_STABILITY", "REFERENCE_RETENTION", "PROP_STABILITY",
    "MOTION_RESTRAINT",
)
DEFECTS = (
    "waxy skin", "porcelain/plastic face", "excessive smoothing", "uncanny eyes",
    "anatomy mutation", "finger mutation", "fabric melting", "prop mutation", "identity drift",
    "background morphing", "fake HDR", "excessive sharpening", "artificial rim light",
    "excessive bokeh", "synthetic material sheen", "floating camera", "subject sliding",
    "inconsistent shadows", "unexplained lighting changes", "visible watermark",
)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fixtures() -> dict[str, dict[str, Any]]:
    image_intents = {
        "IMAGE-A": (
            "Medium full-body documentary photograph of Mara, an adult traveler with dark brown hair tied back, "
            "wearing a worn dark green field jacket over practical charcoal layers, standing on an ordinary weathered "
            "railway platform at dusk. Quiet attentive expression, hands relaxed and anatomically natural, no pose for "
            "camera, no fantasy gear, no text."
        ),
        "IMAGE-B": (
            "Observed photograph inside a lived-in abandoned station waiting room: scratched wooden bench, rumpled wool "
            "cloth, oxidized metal fixtures, dusty intact window glass, chipped plaster, scuffed floor, and small signs "
            "of ordinary past use. Natural dusk light through windows, no person, no staged showroom arrangement, no text."
        ),
        "IMAGE-C": (
            "Documentary photograph of the same supplied Mara in the same worn dark green field jacket and charcoal "
            "layers, now inside the abandoned station waiting room. She holds the same aged brass compass near a cracked "
            "wooden bench. Preserve face, hair, clothing wear, compass shape, and natural physical proportions; no text."
        ),
    }
    videos = {
        "VIDEO-A": compile_video_prompt(subject_motion="natural breathing, one blink, tiny shift of gaze and posture",
                                         environmental_motion="barely perceptible hair and jacket movement",
                                         camera_motion="STATIC", timing="six to eight seconds, unhurried"),
        "VIDEO-B": compile_video_prompt(subject_motion="Mara takes two grounded steps, then raises and checks the brass compass",
                                         environmental_motion="subtle jacket and loose hair response only",
                                         camera_motion="SUBTLE_HANDHELD", timing="six to eight seconds, one continuous action"),
    }
    result: dict[str, dict[str, Any]] = {}
    for case, intent in image_intents.items():
        result[case] = {"media_type": "IMAGE", "semantic_intent": intent,
                        "prompt": compile_image_prompt(intent, deepcopy(DEFAULT_VISUAL_POLICY)),
                        "aspect_ratio": "16:9", "output_count": 1}
    for case, prompt in videos.items():
        result[case] = {"media_type": "VIDEO", "semantic_intent": prompt, "prompt": prompt,
                        "aspect_ratio": "16:9", "output_count": 1}
    return result


def _mapping(seed: str) -> dict[str, dict[str, str]]:
    rng = random.Random(int(_hash_text(seed)[:16], 16))
    result: dict[str, dict[str, str]] = {}
    for family, models in (("IMAGE", list(IMAGE_MODELS)), ("VIDEO", list(VIDEO_MODELS))):
        rng.shuffle(models)
        result[family] = {f"Candidate {chr(65 + index)}": model for index, model in enumerate(models)}
    return result


def build_benchmark_workspace(root: Path, *, capability_evidence: list[dict[str, Any]],
                              credential_probe: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    root.mkdir(parents=True, exist_ok=True)
    fixtures = _fixtures()
    mapping = _mapping("story-auto-goal08-provider-benchmark-v1")
    requests: list[dict[str, Any]] = []
    for case, fixture in fixtures.items():
        family = fixture["media_type"]
        attempts = (1, 2) if family == "IMAGE" else (1,)
        for label, model in mapping[family].items():
            for attempt in attempts:
                request_id = f"{case.lower()}-{label[-1].lower()}-{attempt}"
                status = "PENDING"
                failure = None
                if model.startswith("gemini-") or model.startswith("veo-"):
                    status = "BLOCKED"
                    failure = "GEMINI_API_PAID_QUOTA_REQUIRED"
                requests.append({
                    "request_id": request_id,
                    "case": case,
                    "anonymous_candidate": label,
                    "provider": "google_flow" if model == "google_flow_web" else "google_gemini_api",
                    "actual_model": model,
                    "attempt": attempt,
                    "pass": "FAIR_BASELINE",
                    "media_type": family,
                    "reference_hashes": [],
                    "prompt_sha256": _hash_text(fixture["prompt"]),
                    "actual_prompt": fixture["prompt"],
                    "output_settings": {"aspect_ratio": fixture["aspect_ratio"], "output_count": 1},
                    "local_asset": None,
                    "asset_sha256": None,
                    "technical_validation": "NOT_RUN",
                    "visible_watermark": "UNCERTAIN",
                    "automated_qc_scores": None,
                    "human_review": "PENDING",
                    "status": status,
                    "failure_class": failure,
                    "attempt_history": [],
                })
    manifest = {
        "schema_version": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_status": "BLOCKED_PROVIDER_ACCOUNT",
        "selection_status": "NO_PRODUCTION_DEFAULT_CHANGE",
        "visual_policy": deepcopy(DEFAULT_VISUAL_POLICY),
        "fixtures": fixtures,
        "capability_evidence": capability_evidence,
        "credential_probe": credential_probe,
        "requests": requests,
        "automated_review_is_advisory": True,
        "human_review_required": True,
    }
    atomic_write_json(root / "benchmark_manifest.json", manifest)
    atomic_write_json(root / "provider_mapping.json", {
        "schema_version": "story-auto-provider-mapping/1.0.0", "mapping": mapping,
        "notice": "Reveal only after blind quality scoring. No production default has been selected.",
    })
    return manifest, mapping


def _placeholder(text: str, path: Path, *, size: tuple[int, int] = (960, 540)) -> None:
    image = Image.new("RGB", size, "#101722")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    lines = text.split("\n")
    y = size[1] // 2 - len(lines) * 18
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        draw.text(((size[0] - (box[2] - box[0])) // 2, y), line, fill="#dce7f5", font=font)
        y += 36
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG")


def write_review_package(root: Path, manifest: dict[str, Any]) -> None:
    previews = root / "previews"
    for request in manifest["requests"]:
        if request["media_type"] == "IMAGE" and request.get("local_asset"):
            request["preview"] = request["local_asset"]
        elif request["media_type"] == "IMAGE":
            name = f'{request["request_id"]}.png'
            _placeholder(f'{request["case"]} · {request["anonymous_candidate"]}\nAttempt {request["attempt"]}\nOUTPUT UNAVAILABLE', previews / name)
            request["preview"] = f"previews/{name}"
        elif request["media_type"] == "VIDEO" and request.get("local_asset"):
            metadata = request.get("technical_validation", {})
            duration = float(metadata.get("duration_seconds", 0) or 0)
            frame_paths = []
            for label, second in (("early", max(0.1, duration * 0.15)), ("middle", duration * 0.5),
                                  ("late", max(0.1, duration * 0.85))):
                name = f'{request["request_id"]}_{label}.jpg'
                destination = previews / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(second),
                                "-i", str(root / request["local_asset"]), "-frames:v", "1", str(destination)], check=True)
                frame_paths.append(f"previews/{name}")
            request["review_frames"] = frame_paths
    sheets: list[str] = []
    for case in ("IMAGE-A", "IMAGE-B", "IMAGE-C"):
        items = [item for item in manifest["requests"] if item["case"] == case]
        canvas = Image.new("RGB", (960, 360 * len(items)), "#0b1018")
        for index, item in enumerate(items):
            with Image.open(root / item["preview"]) as image:
                image.thumbnail((640, 350))
                canvas.paste(image, (0, index * 360))
            ImageDraw.Draw(canvas).text((660, index * 360 + 30),
                                        f'{item["anonymous_candidate"]}\nAttempt {item["attempt"]}\n{item["status"]}',
                                        fill="white", font=ImageFont.load_default())
        sheet = root / f"contact_sheet_{case.lower()}.jpg"
        canvas.save(sheet, "JPEG", quality=92)
        sheets.append(sheet.name)
    cards = []
    for request in manifest["requests"]:
        title = f'{request["case"]} · {request["anonymous_candidate"]} · Attempt {request["attempt"]}'
        if request["media_type"] == "IMAGE":
            media = f'<a href="{html.escape(request["preview"])}" target="_blank"><img src="{html.escape(request["preview"])}" alt="{html.escape(title)}"></a>'
            dimensions = IMAGE_DIMENSIONS
        elif request.get("local_asset"):
            frames = "".join(f'<a href="{html.escape(path)}" target="_blank"><img class="frame" src="{html.escape(path)}"></a>' for path in request.get("review_frames", []))
            media = f'<video controls preload="metadata" src="{html.escape(request["local_asset"])}"></video><div class="frames">{frames}</div>'
            dimensions = VIDEO_DIMENSIONS
        else:
            media = '<div class="unavailable">VIDEO OUTPUT UNAVAILABLE</div>'
            dimensions = VIDEO_DIMENSIONS
        scores = "".join(f'<label>{dimension}<input type="number" min="1" max="5" step="1"></label>' for dimension in dimensions)
        defects = "".join(f'<label><input type="checkbox"> {defect}</label>' for defect in DEFECTS)
        cards.append(f'<article><h2>{html.escape(title)}</h2>{media}<details><summary>Score 1–5</summary><div class="scores">{scores}</div><h3>Hard defects</h3><div class="defects">{defects}</div></details><textarea placeholder="Operator notes"></textarea></article>')
    document = f'''<!doctype html><html><head><meta charset="utf-8"><title>Story Auto blind provider review</title><style>
body{{margin:0;background:#080d14;color:#e7eef8;font:15px system-ui}}header{{position:sticky;top:0;background:#111a27;padding:18px 28px;z-index:2}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(440px,1fr));gap:18px;padding:22px}}article{{background:#111925;border:1px solid #26354a;border-radius:12px;padding:16px}}img,video,.unavailable{{width:100%;aspect-ratio:16/9;object-fit:contain;background:#0b1018}}.frames{{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}}.frames .frame{{width:100%}}.unavailable{{display:grid;place-items:center;color:#f2bd67}}.scores{{display:grid;grid-template-columns:1fr 70px;gap:6px}}.scores label{{display:contents}}.defects{{display:grid;grid-template-columns:1fr 1fr;gap:5px}}textarea{{width:100%;min-height:80px;margin-top:12px;background:#0b1018;color:white}}a{{color:#8ec5ff}}</style></head><body><header><h1>Story Auto · Blind Provider Quality Review</h1><p>Do not open <code>provider_mapping.json</code> until scoring is complete. Watch every video; frames alone cannot establish temporal quality. Current API outputs are blocked by account quota, so unavailable cards are not scoreable.</p><p>Contact sheets: {' · '.join(f'<a href="{s}">{s}</a>' for s in sheets)}</p></header><main>{''.join(cards)}</main></body></html>'''
    (root / "review.html").write_text(document, encoding="utf-8")
    atomic_write_json(root / "benchmark_manifest.json", manifest)

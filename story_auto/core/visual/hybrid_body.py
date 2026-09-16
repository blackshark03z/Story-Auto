"""Deterministic Hybrid Visual body recipe and stock-video asset binding.

The narration/alignment duration is the master clock. This module plans image
and stock-video slots after the Opening Builder without release-enabling the
Hybrid mode or invoking any external provider by itself.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import re
from pathlib import Path
import shutil
from typing import Any

from PIL import Image

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock
from story_auto.core.render.compiler import compile_video
from story_auto.core.render.media import MediaError, MediaTarget, probe_media
from story_auto.core.visual.opening_builder import opening_builder_view
from story_auto.core.visual.policy import compile_image_prompt, default_visual_policy
from story_auto.providers.pexels.client import PexelsError, select_candidate


HYBRID_BODY_VERSION = "story-auto-hybrid-body-plan/1.0.0"
HYBRID_BODY_PATH = "output/hybrid_body_plan.json"
_IMAGE_EFFECTS = ("ZOOM_IN", "ZOOM_OUT", "PAN_LEFT", "PAN_RIGHT", "SLOW_PUSH")
_STOPWORDS = {
    "the", "and", "that", "this", "with", "from", "into", "then", "when", "where", "while",
    "một", "những", "các", "và", "của", "trong", "khi", "với", "đang", "được", "này", "đó", "cho",
    "nhưng", "rồi", "thì", "lại", "vào", "ra", "từ", "trên", "dưới", "cùng", "vẫn",
}


class HybridBodyError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(failure_class + (f": {detail}" if detail else ""))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_project(runtime_root: Path | str, project_id: str):
    runtime = RuntimeLayout.from_root(runtime_root)
    paths, config = load_project(runtime, project_id)
    if config.render_mode != "hybrid_hook":
        raise HybridBodyError("HYBRID_BODY_MODE_INVALID")
    return paths, config


def _target(config) -> MediaTarget:
    render = config.settings.get("render", {}) if isinstance(config.settings, dict) else {}
    try:
        return MediaTarget(int(render.get("width", 1920)), int(render.get("height", 1080)),
                           int(render.get("fps", 30)), str(render.get("pixel_format", "yuv420p")))
    except Exception as error:
        raise HybridBodyError("HYBRID_RENDER_SETTINGS_INVALID") from error


def _semantic_text(segments: list[dict[str, Any]], start: float, end: float) -> str:
    texts = []
    for segment in segments:
        try:
            seg_start, seg_end = float(segment["start"]), float(segment["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if seg_end <= start or seg_start >= end:
            continue
        text = segment.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text.strip())
    return " ".join(texts).strip()


def semantic_stock_query(text: str, *, max_terms: int = 8) -> str:
    tokens = [token.lower() for token in re.findall(r"[^\W_]+", text, flags=re.UNICODE)
              if len(token) >= 3 and token.lower() not in _STOPWORDS]
    unique: list[str] = []
    for token in tokens:
        if token not in unique:
            unique.append(token)
        if len(unique) >= max_terms:
            break
    return " ".join(unique) if unique else "cinematic story atmosphere"


def _slot(slot_id: str, start: float, end: float, visual_type: str, semantic_context: str,
          *, effect: str | None = None) -> dict[str, Any]:
    duration = round(end - start, 6)
    value = {
        "slot_id": slot_id,
        "start": round(start, 6),
        "end": round(end, 6),
        "target_duration": duration,
        "visual_type": visual_type,
        "semantic_context": semantic_context,
        "status": "PLANNED",
        "source_asset": None,
        "normalized_asset": None,
        "replacement_history": [],
    }
    if visual_type == "IMAGE":
        value.update({"effect": effect or "SLOW_PUSH", "transition": "CROSSFADE", "fallback_policy": "BLOCK"})
    else:
        value.update({"provider": "pexels", "provider_query": semantic_stock_query(semantic_context),
                      "provider_locale": "vi-VN", "fallback_policy": "IMAGE",
                      "provider_selection": None, "attribution": None})
    return value


def build_hybrid_body_plan(runtime_root: Path | str, project_id: str, *, image_slot_seconds: float = 6.0,
                           images_per_block: int = 3, stock_slot_seconds: float = 7.0) -> dict[str, Any]:
    """Build exact, non-overlapping body slots from the master alignment clock."""
    paths, config = _require_project(runtime_root, project_id)
    opening = opening_builder_view(runtime_root, project_id)
    if not opening or opening.get("status") == "NOT_CONFIGURED":
        raise HybridBodyError("HYBRID_OPENING_NOT_CONFIGURED")
    try:
        image_seconds = float(image_slot_seconds)
        stock_seconds = float(stock_slot_seconds)
        image_count = int(images_per_block)
    except (TypeError, ValueError) as error:
        raise HybridBodyError("HYBRID_RECIPE_INVALID") from error
    if not (4.0 <= image_seconds <= 7.0) or not (2 <= image_count <= 5) or not (5.0 <= stock_seconds <= 10.0):
        raise HybridBodyError("HYBRID_RECIPE_INVALID")
    alignment_path = paths.artifact_path("output/alignment.json")
    if not alignment_path.is_file():
        raise HybridBodyError("HYBRID_ALIGNMENT_MISSING")
    try:
        alignment = read_json(alignment_path)
        total = float(alignment["duration_seconds"])
        segments = [item for item in alignment.get("segments", []) if isinstance(item, dict)]
    except Exception as error:
        raise HybridBodyError("HYBRID_ALIGNMENT_INVALID") from error
    opening_end = float(opening.get("opening_duration_seconds") or 0.0)
    if total <= opening_end + .05:
        raise HybridBodyError("HYBRID_BODY_EMPTY")
    cursor = opening_end
    slots: list[dict[str, Any]] = []
    sequence = 1
    image_effect_index = 0
    while cursor < total - .001:
        for image_index in range(image_count):
            remaining = total - cursor
            if remaining <= .001:
                break
            duration = min(image_seconds, remaining)
            # If consuming another image would eliminate the stock beat, stop
            # the image block early after at least one image and reserve >=5s.
            if image_index > 0 and remaining >= 5.0 and remaining - duration < 5.0:
                break
            end = cursor + duration
            context = _semantic_text(segments, cursor, end)
            slots.append(_slot(f"BODY_{sequence:04d}", cursor, end, "IMAGE", context,
                               effect=_IMAGE_EFFECTS[image_effect_index % len(_IMAGE_EFFECTS)]))
            sequence += 1
            image_effect_index += 1
            cursor = end
        remaining = total - cursor
        if remaining < 5.0 - .001:
            continue
        duration = min(stock_seconds, remaining)
        # A final remainder below ~2s is visually awkward as its own still; let
        # the stock clip absorb it only while staying inside the 10s contract.
        tail = remaining - duration
        if 0 < tail < 2.0 and remaining <= 10.0:
            duration = remaining
        end = cursor + duration
        context = _semantic_text(segments, cursor, end)
        slots.append(_slot(f"BODY_{sequence:04d}", cursor, end, "STOCK_VIDEO", context))
        sequence += 1
        cursor = end
    for previous, current in zip(slots, slots[1:]):
        if abs(float(previous["end"]) - float(current["start"])) > .001:
            raise HybridBodyError("HYBRID_SLOT_TIMELINE_INVALID")
    target = _target(config)
    plan = {
        "schema_version": HYBRID_BODY_VERSION,
        "project_id": project_id,
        "render_mode": "hybrid_hook",
        "status": "PLANNED",
        "master_duration_seconds": total,
        "opening_end_seconds": opening_end,
        "recipe": {"image_slot_seconds": image_seconds, "images_per_block": image_count,
                   "stock_slot_seconds": stock_seconds, "pattern": "IMAGES_THEN_STOCK"},
        "render_target": {"width": target.width, "height": target.height, "fps": target.fps,
                          "pixel_format": target.pixel_format},
        "slots": slots,
        "created_at": _now(),
        "updated_at": _now(),
    }
    with ProjectLock(paths.runtime, project_id):
        path = paths.artifact_path(HYBRID_BODY_PATH)
        if path.is_file():
            old = read_json(path)
            if any(isinstance(item, dict) and (item.get("provider_selection") or item.get("normalized_asset"))
                   for item in old.get("slots", [])):
                raise HybridBodyError("HYBRID_BODY_PLAN_LOCKED")
        atomic_write_json(path, plan)
    return deepcopy(plan)


def hybrid_body_view(runtime_root: Path | str, project_id: str) -> dict[str, Any] | None:
    paths, _config = _require_project(runtime_root, project_id)
    path = paths.artifact_path(HYBRID_BODY_PATH)
    if not path.is_file():
        return None
    value = read_json(path)
    if value.get("schema_version") != HYBRID_BODY_VERSION or value.get("project_id") != project_id:
        raise HybridBodyError("HYBRID_BODY_PLAN_INVALID")
    return deepcopy(value)


def apply_pexels_search_result(runtime_root: Path | str, project_id: str, slot_id: str,
                               search_result: dict[str, Any]) -> dict[str, Any]:
    """Persist one deterministic Pexels candidate; no network/download occurs here."""
    paths, config = _require_project(runtime_root, project_id)
    target = _target(config)
    with ProjectLock(paths.runtime, project_id):
        path = paths.artifact_path(HYBRID_BODY_PATH)
        if not path.is_file():
            raise HybridBodyError("HYBRID_BODY_PLAN_MISSING")
        plan = read_json(path)
        slot = next((item for item in plan.get("slots", []) if isinstance(item, dict) and item.get("slot_id") == slot_id), None)
        if slot is None or slot.get("visual_type") != "STOCK_VIDEO":
            raise HybridBodyError("HYBRID_STOCK_SLOT_INVALID")
        if slot.get("provider_selection"):
            return deepcopy(plan)
        if str(search_result.get("query") or "").strip().lower() != str(slot.get("provider_query") or "").strip().lower():
            raise HybridBodyError("HYBRID_STOCK_QUERY_MISMATCH")
        used = {str(item.get("provider_selection", {}).get("provider_asset_id"))
                for item in plan.get("slots", []) if isinstance(item, dict) and isinstance(item.get("provider_selection"), dict)}
        try:
            selected = select_candidate(search_result, slot_id=slot_id, used_asset_ids=used,
                                        target_duration=float(slot["target_duration"]),
                                        target_width=target.width, target_height=target.height)
        except PexelsError as error:
            slot.update({"status": "FALLBACK_IMAGE_REQUIRED", "failure_class": error.failure_class})
            plan["updated_at"] = _now()
            atomic_write_json(path, plan)
            return deepcopy(plan)
        slot["provider_selection"] = selected
        slot["attribution"] = deepcopy(selected.get("attribution"))
        slot["search_observation"] = {"query": search_result.get("query"), "locale": search_result.get("locale"),
                                      "cache_key": search_result.get("cache_key"), "cache_hit": search_result.get("cache_hit"),
                                      "rate_limit": deepcopy(search_result.get("rate_limit"))}
        slot["status"] = "SELECTED"
        slot["failure_class"] = None
        slot["selected_at"] = _now()
        plan["updated_at"] = _now()
        atomic_write_json(path, plan)
        return deepcopy(plan)


def adopt_hybrid_body_image(runtime_root: Path | str, project_id: str, slot_id: str,
                            source_path: Path | str, *, original_filename: str | None = None,
                            as_stock_fallback: bool = False) -> dict[str, Any]:
    """Bind one explicit local image to an IMAGE slot or STOCK_VIDEO fallback."""
    source = Path(source_path)
    if not source.is_file():
        raise HybridBodyError("HYBRID_IMAGE_SOURCE_MISSING")
    try:
        with Image.open(source) as image:
            width, height = image.size
            image.verify()
    except Exception as error:
        raise HybridBodyError("HYBRID_IMAGE_SOURCE_INVALID") from error
    if width <= 0 or height <= 0:
        raise HybridBodyError("HYBRID_IMAGE_SOURCE_INVALID")
    paths, _config = _require_project(runtime_root, project_id)
    with ProjectLock(paths.runtime, project_id):
        plan_path = paths.artifact_path(HYBRID_BODY_PATH)
        if not plan_path.is_file():
            raise HybridBodyError("HYBRID_BODY_PLAN_MISSING")
        plan = read_json(plan_path)
        slot = next((item for item in plan.get("slots", []) if isinstance(item, dict) and item.get("slot_id") == slot_id), None)
        if slot is None:
            raise HybridBodyError("HYBRID_BODY_SLOT_INVALID")
        if as_stock_fallback:
            if slot.get("visual_type") != "STOCK_VIDEO":
                raise HybridBodyError("HYBRID_STOCK_SLOT_INVALID")
            asset_key = "fallback_image_asset"
            history_key = "fallback_replacement_history"
        else:
            if slot.get("visual_type") != "IMAGE":
                raise HybridBodyError("HYBRID_IMAGE_SLOT_INVALID")
            asset_key = "source_asset"
            history_key = "replacement_history"
        digest = sha256_file(source)
        suffix = source.suffix.lower() if source.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} else ".png"
        kind = "fallback" if as_stock_fallback else "image"
        relative = f"assets/hybrid/images/{slot_id}/{kind}_{digest[:12]}{suffix}"
        destination = paths.artifact_path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        previous = deepcopy(slot.get(asset_key))
        if not destination.is_file() or sha256_file(destination) != digest:
            shutil.copy2(source, destination)
        asset = {"path": relative, "sha256": sha256_file(destination),
                 "original_filename": Path(original_filename or source.name).name,
                 "width": width, "height": height, "bound_at": _now()}
        if previous and previous.get("sha256") != asset["sha256"]:
            history = slot.setdefault(history_key, [])
            history.append({"asset": previous, "replaced_at": _now()})
        slot[asset_key] = asset
        if as_stock_fallback and slot.get("status") != "READY":
            slot["status"] = "FALLBACK_IMAGE_READY"
        elif not as_stock_fallback:
            slot["status"] = "IMAGE_READY"
        plan["updated_at"] = _now()
        atomic_write_json(plan_path, plan)
        return deepcopy(plan)


def adopt_pexels_stock_video(runtime_root: Path | str, project_id: str, slot_id: str,
                             source_path: Path | str) -> dict[str, Any]:
    """Normalize downloaded selected Pexels bytes into a silent slot asset."""
    source = Path(source_path)
    if not source.is_file():
        raise HybridBodyError("HYBRID_STOCK_SOURCE_MISSING")
    paths, config = _require_project(runtime_root, project_id)
    target = _target(config)
    try:
        source_meta = probe_media(source)
    except MediaError as error:
        raise HybridBodyError("HYBRID_STOCK_MEDIA_INVALID", error.failure_class) from error
    if not isinstance(source_meta.get("video"), dict):
        raise HybridBodyError("HYBRID_STOCK_VIDEO_REQUIRED")
    with ProjectLock(paths.runtime, project_id):
        plan_path = paths.artifact_path(HYBRID_BODY_PATH)
        if not plan_path.is_file():
            raise HybridBodyError("HYBRID_BODY_PLAN_MISSING")
        plan = read_json(plan_path)
        slot = next((item for item in plan.get("slots", []) if isinstance(item, dict) and item.get("slot_id") == slot_id), None)
        if slot is None or slot.get("visual_type") != "STOCK_VIDEO" or not isinstance(slot.get("provider_selection"), dict):
            raise HybridBodyError("HYBRID_STOCK_SELECTION_REQUIRED")
        duration = float(slot["target_duration"])
        if float(source_meta["duration_seconds"]) + .05 < duration:
            raise HybridBodyError("HYBRID_STOCK_SOURCE_TOO_SHORT")
        asset_id = str(slot["provider_selection"].get("provider_asset_id") or "unknown")
        source_sha = str(source_meta["sha256"])
        source_rel = f"assets/hybrid/stock/{slot_id}/pexels_{asset_id}_{source_sha[:12]}{source.suffix.lower() or '.mp4'}"
        normalized_rel = f"assets/hybrid/normalized/{slot_id}.mp4"
        durable_source = paths.artifact_path(source_rel)
        normalized = paths.artifact_path(normalized_rel)
        durable_source.parent.mkdir(parents=True, exist_ok=True)
        normalized.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, durable_source)
        try:
            normalized_meta = compile_video(durable_source, normalized, duration=duration, short_policy="BLOCK", target=target)
        except Exception:
            durable_source.unlink(missing_ok=True)
            normalized.unlink(missing_ok=True)
            raise
        slot["source_asset"] = {"path": source_rel, "sha256": sha256_file(durable_source),
                                "duration_seconds": source_meta["duration_seconds"], "downloaded_at": _now()}
        slot["normalized_asset"] = {"path": normalized_rel, "sha256": normalized_meta["sha256"],
                                    "duration_seconds": normalized_meta["duration_seconds"],
                                    "width": normalized_meta["video"]["width"], "height": normalized_meta["video"]["height"],
                                    "frame_rate": normalized_meta["video"]["frame_rate"], "audio_stripped": True,
                                    "normalized_at": _now()}
        slot["status"] = "READY"
        plan["updated_at"] = _now()
        atomic_write_json(plan_path, plan)
        return deepcopy(plan)


def compile_hybrid_body_generation_requests(runtime_root: Path | str, project_id: str) -> dict[str, Any]:
    """Create canonical Flow IMAGE requests only for Hybrid body image slots."""
    paths, _config = _require_project(runtime_root, project_id)
    plan_path = paths.artifact_path(HYBRID_BODY_PATH)
    if not plan_path.is_file():
        raise HybridBodyError("HYBRID_BODY_PLAN_MISSING")
    with ProjectLock(paths.runtime, project_id):
        plan = read_json(plan_path)
        policy = default_visual_policy()
        requests: list[dict[str, Any]] = []
        for index, slot in enumerate(plan.get("slots", []), 1):
            if not isinstance(slot, dict) or slot.get("visual_type") != "IMAGE":
                continue
            semantic = str(slot.get("semantic_context") or "Narrated story moment").strip()
            request_id = "req_hybrid_" + hashlib.sha256(
                f"{project_id}|{slot.get('slot_id')}|{semantic}".encode("utf-8")
            ).hexdigest()[:20]
            prompt = compile_image_prompt(
                f"Cinematic 16:9 story illustration for this narration beat: {semantic}. "
                "No text, lettering, subtitles, logo, watermark, collage, or split screen.",
                policy,
            )
            slot["generation_request_id"] = request_id
            slot["generation_prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            requests.append({
                "request_id": request_id,
                "purpose": "SHOT",
                "shot_id": str(slot.get("slot_id")),
                "media_type": "IMAGE",
                "requirement": "REQUIRED",
                "provider": "google_flow",
                "prompt": prompt,
                "visual_policy": policy,
                "output_count": 1,
                "execution_tier": "STANDARD_PRODUCTION",
                "reference_asset_ids": [],
                "depends_on": [],
                "part_index": 1,
                "part_count": 1,
                "target_start": float(slot["start"]),
                "target_end": float(slot["end"]),
                "target_duration": float(slot["target_duration"]),
                "aspect_ratio": "16:9",
                "priority": 1,
                "fingerprint": hashlib.sha256(
                    f"{request_id}|{slot.get('generation_prompt_sha256')}".encode("utf-8")
                ).hexdigest(),
            })
        if not requests:
            raise HybridBodyError("HYBRID_BODY_IMAGE_REQUESTS_EMPTY")
        value = {
            "schema_version": "story-auto-generation-requests/1.0.0",
            "project_id": project_id,
            "prompt_version": "hybrid-body-image-cuj/1.0.0",
            "requests": requests,
            "guardrail_estimate": {
                "reference_image_requests": 0,
                "shot_image_requests": len(requests),
                "required_video_requests": 0,
                "preferred_video_requests": 0,
                "total_generation_requests": len(requests),
                "max_attempts_per_request": 2,
                "worst_case_attempt_count": len(requests) * 2,
                "large_batch_request_threshold": 20,
                "requires_later_execution_confirmation": False,
            },
            "provider_execution_authorized": True,
            "review_status": "VALIDATED",
            "hybrid_body_plan_sha256": sha256_file(plan_path),
        }
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), value)
        plan["updated_at"] = _now()
        atomic_write_json(plan_path, plan)
        return deepcopy(value)


def sync_hybrid_body_generated_images(runtime_root: Path | str, project_id: str) -> dict[str, Any]:
    """Bind Flow-selected IMAGE bytes back to exact Hybrid body slots."""
    paths, _config = _require_project(runtime_root, project_id)
    manifest_path = paths.artifact_path("output/generation_manifest.json")
    plan_path = paths.artifact_path(HYBRID_BODY_PATH)
    if not plan_path.is_file():
        raise HybridBodyError("HYBRID_BODY_PLAN_MISSING")
    manifest = read_json(manifest_path) if manifest_path.is_file() else {"requests": []}
    entries = {str(item.get("request_id")): item for item in manifest.get("requests", []) if isinstance(item, dict)}
    with ProjectLock(paths.runtime, project_id):
        plan = read_json(plan_path)
        changed = False
        for slot in plan.get("slots", []):
            if not isinstance(slot, dict) or slot.get("visual_type") != "IMAGE":
                continue
            request_id = slot.get("generation_request_id")
            entry = entries.get(str(request_id)) if request_id else None
            asset = entry.get("selected_asset") if isinstance(entry, dict) else None
            if not isinstance(asset, dict):
                continue
            relative, digest = asset.get("path"), asset.get("sha256")
            if not isinstance(relative, str) or not isinstance(digest, str):
                continue
            source = paths.artifact_path(relative)
            if not source.is_file() or sha256_file(source) != digest:
                continue
            current = slot.get("source_asset") if isinstance(slot.get("source_asset"), dict) else None
            if current and current.get("sha256") == digest:
                continue
            try:
                with Image.open(source) as image:
                    width, height = image.size
            except Exception:
                continue
            slot["source_asset"] = {
                "path": relative,
                "sha256": digest,
                "original_filename": source.name,
                "width": width,
                "height": height,
                "bound_at": _now(),
                "source": "FLOW_GENERATION",
                "generation_request_id": request_id,
            }
            slot["status"] = "IMAGE_READY"
            changed = True
        if changed:
            plan["updated_at"] = _now()
            atomic_write_json(plan_path, plan)
        return deepcopy(plan)


def fill_hybrid_stock_image_fallbacks(runtime_root: Path | str, project_id: str) -> dict[str, Any]:
    """Use an already-generated body image as deterministic stock fallback."""
    paths, _config = _require_project(runtime_root, project_id)
    plan_path = paths.artifact_path(HYBRID_BODY_PATH)
    if not plan_path.is_file():
        raise HybridBodyError("HYBRID_BODY_PLAN_MISSING")
    with ProjectLock(paths.runtime, project_id):
        plan = read_json(plan_path)
        image_assets = [slot.get("source_asset") for slot in plan.get("slots", [])
                        if isinstance(slot, dict) and slot.get("visual_type") == "IMAGE"
                        and isinstance(slot.get("source_asset"), dict)]
        valid_assets = [asset for asset in image_assets
                        if isinstance(asset.get("path"), str) and isinstance(asset.get("sha256"), str)
                        and paths.artifact_path(asset["path"]).is_file()
                        and sha256_file(paths.artifact_path(asset["path"])) == asset["sha256"]]
        if not valid_assets:
            return deepcopy(plan)
        stock_index = 0
        changed = False
        for slot in plan.get("slots", []):
            if not isinstance(slot, dict) or slot.get("visual_type") != "STOCK_VIDEO":
                continue
            normalized = slot.get("normalized_asset")
            if slot.get("status") == "READY" and isinstance(normalized, dict):
                continue
            fallback = slot.get("fallback_image_asset")
            if isinstance(fallback, dict) and isinstance(fallback.get("path"), str):
                local = paths.artifact_path(fallback["path"])
                if local.is_file() and sha256_file(local) == fallback.get("sha256"):
                    continue
            chosen = deepcopy(valid_assets[stock_index % len(valid_assets)])
            chosen["source"] = "HYBRID_AUTOMATIC_IMAGE_FALLBACK"
            chosen["bound_at"] = _now()
            slot["fallback_image_asset"] = chosen
            slot["status"] = "FALLBACK_IMAGE_READY"
            stock_index += 1
            changed = True
        if changed:
            plan["updated_at"] = _now()
            atomic_write_json(plan_path, plan)
        return deepcopy(plan)

"""Publishing metadata and thumbnail provenance using established providers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.checkpoint import CheckpointStore, fingerprint
from story_auto.core.content import parse_content_markdown
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock
from story_auto.core.visual import DEFAULT_VISUAL_POLICY, compile_image_prompt
from story_auto.providers.flow.validation import validate_image
from story_auto.providers.llm.gemini import GeminiProvider, LLMRequest


PUBLISHING_VERSION = "story-auto-publishing/1.0.0"
PUBLISHING_SCHEMA_VERSION = "story-auto-publishing-package/1.0.0"
PUBLISHING_PROMPT_VERSION = "story-auto-publishing-prompt/1.0.0"
THUMBNAIL_PROMPT_VERSION = "story-auto-thumbnail-prompt/1.0.0"


class PublishingError(RuntimeError):
    def __init__(self, failure_class: str, detail: str = "") -> None:
        self.failure_class = failure_class
        super().__init__(failure_class + (f": {detail}" if detail else ""))


def _hash(value: Any) -> str:
    content = value if isinstance(value, str) else json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(content.encode()).hexdigest()


def _schema() -> dict[str, Any]:
    return {"type": "object", "properties": {
        "title_candidates": {"type": "array", "items": {"type": "string"}},
        "description": {"type": "string"},
        "thumbnail_brief": {"type": "string"},
    }, "required": ["title_candidates", "description", "thumbnail_brief"]}


def run_publishing_metadata(runtime_root: Path | str, project_id: str, *, provider: GeminiProvider | None = None) -> str:
    paths, config = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    llm = config.settings.get("llm", {})
    if not isinstance(llm, dict) or llm.get("provider") != "gemini":
        raise PublishingError("PUBLISHING_LLM_NOT_CONFIGURED")
    model = str(llm.get("model", "gemini-3.5-flash"))
    narration = parse_content_markdown(paths.content_file.read_text(encoding="utf-8")).narration
    final_manifest = read_json(paths.artifact_path("output/final_manifest.json"))
    direct = {"narration_sha256": _hash(narration), "final_sha256": final_manifest["final_sha256"],
              "prompt_version": PUBLISHING_PROMPT_VERSION, "model": model}
    stage_fp = fingerprint(stage_name="publishing_metadata", producer_version=PUBLISHING_VERSION,
                           artifact_schema_version=PUBLISHING_SCHEMA_VERSION, direct_inputs=direct,
                           settings={key: value for key, value in llm.items() if key not in {"api_key", "key", "token", "secret"}})
    package_path = paths.artifact_path("output/publishing_package.json")
    with ProjectLock(paths.runtime, project_id):
        checkpoints = CheckpointStore(paths)
        if checkpoints.decide("publishing_metadata", stage_fp).action == "SKIP" and package_path.is_file():
            current = read_json(package_path)
            if current.get("title_candidates") and current.get("description"):
                return "SKIP"
        active = provider or GeminiProvider()
        response = active.generate_structured(LLMRequest(
            model=model,
            prompt=(f"{PUBLISHING_PROMPT_VERSION}\nCreate 3 accurate, compelling YouTube title candidates, a useful description, "
                    f"and a cinematic 16:9 thumbnail brief. Do not invent events absent from the narration.\nNarration:\n{narration}"),
            response_schema=_schema(), settings=llm, request_id=_hash(stage_fp)[:24], stage="publishing_metadata",
        ))
        value = response.value
        titles = [str(item).strip() for item in value.get("title_candidates", []) if str(item).strip()]
        description, brief = str(value.get("description", "")).strip(), str(value.get("thumbnail_brief", "")).strip()
        if not titles or not description or not brief:
            raise PublishingError("PUBLISHING_METADATA_INVALID")
        prior = read_json(package_path) if package_path.is_file() else {}
        package = {"schema_version": PUBLISHING_SCHEMA_VERSION, "project_id": project_id,
                   "title_candidates": titles, "selected_title": titles[0], "description": description,
                   "thumbnail": {"brief": brief, **({key: value for key, value in prior.get("thumbnail", {}).items()
                                                        if key in {"request_id", "path", "sha256", "metadata"}})},
                   "approved": False,
                   "provenance": {"provider": "gemini", "model": model, "prompt_version": PUBLISHING_PROMPT_VERSION,
                                  "request_id": response.request_id, "usage": response.usage}}
        atomic_write_json(package_path, package)
        checkpoints.record("publishing_metadata", fingerprint=stage_fp, status="SUCCESS",
                           outputs=["output/publishing_package.json"], producer_version=PUBLISHING_VERSION)
    return "RUN"


def prepare_thumbnail_request(runtime_root: Path | str, project_id: str) -> dict[str, Any]:
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    package_path = paths.artifact_path("output/publishing_package.json")
    request_path = paths.artifact_path("output/generation_requests.json")
    manifest_path = paths.artifact_path("output/generation_manifest.json")
    with ProjectLock(paths.runtime, project_id):
        package, requests, manifest = read_json(package_path), read_json(request_path), read_json(manifest_path)
        reference_ids = {item.get("request_id") for item in requests.get("requests", []) if item.get("purpose") == "REFERENCE"}
        succeeded = {item.get("request_id") for item in manifest.get("requests", []) if item.get("status") == "SUCCEEDED" and item.get("selected_asset")}
        dependencies = sorted(reference_ids & succeeded)[:3]
        seed = {"project_id": project_id, "brief": package["thumbnail"]["brief"], "title": package["selected_title"],
                "dependencies": dependencies, "prompt_version": THUMBNAIL_PROMPT_VERSION}
        identity = _hash(seed)
        request_id = "req_thumbnail_" + identity[:16]
        request = {"request_id": request_id, "purpose": "THUMBNAIL", "shot_id": None, "entity_id": None,
                   "media_type": "IMAGE", "requirement": "REQUIRED", "provider": "google_flow",
                   "prompt": compile_image_prompt(f"{package['thumbnail']['brief']}. No text, lettering, or logos", dict(DEFAULT_VISUAL_POLICY)),
                   "visual_policy": dict(DEFAULT_VISUAL_POLICY), "output_count": 1,
                   "reference_asset_ids": dependencies, "depends_on": dependencies, "target_duration": None,
                   "aspect_ratio": "16:9", "priority": 3, "fingerprint": identity, "execution_tier": "STANDARD_PRODUCTION"}
        prior = [item for item in requests.get("requests", []) if item.get("purpose") != "THUMBNAIL" or item.get("request_id") == request_id]
        if not any(item.get("request_id") == request_id for item in prior):
            prior.append(request)
        requests["requests"] = prior
        package["thumbnail"]["request_id"] = request_id
        atomic_write_json(request_path, requests)
        atomic_write_json(package_path, package)
        return request


def finalize_thumbnail(runtime_root: Path | str, project_id: str) -> str:
    paths, _ = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    package_path = paths.artifact_path("output/publishing_package.json")
    final_manifest_path = paths.artifact_path("output/final_manifest.json")
    with ProjectLock(paths.runtime, project_id):
        package, manifest = read_json(package_path), read_json(paths.artifact_path("output/generation_manifest.json"))
        request_id = package.get("thumbnail", {}).get("request_id")
        entry = next((item for item in manifest.get("requests", []) if item.get("request_id") == request_id), None)
        if not entry or entry.get("status") != "SUCCEEDED" or not isinstance(entry.get("selected_asset"), dict):
            raise PublishingError("THUMBNAIL_REQUIRED_MEDIA_UNRESOLVED")
        selected = entry["selected_asset"]
        if selected.get("production_qc") != "APPROVED":
            raise PublishingError("THUMBNAIL_PRODUCTION_QC_REQUIRED")
        metadata = validate_image(paths.artifact_path(selected["path"]))
        if metadata["sha256"] != selected.get("sha256"):
            raise PublishingError("THUMBNAIL_ASSET_INVALID")
        package["thumbnail"].update({"path": selected["path"], "sha256": selected["sha256"], "metadata": metadata,
                                     "provider": "google_flow", "attempt": selected.get("attempt")})
        atomic_write_json(package_path, package)
        if final_manifest_path.is_file():
            final_manifest = read_json(final_manifest_path)
            final_manifest["publishing_package_sha256"] = sha256_file(package_path)
            atomic_write_json(final_manifest_path, final_manifest)
    return "RUN"

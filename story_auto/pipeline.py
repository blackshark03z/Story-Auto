"""The single real foundation stage: content.md to content_manifest.json."""

from __future__ import annotations

from pathlib import Path

from story_auto.core.artifacts import atomic_write_json
from story_auto.core.checkpoint import CheckpointStore, fingerprint
from story_auto.core.content import ContentValidationError, narration_hash, parse_content_markdown
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock

CONTENT_PRODUCER_VERSION = "story-auto-content-stage/1.0.0"
CONTENT_MANIFEST_SCHEMA_VERSION = "story-auto-content-manifest/1.0.0"


def run_content_stage(runtime_root: Path | str, project_id: str) -> str:
    paths, config = load_project(RuntimeLayout.from_root(runtime_root), project_id)
    if not paths.content_file.is_file():
        raise ContentValidationError(f"missing content.md: {paths.content_file}")
    try:
        source = paths.content_file.read_text(encoding="utf-8")
    except OSError as error:
        raise ContentValidationError(f"could not read content.md: {paths.content_file}") from error
    narration = parse_content_markdown(source).narration
    narration_sha256 = narration_hash(narration)
    stage_fingerprint = fingerprint(stage_name="content", producer_version=CONTENT_PRODUCER_VERSION,
                                    artifact_schema_version=CONTENT_MANIFEST_SCHEMA_VERSION,
                                    direct_inputs={"narration_sha256": narration_sha256}, settings={})
    with ProjectLock(paths.runtime, project_id):
        checkpoints = CheckpointStore(paths)
        decision = checkpoints.decide("content", stage_fingerprint)
        if decision.action == "SKIP":
            return "SKIP"
        output = "output/content_manifest.json"
        try:
            atomic_write_json(paths.artifact_path(output), {
                "schema_version": CONTENT_MANIFEST_SCHEMA_VERSION, "narration_sha256": narration_sha256,
                "character_count": len(narration), "paragraph_count": len(narration.split("\n\n")),
            })
            checkpoints.record("content", fingerprint=stage_fingerprint, status="SUCCESS", outputs=[output], producer_version=CONTENT_PRODUCER_VERSION)
        except Exception:
            checkpoints.record("content", fingerprint=stage_fingerprint, status="FAILED", outputs=[], producer_version=CONTENT_PRODUCER_VERSION)
            raise
    return "RUN"

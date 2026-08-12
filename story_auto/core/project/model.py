"""Small, versioned project contract for Story Auto's local runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from story_auto.core.artifacts import atomic_write_json, read_json
from .paths import ProjectPaths, RuntimeLayout


PROJECT_SCHEMA_VERSION = "story-auto-project/1.0.0"
RENDER_MODES = frozenset({"hybrid_hook", "full_video_ai"})


class ProjectValidationError(ValueError):
    failure_class = "PROJECT_INVALID"


@dataclass(frozen=True)
class ProjectConfig:
    project_id: str
    content_path: str = "content.md"
    render_mode: str = "hybrid_hook"
    settings: dict[str, Any] = field(default_factory=dict)
    schema_version: str = PROJECT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PROJECT_SCHEMA_VERSION:
            raise ProjectValidationError(f"unsupported project schema_version: {self.schema_version!r}")
        if self.render_mode not in RENDER_MODES:
            raise ProjectValidationError(f"invalid render_mode: {self.render_mode!r}")
        if self.content_path != "content.md":
            raise ProjectValidationError("content_path must be the project-relative content.md")
        if not isinstance(self.settings, dict):
            raise ProjectValidationError("settings must be a JSON object")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "project_id": self.project_id,
                "content_path": self.content_path, "render_mode": self.render_mode,
                "settings": self.settings}

    @classmethod
    def from_dict(cls, value: Any) -> "ProjectConfig":
        if not isinstance(value, dict) or set(value) != {"schema_version", "project_id", "content_path", "render_mode", "settings"}:
            raise ProjectValidationError("project.json must contain only the required project contract fields")
        try:
            return cls(**value)
        except TypeError as error:
            raise ProjectValidationError("project.json has invalid field types") from error


def create_project(runtime: RuntimeLayout, config: ProjectConfig, narration_template: str = "# Story\n\n## Narration\n\nWrite narration here.\n") -> ProjectPaths:
    paths = ProjectPaths(runtime.ensure(), config.project_id)
    if paths.root.exists():
        raise ProjectValidationError(f"project already exists: {config.project_id}")
    paths.root.mkdir(parents=True)
    (paths.root / "output").mkdir()
    (paths.root / "logs").mkdir()
    atomic_write_json(paths.project_file, config.to_dict())
    from story_auto.core.artifacts import atomic_write_text
    atomic_write_text(paths.content_file, narration_template)
    return paths


def load_project(runtime: RuntimeLayout, project_id: str) -> tuple[ProjectPaths, ProjectConfig]:
    paths = ProjectPaths(runtime.ensure(), project_id)
    if not paths.project_file.is_file():
        raise ProjectValidationError(f"missing project.json for project {project_id}")
    try:
        config = ProjectConfig.from_dict(read_json(paths.project_file))
    except (ProjectValidationError, OSError) as error:
        raise ProjectValidationError(f"invalid project configuration at {paths.project_file}") from error
    if config.project_id != project_id:
        raise ProjectValidationError("project.json project_id does not match project directory")
    return paths, config

"""Small, versioned project contract for Story Auto's local runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Any

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.visual.ambient import AMBIENT_STYLES
from .execution import execution_mode
from .quality_policy import QC_POLICY_SETTING, validate_qc_policy, settings_with_default_qc_policy
from .paths import ProjectPaths, RuntimeLayout


PROJECT_SCHEMA_VERSION = "story-auto-project/1.0.0"
RENDER_MODES = frozenset({"hybrid_hook", "full_video_ai", "ambient_story", "full_image"})
TTS_PROVIDERS = frozenset({"elevenlabs", "typecast", "kokoro_local"})
FULL_IMAGE_CADENCES = frozenset({"SEMANTIC_ADAPTIVE", "FIXED"})
FULL_IMAGE_MOTION = "AUTO_CONTINUOUS_ZOOM"
FULL_IMAGE_ZOOM_MIN_SCALE = 1.0
FULL_IMAGE_ZOOM_MAX_SCALE = 1.16


def full_image_motion_spec(direction: str) -> dict[str, object]:
    """Return the single canonical still-camera contract for FULL_IMAGE."""
    if direction == "ZOOM_IN":
        start_scale, end_scale = FULL_IMAGE_ZOOM_MIN_SCALE, FULL_IMAGE_ZOOM_MAX_SCALE
    elif direction == "ZOOM_OUT":
        start_scale, end_scale = FULL_IMAGE_ZOOM_MAX_SCALE, FULL_IMAGE_ZOOM_MIN_SCALE
    else:
        raise ProjectValidationError("FULL_IMAGE_MOTION_DIRECTION_INVALID")
    return {"mode": FULL_IMAGE_MOTION, "direction": direction,
            "start_scale": start_scale, "end_scale": end_scale, "easing": "SMOOTH"}


def resolve_full_image_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical, seconds-based FULL_IMAGE configuration."""
    raw = settings.get("full_image", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict) or not set(raw).issubset({"image_duration_seconds", "cadence", "motion", "audio_visualizer"}):
        raise ProjectValidationError("settings.full_image has unsupported fields")
    duration = raw.get("image_duration_seconds", 30.0)
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(float(duration)) or not 5.0 <= float(duration) <= 120.0:
        raise ProjectValidationError("settings.full_image.image_duration_seconds must be between 5 and 120 seconds")
    cadence = raw.get("cadence", "SEMANTIC_ADAPTIVE")
    if cadence not in FULL_IMAGE_CADENCES:
        raise ProjectValidationError("settings.full_image.cadence must be SEMANTIC_ADAPTIVE or FIXED")
    if raw.get("motion", FULL_IMAGE_MOTION) != FULL_IMAGE_MOTION:
        raise ProjectValidationError("settings.full_image.motion must be AUTO_CONTINUOUS_ZOOM")
    visualizer = raw.get("audio_visualizer", True)
    if not isinstance(visualizer, bool):
        raise ProjectValidationError("settings.full_image.audio_visualizer must be boolean")
    return {"image_duration_seconds": float(duration), "cadence": cadence,
            "motion": FULL_IMAGE_MOTION, "audio_visualizer": visualizer}


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
        try:
            execution_mode(self.settings)
        except ValueError as error:
            raise ProjectValidationError(str(error)) from error
        if QC_POLICY_SETTING in self.settings:
            try:
                validate_qc_policy(self.settings[QC_POLICY_SETTING])
            except ValueError as error:
                raise ProjectValidationError(str(error)) from error
        ambient_style = self.settings.get("ambient_style")
        if self.render_mode == "ambient_story" and ambient_style not in AMBIENT_STYLES:
            raise ProjectValidationError("ambient_story requires settings.ambient_style to be quiet_verdict or hidden_mastery")
        if ambient_style is not None and ambient_style not in AMBIENT_STYLES:
            raise ProjectValidationError("settings.ambient_style must be quiet_verdict or hidden_mastery")
        if self.render_mode == "full_image":
            object.__setattr__(self, "settings", {**self.settings, "full_image": resolve_full_image_settings(self.settings)})
        tts = self.settings.get("tts")
        if tts is not None:
            if not isinstance(tts, dict) or tts.get("provider") not in TTS_PROVIDERS:
                raise ProjectValidationError("settings.tts.provider must be elevenlabs, typecast, or kokoro_local")
            if tts.get("allow_cross_provider_fallback", False) is not False:
                raise ProjectValidationError("settings.tts.allow_cross_provider_fallback must be false")
            provider = tts["provider"]
            provider_settings = tts.get(provider)
            if not isinstance(provider_settings, dict) or not isinstance(provider_settings.get("voice_id"), str) or not provider_settings["voice_id"].strip():
                raise ProjectValidationError(f"settings.tts.{provider}.voice_id is required")
        llm = self.settings.get("llm")
        if llm is not None:
            if not isinstance(llm, dict) or llm.get("provider") != "gemini":
                raise ProjectValidationError("settings.llm.provider must be gemini")
            model = llm.get("model", "gemini-3.5-flash")
            if not isinstance(model, str) or not model.strip():
                raise ProjectValidationError("settings.llm.model must be non-empty text")
            if any(key.lower() in {"api_key", "key", "token", "secret", "credential"} for key in llm):
                raise ProjectValidationError("settings.llm must not contain credentials")
        binding = self.settings.get("flow_binding")
        if binding is not None:
            if (not isinstance(binding, dict) or set(binding) != {"connection_id", "connection_revision"}
                    or not isinstance(binding["connection_id"], str) or not binding["connection_id"].startswith("flow_")
                    or not isinstance(binding["connection_revision"], int) or binding["connection_revision"] < 1):
                raise ProjectValidationError("settings.flow_binding must reference a Flow connection revision")
        project_binding = self.settings.get("flow_project_binding")
        if project_binding is not None:
            if (not isinstance(project_binding, dict) or set(project_binding) != {"project_identity", "project_url"}
                    or not isinstance(project_binding["project_identity"], str) or not project_binding["project_identity"].strip()
                    or not isinstance(project_binding["project_url"], str) or not project_binding["project_url"].strip()):
                raise ProjectValidationError("settings.flow_project_binding must retain the expected Flow project")
        provider_binding = self.settings.get("provider_binding")
        if provider_binding is not None:
            if not isinstance(provider_binding, dict) or set(provider_binding) != {"flow"}:
                raise ProjectValidationError("settings.provider_binding must contain only flow")
            flow = provider_binding.get("flow")
            required = {"state", "project_url", "project_identity", "created_for_story_project_id",
                        "project_name", "activation_state", "created_at"}
            optional = {"activation_started_at", "created_at_provider", "bound_at", "last_setup_failure", "last_setup_failure_at"}
            if (not isinstance(flow, dict) or not required.issubset(flow)
                    or not set(flow).issubset(required | optional)
                    or flow.get("state") not in {"CREATE_INTENT", "CREATED", "BOUND"}
                    or flow.get("activation_state") not in {"NOT_ATTEMPTED", "STARTED"}
                    or flow.get("created_for_story_project_id") != self.project_id
                    or not isinstance(flow.get("project_name"), str) or not flow["project_name"].strip()
                    or not isinstance(flow.get("created_at"), str) or not flow["created_at"].strip()):
                raise ProjectValidationError("settings.provider_binding.flow is invalid")
            if flow["state"] in {"CREATED", "BOUND"}:
                if (not isinstance(flow.get("project_url"), str) or not flow["project_url"].strip()
                        or not isinstance(flow.get("project_identity"), str) or not flow["project_identity"].strip()):
                    raise ProjectValidationError("settings.provider_binding.flow created project is incomplete")
            elif flow.get("project_url") is not None or flow.get("project_identity") is not None:
                raise ProjectValidationError("settings.provider_binding.flow intent cannot claim a project")
        recovery = self.settings.get("provider_recovery")
        if recovery is not None:
            seconds = recovery.get("stuck_pending_seconds") if isinstance(recovery, dict) else None
            if (not isinstance(recovery, dict) or set(recovery) != {"stuck_pending_seconds"}
                    or isinstance(seconds, bool) or not isinstance(seconds, int) or not 300 <= seconds <= 86400):
                raise ProjectValidationError("settings.provider_recovery.stuck_pending_seconds must be 300..86400")

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
    # Defaults are materialized only for new projects.  Loading an historical
    # project must not rewrite its truth or silently change its old manual gate.
    config = ProjectConfig(config.project_id, content_path=config.content_path, render_mode=config.render_mode,
                           settings=settings_with_default_qc_policy(config.settings), schema_version=config.schema_version)
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

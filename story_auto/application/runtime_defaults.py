"""Durable, non-secret defaults for new Story Auto projects.

These values are runtime-owned.  A project receives a copy when it is created,
so changing them later can never rewrite the behaviour of an existing video.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import AUTO_ACCEPT, QC_POLICIES, RuntimeLayout


RUNTIME_DEFAULTS_SCHEMA_VERSION = "story-auto-runtime-defaults/1.0.0"


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


class RuntimeDefaults:
    """Read and write the small allowlisted default payload."""

    def __init__(self, runtime: RuntimeLayout, factory):
        self.runtime = runtime.ensure()
        self.factory = factory

    @property
    def path(self):
        return self.runtime.config / "runtime_defaults.json"

    def _baseline(self) -> dict[str, Any]:
        return {
            "schema_version": RUNTIME_DEFAULTS_SCHEMA_VERSION,
            "render_mode": "full_image",
            "ambient_style": "quiet_verdict",
            "visual_style": "natural",
            "narrator": {"voice_id": "bm_george"},
            "project_settings": {
                "qc_policy": AUTO_ACCEPT,
                "ui": {"production_style": "natural"},
                "full_image": {"image_duration_seconds": 30.0, "cadence": "SEMANTIC_ADAPTIVE", "motion": "AUTO_CONTINUOUS_ZOOM", "audio_visualizer": True},
                "render": {},
            },
        }

    def read(self) -> dict[str, Any]:
        baseline = self._baseline()
        try:
            raw = read_json(self.path)
        except Exception:
            return baseline
        if not isinstance(raw, dict) or raw.get("schema_version") != RUNTIME_DEFAULTS_SCHEMA_VERSION:
            return baseline
        merged = _merge(baseline, raw)
        # Preserve an older defaults file while exposing the only supported
        # creation mode for this release.
        merged["render_mode"] = "full_image"
        return self._validate(merged)

    def update(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("runtime defaults must be an object")
        allowed = {"render_mode", "ambient_style", "visual_style", "narrator", "project_settings"}
        if not set(value).issubset(allowed):
            raise ValueError("runtime defaults contain unsupported fields")
        merged = self._validate(_merge(self.read(), value))
        atomic_write_json(self.path, merged)
        return merged

    def _validate(self, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("render_mode") != "full_image":
            raise ValueError("runtime default render mode must be full_image in this release")
        if value.get("ambient_style") not in {"quiet_verdict", "hidden_mastery"}:
            raise ValueError("runtime default ambient style is invalid")
        if value.get("visual_style") not in {"natural", "documentary"}:
            raise ValueError("runtime default visual style is invalid")
        narrator = value.get("narrator")
        if not isinstance(narrator, dict) or not isinstance(narrator.get("voice_id"), str) or not narrator["voice_id"].strip():
            raise ValueError("runtime default narrator is invalid")
        settings = value.get("project_settings")
        if not isinstance(settings, dict) or settings.get("qc_policy") not in QC_POLICIES:
            raise ValueError("runtime default quality policy is invalid")
        full_image = settings.get("full_image")
        if not isinstance(full_image, dict) or not isinstance(full_image.get("audio_visualizer"), bool):
            raise ValueError("runtime default waveform setting is invalid")
        settings.setdefault("ui", {})["production_style"] = value["visual_style"]
        value["schema_version"] = RUNTIME_DEFAULTS_SCHEMA_VERSION
        return value

    def project_snapshot(self, explicit: dict[str, Any] | None) -> dict[str, Any]:
        """Copy defaults for exactly one new project, then apply its choices."""
        value = self.read()
        snapshot = _merge(value["project_settings"], explicit or {})
        snapshot.setdefault("ui", {}).setdefault("production_style", value["visual_style"])
        return snapshot

    def creation_snapshot(self) -> dict[str, Any]:
        """Return global defaults for the New Video draft without project scans."""
        value = self.read()
        return _merge(self.factory(value["narrator"]["voice_id"]), value["project_settings"])

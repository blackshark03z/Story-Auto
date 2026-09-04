"""Canonical, runtime-owned Google Flow connection and project binding service.

The record deliberately contains no cookies, tokens, or browser profile data.
It is the only mutable Flow authority; projects hold an immutable reference to
the revision they intend to use, while provider attempts snapshot that reference.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit
import uuid

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, load_project
from .session import FlowCapabilities, FlowRuntime, FlowSessionError, preflight


CONNECTION_SCHEMA = "story-auto-flow-connection/1.0.0"
VALID_STATUSES = frozenset({"CONNECTED", "NOT_CONFIGURED", "STALE", "AUTH_REQUIRED", "PROJECT_MISMATCH", "CAPABILITY_MISSING"})


class FlowConnectionError(RuntimeError):
    failure_class = "FLOW_CONNECTION_INVALID"

    def __init__(self, code: str):
        self.failure_class = code
        super().__init__(code)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_project_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FlowConnectionError("FLOW_URL_INVALID")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise FlowConnectionError("FLOW_URL_INVALID")
    if parsed.query or parsed.fragment:
        raise FlowConnectionError("FLOW_URL_INVALID")
    path = parsed.path.rstrip("/")
    if not path or "/flow" not in path.lower():
        raise FlowConnectionError("FLOW_URL_INVALID")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def stable_project_identity(project_url: str) -> str:
    """A deterministic non-secret identity when Flow has no separate public ID."""
    return normalize_project_url(project_url)


def _capability_dict(capabilities: FlowCapabilities) -> dict[str, bool]:
    return {"IMAGE": capabilities.image, "VIDEO": capabilities.video,
            "REFERENCE_IMAGE": capabilities.reference_image, "FRAME_VIDEO": capabilities.frame_video}


def _required(values: Iterable[str] | None) -> list[str]:
    return sorted({str(value).upper() for value in (values or []) if str(value).upper() in {"IMAGE", "VIDEO", "REFERENCE_IMAGE", "FRAME_VIDEO"}})


@dataclass(frozen=True)
class FlowConnection:
    connection_id: str
    revision: int
    project_url: str
    project_identity: str
    dedicated_profile_identity: str
    validation_status: str
    validated_at: str | None
    capabilities: dict[str, bool]
    schema_version: str = CONNECTION_SCHEMA

    def __post_init__(self) -> None:
        if not self.connection_id.startswith("flow_") or self.revision < 1:
            raise FlowConnectionError("FLOW_CONNECTION_INVALID")
        if self.validation_status not in VALID_STATUSES - {"NOT_CONFIGURED"}:
            raise FlowConnectionError("FLOW_CONNECTION_INVALID")
        object.__setattr__(self, "project_url", normalize_project_url(self.project_url))
        if not isinstance(self.project_identity, str) or not self.project_identity.strip():
            raise FlowConnectionError("FLOW_CONNECTION_INVALID")
        if not isinstance(self.dedicated_profile_identity, str) or not self.dedicated_profile_identity.strip():
            raise FlowConnectionError("FLOW_CONNECTION_INVALID")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "connection_id": self.connection_id, "revision": self.revision,
                "project_url": self.project_url, "project_identity": self.project_identity,
                "dedicated_profile_identity": self.dedicated_profile_identity,
                "validation_status": self.validation_status, "validated_at": self.validated_at,
                "capabilities": self.capabilities}

    @classmethod
    def from_dict(cls, value: Any) -> "FlowConnection":
        if not isinstance(value, dict) or set(value) != {"schema_version", "connection_id", "revision", "project_url", "project_identity", "dedicated_profile_identity", "validation_status", "validated_at", "capabilities"}:
            raise FlowConnectionError("FLOW_CONNECTION_INVALID")
        if value.get("schema_version") != CONNECTION_SCHEMA or not isinstance(value.get("capabilities"), dict):
            raise FlowConnectionError("FLOW_CONNECTION_INVALID")
        return cls(**value)


class FlowConnectionService:
    """The single application/domain service for Flow connection semantics."""

    def __init__(self, runtime: RuntimeLayout | Path | str):
        self.runtime = runtime if isinstance(runtime, RuntimeLayout) else RuntimeLayout.from_root(runtime)
        self.runtime.ensure()

    def get_current_connection(self) -> FlowConnection | None:
        path = self.runtime.flow_connection_file
        if not path.is_file():
            return None
        try:
            return FlowConnection.from_dict(read_json(path))
        except Exception as error:
            raise FlowConnectionError("FLOW_CONNECTION_RECORD_INVALID") from error

    def get_connection_status(self, *, required_capabilities: Iterable[str] | None = None) -> dict[str, Any]:
        connection = self.get_current_connection()
        required = _required(required_capabilities)
        if connection is None:
            return {"status":"NOT_CONFIGURED", "code":"FLOW_NOT_CONFIGURED", "message":"No validated Story Auto Flow connection is configured.",
                    "project_url":None, "project_identity":None, "connection_id":None, "connection_revision":None,
                    "required_capabilities":required, "observed_capabilities":{}}
        observed = dict(connection.capabilities)
        missing = [capability for capability in required if not observed.get(capability, False)]
        status = connection.validation_status
        code = "FLOW_CONNECTED" if status == "CONNECTED" else "FLOW_" + status
        message = "Flow connection is ready." if status == "CONNECTED" else "Flow connection needs validation."
        if missing:
            status, code, message = "CAPABILITY_MISSING", "FLOW_CAPABILITY_UNAVAILABLE", "Required Flow capability is not available."
        return {"status":status, "code":code, "message":message, "project_url":connection.project_url,
                "project_identity":connection.project_identity, "connection_id":connection.connection_id,
                "connection_revision":connection.revision, "dedicated_profile_identity":connection.dedicated_profile_identity,
                "validated_at":connection.validated_at, "required_capabilities":required, "observed_capabilities":observed}

    def validate_candidate(self, project_url: str, *, project_identity: str | None = None,
                           required_capabilities: Iterable[str] | None = None, inspector=None) -> dict[str, Any]:
        normalized = normalize_project_url(project_url)
        identity = project_identity.strip() if isinstance(project_identity, str) and project_identity.strip() else stable_project_identity(normalized)
        required = _required(required_capabilities)
        runtime = FlowRuntime(self.runtime.flow_profile, "http://127.0.0.1:9222", normalized, identity)
        try:
            capabilities = preflight(runtime, inspector) if inspector is not None else preflight(runtime, __import__("story_auto.providers.flow.live", fromlist=["FlowInspector"]).FlowInspector(runtime))
            if not capabilities.authenticated:
                return self._candidate_status("AUTH_REQUIRED", "FLOW_AUTH_REQUIRED", capabilities.detail, normalized, identity, required, {})
            if not capabilities.project_ok:
                return self._candidate_status("PROJECT_MISMATCH", "FLOW_PROJECT_MISMATCH", capabilities.detail, normalized, identity, required, _capability_dict(capabilities))
            observed = _capability_dict(capabilities)
            missing = [cap for cap in required if not observed.get(cap, False)]
            if missing:
                return self._candidate_status("CAPABILITY_MISSING", "FLOW_CAPABILITY_UNAVAILABLE", "Required Flow capability is not available.", normalized, identity, required, observed)
            return self._candidate_status("CONNECTED", "FLOW_CONNECTED", "Flow profile, project, and required capabilities are confirmed.", normalized, identity, required, observed)
        except FlowSessionError as error:
            code = error.failure_class
            status = "PROJECT_MISMATCH" if code == "FLOW_PROJECT_MISMATCH" else "AUTH_REQUIRED" if code == "FLOW_AUTH_REQUIRED" else "STALE"
            return self._candidate_status(status, code, str(error), normalized, identity, required, {})

    @staticmethod
    def _candidate_status(status: str, code: str, message: str, project_url: str, project_identity: str,
                          required: list[str], observed: dict[str, bool]) -> dict[str, Any]:
        return {"status":status, "code":code, "message":message, "project_url":project_url, "project_identity":project_identity,
                "required_capabilities":required, "observed_capabilities":observed,
                "dedicated_profile_identity":"runtime/browser/flow-profile"}

    def save_validated_candidate(self, validation: dict[str, Any]) -> FlowConnection:
        if not isinstance(validation, dict) or validation.get("status") != "CONNECTED":
            raise FlowConnectionError("FLOW_CONNECTION_NOT_VALIDATED")
        current = self.get_current_connection()
        connection = FlowConnection(
            connection_id=current.connection_id if current else "flow_" + uuid.uuid4().hex,
            revision=(current.revision + 1) if current else 1,
            project_url=str(validation["project_url"]), project_identity=str(validation["project_identity"]),
            dedicated_profile_identity="runtime/browser/flow-profile", validation_status="CONNECTED",
            validated_at=_now(), capabilities=dict(validation.get("observed_capabilities", {})),
        )
        atomic_write_json(self.runtime.flow_connection_file, connection.to_dict())
        return connection

    @staticmethod
    def _project_reference(config: ProjectConfig) -> dict[str, str] | None:
        value = config.settings.get("flow_project_binding") if isinstance(config.settings, dict) else None
        if not isinstance(value, dict):
            return None
        identity, url = value.get("project_identity"), value.get("project_url")
        if not isinstance(identity, str) or not identity.strip() or not isinstance(url, str) or not url.strip():
            return None
        return {"project_identity": identity, "project_url": normalize_project_url(url)}

    def connection_for_project(self, project_id: str, *, required_capabilities: Iterable[str] | None = None) -> tuple[FlowConnection | None, dict[str, Any]]:
        paths, config = load_project(self.runtime, project_id)
        from .project_binding import managed_binding, canonical_project
        managed = managed_binding(config)
        binding = config.settings.get("flow_binding") if isinstance(config.settings, dict) else None
        expected = self._project_reference(config)
        current = self.get_current_connection()
        if managed is not None:
            if managed.get("state") != "BOUND":
                code = ("FLOW_PROJECT_CREATION_RECONCILIATION_REQUIRED"
                        if managed.get("activation_state") == "STARTED" else "FLOW_PROJECT_SETUP_REQUIRED")
                return None, {**self.get_connection_status(required_capabilities=required_capabilities),
                              "status":"PROJECT_SETUP_REQUIRED", "code":code,
                              "message":"Story Auto must finish creating this project's Flow project before media can be created.",
                              "project_url":managed.get("project_url"), "project_identity":managed.get("project_identity")}
            if current is None:
                return None, {**self.get_connection_status(required_capabilities=required_capabilities),
                              "status":"NOT_CONFIGURED", "code":"FLOW_NOT_CONFIGURED"}
            exact = canonical_project(managed)
            composed = replace(current, project_url=exact["project_url"], project_identity=exact["project_identity"])
            status = self.get_connection_status(required_capabilities=required_capabilities)
            return composed, {**status, "project_url":exact["project_url"], "project_identity":exact["project_identity"]}
        if isinstance(binding, dict):
            if current is None or binding.get("connection_id") != current.connection_id:
                return None, {**self.get_connection_status(required_capabilities=required_capabilities), "status":"STALE", "code":"FLOW_CONNECTION_STALE", "message":"Flow connection needs confirmation before this project can create media."}
            if expected is not None:
                if expected["project_identity"] != current.project_identity:
                    return None, {**self.get_connection_status(required_capabilities=required_capabilities), "status":"PROJECT_MISMATCH", "code":"FLOW_PROJECT_MISMATCH", "message":"Open the correct Flow project or explicitly rebind this Story Auto project.", "expected_project_identity": expected["project_identity"], "expected_project_url": expected["project_url"]}
                return current, self.get_connection_status(required_capabilities=required_capabilities)
            if binding.get("connection_revision") != current.revision:
                return None, {**self.get_connection_status(required_capabilities=required_capabilities), "status":"STALE", "code":"FLOW_CONNECTION_STALE", "message":"Flow connection needs confirmation before this project can create media."}
            return current, self.get_connection_status(required_capabilities=required_capabilities)
        legacy = config.settings.get("flow") if isinstance(config.settings, dict) else None
        if isinstance(legacy, dict) and (legacy.get("project_url") or legacy.get("project_identity")):
            return None, {"status":"STALE", "code":"FLOW_LEGACY_PROJECT_BINDING", "message":"This legacy project retains its original Flow binding. Validate and update it before a new provider attempt.", "project_url":legacy.get("project_url"), "project_identity":legacy.get("project_identity"), "connection_id":None, "connection_revision":None, "required_capabilities":_required(required_capabilities), "observed_capabilities":{}}
        manifest_path = paths.artifact_path("output/generation_manifest.json")
        if manifest_path.is_file():
            manifest = read_json(manifest_path)
            if isinstance(manifest, dict) and any(isinstance(item, dict) and item.get("attempts") for item in manifest.get("requests", [])):
                return None, {"status":"STALE", "code":"FLOW_BINDING_MISSING_HISTORY_IMMUTABLE", "message":"This project has historical Flow attempts but no versioned connection binding. Historical provenance is preserved; reconcile before a new provider attempt.", "project_url":None, "project_identity":None, "connection_id":None, "connection_revision":None, "required_capabilities":_required(required_capabilities), "observed_capabilities":{}}
        # A runtime connection is never an implicit project decision.  New
        # projects snapshot it at creation; older unbound projects must use the
        # explicit recovery/rebind surface before reaching a provider boundary.
        return None, {**self.get_connection_status(required_capabilities=required_capabilities), "status":"NOT_CONFIGURED",
                      "code":"FLOW_PROJECT_BINDING_REQUIRED", "message":"Connect this Story Auto project to the intended Flow project before creating media."}

    def bind_project(self, project_id: str, connection: FlowConnection | None = None, *, explicit_owner_decision: bool = False) -> dict[str, int | str]:
        paths, config = load_project(self.runtime, project_id)
        connection = connection or self.get_current_connection()
        if connection is None or connection.validation_status != "CONNECTED":
            raise FlowConnectionError("FLOW_CONNECTION_NOT_VALIDATED")
        manifest_path = paths.artifact_path("output/generation_manifest.json")
        if manifest_path.is_file() and not explicit_owner_decision:
            manifest = read_json(manifest_path)
            if isinstance(manifest, dict) and any(isinstance(item, dict) and item.get("attempts") for item in manifest.get("requests", [])):
                raise FlowConnectionError("FLOW_REBIND_HISTORY_IMMUTABLE")
        settings = dict(config.settings)
        settings.pop("flow", None)  # legacy values were used only until this safe, pre-dispatch binding.
        settings["flow_binding"] = {"connection_id":connection.connection_id, "connection_revision":connection.revision}
        settings["flow_project_binding"] = {"project_identity":connection.project_identity, "project_url":connection.project_url}
        updated = ProjectConfig(config.project_id, content_path=config.content_path, render_mode=config.render_mode, settings=settings, schema_version=config.schema_version)
        atomic_write_json(paths.project_file, updated.to_dict())
        return dict(settings["flow_binding"])

    def runtime_for_connection(self, connection: FlowConnection) -> FlowRuntime:
        return FlowRuntime(self.runtime.flow_profile, "http://127.0.0.1:9222", connection.project_url, connection.project_identity)

    @staticmethod
    def provenance(connection: FlowConnection) -> dict[str, Any]:
        return {"flow_connection_id":connection.connection_id, "flow_connection_revision":connection.revision,
                "flow_project_identity":connection.project_identity, "flow_project_url":connection.project_url,
                "dedicated_profile_identity":connection.dedicated_profile_identity}

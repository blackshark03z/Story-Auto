"""Canonical attempt binding for passively observed Flow video identities."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock

from .response_model import FlowObservedIdentity, RESPONSE_MODEL_VERSION
from .session import FlowSessionError


ATTEMPT_VIDEO_IDENTITY_VERSION = "flow-observed-video-attempt-identity/1.0.0"
GENERATION_MANIFEST_VERSION = "story-auto-generation-manifest/1.0.0"
_BINDING_FIELDS = {
    "schema_version",
    "project_id",
    "request_id",
    "attempt",
    "response_model_version",
    "component_1",
    "project_identity",
    "component_3",
    "recorded_at",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_uuid(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 36:
        return False
    groups = value.split("-")
    return (
        [len(group) for group in groups] == [8, 4, 4, 4, 12]
        and all(character in "0123456789abcdefABCDEF" for group in groups for character in group)
    )


@dataclass(frozen=True)
class FlowAttemptVideoIdentity:
    project_id: str
    request_id: str
    attempt: int
    observed_identity: FlowObservedIdentity
    recorded_at: str
    binding_sha256: str

    @classmethod
    def from_dict(cls, value: Any) -> "FlowAttemptVideoIdentity":
        if not isinstance(value, dict) or set(value) != _BINDING_FIELDS | {"binding_sha256"}:
            raise FlowSessionError(
                "FLOW_VIDEO_IDENTITY_BINDING_INVALID", "attempt video identity has an invalid shape",
            )
        core = {key: value[key] for key in _BINDING_FIELDS}
        if (
            value["schema_version"] != ATTEMPT_VIDEO_IDENTITY_VERSION
            or value["response_model_version"] != RESPONSE_MODEL_VERSION
            or not isinstance(value["project_id"], str)
            or not isinstance(value["request_id"], str)
            or not value["request_id"].strip()
            or isinstance(value["attempt"], bool)
            or not isinstance(value["attempt"], int)
            or value["attempt"] < 1
            or not isinstance(value["recorded_at"], str)
            or not value["recorded_at"].strip()
            or not all(_is_uuid(value[key]) for key in (
                "component_1", "project_identity", "component_3",
            ))
            or value["binding_sha256"] != _sha256(core)
        ):
            raise FlowSessionError(
                "FLOW_VIDEO_IDENTITY_BINDING_INVALID", "attempt video identity failed validation",
            )
        identity = FlowObservedIdentity(
            value["component_1"].lower(),
            value["project_identity"].lower(),
            value["component_3"].lower(),
        )
        return cls(
            project_id=value["project_id"],
            request_id=value["request_id"],
            attempt=value["attempt"],
            observed_identity=identity,
            recorded_at=value["recorded_at"],
            binding_sha256=value["binding_sha256"],
        )

    def to_dict(self) -> dict[str, Any]:
        core = {
            "schema_version": ATTEMPT_VIDEO_IDENTITY_VERSION,
            "project_id": self.project_id,
            "request_id": self.request_id,
            "attempt": self.attempt,
            "response_model_version": RESPONSE_MODEL_VERSION,
            "component_1": self.observed_identity.component_1,
            "project_identity": self.observed_identity.project_identity,
            "component_3": self.observed_identity.component_3,
            "recorded_at": self.recorded_at,
        }
        return {**core, "binding_sha256": _sha256(core)}


def _bound_project_identity(config) -> str:
    flow = config.settings.get("provider_binding", {}).get("flow", {})
    identity = flow.get("project_identity") if isinstance(flow, dict) else None
    if not isinstance(flow, dict) or flow.get("state") != "BOUND" or not _is_uuid(identity):
        raise FlowSessionError(
            "FLOW_PROJECT_MISMATCH", "canonical Flow project binding is unavailable",
        )
    return identity.lower()


def _canonical_attempt(paths, project_id: str, request_id: str, attempt_number: int):
    if isinstance(attempt_number, bool) or not isinstance(attempt_number, int) or attempt_number < 1:
        raise FlowSessionError(
            "FLOW_VIDEO_IDENTITY_BINDING_INVALID", "attempt number must be positive",
        )
    try:
        requests_document = read_json(paths.artifact_path("output/generation_requests.json"))
        manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
    except Exception as error:
        raise FlowSessionError(
            "FLOW_VIDEO_IDENTITY_BINDING_INVALID", "canonical request evidence is unavailable",
        ) from error
    if (
        not isinstance(requests_document, dict)
        or not isinstance(requests_document.get("requests"), list)
        or not isinstance(manifest, dict)
        or manifest.get("schema_version") != GENERATION_MANIFEST_VERSION
        or manifest.get("project_id") != project_id
        or not isinstance(manifest.get("requests"), list)
    ):
        raise FlowSessionError(
            "FLOW_VIDEO_IDENTITY_BINDING_INVALID", "canonical request evidence is invalid",
        )
    requests = [
        item for item in requests_document["requests"]
        if isinstance(item, dict) and item.get("request_id") == request_id
    ]
    entries = [
        item for item in manifest["requests"]
        if isinstance(item, dict) and item.get("request_id") == request_id
    ]
    if len(requests) != 1 or len(entries) != 1:
        raise FlowSessionError(
            "FLOW_VIDEO_IDENTITY_BINDING_INVALID", "request must resolve exactly once",
        )
    request, entry = requests[0], entries[0]
    if (
        request.get("media_type") != "VIDEO"
        or entry.get("media_type") != "VIDEO"
        or request.get("fingerprint") != entry.get("request_identity_sha256")
    ):
        raise FlowSessionError(
            "FLOW_VIDEO_IDENTITY_BINDING_INVALID", "identity binding requires one exact VIDEO request",
        )
    raw_attempts = entry.get("attempts")
    if not isinstance(raw_attempts, list):
        raise FlowSessionError(
            "FLOW_VIDEO_IDENTITY_BINDING_INVALID", "attempt evidence is invalid",
        )
    attempts = [
        item for item in raw_attempts
        if isinstance(item, dict) and item.get("attempt") == attempt_number
    ]
    if len(attempts) != 1:
        raise FlowSessionError(
            "FLOW_VIDEO_IDENTITY_BINDING_INVALID", "attempt must resolve exactly once",
        )
    return manifest, attempts[0]


def _require_confirmed_provider_attempt(attempt: dict) -> None:
    if (
        attempt.get("provider_execution_state") != "PROVIDER_BOUNDARY_ENTERED"
        or attempt.get("dispatch_confirmed") is not True
    ):
        raise FlowSessionError(
            "FLOW_VIDEO_IDENTITY_BINDING_PRECONDITION_FAILED",
            "attempt has no confirmed provider dispatch",
        )


def bind_confirmed_attempt_video_identity(
    attempt: dict,
    *,
    project_id: str,
    request_id: str,
    attempt_number: int,
    project_identity: str,
    identity: FlowObservedIdentity,
    recorded_at: str | None = None,
) -> FlowAttemptVideoIdentity:
    """Bind one identity to an already validated in-memory canonical attempt.

    The caller owns the project lock and must atomically persist its manifest
    before any byte acquisition starts.
    """
    if not isinstance(attempt, dict):
        raise FlowSessionError(
            "FLOW_VIDEO_IDENTITY_BINDING_INVALID", "attempt evidence is invalid",
        )
    if (
        isinstance(attempt_number, bool)
        or not isinstance(attempt_number, int)
        or attempt_number < 1
        or attempt.get("attempt") != attempt_number
        or not isinstance(identity, FlowObservedIdentity)
        or not all(_is_uuid(value) for value in (
            project_identity,
            identity.component_1,
            identity.project_identity,
            identity.component_3,
        ))
    ):
        raise FlowSessionError(
            "FLOW_VIDEO_IDENTITY_BINDING_INVALID", "observed identity is invalid",
        )
    identity = FlowObservedIdentity(
        identity.component_1.lower(),
        identity.project_identity.lower(),
        identity.component_3.lower(),
    )
    if identity.project_identity != project_identity.lower():
        raise FlowSessionError(
            "FLOW_PROJECT_MISMATCH", "observed identity belongs to another Flow project",
        )
    _require_confirmed_provider_attempt(attempt)
    existing = attempt.get("flow_observed_video_identity")
    if existing is not None:
        bound = FlowAttemptVideoIdentity.from_dict(existing)
        if (
            bound.project_id != project_id
            or bound.request_id != request_id
            or bound.attempt != attempt_number
            or bound.observed_identity != identity
        ):
            raise FlowSessionError(
                "FLOW_VIDEO_IDENTITY_CONFLICT", "attempt already owns another video identity",
            )
        return bound
    bound = FlowAttemptVideoIdentity(
        project_id=project_id,
        request_id=request_id,
        attempt=attempt_number,
        observed_identity=identity,
        recorded_at=recorded_at or _now(),
        binding_sha256="",
    )
    value = bound.to_dict()
    attempt["flow_observed_video_identity"] = value
    return FlowAttemptVideoIdentity.from_dict(value)


def persist_attempt_video_identity(
    runtime_root: Path | str,
    project_id: str,
    request_id: str,
    attempt_number: int,
    identity: FlowObservedIdentity,
) -> FlowAttemptVideoIdentity:
    """Persist one immutable observed tuple before canonical video acquisition."""
    if not isinstance(identity, FlowObservedIdentity):
        raise TypeError("identity must be FlowObservedIdentity")
    runtime = RuntimeLayout.from_root(runtime_root)
    with ProjectLock(runtime, project_id):
        paths, config = load_project(runtime, project_id)
        project_identity = _bound_project_identity(config)
        manifest, attempt = _canonical_attempt(paths, project_id, request_id, attempt_number)
        bound = bind_confirmed_attempt_video_identity(
            attempt,
            project_id=project_id,
            request_id=request_id,
            attempt_number=attempt_number,
            project_identity=project_identity,
            identity=identity,
        )
        atomic_write_json(paths.artifact_path("output/generation_manifest.json"), manifest)
        return bound


def load_attempt_video_identity(
    runtime_root: Path | str,
    project_id: str,
    request_id: str,
    attempt_number: int,
) -> FlowAttemptVideoIdentity:
    """Read and verify a canonical tuple without mutating provider or project state."""
    runtime = RuntimeLayout.from_root(runtime_root)
    with ProjectLock(runtime, project_id):
        paths, config = load_project(runtime, project_id)
        project_identity = _bound_project_identity(config)
        _manifest, attempt = _canonical_attempt(paths, project_id, request_id, attempt_number)
        _require_confirmed_provider_attempt(attempt)
        value = attempt.get("flow_observed_video_identity")
        if value is None:
            raise FlowSessionError(
                "FLOW_VIDEO_IDENTITY_NOT_PERSISTED",
                "attempt has no canonical observed video identity",
            )
        bound = FlowAttemptVideoIdentity.from_dict(value)
        if (
            bound.project_id != project_id
            or bound.request_id != request_id
            or bound.attempt != attempt_number
            or bound.observed_identity.project_identity != project_identity
        ):
            raise FlowSessionError(
                "FLOW_VIDEO_IDENTITY_BINDING_INVALID", "attempt identity does not match canonical state",
            )
        return bound

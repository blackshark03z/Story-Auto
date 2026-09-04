"""Compact, product-facing Flow status and recovery decisions.

The runtime connection service owns browser/session evidence.  A project owns
only its expected Flow reference.  This adapter deliberately returns neither
CDP nor revision details, so UI, CLI, and Worker can share one safe contract.
"""
from __future__ import annotations

from typing import Iterable

from story_auto.core.project.execution import execution_mode


_MESSAGES = {
    "CONNECTED": "Flow connected",
    "NOT_CONFIGURED": "Connect Flow to continue",
    "AUTH_REQUIRED": "Sign in to Flow to continue",
    "STALE": "Flow connection needs confirmation",
    "PROJECT_MISMATCH": "Open the correct Flow project to continue",
    "CAPABILITY_MISSING": "This Flow project cannot create the required media",
    "PROJECT_SETUP_REQUIRED": "Story Auto is setting up this video's Flow project",
}

_ACTIONS = {
    "CONNECTED": {"action": "continue_production", "label": "Continue production"},
    "NOT_CONFIGURED": {"action": "settings", "label": "Connect Flow"},
    "AUTH_REQUIRED": {"action": "open_flow_sign_in", "label": "Sign in to Flow"},
    "STALE": {"action": "validate_flow_connection", "label": "Validate Flow connection"},
    "PROJECT_MISMATCH": {"action": "open_flow_sign_in", "label": "Open expected Flow project"},
    "CAPABILITY_MISSING": {"action": "settings", "label": "Review Flow project"},
    "PROJECT_SETUP_REQUIRED": {"action": "ensure_flow_project", "label": "Finish Flow project setup"},
}


# Provider capability and product availability are separate facts. Legacy
# project configuration remains readable, but this release supports only Full
# Image. Deferred implementations stay intact while production fails before
# any provider boundary.
DEFERRED_MODE_UNAVAILABLE = {
    "available": False,
    "reason_code": "FEATURE_NOT_AVAILABLE",
    "human_message": "Only Full Image is available in this release.",
    "retryable": False,
}


def render_mode_availability(render_mode: str) -> dict:
    if render_mode == "full_image":
        return {"available": True, "reason_code": None, "human_message": None, "retryable": False}
    return dict(DEFERRED_MODE_UNAVAILABLE)


def required_capabilities(config, request_media_types: Iterable[str] | None = None) -> list[str]:
    if execution_mode(config.settings) == "RENDER_ONLY":
        return []
    kinds = {str(kind).upper() for kind in (request_media_types or [])}
    if not kinds:
        kinds = {"VIDEO"} if config.render_mode == "full_video_ai" else {"IMAGE"}
    return sorted(kind for kind in kinds if kind in {"IMAGE", "VIDEO"})


def product_flow_status(connections, project_id: str, config, *, request_media_types: Iterable[str] | None = None,
                        auth_required: bool = False) -> dict:
    required = required_capabilities(config, request_media_types)
    if auth_required:
        status = "AUTH_REQUIRED"
    else:
        _connection, detail = connections.connection_for_project(project_id, required_capabilities=required)
        status = detail.get("status", "NOT_CONFIGURED")
    if status not in _MESSAGES:
        status = "AUTH_REQUIRED"
    return {"status": status, "human_message": _MESSAGES[status], "recoverable": status != "CONNECTED",
            "next_action": dict(_ACTIONS[status])}

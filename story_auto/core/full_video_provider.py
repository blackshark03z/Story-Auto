"""Narrow capability contract for Full Video providers.

This is intentionally not a generic provider router.  It records only the
variation already proven by Goal 54 and keeps production enablement explicit.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_FULL_VIDEO_PROVIDER = "byteplus_seedance"


class FullVideoProviderError(ValueError):
    def __init__(self, failure_class: str) -> None:
        self.failure_class = failure_class
        super().__init__(failure_class)


_CAPABILITIES: dict[str, dict[str, Any]] = {
    "byteplus_seedance": {
        "provider_id": "byteplus_seedance",
        "generation_mode": "t2v",
        "reference_image_policy": "NOT_REQUIRED",
        "durable_recovery": "PROVIDER_TASK_ID",
        "cost_preflight": "READINESS_ONLY",
        "consequence_policy": "DIRECT_OUTPUT",
        "production_enabled": True,
    },
    "elyum_seedance": {
        "provider_id": "elyum_seedance",
        "generation_mode": "i2v",
        "reference_image_policy": "REQUIRED",
        "durable_recovery": "CLIENT_REF_AND_JOB_ID",
        "cost_preflight": "BALANCE_AND_ESTIMATE_REQUIRED",
        "consequence_policy": "EXPLICIT_KEEP_UNLOCK",
        # Goal 54 repeatability qualifies the method, not the production
        # continuity lifecycle. Slice B/C must land before this can become True.
        "production_enabled": False,
    },
}


def resolve_full_video_provider(settings: dict[str, Any]) -> str:
    value = settings.get("full_video_provider", DEFAULT_FULL_VIDEO_PROVIDER)
    if not isinstance(value, str) or value not in _CAPABILITIES:
        raise FullVideoProviderError("FULL_VIDEO_PROVIDER_INVALID")
    return value


def full_video_provider_snapshot(settings: dict[str, Any]) -> dict[str, Any]:
    """Return immutable JSON-safe provider capability truth for one run."""
    return deepcopy(_CAPABILITIES[resolve_full_video_provider(settings)])


def require_production_full_video_provider(settings: dict[str, Any]) -> dict[str, Any]:
    snapshot = full_video_provider_snapshot(settings)
    if snapshot["production_enabled"] is not True:
        raise FullVideoProviderError("FULL_VIDEO_PROVIDER_NOT_PRODUCTION_ENABLED")
    return snapshot

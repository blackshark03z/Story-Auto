"""Canonical capability-first video provider registry.

This module is deliberately small: it describes replaceable provider realities
without owning provider execution. Provider adapters keep their own lifecycle and
external-effect semantics.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

_SAFE_CROSS_PROVIDER_STATES = frozenset({
    "NOT_CONFIGURED",
    "CAPABILITY_UNSUPPORTED",
    "PREFLIGHT_FAILED",
    "CONFIRMED_NOT_DISPATCHED",
})

_DESCRIPTORS: dict[str, dict[str, Any]] = {
    "byteplus_seedance": {
        "provider_id": "byteplus_seedance",
        "display_name": "BytePlus ModelArk",
        "tier": "A",
        "transport": "DIRECT_ASYNC_API",
        "model_family": "seedance",
        "models": ["2.5"],
        "modes": ["T2V"],
        "lifecycle": "ASYNC_TASK",
        "consequence_model": "GENERATION_BILLED_BY_PROVIDER",
        "production_routed": True,
        "experimental": False,
    },
    "elyum_seedance": {
        "provider_id": "elyum_seedance",
        "display_name": "Elyum",
        "tier": "A",
        "transport": "MCP_STREAMABLE_HTTP",
        "model_family": "seedance",
        "models": ["2-fast-i2v", "2.5-reference"],
        "modes": ["T2V", "I2V", "REFERENCE"],
        "lifecycle": "LOCKED_PREVIEW_KEEP_KILL",
        "consequence_model": "KEEP_IS_SPEND_BOUNDARY",
        "production_routed": False,
        "experimental": False,
    },
    "dola_session": {
        "provider_id": "dola_session",
        "display_name": "Dola",
        "tier": "B",
        "transport": "SESSION_BASED_EXPERIMENTAL",
        "model_family": "seedance",
        "models": [],
        "modes": ["T2V", "I2V"],
        "lifecycle": "UNQUALIFIED_SESSION",
        "consequence_model": "UNKNOWN_UNTIL_QUALIFIED",
        "production_routed": False,
        "experimental": True,
    },
    "manual_external": {
        "provider_id": "manual_external",
        "display_name": "Manual external generation",
        "tier": "C",
        "transport": "USER_MEDIATED",
        "model_family": "any",
        "models": [],
        "modes": ["T2V", "I2V"],
        "lifecycle": "MANUAL_IMPORT",
        "consequence_model": "EXTERNAL_TO_STORY_AUTO",
        "production_routed": True,
        "experimental": False,
    },
}


def cross_provider_fallback_allowed(effect_state: str) -> bool:
    """Return whether a provider switch is safe from the known effect state."""
    return str(effect_state or "").strip().upper() in _SAFE_CROSS_PROVIDER_STATES


def provider_descriptor(provider_id: str) -> dict[str, Any]:
    try:
        return deepcopy(_DESCRIPTORS[provider_id])
    except KeyError as error:
        raise ValueError("unknown video provider") from error


def _runtime_readiness(provider_id: str) -> dict[str, Any]:
    if provider_id == "byteplus_seedance":
        from story_auto.providers.byteplus_seedance import BytePlusSeedanceClient
        return dict(BytePlusSeedanceClient().readiness())
    if provider_id == "elyum_seedance":
        from story_auto.providers.elyum_seedance import ElyumSeedanceClient
        return dict(ElyumSeedanceClient().readiness())
    if provider_id == "manual_external":
        return {"status": "READY", "reason_code": None}
    if provider_id == "dola_session":
        return {"status": "EXPERIMENTAL_NOT_IMPLEMENTED", "reason_code": "SESSION_ADAPTER_NOT_QUALIFIED"}
    raise ValueError("unknown video provider")


def video_provider_catalog() -> list[dict[str, Any]]:
    """Return a secret-free capability/readiness catalog for product surfaces."""
    rows: list[dict[str, Any]] = []
    for provider_id in ("byteplus_seedance", "elyum_seedance", "dola_session", "manual_external"):
        row = provider_descriptor(provider_id)
        readiness = _runtime_readiness(provider_id)
        row["status"] = readiness.get("status", "UNKNOWN")
        row["reason_code"] = readiness.get("reason_code")
        rows.append(row)
    return rows

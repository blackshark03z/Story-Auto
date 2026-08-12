"""Canonical direct-input fingerprints used by pipeline stages."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


class FingerprintError(ValueError):
    """Raised when inputs cannot be represented as a stable JSON identity."""


def canonical_json(value: Any) -> str:
    """Return stable UTF-8 JSON suitable for a content-addressed identity."""

    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise FingerprintError("fingerprint inputs must be finite JSON values") from error


def fingerprint(
    *,
    namespace: str | None = None,
    direct_inputs: Mapping[str, Any],
    stage_name: str | None = None,
    producer_version: str | None = None,
    artifact_schema_version: str | None = None,
    settings: Mapping[str, Any] | None = None,
) -> str:
    """Hash an explicit namespace and the stage's direct inputs.

    The namespace makes otherwise-identical input data distinct between stage
    contracts.  Callers must pass direct inputs only; dependency expansion and
    cache policy stay owned by later checkpoint services.
    """

    if namespace is None:
        namespace = stage_name
    if not isinstance(namespace, str) or not namespace.strip():
        raise FingerprintError("fingerprint namespace must be non-empty text")
    if not isinstance(direct_inputs, Mapping):
        raise FingerprintError("direct_inputs must be a mapping")

    if producer_version is not None and (not isinstance(producer_version, str) or not producer_version):
        raise FingerprintError("producer_version must be non-empty text")
    if artifact_schema_version is not None and (not isinstance(artifact_schema_version, str) or not artifact_schema_version):
        raise FingerprintError("artifact_schema_version must be non-empty text")
    if settings is not None and not isinstance(settings, Mapping):
        raise FingerprintError("settings must be a mapping")
    payload = canonical_json({
        "namespace": namespace,
        "producer_version": producer_version,
        "artifact_schema_version": artifact_schema_version,
        "direct_inputs": dict(direct_inputs),
        "settings": dict(settings or {}),
    })
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

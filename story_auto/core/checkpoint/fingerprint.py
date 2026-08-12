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


def fingerprint(*, namespace: str, direct_inputs: Mapping[str, Any]) -> str:
    """Hash an explicit namespace and the stage's direct inputs.

    The namespace makes otherwise-identical input data distinct between stage
    contracts.  Callers must pass direct inputs only; dependency expansion and
    cache policy stay owned by later checkpoint services.
    """

    if not isinstance(namespace, str) or not namespace.strip():
        raise FingerprintError("fingerprint namespace must be non-empty text")
    if not isinstance(direct_inputs, Mapping):
        raise FingerprintError("direct_inputs must be a mapping")

    payload = canonical_json({"namespace": namespace, "direct_inputs": dict(direct_inputs)})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

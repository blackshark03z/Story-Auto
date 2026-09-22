"""Pure, fail-closed contract for Flow's observed batchexecute transport.

This module deliberately knows no browser, cookies, secrets, or network code.
It turns the qualified wire observations into bounded request builders and
strict response checks for an adapter to call behind its feature gate.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any


CONTRACT_VERSION = "flow-batchexecute/2026-09-20.1"
QUALIFIED_BASELINE_FINGERPRINT = (
    "78ca7a1c3048b2c86802981696ca7e196752a661a027d3f11b8b5edece84e049"
)
RPC_UPLOAD = "maseQ"
RPC_VIDEO = "MZZa6b"
RPC_CATALOG = "Zzl0ze"
RPC_MEDIA = "as29s"
SURFACE_ID = 22
MAX_RESPONSE_BYTES = 2_000_000
MAX_JSON_DEPTH = 16
UUID_RE = re.compile(r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class ContractError(ValueError):
    """A wire-contract deviation which must stop the caller before mutation."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _uuid(value: str, code: str) -> str:
    if not isinstance(value, str) or not UUID_RE.fullmatch(value):
        raise ContractError(code)
    return value


def _request_id(value: str) -> str:
    return _uuid(value, "REQUEST_ID_INVALID")


def _context(project_id: str, captcha: str) -> list[Any]:
    _uuid(project_id, "PROJECT_ID_INVALID")
    if not isinstance(captcha, str) or not captcha:
        raise ContractError("CAPTCHA_INVALID")
    return [None, SURFACE_ID, None, None, None, project_id, None, None, None, None, [captcha, 1]]


def _envelope(rpcid: str, payload: Any) -> str:
    return json.dumps(
        [[[rpcid, json.dumps(payload, separators=(",", ":"), ensure_ascii=False), None, "generic"]]],
        separators=(",", ":"), ensure_ascii=False,
    )


def _new_uuid(request_id: str, suffix: str) -> str:
    """Deterministic non-secret correlation UUIDs derived from the caller's UUID."""
    return str(uuid.uuid5(uuid.UUID(request_id), suffix)).upper()


def build_upload(project_id: str, data: bytes, captcha: str, request_id: str) -> str:
    """Build the qualified PNG upload f.req shape (maseQ)."""
    _request_id(request_id)
    if not isinstance(data, bytes) or not data:
        raise ContractError("UPLOAD_DATA_INVALID")
    payload = [
        _context(project_id, captcha),
        base64.b64encode(data).decode("ascii"),
        "image/png",
        1,
        None, None, None, None,
        "story-auto-reference.png",
        None,
        _new_uuid(request_id, "upload-client"),
        _new_uuid(request_id, "upload-session"),
    ]
    return _envelope(RPC_UPLOAD, payload)


def build_video(
    project_id: str, prompt: str, reference_id: str, captcha: str, request_id: str
) -> str:
    """Build the qualified 8-second 16:9 abra_r2v_8s reference-video f.req."""
    _request_id(request_id)
    _uuid(reference_id, "REFERENCE_ID_INVALID")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ContractError("PROMPT_INVALID")
    request = [
        [None, None, [[[prompt]]]],
        [[None, reference_id]],
        "abra_r2v_8s",
        2,  # observed Flow 16:9 ratio enum
        None,
        [None, None, None, None, _new_uuid(request_id, "video-client"), _new_uuid(request_id, "video-session")],
    ]
    return _envelope(RPC_VIDEO, [[request], _context(project_id, captcha), [_new_uuid(request_id, "video-request"), 2]])


def build_catalog(project_id: str) -> str:
    _uuid(project_id, "PROJECT_ID_INVALID")
    return _envelope(RPC_CATALOG, [f"projects/{project_id}", None, None, None, [1]])


def build_media(media_id: str) -> str:
    _uuid(media_id, "MEDIA_ID_INVALID")
    return _envelope(RPC_MEDIA, [media_id])


def _walk(value: Any, depth: int = 0):
    if depth > MAX_JSON_DEPTH:
        raise ContractError("RESPONSE_DEPTH_EXCEEDED")
    yield value
    if isinstance(value, list):
        for item in value:
            yield from _walk(item, depth + 1)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk(item, depth + 1)


def _frames(text: str) -> list[Any]:
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise ContractError("RESPONSE_SIZE_INVALID")
    if not text.startswith(")]}'\n"):
        raise ContractError("ANTI_XSSI_MISSING")
    raw_lines = [line for line in text[5:].splitlines() if line.strip()]
    if not raw_lines:
        raise ContractError("RESPONSE_EMPTY")
    decoded: list[Any] = []
    for line in raw_lines:
        try:
            decoded.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ContractError("FRAME_JSON_INVALID") from exc
    return decoded


def parse_rpc(text: str, rpcid: str) -> Any:
    """Return the unique decoded wrb.fr payload for ``rpcid`` or fail closed."""
    if not isinstance(rpcid, str) or not rpcid:
        raise ContractError("RPC_ID_INVALID")
    matched: list[Any] = []
    for frame in _frames(text):
        for node in _walk(frame):
            if not isinstance(node, list) or not node or node[0] != "wrb.fr":
                continue
            if len(node) < 3 or not isinstance(node[1], str):
                raise ContractError("WRB_FRAME_SHAPE_INVALID")
            if node[1] != rpcid:
                continue
            payload = node[2]
            if payload is not None and not isinstance(payload, (str, list, dict)):
                raise ContractError("WRB_PAYLOAD_SHAPE_INVALID")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError as exc:
                    raise ContractError("WRB_PAYLOAD_JSON_INVALID") from exc
            matched.append(payload)
    if not matched:
        raise ContractError("RPC_PAYLOAD_NOT_FOUND")
    if len(matched) != 1:
        raise ContractError("RPC_PAYLOAD_AMBIGUOUS")
    return matched[0]


def _deep_decode(value: Any, depth: int = 0) -> Any:
    if depth > MAX_JSON_DEPTH:
        raise ContractError("RESPONSE_DEPTH_EXCEEDED")
    if isinstance(value, str) and value.lstrip().startswith(("[", "{")):
        try:
            return _deep_decode(json.loads(value), depth + 1)
        except json.JSONDecodeError:
            return value
    if isinstance(value, list):
        return [_deep_decode(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {key: _deep_decode(item, depth + 1) for key, item in value.items()}
    return value


def _value_shape(value, depth=0):
    if depth > MAX_JSON_DEPTH:
        raise ContractError("RESPONSE_DEPTH_EXCEEDED")
    return ([_value_shape(item, depth + 1) for item in value] if isinstance(value, list)
            else None if value is None else type(value).__name__)


def _validate_catalog_aux(payload):
    # Captured on empty and populated owner projects, 2026-09-21. These are
    # auxiliary schema guards, not result attribution or account/quota claims.
    model_shape = ['str', 'int', 'str', ['str'] + [None] * 9 + [[['str', 'str', 'bool', 'str']]]]
    quota_shape = [None, None, [[None, 'int', 'int', None, 'str']] * 2, None, 'int']
    if (len(payload[3]) != 30 or any(_value_shape(row) != model_shape for row in payload[3])
            or _value_shape(payload[7]) != quota_shape):
        raise ContractError('CATALOG_AUX_SCHEMA_DRIFT')
    if payload[1] is not None:
        auxiliary_shapes = [
            ['str', None, None, ['str', ['int','int'], None, None, 'str', optional, ['int','int']], 'str']
            for optional in (None, 'str')]
        if not isinstance(payload[1], list) or any(_value_shape(row) not in auxiliary_shapes for row in payload[1]):
            raise ContractError('CATALOG_AUX_SCHEMA_DRIFT')


def catalog_records(text: str, project_id: str) -> list[list[Any]]:
    """Read the observed catalog slot, never treat unmatched content as empty."""
    payload = parse_rpc(text, RPC_CATALOG)
    if (not isinstance(payload, list) or len(payload) != 8
            or payload[0] is not None or any(payload[i] is not None for i in (4, 5, 6))
            or not isinstance(payload[3], list) or not payload[3]
            or not isinstance(payload[7], list) or len(payload[7]) != 5):
        raise ContractError("CATALOG_ENVELOPE_DRIFT")
    _validate_catalog_aux(payload)
    if payload[1] is None and payload[2] is None:
        _uuid(project_id, "PROJECT_ID_INVALID")
        return []
    if (not isinstance(payload[1], list) or not isinstance(payload[2], list)
            or not payload[2] or len(payload[1]) != len(payload[2])):
        raise ContractError("CATALOG_ENVELOPE_DRIFT")
    return _validate_catalog_rows(payload[2], project_id)


def _validate_catalog_rows(records, project_id):
    project = _uuid(project_id, "PROJECT_ID_INVALID").lower()
    ids: set[str] = set()
    if not isinstance(records, list):
        raise ContractError("CATALOG_RECORD_SHAPE_DRIFT")
    for node in records:
        if not isinstance(node, list) or len(node) not in {7, 8}:
            raise ContractError("CATALOG_RECORD_SHAPE_DRIFT")
        identity = _uuid(node[0], "CATALOG_RECORD_ID_INVALID").lower()
        if not isinstance(node[1], str) or node[1].lower() != project:
            raise ContractError("CATALOG_RECORD_PROJECT_MISMATCH")
        if not isinstance(node[3], str):
            raise ContractError("CATALOG_RECORD_STATUS_INVALID")
        if identity in ids:
            raise ContractError("CATALOG_RECORD_IDENTITY_COLLISION")
        ids.add(identity)
    return records


def _strings(value: Any):
    for node in _walk(value):
        if isinstance(node, str):
            yield node


def match_output(
    records: list[list[Any]], project_id: str, prompt: str, reference_id: str
) -> list[Any] | None:
    """Find the one server row that proves the exact submission lineage."""
    project = _uuid(project_id, "PROJECT_ID_INVALID").lower()
    _uuid(reference_id, "REFERENCE_ID_INVALID")
    if not isinstance(prompt, str) or not prompt:
        raise ContractError("PROMPT_INVALID")
    matches: list[list[Any]] = []
    identities: set[str] = set()
    for record in records:
        if not isinstance(record, list) or len(record) not in {7, 8}:
            raise ContractError("CATALOG_RECORD_SHAPE_DRIFT")
        if not isinstance(record[0], str) or not UUID_RE.fullmatch(record[0]):
            raise ContractError("CATALOG_RECORD_ID_INVALID")
        if not isinstance(record[1], str) or record[1].lower() != project:
            raise ContractError("CATALOG_RECORD_PROJECT_MISMATCH")
        identity = record[0].lower()
        if identity in identities:
            raise ContractError("CATALOG_RECORD_IDENTITY_COLLISION")
        identities.add(identity)
        strings = set(_strings(record))
        if prompt not in strings:
            continue
        try:
            if record[5][1] != prompt or record[5][6][2][0][2][0][0][0] != prompt:
                raise ContractError("OUTPUT_PROMPT_SLOT_MISMATCH")
            if record[5][6][1][1][0][2] != reference_id:
                raise ContractError("OUTPUT_REFERENCE_MISMATCH")
            if record[5][6][1][0][0] != "abra_r2v_8s":
                raise ContractError("OUTPUT_MODEL_MISMATCH")
            if len(record) != 8 or record[7][0][7] != prompt or record[7][0][12] != "abra_r2v_8s" or record[7][2] != [record[0]]:
                raise ContractError("OUTPUT_LINEAGE_SLOT_MISMATCH")
        except (IndexError, TypeError):
            raise ContractError("OUTPUT_LINEAGE_SHAPE_DRIFT") from None
        if identity == reference_id.lower():
            raise ContractError("OUTPUT_REFERENCE_NOT_DISTINCT")
        if record[3] != "CAE":
            raise ContractError("OUTPUT_STATUS_UNQUALIFIED")
        matches.append(record)
    if len(matches) > 1:
        raise ContractError("OUTPUT_AMBIGUOUS")
    return matches[0] if matches else None


def validate_catalog_baseline(meta, records, project_id):
    validate_session(meta, project_id)
    _validate_catalog_rows(records, project_id)
    shape = {"host": meta["host"], "source_path_prefix": "project",
             "wiz": {"at_len": len(meta["at"]), "sid_present": bool(meta["sid"]), "bl_present": bool(meta["bl"])},
             "captcha_execute": meta["captcha"], "catalog_anti_xssi": True,
             # Fingerprint the qualified schema, not which row variants happen to
             # populate this project today. The envelope/rows are validated first.
             "catalog": {"record_lengths": [7, 8],
                         "project_position": 1,
                         "status_types": ["str"]}}
    fingerprint = hashlib.sha256(json.dumps(shape, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if fingerprint != QUALIFIED_BASELINE_FINGERPRINT:
        raise ContractError("CATALOG_BASELINE_DRIFT")
    return fingerprint


def sanitize_session(meta: dict[str, Any], project_id: str) -> dict[str, Any]:
    """Return safe diagnostics; never return WIZ or captcha token values."""
    validate_session(meta, project_id)
    return {
        "contract_version": CONTRACT_VERSION,
        "qualified_baseline_fingerprint": QUALIFIED_BASELINE_FINGERPRINT,
        "host": meta["host"],
        "source": meta["source"],
        "project_id": project_id,
        "at_length": len(meta["at"]),
        "sid_present": bool(meta["sid"]),
        "bl_present": bool(meta["bl"]),
        "hl": meta["hl"],
        "captcha_available": meta["captcha"],
    }


def validate_session(meta: dict[str, Any], project_id: str) -> None:
    _uuid(project_id, "PROJECT_ID_INVALID")
    if not isinstance(meta, dict):
        raise ContractError("SESSION_METADATA_INVALID")
    required_text = ("host", "source", "at", "sid", "bl", "hl")
    for key in required_text:
        if not isinstance(meta.get(key), str) or not meta[key]:
            raise ContractError(f"SESSION_{key.upper()}_MISSING")
    if meta["host"] != "flow.google.com":
        raise ContractError("SESSION_HOST_MISMATCH")
    if meta["source"].rstrip("/") != f"/project/{project_id}":
        raise ContractError("SESSION_PROJECT_MISMATCH")
    if len(meta["at"]) != 42:
        raise ContractError("SESSION_AT_SHAPE_INVALID")
    if len(meta["hl"]) > 16 or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8})?", meta["hl"]):
        raise ContractError("SESSION_HL_INVALID")
    if meta.get("captcha") is not True:
        raise ContractError("SESSION_CAPTCHA_UNAVAILABLE")

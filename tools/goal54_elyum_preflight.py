"""Credential-safe, zero-generation Elyum MCP preflight for Goal 54.

The tool performs only MCP initialize/tools-list plus the read-class tools
`elyum_account`, `elyum_models`, and `elyum_estimate`. It never calls generate,
keep, kill, upload, or creator mutation tools. Secret material is read locally
from a caller-supplied file and is never printed.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_ENDPOINT = "https://elyum.ai/mcp"
PROTOCOL_VERSION = "2025-06-18"
READ_TOOLS = ("elyum_account", "elyum_models", "elyum_estimate")


class PreflightError(RuntimeError):
    pass


def _decode_rpc(body: bytes, content_type: str) -> dict[str, Any] | None:
    if not body:
        return None
    text = body.decode("utf-8", errors="replace")
    if "text/event-stream" in (content_type or "").lower():
        payloads = []
        for line in text.splitlines():
            if line.startswith("data:"):
                raw = line[5:].strip()
                if raw and raw != "[DONE]":
                    try:
                        value = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(value, dict):
                        payloads.append(value)
        return payloads[-1] if payloads else None
    value = json.loads(text)
    return value if isinstance(value, dict) else None


class McpHttpClient:
    def __init__(self, endpoint: str, key: str, timeout: float = 30.0) -> None:
        self.endpoint = endpoint
        self.key = key
        self.timeout = timeout
        self.session_id: str | None = None
        self.next_id = 1

    def _post(self, message: dict[str, Any]) -> dict[str, Any] | None:
        headers = {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "User-Agent": "StoryAuto-Goal54-ElyumPreflight/1",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(message, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                session = response.headers.get("Mcp-Session-Id")
                if session:
                    self.session_id = session
                return _decode_rpc(response.read(), response.headers.get("Content-Type", ""))
        except urllib.error.HTTPError as error:
            raise PreflightError(f"HTTP_{error.code}") from error
        except (TimeoutError, urllib.error.URLError, OSError) as error:
            raise PreflightError(type(error).__name__.upper()) from error

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        value = self._post({"jsonrpc": "2.0", "id": request_id, "method": method,
                            **({"params": params} if params is not None else {})})
        if not isinstance(value, dict):
            raise PreflightError("MCP_RESPONSE_MISSING")
        if value.get("id") not in {request_id, str(request_id)}:
            raise PreflightError("MCP_RESPONSE_ID_MISMATCH")
        if isinstance(value.get("error"), dict):
            code = value["error"].get("code")
            raise PreflightError(f"MCP_ERROR_{code}")
        result = value.get("result")
        if not isinstance(result, dict):
            raise PreflightError("MCP_RESULT_INVALID")
        return result

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._post({"jsonrpc": "2.0", "method": method,
                    **({"params": params} if params is not None else {})})

    def initialize(self) -> dict[str, Any]:
        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "story-auto-goal54-preflight", "version": "1.0"},
        })
        self.notify("notifications/initialized")
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        result = self.request("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise PreflightError("MCP_TOOLS_INVALID")
        return [item for item in tools if isinstance(item, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})


def _extract_tool_payload(result: dict[str, Any]) -> Any:
    structured = result.get("structuredContent")
    if structured is not None:
        return structured
    content = result.get("content")
    if isinstance(content, list):
        texts = [item.get("text") for item in content
                 if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)]
        for text in texts:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
        if texts:
            return {"message": texts[0][:400]}
    return {}


def _safe_account(value: Any) -> dict[str, Any]:
    allowed_fragments = ("plan", "credit", "balance", "kill", "scope", "cap", "limit", "concurr")
    blocked_fragments = ("email", "token", "secret", "apikey", "api_key", "authorization", "password")
    out: dict[str, Any] = {}

    def walk(node: Any, prefix: str = "") -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                label = str(key)
                lower = label.lower()
                path = f"{prefix}.{label}" if prefix else label
                if any(fragment in lower for fragment in blocked_fragments):
                    continue
                if isinstance(child, (str, int, float, bool)) or child is None:
                    if any(fragment in lower for fragment in allowed_fragments):
                        out[path] = child
                elif isinstance(child, (dict, list)):
                    walk(child, path)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{prefix}[{index}]")

    walk(value)
    return out


def _seedance_models(value: Any) -> list[dict[str, Any]]:
    keep_fragments = ("slug", "model", "name", "role", "duration", "resolution", "ratio", "mode", "credit", "price")
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "seedance" in json.dumps(node, ensure_ascii=False).lower():
                row = {}
                for key, child in node.items():
                    lower = str(key).lower()
                    if any(fragment in lower for fragment in keep_fragments) and isinstance(child, (str, int, float, bool, list, dict)):
                        row[str(key)] = child
                if row and row not in found:
                    found.append(row)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return found[:20]


def _estimate_arguments(schema: dict[str, Any], model: str, duration: int, resolution: str) -> tuple[dict[str, Any], list[str]]:
    properties = schema.get("properties") if isinstance(schema, dict) else None
    required = schema.get("required") if isinstance(schema, dict) else None
    properties = properties if isinstance(properties, dict) else {}
    required = [str(item) for item in required] if isinstance(required, list) else []
    args: dict[str, Any] = {}

    aliases = {
        "model": model, "modelslug": model, "model_slug": model, "modelid": model, "model_id": model,
        "duration": duration, "durationseconds": duration, "duration_seconds": duration, "seconds": duration,
        "resolution": resolution,
        "ratio": "16:9", "aspectratio": "16:9", "aspect_ratio": "16:9",
        "kind": "video", "type": "video", "role": "video", "mode": "t2v",
        "variants": 1, "count": 1, "quantity": 1,
    }
    for key, spec in properties.items():
        normalized = str(key).replace("-", "_").lower()
        compact = normalized.replace("_", "")
        if normalized in aliases:
            args[key] = aliases[normalized]
        elif compact in aliases:
            args[key] = aliases[compact]
        elif isinstance(spec, dict) and "default" in spec:
            args[key] = spec["default"]
        elif key in required and isinstance(spec, dict) and isinstance(spec.get("enum"), list) and spec["enum"]:
            args[key] = spec["enum"][0]
    missing = [key for key in required if key not in args]
    return args, missing


def _safe_estimate(value: Any) -> dict[str, Any]:
    keep = ("model", "credit", "cost", "hold", "duration", "resolution", "ratio", "price")
    out: dict[str, Any] = {}

    def walk(node: Any, prefix: str = "") -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                label = str(key)
                path = f"{prefix}.{label}" if prefix else label
                if isinstance(child, (str, int, float, bool)) or child is None:
                    if any(fragment in label.lower() for fragment in keep):
                        out[path] = child
                else:
                    walk(child, path)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{prefix}[{index}]")

    walk(value)
    return out


def run_preflight(key: str, *, endpoint: str = DEFAULT_ENDPOINT, model: str = "seedance-2-mini",
                  duration: int = 4, resolution: str = "480p", timeout: float = 30.0) -> dict[str, Any]:
    client = McpHttpClient(endpoint, key, timeout)
    initialized = client.initialize()
    tools = client.list_tools()
    by_name = {str(item.get("name")): item for item in tools if isinstance(item.get("name"), str)}
    missing_tools = [name for name in READ_TOOLS if name not in by_name]
    if missing_tools:
        return {"status": "BLOCKED", "reason_code": "READ_TOOL_MISSING", "missing_tools": missing_tools}

    account = _extract_tool_payload(client.call_tool("elyum_account"))
    models = _extract_tool_payload(client.call_tool("elyum_models"))
    estimate_schema = by_name["elyum_estimate"].get("inputSchema")
    estimate_schema = estimate_schema if isinstance(estimate_schema, dict) else {}
    estimate_args, missing_required = _estimate_arguments(estimate_schema, model, duration, resolution)
    estimate: dict[str, Any]
    if missing_required:
        estimate = {"status": "BLOCKED_SCHEMA", "missing_required": missing_required,
                    "known_properties": sorted((estimate_schema.get("properties") or {}).keys())}
    else:
        estimate_payload = _extract_tool_payload(client.call_tool("elyum_estimate", estimate_args))
        estimate = {"status": "PASS", "request": {"model": model, "duration": duration, "resolution": resolution},
                    "result": _safe_estimate(estimate_payload)}

    server_info = initialized.get("serverInfo") if isinstance(initialized.get("serverInfo"), dict) else {}
    return {
        "status": "PASS" if estimate.get("status") == "PASS" else "PARTIAL",
        "transport": "MCP_STREAMABLE_HTTP",
        "protocol_version": initialized.get("protocolVersion"),
        "server": {"name": server_info.get("name"), "version": server_info.get("version")},
        "session_present": bool(client.session_id),
        "read_tools": {name: True for name in READ_TOOLS},
        "account": _safe_account(account),
        "seedance_models": _seedance_models(models),
        "estimate": estimate,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Elyum MCP preflight; never generates or spends credits.")
    parser.add_argument("--key-file", required=True, type=Path)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default="seedance-2-mini")
    parser.add_argument("--duration", type=int, default=4)
    parser.add_argument("--resolution", default="480p")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    try:
        key = args.key_file.read_text(encoding="utf-8").strip()
    except OSError:
        print(json.dumps({"status": "BLOCKED", "reason_code": "KEY_FILE_UNREADABLE"}, sort_keys=True))
        return 2
    if not key:
        print(json.dumps({"status": "BLOCKED", "reason_code": "KEY_EMPTY"}, sort_keys=True))
        return 2

    try:
        result = run_preflight(key, endpoint=args.endpoint, model=args.model,
                               duration=args.duration, resolution=args.resolution, timeout=args.timeout)
    except PreflightError as error:
        # Never print provider bodies or the credential. Failure classes only.
        print(json.dumps({"status": "FAIL", "reason_code": str(error)}, sort_keys=True))
        return 1
    finally:
        key = ""
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

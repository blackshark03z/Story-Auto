"""Read-only Elyum MCP schema probe for Goal 54.

This script performs only MCP initialize + tools/list, then prints sanitized
metadata for the mutation/recovery tool contracts Story Auto may later use. It
never calls generate, wait, keep, kill, upload, or any other provider tool.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from goal54_elyum_preflight import DEFAULT_ENDPOINT, McpHttpClient, PreflightError


DEFAULT_TOOL_NAMES = (
    "elyum_job_status",
    "elyum_wait",
    "elyum_keep",
    "elyum_kill",
)


def select_tool_schemas(tools: list[dict[str, Any]], names: tuple[str, ...] = DEFAULT_TOOL_NAMES) -> dict[str, Any]:
    wanted = set(names)
    out: dict[str, Any] = {}
    for tool in tools:
        name = tool.get("name")
        if name not in wanted:
            continue
        out[str(name)] = {
            "description": tool.get("description") if isinstance(tool.get("description"), str) else None,
            "inputSchema": tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {},
        }
    return out


def select_creation_candidates(tools: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for tool in tools:
        name = tool.get("name")
        if not isinstance(name, str):
            continue
        lower = name.lower()
        if not ("make" in lower or "video" in lower or "render" in lower or "generate" in lower):
            continue
        out[name] = {
            "description": tool.get("description") if isinstance(tool.get("description"), str) else None,
            "inputSchema": tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {},
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Elyum tools/list schema probe; never calls provider mutation tools.")
    parser.add_argument("--key-file", required=True, type=Path)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--tool", action="append", dest="requested_tools",
                        help="Return only this tool schema (repeatable); tools/list only.")
    args = parser.parse_args()

    try:
        key = args.key_file.read_text(encoding="utf-8").strip()
    except OSError:
        print(json.dumps({"status": "BLOCKED", "reason_code": "KEY_FILE_UNREADABLE"}, sort_keys=True))
        return 2
    if not key:
        print(json.dumps({"status": "BLOCKED", "reason_code": "KEY_EMPTY"}, sort_keys=True))
        return 2

    try:
        client = McpHttpClient(args.endpoint, key, args.timeout)
        initialized = client.initialize()
        tools = client.list_tools()
        schemas = select_tool_schemas(tools)
        creation_candidates = select_creation_candidates(tools)
    except PreflightError as error:
        print(json.dumps({"status": "FAIL", "reason_code": str(error)}, sort_keys=True))
        return 1
    finally:
        key = ""

    missing = [name for name in DEFAULT_TOOL_NAMES if name not in schemas]
    server_info = initialized.get("serverInfo") if isinstance(initialized.get("serverInfo"), dict) else {}
    requested_missing: list[str] = []
    if args.requested_tools:
        available = {}
        for tool in tools:
            name = tool.get("name")
            if not isinstance(name, str):
                continue
            available[name] = {
                "description": tool.get("description") if isinstance(tool.get("description"), str) else None,
                "inputSchema": tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {},
            }
        requested = {}
        for name in args.requested_tools:
            if name in available:
                requested[name] = available[name]
            else:
                requested_missing.append(name)
        payload = {
            "status": "PASS" if not requested_missing else "PARTIAL",
            "server": {"name": server_info.get("name"), "version": server_info.get("version")},
            "protocol_version": initialized.get("protocolVersion"),
            "requested_missing": requested_missing,
            "requested_tools": requested,
        }
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        return 0 if not requested_missing else 2

    print(json.dumps({
        "status": "PASS" if not missing else "PARTIAL",
        "server": {"name": server_info.get("name"), "version": server_info.get("version")},
        "protocol_version": initialized.get("protocolVersion"),
        "missing": missing,
        "tools": schemas,
        "creation_candidates": creation_candidates,
    }, ensure_ascii=True, sort_keys=True))
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())

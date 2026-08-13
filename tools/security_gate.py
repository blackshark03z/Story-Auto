#!/usr/bin/env python3
"""Fail closed on credential material and forbidden runtime coupling."""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TEXT_SUFFIXES={".py",".json",".md",".txt",".yaml",".yml",".toml",".js",".css",".html"}
PATTERNS={
    "PRIVATE_KEY":re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GOOGLE_API_KEY":re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    "OPENAI_STYLE_KEY":re.compile(r"\bsk-[0-9A-Za-z_-]{20,}"),
    "BEARER_TOKEN":re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+[0-9A-Za-z._~-]{16,}"),
    "COOKIE_SECRET":re.compile(r"(?i)(?:SAPISID|APISID|SSID|HSID|SID)=[^\s;]{12,}"),
    "SIGNED_PROVIDER_URL":re.compile(r"(?i)https?://[^\s\"']+[?&](?:x-goog-signature|x-amz-signature|signature|sig)=[^&\s\"']+"),
}


def fail(kind: str, path: Path) -> None:
    print(f"SECURITY_GATE=FAIL kind={kind} file={path.relative_to(ROOT)}",file=sys.stderr); raise SystemExit(1)


def candidates() -> list[Path]:
    tracked=subprocess.run(["git","ls-files","-z"],cwd=ROOT,capture_output=True,check=True).stdout.split(b"\0")
    paths=[ROOT/item.decode("utf-8") for item in tracked if item]
    for base in (ROOT/".buildos"/"evidence",ROOT/"runtime"):
        if base.is_dir(): paths.extend(path for path in base.rglob("*") if path.is_file() and "evidence" in path.parts)
    return sorted(set(path.resolve() for path in paths if path.suffix.lower() in TEXT_SUFFIXES and path.is_file() and path.stat().st_size<=8*1024*1024))


for path in candidates():
    try: text=path.read_text(encoding="utf-8",errors="strict")
    except (OSError,UnicodeError): continue
    for kind,pattern in PATTERNS.items():
        if pattern.search(text): fail(kind,path)

for path in (ROOT/"story_auto").rglob("*.py"):
    try: tree=ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
    except (OSError,SyntaxError) as error: fail("PYTHON_IMPORT_SCAN_INVALID",path)
    for node in ast.walk(tree):
        names=[]
        if isinstance(node,ast.Import): names=[alias.name for alias in node.names]
        elif isinstance(node,ast.ImportFrom): names=[node.module or ""]
        if any(name=="youtube_auto" or name.startswith("youtube_auto.") for name in names): fail("YOUTUBE_AUTO_RUNTIME_IMPORT",path)

print("SECURITY_GATE=PASS")
print("YOUTUBE_AUTO_RUNTIME_IMPORTS=0")

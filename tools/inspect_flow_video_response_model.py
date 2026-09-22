"""Read-only diagnostic for the experimental passive Flow video identity model."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from story_auto.core.project import RuntimeLayout, load_project
from story_auto.providers.flow.cdp import CdpPage
from story_auto.providers.flow.response_model import (
    RESPONSE_MODEL_VERSION,
    FlowPassiveResponseObserver,
)
from story_auto.providers.flow.session import FlowRuntime
from story_auto.providers.flow.session import FlowSessionError


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("runtime_root", type=Path)
parser.add_argument("project_id")
parser.add_argument("--output", type=Path)
args = parser.parse_args()
paths, config = load_project(RuntimeLayout.from_root(args.runtime_root), args.project_id)
binding = config.settings.get("provider_binding", {}).get("flow", {})
flow_settings = config.settings.get("flow", {})
runtime = FlowRuntime(
    paths.runtime.flow_profile,
    str(flow_settings.get("cdp_url", "http://127.0.0.1:9222")),
    str(binding.get("project_url", "")),
    str(binding.get("project_identity", "")),
)
result = {
    "status": "PREPARING",
    "contract_version": RESPONSE_MODEL_VERSION,
    "generate_clicks": 0,
    "rpc_replays": 0,
    "project_id": args.project_id,
    "surface_scope": "VISIBLE_RENDERED_VIDEO_TILES",
}

page = None
try:
    with FlowPassiveResponseObserver(runtime) as observer:
        page = CdpPage.open(runtime)
        page.command("Page.reload", {"ignoreCache": False})
        deadline = time.monotonic() + 30
        urls = []
        while time.monotonic() < deadline:
            ready = page.evaluate(
                """(()=>({ready:document.readyState==='complete',urls:Array.from(
                document.querySelectorAll('flow-video-tile img.thumbnail'))
                .filter(e=>e.naturalWidth>0).map(e=>e.currentSrc||e.src).filter(Boolean)}))()"""
            ) or {}
            urls = ready.get("urls", [])
            if ready.get("ready") and urls and observer.observed_response_count:
                time.sleep(2)
                break
            time.sleep(.25)
        identities = observer.resolve_urls(urls)
        rows = []
        for url, identity in zip(urls, identities):
            token = urlsplit(url).path.rsplit("/", 1)[-1]
            rows.append({
                "thumbnail_token_sha256": sha(token),
                "identity_component_hashes": (
                    [sha(identity.component_1), sha(identity.project_identity),
                     sha(identity.component_3)] if identity else None
                ),
            })
        resolved = [row for row in rows if row["identity_component_hashes"]]
        result.update({
            "status": "OBSERVED" if len(resolved) == len(rows) and rows else "INCOMPLETE",
            "video_tile_count": len(rows),
            "resolved_identity_count": len(resolved),
            "observed_response_count": observer.observed_response_count,
            "rows": rows,
        })
except FlowSessionError as error:
    result.update(status="BLOCKED", failure_class=error.failure_class)
finally:
    if page is not None:
        page.close()

payload = json.dumps(result, indent=2)
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, args.output)
print(payload)

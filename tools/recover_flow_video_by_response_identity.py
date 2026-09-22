"""Read-only recovery of one existing Flow video by observed response identity."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path

from story_auto.core.project import RuntimeLayout, load_project
from story_auto.providers.flow.cdp import CdpPage
from story_auto.providers.flow.response_model import FlowPassiveResponseObserver
from story_auto.providers.flow.session import FlowRuntime, FlowSessionError
from story_auto.providers.flow.video_acquisition import FlowObservedVideoAcquirer


SHA256 = re.compile(r"^[0-9a-f]{64}$")


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("runtime_root", type=Path)
parser.add_argument("project_id")
parser.add_argument("destination", type=Path)
parser.add_argument("--component-hash", action="append", required=True)
parser.add_argument("--expected-output-sha256")
parser.add_argument("--evidence", type=Path)
args = parser.parse_args()
if len(args.component_hash) != 3 or any(not SHA256.fullmatch(item) for item in args.component_hash):
    parser.error("exactly three lowercase SHA-256 component hashes are required")
if args.expected_output_sha256 and not SHA256.fullmatch(args.expected_output_sha256):
    parser.error("expected output SHA-256 must be lowercase hexadecimal")

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
    "project_id": args.project_id,
    "generate_clicks": 0,
    "rpc_replays": 0,
    "requested_identity_component_hashes": args.component_hash,
}


def save() -> None:
    if not args.evidence:
        return
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.evidence.with_suffix(args.evidence.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2), encoding="utf-8")
    os.replace(temporary, args.evidence)


page = None
try:
    save()
    with FlowPassiveResponseObserver(runtime) as observer:
        page = CdpPage.open(runtime)
        page.command("Page.reload", {"ignoreCache": False})
        deadline = time.monotonic() + 30
        urls = []
        while time.monotonic() < deadline:
            state = page.evaluate(
                """(()=>({ready:document.readyState==='complete',urls:Array.from(
                document.querySelectorAll('flow-video-tile img.thumbnail'))
                .filter(e=>e.naturalWidth>0).map(e=>e.currentSrc||e.src).filter(Boolean)}))()"""
            ) or {}
            urls = state.get("urls", [])
            if state.get("ready") and urls and observer.observed_response_count:
                time.sleep(2)
                break
            time.sleep(.25)
        identities = observer.resolve_urls(urls)
        candidates = [
            identity for identity in identities
            if identity is not None and [
                sha(identity.component_1), sha(identity.project_identity), sha(identity.component_3)
            ] == args.component_hash
        ]
        if len(candidates) != 1:
            raise FlowSessionError(
                "FLOW_RESPONSE_IDENTITY_AMBIGUOUS" if len(candidates) > 1
                else "FLOW_VIDEO_IDENTITY_NOT_RENDERED",
                "requested response identity did not resolve to exactly one rendered tile",
            )
        target = candidates[0]
        result.update(
            status="EXACT_IDENTITY_RESOLVED",
            rendered_video_count=len(urls),
            resolved_identity_count=sum(identity is not None for identity in identities),
            observed_response_count=observer.observed_response_count,
        )
        save()
        page.close()
        page = None
        acquirer = FlowObservedVideoAcquirer(runtime, observer)
        try:
            acquired = acquirer.acquire(target, args.destination)
        except FlowSessionError:
            result["acquisition_phase"] = acquirer.last_phase
            result["acquisition_error_type"] = acquirer.last_error_type
            raise
        output_hash = acquired["sha256"]
        expected_match = (
            output_hash == args.expected_output_sha256
            if args.expected_output_sha256 else None
        )
        result.update(
            status=(
                "EXACT_IDENTITY_VIDEO_RECOVERY_PASS"
                if expected_match is not False else "RECOVERED_OUTPUT_HASH_MISMATCH"
            ),
            acquisition_version=acquired["acquisition_version"],
            output_sha256=output_hash,
            output_bytes=Path(args.destination).stat().st_size,
            duration_seconds=acquired["duration_seconds"],
            width=acquired["width"],
            height=acquired["height"],
            codec=acquired["codec"],
            audio_present=acquired["audio_present"],
            expected_output_sha256_match=expected_match,
        )
except FlowSessionError as error:
    result.update(status="BLOCKED", failure_class=error.failure_class)
finally:
    if page is not None:
        page.close()
    save()

print(json.dumps(result, indent=2))
raise SystemExit(0 if result["status"] == "EXACT_IDENTITY_VIDEO_RECOVERY_PASS" else 2)

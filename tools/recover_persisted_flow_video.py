"""Recover one existing Flow video from its canonical attempt-bound identity."""
from __future__ import annotations

import argparse
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
from story_auto.providers.flow.video_identity import load_attempt_video_identity


SHA256 = re.compile(r"^[0-9a-f]{64}$")

parser = argparse.ArgumentParser()
parser.add_argument("runtime_root", type=Path)
parser.add_argument("project_id")
parser.add_argument("request_id")
parser.add_argument("attempt", type=int)
parser.add_argument("destination", type=Path)
parser.add_argument("--expected-output-sha256")
parser.add_argument("--evidence", type=Path)
args = parser.parse_args()
if args.attempt < 1:
    parser.error("attempt must be positive")
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
    "request_id": args.request_id,
    "attempt": args.attempt,
    "generate_clicks": 0,
    "rpc_replays": 0,
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
    persisted_binding = load_attempt_video_identity(
        args.runtime_root, args.project_id, args.request_id, args.attempt,
    )
    result.update(
        status="PERSISTED_IDENTITY_VERIFIED",
        identity_binding_sha256=persisted_binding.binding_sha256,
    )
    save()
    with FlowPassiveResponseObserver(runtime) as observer:
        page = CdpPage.open(runtime)
        page.command("Page.reload", {"ignoreCache": False})
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            state = page.evaluate(
                """(()=>({ready:document.readyState==='complete',count:Array.from(
                document.querySelectorAll('flow-video-tile img.thumbnail'))
                .filter(e=>e.naturalWidth>0).length}))()"""
            ) or {}
            if state.get("ready") and state.get("count") and observer.observed_response_count:
                time.sleep(2)
                break
            time.sleep(.25)
        result.update(
            status="PASSIVE_RESPONSES_OBSERVED",
            observed_response_count=observer.observed_response_count,
        )
        save()
        page.close()
        page = None
        acquirer = FlowObservedVideoAcquirer(runtime, observer)
        try:
            acquired = acquirer.acquire_persisted(
                args.runtime_root,
                args.project_id,
                args.request_id,
                args.attempt,
                args.destination,
            )
        except FlowSessionError:
            result["acquisition_phase"] = acquirer.last_phase
            result["acquisition_error_type"] = acquirer.last_error_type
            raise
        expected_match = (
            acquired["sha256"] == args.expected_output_sha256
            if args.expected_output_sha256 else None
        )
        result.update(
            status=(
                "PERSISTED_IDENTITY_VIDEO_RECOVERY_PASS"
                if expected_match is not False else "RECOVERED_OUTPUT_HASH_MISMATCH"
            ),
            acquisition_version=acquired["acquisition_version"],
            identity_binding_sha256=acquired["identity_binding_sha256"],
            output_sha256=acquired["sha256"],
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
raise SystemExit(
    0 if result["status"] == "PERSISTED_IDENTITY_VIDEO_RECOVERY_PASS" else 2
)

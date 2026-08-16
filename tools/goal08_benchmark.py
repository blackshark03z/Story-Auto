"""Materialize the sanitized Goal 08 blind provider-quality review workspace."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from story_auto.core.artifacts import atomic_write_json, read_json, sha256_file
from story_auto.core.benchmark import build_benchmark_workspace, write_review_package
from story_auto.core.project.paths import RuntimeLayout
from story_auto.providers.flow import FlowRuntime
from story_auto.providers.flow.cdp import CdpPage
from story_auto.providers.flow.live import LiveFlowGenerator
from story_auto.providers.flow.service import FlowError
from story_auto.providers.flow.validation import AssetValidationError, validate_image, validate_video
from story_auto.providers.gemini_media import GeminiMediaClient, GeminiMediaError, execute_media_request
from story_auto.providers.gemini_web import (
    GeminiWebError,
    GeminiWebRuntime,
    inspect_capabilities,
    launch_dedicated_session as launch_gemini_web_session,
    LiveGeminiWebGenerator,
    execute_web_request,
)


def capability_evidence(runtime: GeminiWebRuntime) -> list[dict]:
    try:
        return [{"provider": "google_gemini_web", **inspect_capabilities(runtime).to_dict()}]
    except GeminiWebError as error:
        return [{"provider": "google_gemini_web", "status": "UNAVAILABLE",
                 "failure_class": error.failure_class, "detail": error.detail}]


def bind_flow_baseline(root: Path, manifest: dict) -> None:
    sources = {
        "IMAGE-A": Path("runtime/goal07_hybrid/projects/prj_goal07hybrid/assets/image/req_goal06_image/manual_recovery_002.png"),
        "VIDEO-A": Path("runtime/goal07_hybrid/projects/prj_goal07hybrid/assets/video/req_goal06_video/manual_recovery_008.mp4"),
    }
    assets = root / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for case, source in sources.items():
        candidate = next(item for item in manifest["requests"]
                         if item["case"] == case and item["actual_model"] == "google_flow_web" and item["attempt"] == 1)
        suffix = source.suffix.lower()
        destination = assets / f"flow_{case.lower()}_attempt_1{suffix}"
        if not destination.exists() or sha256_file(destination) != sha256_file(source):
            shutil.copy2(source, destination)
        metadata = validate_image(destination) if candidate["media_type"] == "IMAGE" else validate_video(destination)
        candidate.update({
            "status": "SUCCEEDED", "failure_class": None, "local_asset": destination.relative_to(root).as_posix(),
            "asset_sha256": sha256_file(destination), "technical_validation": {"status": "PASS", **metadata},
            "visible_watermark": "YES", "human_review": "PENDING",
            "attempt_history": [{"attempt": 1, "status": "SUCCEEDED", "source": "accepted_existing_flow_provenance"}],
        })


def _reference(root: Path) -> Path:
    path = root / "assets" / "flow_image-a_attempt_1.png"
    if not path.is_file():
        raise RuntimeError("benchmark reference is missing")
    return path


def _valid(item: dict, root: Path) -> bool:
    relative = item.get("local_asset")
    if not isinstance(relative, str):
        return False
    try:
        metadata = validate_image(root / relative) if item["media_type"] == "IMAGE" else validate_video(root / relative)
        return metadata["sha256"] == item.get("asset_sha256")
    except AssetValidationError:
        return False


def _request_identity(item: dict, reference_hashes: list[str]) -> str:
    identity = {
        "request_id": item["request_id"],
        "model": item["actual_model"],
        "media_type": item["media_type"],
        "prompt_sha256": item["prompt_sha256"],
        "reference_hashes": reference_hashes,
        "output_settings": item["output_settings"],
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _set_review_readiness(manifest: dict) -> None:
    flow = [item for item in manifest["requests"] if item.get("provider") == "google_flow"]
    web = [item for item in manifest["requests"] if item.get("provider") == "google_gemini_web"]
    manifest["flow_baseline_status"] = (
        "COMPLETE" if flow and all(item.get("status") == "SUCCEEDED" for item in flow) else "INCOMPLETE"
    )
    manifest["gemini_web_status"] = (
        "COMPLETE" if web and all(item.get("status") == "SUCCEEDED" for item in web) else "PENDING"
    )
    if all(item.get("status") == "SUCCEEDED" for item in manifest["requests"]):
        manifest["benchmark_status"] = "PROVIDER_QUALITY_REVIEW_REQUIRED"
        manifest["selection_status"] = "NO_PRODUCTION_DEFAULT_CHANGE"


def mark_flow_watermarks(root: Path, manifest: dict, value: str) -> None:
    for item in manifest["requests"]:
        if item["provider"] == "google_flow" and _valid(item, root):
            item["visible_watermark"] = value
    atomic_write_json(root / "benchmark_manifest.json", manifest)


def _flow_focus_guard(dispatch_confirmed, *, exclusive: bool) -> tuple[threading.Thread, threading.Event]:
    """Keep the dedicated Flow window foregrounded only until dispatch acknowledgement."""
    import ctypes

    user32 = ctypes.windll.user32
    matches: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @callback_type
    def collect(handle, _parameter):
        length = user32.GetWindowTextLengthW(handle)
        if length:
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(handle, title, length + 1)
            if title.value.startswith("Google Flow") and user32.IsWindowVisible(handle):
                matches.append(int(handle))
        return True

    user32.EnumWindows(collect, 0)
    if len(matches) != 1:
        raise RuntimeError(f"expected one visible Google Flow window, found {len(matches)}")

    stop = threading.Event()

    def maintain() -> None:
        previous = int(user32.GetForegroundWindow())
        minimized_previous = bool(exclusive and previous not in {0, matches[0]} and not user32.IsIconic(previous))
        if minimized_previous:
            user32.ShowWindowAsync(previous, 6)
        deadline = time.monotonic() + 30
        try:
            while not stop.is_set() and not dispatch_confirmed() and time.monotonic() < deadline:
                user32.ShowWindowAsync(matches[0], 9)
                user32.SetForegroundWindow(matches[0])
                time.sleep(0.1)
        finally:
            if minimized_previous:
                user32.ShowWindowAsync(previous, 9)
                user32.SetForegroundWindow(previous)

    thread = threading.Thread(target=maintain, name="flow-focus-guard", daemon=True)
    thread.start()
    return thread, stop


def accept_reconciled_flow_image(
    root: Path, manifest: dict, request_id: str, asset: Path, *, visible_watermark: str,
) -> None:
    item = next((row for row in manifest["requests"] if row["request_id"] == request_id), None)
    if item is None or item["actual_model"] != "google_flow_web" or item["media_type"] != "IMAGE":
        raise RuntimeError("reconciliation target is not a Flow image request")
    if item.get("status") != "AMBIGUOUS":
        raise RuntimeError("reconciliation target is not ambiguous")
    resolved = asset.resolve()
    try:
        relative = resolved.relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise RuntimeError("reconciled asset must remain inside benchmark root") from error
    metadata = validate_image(resolved)
    attempts = item.get("attempt_history", [])
    if not attempts or attempts[-1].get("status") != "AMBIGUOUS":
        raise RuntimeError("ambiguous attempt history is missing")
    attempts[-1].update({
        "status": "SUCCEEDED_RECONCILED",
        "reconciled_at": datetime.now(timezone.utc).isoformat(),
        "reconciliation": "operator_attributed_exact_asset_path",
        "asset_sha256": metadata["sha256"],
    })
    item.update({
        "status": "SUCCEEDED",
        "failure_class": None,
        "local_asset": relative,
        "asset_sha256": metadata["sha256"],
        "technical_validation": {"status": "PASS", **metadata},
        "visible_watermark": visible_watermark,
        "human_review": "PENDING",
    })
    atomic_write_json(root / "benchmark_manifest.json", manifest)


def execute_api(root: Path, manifest: dict) -> None:
    """Execute Gemini candidates only after an operator explicitly enables this flag."""
    client = GeminiMediaClient()
    ledger_path = root / "api_generation_manifest.json"
    for item in manifest["requests"]:
        if item["provider"] != "google_gemini_api" or _valid(item, root):
            continue
        references = [_reference(root)] if item["case"] in {"IMAGE-C", "VIDEO-A", "VIDEO-B"} else []
        reference_hashes = [sha256_file(path) for path in references]
        request = {
            "request_id": item["request_id"],
            "request_identity_sha256": _request_identity(item, reference_hashes),
            "media_type": item["media_type"],
            "model": item["actual_model"],
            "prompt": item["actual_prompt"],
            "endpoint_identity": "predictLongRunning" if item["actual_model"].startswith("veo-") else "interactions",
            "aspect_ratio": item["output_settings"]["aspect_ratio"],
            "image_size": "2K",
        }
        if item["actual_model"] == "gemini-omni-flash-preview":
            request["reference_mode"] = "image_to_video" if item["case"] == "VIDEO-A" else "reference_to_video"
        elif item["actual_model"].startswith("veo-"):
            request["reference_mode"] = "FIRST_FRAME" if item["case"] == "VIDEO-A" else "REFERENCE_IMAGES"
        suffix = ".png" if item["media_type"] == "IMAGE" else ".mp4"
        destination = root / "assets" / f'{item["request_id"]}{suffix}'
        try:
            execute_media_request(
                manifest_path=ledger_path,
                artifact_root=root,
                request=request,
                references=references,
                destination=destination,
                client=client,
            )
        except GeminiMediaError as error:
            ledger = read_json(ledger_path)
            entry = next(row for row in ledger["requests"] if row["request_id"] == item["request_id"])
            item.update({
                "status": "AMBIGUOUS" if entry["status"] == "AMBIGUOUS" else "BLOCKED",
                "failure_class": error.failure_class,
                "reference_hashes": reference_hashes,
                "attempt_history": entry.get("attempts", []),
            })
            atomic_write_json(root / "benchmark_manifest.json", manifest)
            raise
        ledger = read_json(ledger_path)
        entry = next(row for row in ledger["requests"] if row["request_id"] == item["request_id"])
        selected = entry["selected_asset"]
        item.update({
            "status": "SUCCEEDED",
            "failure_class": None,
            "reference_hashes": reference_hashes,
            "local_asset": selected["path"],
            "asset_sha256": selected["sha256"],
            "technical_validation": {"status": "PASS", **selected["metadata"]},
            "visible_watermark": "UNCERTAIN",
            "human_review": "PENDING",
            "attempt_history": entry.get("attempts", []),
        })
        atomic_write_json(root / "benchmark_manifest.json", manifest)
    _set_review_readiness(manifest)
    atomic_write_json(root / "benchmark_manifest.json", manifest)


def apply_web_capability_state(manifest: dict, evidence: dict) -> None:
    authenticated = evidence.get("authenticated") is True
    for item in manifest["requests"]:
        if item.get("provider") != "google_gemini_web" or item.get("status") == "SUCCEEDED":
            continue
        item["status"] = "PENDING" if authenticated else "BLOCKED"
        item["failure_class"] = None if authenticated else "AUTH_REQUIRED"
    if not authenticated:
        manifest["benchmark_status"] = "BLOCKED_AUTH_REQUIRED"


def execute_gemini_web(root: Path, manifest: dict, runtime: GeminiWebRuntime,
                       *, allow_ambiguous_retry: bool = False,
                       max_requests: int | None = None) -> None:
    evidence = inspect_capabilities(runtime).to_dict()
    if not evidence["authenticated"]:
        apply_web_capability_state(manifest, evidence)
        atomic_write_json(root / "benchmark_manifest.json", manifest)
        raise GeminiWebError("AUTH_REQUIRED", "sign in to the dedicated Story Auto Gemini Web profile")
    generator = LiveGeminiWebGenerator(runtime)
    ledger_path = root / "gemini_web_generation_manifest.json"
    executed = 0
    for item in manifest["requests"]:
        if item.get("provider") != "google_gemini_web" or _valid(item, root):
            continue
        if max_requests is not None and executed >= max_requests:
            break
        references = [_reference(root)] if item["case"] in {"IMAGE-C", "VIDEO-A", "VIDEO-B"} else []
        reference_hashes = [sha256_file(path) for path in references]
        provider_prompt = item["actual_prompt"] + (
            "\n\nGenerate exactly one image." if item["media_type"] == "IMAGE"
            else "\n\nGenerate one six-second video."
        )
        request = {
            "request_id": item["request_id"],
            "request_identity_sha256": _request_identity(item, reference_hashes),
            "media_type": item["media_type"], "prompt": provider_prompt,
            "output_count": 1, "aspect_ratio": item["output_settings"]["aspect_ratio"],
        }
        suffix = ".png" if item["media_type"] == "IMAGE" else ".mp4"
        destination = root / "assets" / f'{item["request_id"]}{suffix}'
        executed += 1
        try:
            execute_web_request(
                manifest_path=ledger_path, artifact_root=root, request=request, references=references,
                destination=destination, generator=generator, allow_ambiguous_retry=allow_ambiguous_retry,
            )
        except GeminiWebError as error:
            ledger = read_json(ledger_path)
            entry = next(row for row in ledger["requests"] if row["request_id"] == item["request_id"])
            item.update({
                "status": entry["status"], "failure_class": error.failure_class,
                "reference_hashes": reference_hashes, "attempt_history": entry.get("attempts", []),
            })
            atomic_write_json(root / "benchmark_manifest.json", manifest)
            raise
        ledger = read_json(ledger_path)
        entry = next(row for row in ledger["requests"] if row["request_id"] == item["request_id"])
        selected = entry["selected_asset"]
        item.update({
            "status": "SUCCEEDED", "failure_class": None, "reference_hashes": reference_hashes,
            "local_asset": selected["path"], "asset_sha256": selected["sha256"],
            "technical_validation": {"status": "PASS", **selected["metadata"]},
            "visible_watermark": "UNCERTAIN", "human_review": "PENDING",
            "attempt_history": entry.get("attempts", []),
        })
        atomic_write_json(root / "benchmark_manifest.json", manifest)
    _set_review_readiness(manifest)
    atomic_write_json(root / "benchmark_manifest.json", manifest)


def execute_flow(
    root: Path,
    manifest: dict,
    runtime_root: Path,
    *,
    max_requests: int | None = None,
    semantic_submit: bool = False,
    focus_guard: bool = False,
    exclusive_focus: bool = False,
    emulate_focus: bool = False,
) -> None:
    project = read_json(runtime_root / "projects" / "prj_goal05live" / "project.json")
    runtime = RuntimeLayout.from_root(runtime_root)
    if semantic_submit:
        import story_auto.providers.flow.live as flow_live

        def click_exact_generate(control) -> None:
            if not control.evidence.get("enabled"):
                raise FlowError("FLOW_GENERATE_DISABLED")
            clicked = control.dom.page.evaluate("""(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable="true"]')).find(visible);if(!editor)return false;let p=editor.parentElement;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button')).filter(e=>visible(e)&&e.type==='submit'&&e.querySelector('i')?.textContent.trim()==='arrow_forward');if(xs.length===1){xs[0].click();return true}if(xs.length>1)return false;p=p.parentElement}return false})()""")
            if clicked is not True:
                raise FlowError("FLOW_UI_CHANGED", "semantic Generate control was not unique")

        flow_live._Control.click = click_exact_generate
    generator = LiveFlowGenerator(FlowRuntime.from_settings(runtime, project["settings"]), timeout_seconds=240)
    executed = 0
    for item in manifest["requests"]:
        if item["actual_model"] != "google_flow_web" or _valid(item, root):
            continue
        if max_requests is not None and executed >= max_requests:
            break
        if item.get("status") == "AMBIGUOUS":
            raise RuntimeError(f'{item["request_id"]}: reconciliation required')
        references = [_reference(root)] if item["case"] in {"IMAGE-C", "VIDEO-A", "VIDEO-B"} else []
        suffix = ".png" if item["media_type"] == "IMAGE" else ".mp4"
        destination = root / "assets" / f'{item["request_id"]}{suffix}'
        reference_hashes = [sha256_file(path) for path in references]
        attempt = {
            "attempt": len(item.get("attempt_history", [])) + 1,
            "status": "GENERATING",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "provider": "google_flow",
            "reference_hashes": reference_hashes,
            "dispatch_confirmed": False,
        }
        item.setdefault("attempt_history", []).append(attempt)
        item["status"] = "GENERATING"
        atomic_write_json(root / "benchmark_manifest.json", manifest)
        executed += 1
        request = {
            "media_type": item["media_type"],
            "prompt": item["actual_prompt"],
            "output_count": 1,
            "aspect_ratio": "16:9",
            "execution_tier": "BENCHMARK",
            "depends_on": ["benchmark-reference"] if references else [],
            "target_duration": 8 if item["media_type"] == "VIDEO" else None,
        }
        guard = None
        emulation_page = None
        try:
            generator.dispatch_confirmed = False
            if emulate_focus:
                emulation_page = CdpPage.open(generator.runtime)
                emulation_page.command("Emulation.setFocusEmulationEnabled", {"enabled": True})
                emulation_page.command("Page.setWebLifecycleState", {"state": "active"})
            guard = _flow_focus_guard(
                lambda: generator.dispatch_confirmed, exclusive=exclusive_focus,
            ) if focus_guard else None
            generator(request, references, destination)
            metadata = validate_image(destination) if item["media_type"] == "IMAGE" else validate_video(destination)
        except FlowError as error:
            ambiguous = bool(generator.dispatch_confirmed)
            attempt.update({
                "status": "AMBIGUOUS" if ambiguous else "FAILED",
                "failure_class": error.failure_class,
                "dispatch_confirmed": ambiguous,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            item.update({"status": attempt["status"], "failure_class": error.failure_class})
            atomic_write_json(root / "benchmark_manifest.json", manifest)
            raise
        finally:
            if guard is not None:
                thread, stop = guard
                stop.set()
                thread.join(timeout=2)
            if emulation_page is not None:
                emulation_page.close()
        relative = destination.relative_to(root).as_posix()
        attempt.update({
            "status": "SUCCEEDED",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "dispatch_confirmed": bool(generator.dispatch_confirmed),
            "provider_settings": generator.last_settings,
            "asset_sha256": metadata["sha256"],
        })
        item.update({
            "status": "SUCCEEDED",
            "failure_class": None,
            "reference_hashes": reference_hashes,
            "local_asset": relative,
            "asset_sha256": metadata["sha256"],
            "technical_validation": {"status": "PASS", **metadata},
            "visible_watermark": "UNCERTAIN",
            "human_review": "PENDING",
        })
        atomic_write_json(root / "benchmark_manifest.json", manifest)
    _set_review_readiness(manifest)
    atomic_write_json(root / "benchmark_manifest.json", manifest)


def close_provider_research(root: Path) -> None:
    """Close selection without probing providers or rewriting completed provenance."""
    manifest_path = root / "benchmark_manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("benchmark_manifest.json is required for owner closure")
    manifest = read_json(manifest_path)
    closed_at = datetime.now(timezone.utc).isoformat()
    decision = {
        "status": "CLOSED_BY_OWNER_DECISION",
        "closed_at": closed_at,
        "production_media_provider": "GOOGLE_FLOW_WEB",
        "images": "GOOGLE_FLOW_WEB",
        "videos": "GOOGLE_FLOW_WEB",
        "visible_flow_watermark": "ACCEPTED_KNOWN_LIMITATION",
        "unfinished_gemini_cases_will_not_run": True,
    }
    for item in manifest.get("requests", []):
        if item.get("provider") == "google_gemini_web" and item.get("status") != "SUCCEEDED":
            item.setdefault("owner_closure", {
                "at": closed_at, "original_status": item.get("status"),
                "original_failure_class": item.get("failure_class"),
            })
            item["status"] = "CLOSED_BY_OWNER_DECISION"
            item["failure_class"] = None
    manifest.update({
        "benchmark_status": "CLOSED_BY_OWNER_DECISION",
        "selection_status": "FINAL_OWNER_DECISION",
        "production_media_provider": "GOOGLE_FLOW_WEB",
        "visible_flow_watermark": "ACCEPTED_KNOWN_LIMITATION",
        "human_review_required": False,
        "owner_decision": decision,
    })
    atomic_write_json(manifest_path, manifest)
    web_ledger = root / "gemini_web_generation_manifest.json"
    if web_ledger.exists():
        ledger = read_json(web_ledger)
        for entry in ledger.get("requests", []):
            if entry.get("status") != "SUCCEEDED":
                entry.setdefault("owner_closure", {
                    "at": closed_at, "original_status": entry.get("status"),
                    "original_failure_class": entry.get("failure_class"),
                    "provider_state_not_reconciled": True,
                })
                entry["status"] = "CLOSED_BY_OWNER_DECISION"
                entry["failure_class"] = None
        ledger["research_status"] = "CLOSED_BY_OWNER_DECISION"
        atomic_write_json(web_ledger, ledger)
    eligibility_path = root / "production_eligibility.json"
    eligibility = read_json(eligibility_path) if eligibility_path.exists() else {
        "schema_version": "story-auto-production-eligibility/1.0.0", "candidates": [],
    }
    eligibility.update({
        "production_provider": "GOOGLE_FLOW_WEB",
        "visible_flow_watermark": "ACCEPTED_KNOWN_LIMITATION",
        "provider_selection_research": "CLOSED_BY_OWNER_DECISION",
        "notice": "Flow's visible mark is accepted for V1 and must not be removed, covered, masked, or cropped away.",
    })
    atomic_write_json(eligibility_path, eligibility)
    atomic_write_json(root / "owner_provider_decision.json", decision)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("runtime/evidence/goal08/provider_benchmark"))
    parser.add_argument("--valid-quota-denials", type=int, default=18, help=argparse.SUPPRESS)
    parser.add_argument("--invalid-credentials", type=int, default=3, help=argparse.SUPPRESS)
    parser.add_argument("--execute-flow", action="store_true")
    parser.add_argument("--max-flow-requests", type=int)
    parser.add_argument("--flow-semantic-submit", action="store_true")
    parser.add_argument("--flow-focus-guard", action="store_true")
    parser.add_argument("--flow-exclusive-focus", action="store_true")
    parser.add_argument("--flow-emulate-focus", action="store_true")
    parser.add_argument("--launch-gemini-web", action="store_true")
    parser.add_argument("--gemini-web-preflight", action="store_true")
    parser.add_argument("--execute-gemini-web", action="store_true")
    parser.add_argument("--allow-gemini-web-ambiguous-retry", action="store_true")
    parser.add_argument("--max-gemini-web-requests", type=int)
    parser.add_argument("--gemini-web-runtime-root", type=Path, default=Path("runtime/goal08_gemini_web"))
    parser.add_argument("--accept-flow-image", nargs=2, metavar=("REQUEST_ID", "ASSET"))
    parser.add_argument("--reconciled-watermark", choices=("YES", "NO", "UNCERTAIN"), default="UNCERTAIN")
    parser.add_argument("--mark-flow-watermarks", choices=("YES", "NO", "UNCERTAIN"))
    parser.add_argument("--close-by-owner-decision", action="store_true")
    parser.add_argument("--flow-runtime-root", type=Path, default=Path("runtime/goal05_live_corrected"))
    args = parser.parse_args()
    root = args.root.resolve()
    if args.close_by_owner_decision:
        close_provider_research(root)
        print(root / "owner_provider_decision.json")
        return 0
    web_runtime = GeminiWebRuntime.from_root(args.gemini_web_runtime_root)
    if args.launch_gemini_web:
        launch_gemini_web_session(web_runtime)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                inspect_capabilities(web_runtime)
                break
            except GeminiWebError:
                time.sleep(0.5)
    credential_probe = {
        "status": "HISTORICAL_BLOCKED_PROVIDER_ACCOUNT",
        "failure_class": "GEMINI_API_PAID_QUOTA_REQUIRED",
        "nano_banana_2_pool": {"quota_denied": args.valid_quota_denials, "invalid_or_unauthenticated": args.invalid_credentials},
        "bounded_candidate_probes": {
            "gemini-3-pro-image": "RATE_LIMITED_ZERO_QUOTA",
            "gemini-omni-flash-preview": "RATE_LIMITED_ZERO_QUOTA",
            "veo-3.1-generate-preview": "RATE_LIMITED_ZERO_QUOTA",
        },
        "provider_requests_accepted": 0,
        "provider_jobs_created": 0,
        "secrets_recorded": False,
    }
    web_evidence = capability_evidence(web_runtime)[0]
    manifest, _ = build_benchmark_workspace(
        root, capability_evidence=[web_evidence], credential_probe=credential_probe,
    )
    api_ledger = root / "api_generation_manifest.json"
    if api_ledger.exists():
        manifest.setdefault("historical_provider_ledgers", {})["gemini_api"] = read_json(api_ledger)
    apply_web_capability_state(manifest, web_evidence)
    bind_flow_baseline(root, manifest)
    if args.accept_flow_image:
        request_id, asset = args.accept_flow_image
        accept_reconciled_flow_image(
            root, manifest, request_id, root / asset, visible_watermark=args.reconciled_watermark,
        )
    if args.execute_flow:
        if args.max_flow_requests is not None and args.max_flow_requests < 1:
            parser.error("--max-flow-requests must be positive")
        execute_flow(
            root,
            manifest,
            args.flow_runtime_root.resolve(),
            max_requests=args.max_flow_requests,
            semantic_submit=args.flow_semantic_submit,
            focus_guard=args.flow_focus_guard,
            exclusive_focus=args.flow_exclusive_focus,
            emulate_focus=args.flow_emulate_focus,
        )
    if args.mark_flow_watermarks:
        mark_flow_watermarks(root, manifest, args.mark_flow_watermarks)
    if args.execute_gemini_web:
        execute_gemini_web(
            root, manifest, web_runtime,
            allow_ambiguous_retry=args.allow_gemini_web_ambiguous_retry,
            max_requests=args.max_gemini_web_requests,
        )
    _set_review_readiness(manifest)
    write_review_package(root, manifest)
    if args.gemini_web_preflight:
        print(json.dumps(web_evidence, sort_keys=True))
    print(root / "review.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

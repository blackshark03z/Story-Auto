"""Bounded live canonical-service canary in a separate persistent runtime.

One local reference import, at most one video. Reinvocation uses the existing
canonical attempt; it never creates a replacement request or clears ambiguity.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

from story_auto.core.artifacts import atomic_write_json, read_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.providers.flow.live import FlowInspector, LiveFlowGenerator
from story_auto.providers.flow.service import FlowExecutor, execute_generation
from story_auto.providers.flow.session import FlowCapabilities, FlowRuntime, preflight


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--cookies", type=Path, help="Explicit cookie-owned experimental session; no external CDP")
    parser.add_argument("--provider-project", help="Exact isolated Flow project override")
    args = parser.parse_args()
    flow = read_json(args.project)["settings"]["provider_binding"]["flow"]
    if args.provider_project:
        from uuid import UUID
        project = str(UUID(args.provider_project))
        flow = dict(flow, project_identity=project, project_url=f'https://flow.google.com/project/{project}')
    runtime = RuntimeLayout.from_root(args.runtime)
    project_id = flow["created_for_story_project_id"]
    marker = args.runtime / "canary-project.json"
    if not marker.exists():
        if args.runtime.exists() and any(args.runtime.iterdir()):
            raise SystemExit("Refusing to initialize a nonempty runtime")
        config = ProjectConfig(project_id, settings={"provider_binding": {"flow": flow}})
        paths = create_project(runtime, config)
        atomic_write_json(paths.artifact_path("output/review_state.json"), {"plan_approval": {"status": "APPROVED"}, "scope": "ENGINEERING_CANARY"})
        requests = [
            {"request_id": "ref", "fingerprint": "local-reference-canary", "purpose": "REFERENCE", "media_type": "IMAGE", "prompt": "Local reference import", "depends_on": [], "provider": "local_fixture"},
            {"request_id": "shot", "fingerprint": "rpc-service-shot-01", "purpose": "SHOT", "media_type": "VIDEO", "prompt": "Slow gentle orbit around the exact geometric reference composition. Preserve shapes and colors. No additional objects.", "depends_on": ["ref"], "provider": "google_flow", "target_duration": 8, "aspect_ratio": "16:9", "output_count": 1, "motion_risk_analysis": {"physical_complexity": "LOW"}},
        ]
        atomic_write_json(paths.artifact_path("output/generation_requests.json"), {"requests": requests})
        atomic_write_json(marker, {"project_id": project_id, "scope": "canonical engineering acceptance, not production QC"})
    from story_auto.core.project import load_project
    paths, config = load_project(runtime, project_id)
    def local_reference(request, refs, destination):
        shutil.copy2(args.reference, destination)
        return destination
    execute_generation(args.runtime, project_id, executor=FlowExecutor(FlowCapabilities(True, True, True, True, True, True), local_reference), execute=True, request_ids={"ref"})
    binding = config.settings["provider_binding"]["flow"]
    flow_runtime = FlowRuntime(args.profile, binding.get("cdp_url", "http://127.0.0.1:9222"), binding["project_url"], binding["project_identity"])
    os.environ["STORY_AUTO_FLOW_RPC_EXPERIMENTAL"] = "1"
    os.environ["STORY_AUTO_FLOW_RPC_PROJECT"] = flow_runtime.project_identity
    result = {"scope": "canonical engineering service, production QC not exercised", "status": "BLOCKED"}
    try:
        session_factory = None
        if args.cookies:
            from functools import partial
            from story_auto.providers.flow.cookie_session import CookieBrowserRpcSession
            session_factory = partial(CookieBrowserRpcSession,cookie_file=args.cookies)
            with session_factory(flow_runtime) as session:
                session.catalog()
            # Narrow canary scope already live-qualified: one PNG -> 8s VIDEO.
            # This is not a general product capability declaration.
            capabilities = FlowCapabilities(True,True,False,True,False,True)
        else:
            capabilities = preflight(flow_runtime, FlowInspector(flow_runtime))
        generator = LiveFlowGenerator(flow_runtime, timeout_seconds=150,rpc_session_factory=session_factory)
        result["execution"] = execute_generation(args.runtime, project_id, executor=FlowExecutor(capabilities, generator), execute=True, request_ids={"shot"})
        manifest = read_json(paths.artifact_path("output/generation_manifest.json"))
        shot = next(row for row in manifest["requests"] if row["request_id"] == "shot")
        result.update(status=shot["status"], attempts=len(shot["attempts"]), provider_submissions=shot.get("provider_submissions"), selected_asset=shot.get("selected_asset"))
    except Exception as error:
        result["error"] = getattr(error, "failure_class", type(error).__name__)
    atomic_write_json(args.runtime / f"result-{uuid4().hex}.json", result)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "SUCCEEDED" else 2


if __name__ == "__main__": raise SystemExit(main())

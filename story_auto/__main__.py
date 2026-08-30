"""Minimal CLI for the Story Auto foundation."""

from __future__ import annotations
import argparse
import json
import uuid
from pathlib import Path

from .core.project import RuntimeLayout
from .providers.flow import FlowRuntime, FlowExecutor, launch_dedicated_session, preflight
from .providers.flow.live import FlowInspector, LiveFlowGenerator
from .application import OperatorService

def main() -> int:
    parser = argparse.ArgumentParser(prog="story-auto")
    parser.add_argument("--runtime-root", default="runtime", help="Story Auto runtime root")
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="Create an isolated project")
    new.add_argument("--project-id")
    new.add_argument("--render-mode", default="hybrid_hook", choices=("hybrid_hook","full_video_ai","ambient_story","full_image"))
    new.add_argument("--ambient-style", choices=("quiet_verdict","hidden_mastery"), help="Required when --render-mode ambient_story")
    for name in ("run", "resume"):
        command = commands.add_parser(name, help="Run the foundation pipeline" if name == "run" else "Resume the foundation pipeline")
        command.add_argument("project_id")
    production_status = commands.add_parser("production-status", help="Show the compact canonical production state")
    production_status.add_argument("project_id")
    flow_status = commands.add_parser("flow-status", help="Show the compact product-facing Flow state")
    flow_status.add_argument("project_id")
    prepare_flow = commands.add_parser("prepare-flow-recovery", help="Show the next safe Flow recovery action")
    prepare_flow.add_argument("project_id")
    validate_flow = commands.add_parser("validate-flow-connection", help="Validate the Flow project already expected by this Story Auto project")
    validate_flow.add_argument("project_id")
    validate_flow.add_argument("--project-url", help="Only for first-time setup; does not rebind this project")
    rebind_flow = commands.add_parser("rebind-flow-project", help="Explicitly use the validated runtime Flow project for future attempts")
    rebind_flow.add_argument("project_id")
    rebind_flow.add_argument("--explicit-owner-decision", action="store_true", required=True)
    continue_production = commands.add_parser("continue-production", help="Resume the same canonical production run")
    continue_production.add_argument("project_id")
    approve = commands.add_parser("approve-plan", help="Approve validated story timeline and continuity")
    approve.add_argument("project_id")
    visual = commands.add_parser("plan-visuals", help="Compile shot, media, and provider-independent generation plans")
    visual.add_argument("project_id")
    approve_shots = commands.add_parser("approve-shot-plan", help="Approve validated shot/media/generation planning")
    approve_shots.add_argument("project_id")
    accept_visuals = commands.add_parser("accept-pending-visuals-by-owner", help="Record owner acceptance when manual visual review is explicitly skipped")
    accept_visuals.add_argument("project_id")
    accept_visuals.add_argument("--reason", required=True)
    qc_policy = commands.add_parser("set-qc-policy", help="Set a supported project quality review policy")
    qc_policy.add_argument("project_id")
    qc_policy.add_argument("policy", choices=("AUTO_ACCEPT", "MANUAL_REVIEW"))
    qc_status = commands.add_parser("qc-status", help="Show compact project quality status")
    qc_status.add_argument("project_id")
    accept_assets = commands.add_parser("accept-assets", help="Accept selected eligible assets under Manual review")
    accept_assets.add_argument("project_id")
    accept_assets.add_argument("request_ids", nargs="+")
    accept_assets.add_argument("--reason", required=True)
    reject_assets = commands.add_parser("reject-assets", help="Reject selected assets under Manual review")
    reject_assets.add_argument("project_id")
    reject_assets.add_argument("request_ids", nargs="+")
    reject_assets.add_argument("--reason", required=True)
    flow = commands.add_parser("flow-preflight", help="Discover the dedicated Flow session capabilities")
    flow.add_argument("project_id")
    open_flow = commands.add_parser("flow-open-session", help="Open the isolated Flow profile for operator login")
    open_flow.add_argument("project_id")
    generate = commands.add_parser("execute-generation", help="Explicitly execute a bounded approved Flow generation slice")
    generate.add_argument("project_id")
    generate.add_argument("--confirm-execute-generation", action="store_true", help="Required: authorizes paid provider submissions")
    generate.add_argument("--all-ready", action="store_true", help="Execute an approved production batch, including repeated media kinds")
    generate.add_argument("--max-requests", type=int, help="Optional safe pause boundary for this invocation")
    render = commands.add_parser("render", help="Resolve, normalize, subtitle, mix, and render final.mp4")
    render.add_argument("project_id")
    publishing = commands.add_parser("publishing-metadata", help="Generate title candidates and description with Gemini")
    publishing.add_argument("project_id")
    thumbnail = commands.add_parser("prepare-thumbnail", help="Compile the publishing thumbnail Flow request")
    thumbnail.add_argument("project_id")
    generate_thumbnail = commands.add_parser("generate-thumbnail", help="Execute the prepared bounded Flow thumbnail request")
    generate_thumbnail.add_argument("project_id")
    generate_thumbnail.add_argument("--confirm-execute-generation", action="store_true")
    finish_thumbnail = commands.add_parser("finalize-thumbnail", help="Validate and bind the selected thumbnail")
    finish_thumbnail.add_argument("project_id")
    ui = commands.add_parser("ui", help="Run the loopback-only local operator UI")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        app = OperatorService(Path(args.runtime_root))
        if args.command == "ui":
            from .ui import serve
            serve(Path(args.runtime_root),args.host,args.port); return 0
        if args.command == "new":
            project_id = args.project_id or f"prj_{uuid.uuid4().hex}"
            app.create_project(project_id=project_id,render_mode=args.render_mode,ambient_style=args.ambient_style)
            print(f"CREATED {project_id}")
            return 0
        if args.command == "production-status":
            print(json.dumps(app.production_query(args.project_id), sort_keys=True))
            return 0
        if args.command == "flow-status":
            print(json.dumps(app.flow_status(args.project_id), sort_keys=True))
            return 0
        if args.command == "prepare-flow-recovery":
            print(json.dumps(app.prepare_flow_recovery(args.project_id), sort_keys=True))
            return 0
        if args.command == "validate-flow-connection":
            print(json.dumps(app.validate_flow_connection(args.project_id, args.project_url), sort_keys=True))
            return 0
        if args.command == "rebind-flow-project":
            print(json.dumps(app.rebind_flow_project(args.project_id, explicit_owner_decision=args.explicit_owner_decision), sort_keys=True))
            return 0
        if args.command == "continue-production":
            print(json.dumps(app.continue_production(args.project_id), sort_keys=True))
            return 0
        if args.command == "approve-plan":
            app.approve_planning(args.project_id)
            print("review_state: APPROVED")
            return 0
        if args.command == "approve-shot-plan":
            app.approve_planning(args.project_id,shots=True)
            print("review_state: APPROVED")
            return 0
        if args.command == "accept-pending-visuals-by-owner":
            print(json.dumps(app.accept_pending_visuals_by_owner(args.project_id, args.reason), sort_keys=True))
            return 0
        if args.command == "set-qc-policy":
            print(json.dumps(app.set_qc_policy(args.project_id, args.policy), sort_keys=True))
            return 0
        if args.command == "qc-status":
            print(json.dumps(app.query_qc_status(args.project_id), sort_keys=True))
            return 0
        if args.command == "accept-assets":
            print(json.dumps(app.accept_selected_assets(args.project_id, set(args.request_ids), args.reason), sort_keys=True))
            return 0
        if args.command == "reject-assets":
            print(json.dumps(app.reject_selected_assets(args.project_id, set(args.request_ids), args.reason), sort_keys=True))
            return 0
        if args.command == "plan-visuals":
            result=app.plan_visuals(args.project_id)
            print(f"shot_plan: READY\nmedia_plan: READY\ngeneration_requests: {len(result['generation_requests']['requests'])}")
            return 0
        if args.command == "flow-preflight":
            connection,status=app.flow_connections.connection_for_project(args.project_id,required_capabilities=["IMAGE"])
            if connection is None: raise ValueError(status["code"])
            runtime=app.flow_connections.runtime_for_connection(connection)
            capabilities = preflight(runtime, FlowInspector(runtime))
            print(json.dumps(capabilities.__dict__, default=str, sort_keys=True))
            return 0
        if args.command == "flow-open-session":
            connection,status=app.flow_connections.connection_for_project(args.project_id)
            if connection is None: raise ValueError(status["code"])
            launch_dedicated_session(app.flow_connections.runtime_for_connection(connection))
            print("FLOW_SESSION_OPENED: sign in manually in the dedicated Story Auto Chrome profile, then run flow-preflight")
            return 0
        if args.command == "execute-generation":
            if not args.confirm_execute_generation:
                raise ValueError("explicit --confirm-execute-generation is required")
            from .core.project import load_project
            paths, _config = load_project(RuntimeLayout.from_root(args.runtime_root), args.project_id)
            connection,status=app.flow_connections.connection_for_project(args.project_id,required_capabilities=["IMAGE"])
            if connection is None: raise ValueError(status["code"])
            runtime=app.flow_connections.runtime_for_connection(connection)
            capabilities = preflight(runtime, FlowInspector(runtime))
            requests = __import__('story_auto.core.artifacts', fromlist=['read_json']).read_json(paths.artifact_path("output/generation_requests.json"))["requests"]
            selected = requests if args.all_ready else []
            if not args.all_ready:
                reference = next((r for r in requests if r.get("purpose") == "REFERENCE" and r.get("media_type") == "IMAGE"), None)
                if reference: selected.append(reference)
                for media_type in ("IMAGE", "VIDEO"):
                    candidate = next((r for r in requests if r.get("purpose") == "SHOT" and r.get("media_type") == media_type and set(r.get("depends_on", [])) <= {reference["request_id"]}), None) if reference else None
                    if candidate: selected.append(candidate)
            if not selected: raise ValueError("no Flow requests are runnable")
            result = app.generate(args.project_id,executor=FlowExecutor(capabilities, LiveFlowGenerator(runtime)),request_ids={r["request_id"] for r in selected},max_requests=args.max_requests)
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.command == "render":
            print(json.dumps(app.render(args.project_id), sort_keys=True))
            return 0
        if args.command == "publishing-metadata":
            print(f"publishing_metadata: {app.publishing(args.project_id,'metadata')}")
            return 0
        if args.command == "prepare-thumbnail":
            print(json.dumps(app.publishing(args.project_id,'prepare_thumbnail'), sort_keys=True))
            return 0
        if args.command == "generate-thumbnail":
            if not args.confirm_execute_generation:
                raise ValueError("explicit --confirm-execute-generation is required")
            request = app.publishing(args.project_id,"prepare_thumbnail")
            connection,status=app.flow_connections.connection_for_project(args.project_id,required_capabilities=["IMAGE"])
            if connection is None: raise ValueError(status["code"])
            runtime=app.flow_connections.runtime_for_connection(connection)
            capabilities = preflight(runtime, FlowInspector(runtime))
            result = app.generate(args.project_id,executor=FlowExecutor(capabilities,LiveFlowGenerator(runtime)),request_ids={request["request_id"]})
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.command == "finalize-thumbnail":
            print(f"thumbnail: {app.publishing(args.project_id,'finalize_thumbnail')}")
            return 0
        result=app.start_or_resume(args.project_id)
        print("\n".join(f"{key}: {value}" for key,value in result.items() if key!="snapshot"))
        from .core.project import load_project
        paths, config = load_project(RuntimeLayout.from_root(args.runtime_root), args.project_id)
        if paths.artifact_path("output/generation_manifest.json").is_file():
            rendered = app.render(args.project_id)
            print(f"final_render: {rendered['actions']['final_render']}")
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"error: {error}\n")

if __name__ == "__main__":
    raise SystemExit(main())

"""Explicit single-shot transport canary; repeat runs are recovery-only."""
import argparse
import json
from pathlib import Path
from story_auto.core.artifacts import atomic_write_json
from story_auto.providers.flow.session import FlowRuntime
from story_auto.providers.flow.rpc_transport import FlowRpcGenerator, JOURNAL_NAME
from story_auto.providers.flow.rpc_transport import BrowserRpcSession
from story_auto.providers.flow.live import LiveFlowGenerator
import os


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--shot-id", default="rpc-integrated-canary-01")
    parser.add_argument("--crash-after-submit", action="store_true")
    args = parser.parse_args()
    flow = json.loads(args.project.read_text(encoding="utf-8"))["settings"]["provider_binding"]["flow"]
    runtime = FlowRuntime(args.profile, flow.get("cdp_url", "http://127.0.0.1:9222"), flow["project_url"], flow["project_identity"])
    request = {"request_id": args.shot_id, "media_type": "VIDEO", "target_duration": 8,
               "aspect_ratio": "16:9", "output_count": 1,
               "prompt": "Very slow camera orbit around the exact reference composition. Preserve the colors and geometric shapes. No additional objects. Smooth cinematic motion."}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    recovery = (args.output_dir / JOURNAL_NAME).exists()
    os.environ["STORY_AUTO_FLOW_RPC_EXPERIMENTAL"] = "1"
    os.environ["STORY_AUTO_FLOW_RPC_PROJECT"] = runtime.project_identity
    generator = LiveFlowGenerator(runtime, timeout_seconds=120)
    if args.crash_after_submit and not recovery:
        original_submit = BrowserRpcSession.submit
        def crash_submit(self, *values):
            response = original_submit(self, *values)
            atomic_write_json(args.output_dir / "crash-injection.json", {"point": "after_post_response_before_journal_ack", "exit_code": 86})
            os._exit(86)
        BrowserRpcSession.submit = crash_submit
    def boundary():
        atomic_write_json(args.output_dir / "boundary.json", {"provider_boundary_entered": True, "request_id": request["request_id"]})
    result = {"scope": "transport canary, not canonical production journey", "recovery_only": recovery}
    try:
        generator.set_before_provider_boundary(boundary)
        if recovery:
            request["_flow_reference_paths"] = [str(args.reference)]
            recovered = generator.reconcile(request, {}, args.output_dir / "output.mp4")
            if recovered["state"] != "CONFIRMED_OUTPUT":
                raise RuntimeError("RECOVERY_UNRESOLVED")
            output = recovered["path"]
        else:
            output = generator(request, [args.reference], args.output_dir / "output.mp4")
        result.update(status="PASS", output=str(output), settings=generator.last_settings)
    except Exception as error:
        result.update(status="UNRESOLVED", error_code=getattr(error, "failure_class", type(error).__name__), detail=str(error))
    label = "recovery" if recovery else "initial"
    target = args.output_dir / f"{label}-result.json"
    if target.exists():
        from uuid import uuid4
        target = args.output_dir / f"{label}-{uuid4().hex}-result.json"
    atomic_write_json(target, result)
    print(json.dumps({k: v for k, v in result.items() if k != "settings"}, indent=2))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__": raise SystemExit(main())

"""Read-only candidate check; never uploads, generates or mints CAPTCHA tokens."""
import argparse
import json
import hashlib
from pathlib import Path
from story_auto.core.artifacts import atomic_write_json
from story_auto.providers.flow.session import FlowRuntime
from story_auto.providers.flow.rpc_transport import BrowserRpcSession
from story_auto.providers.flow.rpc_contract import sanitize_session


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Refusing to overwrite evidence")
    config = json.loads(args.project.read_text(encoding="utf-8"))
    flow = config["settings"]["provider_binding"]["flow"]
    runtime = FlowRuntime(args.profile, flow.get("cdp_url", "http://127.0.0.1:9222"), flow["project_url"], flow["project_identity"])
    result = {"generation_attempts": 0, "upload_attempts": 0, "status": "BLOCKED"}
    try:
        with BrowserRpcSession(runtime) as session:
            result["session"] = sanitize_session(session.meta(), runtime.project_identity)
            records = session.catalog()
            result.update(status="READ_ONLY_PASS", record_count=len(records), record_lengths=sorted(set(map(len, records))))
            safe = result["session"]
            shape = {"host": safe["host"], "source_path_prefix": safe["source"].split("/")[1],
                     "wiz": {"at_len": safe["at_length"], "sid_present": safe["sid_present"], "bl_present": safe["bl_present"]},
                     "captcha_execute": safe["captcha_available"],
                     "catalog": {"record_lengths": result["record_lengths"], "project_position": 1 if records else None,
                                 "status_types": sorted({type(row[3]).__name__ for row in records})},
                     "catalog_anti_xssi": True}
            result["contract_shape"] = shape
            result["observed_fingerprint"] = hashlib.sha256(json.dumps(shape, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if args.baseline:
                baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
                result["baseline_match"] = baseline["contract_shape"] == shape
                if not result["baseline_match"]: result["status"] = "BLOCKED"
    except Exception as error:
        result["status"] = "BLOCKED"
        result["error_code"] = getattr(error, "code", type(error).__name__)
    atomic_write_json(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "READ_ONLY_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

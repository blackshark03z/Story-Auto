"""Read-only sanitized structural evidence from the already completed canary."""
import json
from pathlib import Path
from story_auto.core.artifacts import atomic_write_json
from story_auto.providers.flow.rpc_transport import BrowserRpcSession
from story_auto.providers.flow.session import FlowRuntime


def main():
    config = Path(r"D:\Story Auto\story-auto\runtime\projects\prj_b096c1c8e86948b9be8247ead0284774\project.json")
    journal = json.loads(Path(r"D:\Story Auto\evidence\transport_probe_20260920\integrated-transport-canary-11\flow_rpc_attempt.json").read_text())
    f = json.loads(config.read_text())["settings"]["provider_binding"]["flow"]
    runtime = FlowRuntime(Path(r"D:\Story Auto\story-auto\runtime\browser\flow-profile"), "http://127.0.0.1:9222", f["project_url"], f["project_identity"])
    paths = []
    def sanitize(value, path=()):
        if isinstance(value, list): return [sanitize(v, path+(i,)) for i,v in enumerate(value)]
        if isinstance(value, dict): raise ValueError("Unexpected record object")
        if isinstance(value, str):
            label = ("REFERENCE" if value == journal["reference_id"] else "OUTPUT" if value == journal["output_id"] else "PROJECT" if value == runtime.project_identity else "MODEL" if value == "abra_r2v_8s" else "PROMPT" if journal["marker"] in value else "OTHER")
            if label != "OTHER": paths.append({"path": list(path), "field": label})
            return label
        return value
    with BrowserRpcSession(runtime) as session:
        row = next(row for row in session.catalog() if row[0] == journal["output_id"])
        result = {"source": "completed canary 11 read-only catalog", "record": sanitize(row), "paths": paths}
    target = Path("tests/fixtures/flow_rpc_catalog_redacted.json")
    if target.exists(): raise SystemExit("Evidence already exists")
    atomic_write_json(target, result)
    print(json.dumps(paths))


if __name__ == "__main__": main()

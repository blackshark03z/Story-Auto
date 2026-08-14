"""Cancel one exact, still-running Flow prompt after its attempt is ambiguous."""
from __future__ import annotations

import argparse
from pathlib import Path

from story_auto.core.project import RuntimeLayout, load_project
from story_auto.providers.flow.cdp import CdpPage
from story_auto.providers.flow.session import FlowRuntime


parser = argparse.ArgumentParser()
parser.add_argument("runtime_root", type=Path)
parser.add_argument("project_id")
parser.add_argument("expected_prompt_fragment")
args = parser.parse_args()
paths, config = load_project(RuntimeLayout.from_root(args.runtime_root), args.project_id)
page = CdpPage.open(FlowRuntime.from_settings(paths.runtime, config.settings))
try:
    body = page.evaluate("document.body.innerText") or ""
    if args.expected_prompt_fragment not in body:
        raise SystemExit("EXPECTED_STUCK_PROMPT_NOT_VISIBLE")
    result = page.evaluate("""(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled};const xs=Array.from(document.querySelectorAll('button')).filter(e=>visible(e)&&e.querySelector('i')?.textContent.trim()==='cancel');if(xs.length!==1)return {count:xs.length};xs[0].click();return {count:1,cancelled:true}})()""")
    if not isinstance(result, dict) or result.get("cancelled") is not True:
        raise SystemExit(f"STUCK_GENERATION_CANCEL_AMBIGUOUS:{result}")
    print("EXACT_STUCK_FLOW_PROMPT_CANCELLED")
finally:
    page.close()

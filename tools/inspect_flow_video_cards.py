"""Read-only diagnostic of Flow video nodes and their enclosing card text."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from story_auto.core.project import RuntimeLayout, load_project
from story_auto.providers.flow.cdp import CdpPage
from story_auto.providers.flow.session import FlowRuntime


parser = argparse.ArgumentParser()
parser.add_argument("runtime_root", type=Path)
parser.add_argument("project_id")
args = parser.parse_args()
paths, config = load_project(RuntimeLayout.from_root(args.runtime_root), args.project_id)
page = CdpPage.open(FlowRuntime.from_settings(paths.runtime, config.settings))
try:
    value = page.evaluate("""(()=>Array.from(document.querySelectorAll('video,video source')).map((e,i)=>{
      let p=e;const ancestors=[];
      for(let n=0;n<10&&p;n++,p=p.parentElement)ancestors.push({n,tag:p.tagName,cls:(p.className||'').toString().slice(0,120),text:(p.innerText||'').slice(0,900)});
      return {i,url:e.currentSrc||e.src||e.getAttribute('src'),ancestors};
    }))()""")
    print(json.dumps(value, ensure_ascii=False, indent=2))
finally:
    page.close()

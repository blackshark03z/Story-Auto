from pathlib import Path
from story_auto.core.project import RuntimeLayout, load_project
from story_auto.providers.flow.session import FlowRuntime
from story_auto.providers.flow.cdp import CdpPage
from story_auto.providers.flow.live import _CANDIDATE_RECORDS_JS
import json, sys
rt=RuntimeLayout.from_root(Path(sys.argv[1])); _,cfg=load_project(rt,sys.argv[2]); page=CdpPage.open(FlowRuntime.from_settings(rt,cfg.settings))
try:
    value=page.evaluate("""(()=>({url:location.href,editors:Array.from(document.querySelectorAll('textarea,[contenteditable=true]')).map(e=>({text:e.value||e.innerText,disabled:e.disabled})),buttons:Array.from(document.querySelectorAll('button')).filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0}).slice(-16).map(e=>({text:e.innerText,aria:e.getAttribute('aria-label'),disabled:e.disabled,type:e.type}))}))()""")
    window=page.command("Browser.getWindowForTarget"); value["window"]=page.command("Browser.getWindowBounds",{"windowId":window["windowId"]})
    value["candidates"]=page.evaluate(_CANDIDATE_RECORDS_JS)
    print(json.dumps(value,indent=2,ensure_ascii=False))
finally: page.close()

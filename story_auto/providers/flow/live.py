"""Concrete Flow CDP adapter. UI assumptions live here and fail closed."""
from __future__ import annotations

import base64
import time
from pathlib import Path

from story_auto.core.artifacts import atomic_write_bytes
from .cdp import CdpPage
from .page import FlowComposer
from .service import FlowError
from .settings import ResolvedFlowGenerationSettings, resolve_settings


_VISIBLE = "e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled}"
_EDITOR_JS = """(()=>Array.from(document.querySelectorAll('textarea,[contenteditable="true"]')).filter(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled}).map((e,i)=>({i,text:e.value??e.innerText??'',is_empty:e.tagName==='TEXTAREA'?!e.value:!!e.querySelector('[data-slate-zero-width][data-slate-length="0"]'),tag:e.tagName})))()"""
_CONTROL_JS = """(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable="true"]')).find(visible);if(!editor)return [];let p=editor.parentElement;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button')).filter(e=>visible(e)&&e.type==='submit'&&e.querySelector('i')?.textContent.trim()==='arrow_forward');if(xs.length===1){const e=xs[0],r=e.getBoundingClientRect();return [{label:(e.innerText+' '+(e.getAttribute('aria-label')||'')).trim(),enabled:e.getAttribute('aria-disabled')!=='true',x:r.left+r.width/2,y:r.top+r.height/2}]}if(xs.length>1)return xs.map(e=>({label:e.innerText,enabled:e.getAttribute('aria-disabled')!=='true'}));p=p.parentElement}return []})()"""
_CANDIDATES_JS = """(()=>Array.from(document.querySelectorAll('img,video,video source')).map(e=>e.currentSrc||e.src||e.getAttribute('src')).filter(x=>typeof x==='string'&&x&&!x.startsWith('data:')).filter((x,i,a)=>a.indexOf(x)===i))()"""
_ACTIVATE = "e=>{e.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));e.click()}"
_MODEL_TRIGGER = """(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable="true"]')).find(visible);let p=editor;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button[aria-haspopup="menu"]')).filter(visible);if(xs.length===1)return xs[0];p=p.parentElement}return null})()"""


class _Editor:
    def __init__(self, dom, index): self.dom,self.index=dom,index
    def set_text(self, value):
        # Focus resolution is DOM-only; content changes flow through native CDP
        # keyboard/input events so the React/Slate application state receives them.
        states = self.dom.page.evaluate(_EDITOR_JS) or []
        if self.index >= len(states) or not states[self.index].get("is_empty"):
            raise FlowError("FLOW_UI_CHANGED", "active Flow editor was not empty after safe composer reset")
        self.dom.page.evaluate("""(()=>{const e=Array.from(document.querySelectorAll('textarea,[contenteditable=\"true\"]')).filter(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled})[%d];if(!e)throw Error('editor');e.focus()})()""" % self.index)
        self.dom.page.insert_text(value)
        self.dom.page.key("Tab", code="Tab")
    def read_text(self): return self.dom.page.evaluate(_EDITOR_JS)[self.index]["text"]

class _Control:
    def __init__(self, dom, evidence): self.dom,self.evidence=dom,evidence
    def click(self):
        if not self.evidence.get("enabled"): raise FlowError("FLOW_GENERATE_DISABLED")
        self.dom.page.click(float(self.evidence["x"]), float(self.evidence["y"]))


class FlowBrowserDom:
    def __init__(self, page: CdpPage): self.page = page
    def active_prompt_editors(self): return [_Editor(self, x["i"]) for x in self.page.evaluate(_EDITOR_JS) or []]
    def reset_composer(self, *, timeout_seconds: int = 12) -> None:
        """Reloads a no-dispatch draft to clear stale UI state before an attempt."""
        self.page.command("Page.reload", {"ignoreCache":False})
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                editors = self.page.evaluate(_EDITOR_JS) or []
                if len(editors) == 1 and editors[0].get("is_empty"): return
            except Exception: pass
            time.sleep(.25)
        raise FlowError("FLOW_UI_CHANGED", "Flow composer did not return to one empty editor")
    def choose_mode(self, media_type):
        token = "IMAGE" if media_type == "IMAGE" else "VIDEO"
        result = self.page.evaluate("""(async()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable=\"true\"]')).find(visible);let p=editor,trigger=null;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button[aria-haspopup=\"menu\"]')).filter(visible);if(xs.length===1){trigger=xs[0];break}p=p.parentElement}if(!trigger)return {reason:'model_trigger'};if(trigger.getAttribute('aria-expanded')!=='true'){(%s)(trigger);await new Promise(r=>setTimeout(r,250));}const xs=Array.from(document.querySelectorAll('button[aria-controls*=%s]')).filter(visible);if(xs.length!==1)return {reason:'mode',count:xs.length};(%s)(xs[0]);await new Promise(r=>setTimeout(r,250));return {ok:true}})()""" % (_ACTIVATE, __import__('json').dumps("content-" + token), _ACTIVATE))
        if not isinstance(result, dict) or not result.get("ok"): raise FlowError("FLOW_UI_CHANGED", f"unable to resolve {media_type} mode: {result}")
    def apply_settings(self, resolved: ResolvedFlowGenerationSettings) -> dict:
        """Set/re-read tabs and counts; all labels/DOM stay inside this adapter."""
        token = "IMAGE" if resolved.media_type == "IMAGE" else "VIDEO"
        ratio = {"16:9":"LANDSCAPE", "4:3":"LANDSCAPE_4_3", "1:1":"SQUARE", "3:4":"PORTRAIT_3_4", "9:16":"PORTRAIT"}.get(resolved.aspect_ratio)
        if not ratio: raise FlowError("FLOW_CAPABILITY_UNAVAILABLE", "unsupported Flow aspect ratio")
        script = """(async()=>{const activate=e=>{e.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));e.click()};const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable=\"true\"]')).find(visible);let p=editor,trigger=null;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button[aria-haspopup=\"menu\"]')).filter(visible);if(xs.length===1){trigger=xs[0];break}p=p.parentElement}if(!trigger)throw Error('model_trigger');if(trigger.getAttribute('aria-expanded')!=='true'){activate(trigger);await new Promise(r=>setTimeout(r,250));}const tab=token=>Array.from(document.querySelectorAll('button[aria-controls]')).filter(e=>(e.getAttribute('aria-controls')||'').endsWith('content-'+token)&&visible(e));const choose=(token,reason)=>{const xs=tab(token);if(xs.length!==1)throw Error(reason+':'+xs.length);activate(xs[0])};choose(%s,'mode');await new Promise(r=>setTimeout(r,200));choose(%s,'ratio');await new Promise(r=>setTimeout(r,200));choose(%s,'count');await new Promise(r=>setTimeout(r,200));const active=token=>tab(token).filter(e=>e.getAttribute('aria-selected')==='true').length===1;const out={media:active(%s),ratio:active(%s),count:active(%s),model:trigger.innerText.trim()};activate(trigger);await new Promise(r=>setTimeout(r,200));out.menu_closed=trigger.getAttribute('aria-expanded')!=='true';return out})()""" % tuple(__import__('json').dumps(v) for v in (token,ratio,str(resolved.output_count),token,ratio,str(resolved.output_count)))
        actual = self.page.evaluate(script)
        if not isinstance(actual,dict) or not all(actual.get(k) for k in ("media","ratio","count")): raise FlowError("FLOW_UI_CHANGED", f"settings readback mismatch: {actual}")
        # The configuring trigger itself supplied this value before its menu
        # was closed; do not re-query an icon variant that exists only while
        # the popover is open.
        if not actual["model"]: raise FlowError("FLOW_UI_CHANGED", "actual Flow model selector was ambiguous")
        actual.update({"requested_model":resolved.model_preference,"output_count":resolved.output_count,"aspect_ratio":resolved.aspect_ratio,"workflow_mode":resolved.workflow_mode,"quality_tier":resolved.quality_tier,"reference_mode":resolved.reference_mode,"duration_seconds":resolved.duration_seconds})
        if not actual.pop("menu_closed", False): raise FlowError("FLOW_UI_CHANGED", "Flow settings menu did not close before submit")
        return actual
    def generate_controls(self, _editor, _media_type):
        # A reference upload is asynchronous.  Do not treat a transiently
        # disabled Generate button as a selector mismatch or click it early.
        deadline = time.monotonic() + 12
        last = []
        while time.monotonic() < deadline:
            last = self.page.evaluate(_CONTROL_JS) or []
            if len(last) == 1 and last[0].get("enabled"):
                time.sleep(.25)
                confirmed = self.page.evaluate(_CONTROL_JS) or []
                if len(confirmed) == 1 and confirmed[0].get("enabled"):
                    return [_Control(self, confirmed[0])]
            elif len(last) > 1:
                return [_Control(self, x) for x in last]
            time.sleep(.25)
        if len(last) == 1 and not last[0].get("enabled"):
            raise FlowError("FLOW_GENERATE_DISABLED", "Flow did not enable composer Generate after reference upload")
        return [_Control(self, x) for x in last]
    def add_references(self, files):
        # Native file inputs are normally hidden behind a visible upload button.
        count = self.page.evaluate("document.querySelectorAll('input[type=file]').length")
        if count != 1: raise FlowError("FLOW_UI_CHANGED", f"expected one reference input, found {count}")
        self.page.set_input_files("input[type=file]", [str(Path(f).resolve()) for f in files])
    def media_candidates(self): return self.page.evaluate(_CANDIDATES_JS) or []


class FlowInspector:
    def __init__(self, runtime): self.runtime = runtime
    def inspect(self, _url):
        page = CdpPage.open(self.runtime)
        try:
            state = page.evaluate("""(()=>({url:location.href,text:(document.body?.innerText||'').slice(0,12000),title:document.title}))()""") or {}
            text = (state.get("text", "") + " " + state.get("title", "")).lower()
            login = "accounts.google" in state.get("url", "") or "sign in" in text
            modes = page.evaluate("""(async()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable=\"true\"]')).find(visible);let p=editor,trigger=null;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button[aria-haspopup=\"menu\"]')).filter(visible);if(xs.length===1){trigger=xs[0];break}p=p.parentElement}if(!trigger)return [];if(trigger.getAttribute('aria-expanded')!=='true'){(%s)(trigger);await new Promise(r=>setTimeout(r,250));}return Array.from(document.querySelectorAll('button[aria-controls]')).filter(visible).map(e=>e.getAttribute('aria-controls')||'')})()""" % _ACTIVATE) or []
            image = any("content-IMAGE" in value for value in modes)
            video = any("content-VIDEO" in value for value in modes)
            reference = bool(page.evaluate("document.querySelectorAll('input[type=file]').length"))
            # Project identity is provider runtime configuration, verified from
            # the active project URL rather than story text or current title.
            project_ok = self.runtime.project_identity in state.get("url", "") or state.get("url", "").rstrip("/") == self.runtime.project_url.rstrip("/")
            return {"login_required":login, "project_identity":self.runtime.project_identity if project_ok else "", "image":image, "video":video, "reference_image":reference, "frame_video":reference}
        finally: page.close()


class LiveFlowGenerator:
    def __init__(self, runtime, *, timeout_seconds: int = 180): self.runtime,self.timeout_seconds,self.last_settings,self.dispatch_confirmed=runtime,timeout_seconds,None,False
    def __call__(self, request, references, destination: Path):
        page=CdpPage.open(self.runtime)
        try:
            dom=FlowBrowserDom(page); dom.reset_composer(); resolved=resolve_settings(request); self.last_settings=dom.apply_settings(resolved)
            before, before_text = set(), ""
            def baseline():
                nonlocal before, before_text
                before = set(dom.media_candidates())
                before_text = page.evaluate("document.body.innerText")
            FlowComposer(dom).submit(request["prompt"], references=[x for x in references if x], media_type=request["media_type"], before_dispatch=baseline, mode_already_configured=True)
            # An immediate composer/UI transition is a dispatch acknowledgement;
            # final media remains separately attributable by pre/post comparison.
            for _ in range(8):
                now_text=page.evaluate("document.body.innerText")
                if now_text != before_text or set(dom.media_candidates()) != before:
                    self.dispatch_confirmed = True; self.last_settings["dispatch_ack_method"]="composer_or_output_transition"; break
                time.sleep(.25)
            if not self.dispatch_confirmed: raise FlowError("FLOW_NOT_DISPATCHED", "native click produced no Flow acknowledgement")
            deadline=time.monotonic()+self.timeout_seconds
            while time.monotonic()<deadline:
                added=[x for x in dom.media_candidates() if x not in before]
                if len(added)==1:
                    payload=page.evaluate("""(async()=>{const r=await fetch(%s);if(!r.ok)throw Error('fetch');const b=await r.arrayBuffer();let s='';for(const x of new Uint8Array(b))s+=String.fromCharCode(x);return {data:btoa(s),type:r.headers.get('content-type')||''}})()""" % __import__('json').dumps(added[0]))
                    if not isinstance(payload,dict) or not isinstance(payload.get("data"),str): raise FlowError("ASSET_ACQUISITION_FAILED")
                    atomic_write_bytes(destination, base64.b64decode(payload["data"], validate=True)); return destination
                if len(added)>1: raise FlowError("FLOW_RESULT_AMBIGUOUS", "multiple new provider outputs")
                time.sleep(2)
            raise FlowError("FLOW_TIMEOUT", "submitted request has no uniquely attributable result")
        finally: page.close()

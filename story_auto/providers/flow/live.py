"""Concrete Flow CDP adapter. UI assumptions live here and fail closed."""
from __future__ import annotations

import base64
import time
from pathlib import Path

from story_auto.core.artifacts import atomic_write_bytes
from .cdp import CdpPage
from .page import FlowComposer
from .service import FlowError


_VISIBLE = "e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled}"
_EDITOR_JS = """(()=>Array.from(document.querySelectorAll('textarea,[contenteditable="true"]')).filter(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled}).map((e,i)=>({i,text:e.value??e.innerText??'',tag:e.tagName})))()"""
_CONTROL_JS = """(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled&&e.getAttribute('aria-disabled')!=='true'};const all=Array.from(document.querySelectorAll('button[type="submit"]'));const editor=Array.from(document.querySelectorAll('textarea,[contenteditable="true"]')).find(visible);let p=editor;while(p&&p!==document.body){const xs=all.filter(e=>p.contains(e)&&visible(e));if(xs.length===1){const e=xs[0];return [{i:all.indexOf(e),label:(e.innerText+' '+(e.getAttribute('aria-label')||'')).trim()}]}if(xs.length>1)return xs.map(e=>({i:all.indexOf(e),label:(e.innerText+' '+(e.getAttribute('aria-label')||'')).trim()}));p=p.parentElement}return []})()"""
_CANDIDATES_JS = """(()=>Array.from(document.querySelectorAll('img,video,video source')).map(e=>e.currentSrc||e.src||e.getAttribute('src')).filter(x=>typeof x==='string'&&x&&!x.startsWith('data:')).filter((x,i,a)=>a.indexOf(x)===i))()"""
_ACTIVATE = "e=>{e.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));e.click()}"
_MODEL_TRIGGER = """(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable="true"]')).find(visible);let p=editor;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button[aria-haspopup="menu"]')).filter(visible);if(xs.length===1)return xs[0];p=p.parentElement}return null})()"""


class _Editor:
    def __init__(self, dom, index): self.dom,self.index=dom,index
    def set_text(self, value):
        value = __import__('json').dumps(value)
        self.dom.page.evaluate("""(()=>{const e=Array.from(document.querySelectorAll('textarea,[contenteditable=\"true\"]')).filter(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled})[%d];if(!e)throw Error('editor');e.focus();if(e.tagName==='TEXTAREA'){e.value=%s;e.dispatchEvent(new Event('input',{bubbles:true}));}else{e.textContent=%s;e.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:%s}));}})()""" % (self.index,value,value,value))
    def read_text(self): return self.dom.page.evaluate(_EDITOR_JS)[self.index]["text"]

class _Control:
    def __init__(self, dom, index): self.dom,self.index=dom,index
    def click(self):
        self.dom.page.evaluate("""(()=>{const xs=Array.from(document.querySelectorAll('button[type=\"submit\"]'));if(!xs[%d])throw Error('generate');(%s)(xs[%d])})()""" % (self.index,_ACTIVATE,self.index))


class FlowBrowserDom:
    def __init__(self, page: CdpPage): self.page = page
    def active_prompt_editors(self): return [_Editor(self, x["i"]) for x in self.page.evaluate(_EDITOR_JS) or []]
    def choose_mode(self, media_type):
        token = "IMAGE" if media_type == "IMAGE" else "VIDEO"
        result = self.page.evaluate("""(async()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable=\"true\"]')).find(visible);let p=editor,trigger=null;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button[aria-haspopup=\"menu\"]')).filter(visible);if(xs.length===1){trigger=xs[0];break}p=p.parentElement}if(!trigger)return {reason:'model_trigger'};if(trigger.getAttribute('aria-expanded')!=='true'){(%s)(trigger);await new Promise(r=>setTimeout(r,250));}const xs=Array.from(document.querySelectorAll('button[aria-controls*=%s]')).filter(visible);if(xs.length!==1)return {reason:'mode',count:xs.length};(%s)(xs[0]);await new Promise(r=>setTimeout(r,250));return {ok:true}})()""" % (_ACTIVATE, __import__('json').dumps("content-" + token), _ACTIVATE))
        if not isinstance(result, dict) or not result.get("ok"): raise FlowError("FLOW_UI_CHANGED", f"unable to resolve {media_type} mode: {result}")
    def generate_controls(self, _editor, _media_type): return [_Control(self, x["i"]) for x in self.page.evaluate(_CONTROL_JS) or []]
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
    def __init__(self, runtime, *, timeout_seconds: int = 180): self.runtime,self.timeout_seconds=runtime,timeout_seconds
    def __call__(self, request, references, destination: Path):
        page=CdpPage.open(self.runtime)
        try:
            dom=FlowBrowserDom(page); before=set(dom.media_candidates())
            FlowComposer(dom).submit(request["prompt"], references=[x for x in references if x], media_type=request["media_type"])
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

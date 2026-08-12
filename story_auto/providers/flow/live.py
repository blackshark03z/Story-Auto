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
_CONTROL_JS = """(()=>Array.from(document.querySelectorAll('button,[role="button"]')).filter(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e),n=(e.innerText+' '+(e.getAttribute('aria-label')||'')+' '+(e.getAttribute('title')||'')).trim().toLowerCase();return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled&&n==='generate'}).map((e,i)=>({i,label:(e.innerText+' '+(e.getAttribute('aria-label')||'')).trim()})))()"""
_CANDIDATES_JS = """(()=>Array.from(document.querySelectorAll('img,video,video source')).map(e=>e.currentSrc||e.src||e.getAttribute('src')).filter(x=>typeof x==='string'&&x&&!x.startsWith('data:')).filter((x,i,a)=>a.indexOf(x)===i))()"""


class _Editor:
    def __init__(self, dom, index): self.dom,self.index=dom,index
    def set_text(self, value):
        value = __import__('json').dumps(value)
        self.dom.page.evaluate("""(()=>{const e=Array.from(document.querySelectorAll('textarea,[contenteditable=\"true\"]')).filter(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled})[%d];if(!e)throw Error('editor');e.focus();if(e.tagName==='TEXTAREA'){e.value=%s;e.dispatchEvent(new Event('input',{bubbles:true}));}else{e.textContent=%s;e.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:%s}));}})()""" % (self.index,value,value,value))
    def read_text(self): return self.dom.page.evaluate(_EDITOR_JS)[self.index]["text"]

class _Control:
    def __init__(self, dom, index): self.dom,self.index=dom,index
    def click(self):
        self.dom.page.evaluate("""(()=>{const xs=Array.from(document.querySelectorAll('button,[role=\"button\"]')).filter(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e),n=(e.innerText+' '+(e.getAttribute('aria-label')||'')+' '+(e.getAttribute('title')||'')).trim().toLowerCase();return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled&&n==='generate'});if(!xs[%d])throw Error('generate');xs[%d].click()})()""" % (self.index,self.index))


class FlowBrowserDom:
    def __init__(self, page: CdpPage): self.page = page
    def active_prompt_editors(self): return [_Editor(self, x["i"]) for x in self.page.evaluate(_EDITOR_JS) or []]
    def choose_mode(self, media_type):
        label = media_type.lower()
        matched = self.page.evaluate("""(()=>Array.from(document.querySelectorAll('button,[role=\"button\"]')).filter(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e),n=(e.innerText+' '+(e.getAttribute('aria-label')||'')).trim().toLowerCase();return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&n===%s}).map((e,i)=>i))()""" % __import__('json').dumps(label)) or []
        if len(matched) != 1: raise FlowError("FLOW_UI_CHANGED", f"expected one {media_type} mode control, found {len(matched)}")
        self.page.evaluate("""(()=>{const e=Array.from(document.querySelectorAll('button,[role=\"button\"]')).filter(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e),n=(e.innerText+' '+(e.getAttribute('aria-label')||'')).trim().toLowerCase();return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&n===%s})[0];if(!e)throw Error('mode');e.click()})()""" % __import__('json').dumps(label))
    def generate_controls(self, _editor, _media_type): return [_Control(self, x["i"]) for x in self.page.evaluate(_CONTROL_JS) or []]
    def add_references(self, files):
        # Exactly one visible file input is required; multiple upload affordances are unsafe.
        count = self.page.evaluate("""(()=>Array.from(document.querySelectorAll('input[type=file]')).filter(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'}).length)()""")
        if count != 1: raise FlowError("FLOW_UI_CHANGED", f"expected one visible reference input, found {count}")
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
            image = "image" in text and bool(page.evaluate(_EDITOR_JS))
            video = "video" in text and bool(page.evaluate(_EDITOR_JS))
            reference = bool(page.evaluate("document.querySelectorAll('input[type=file]').length"))
            return {"login_required":login, "project_identity":self.runtime.project_identity if self.runtime.project_identity.lower() in text else "", "image":image, "video":video, "reference_image":reference, "frame_video":reference}
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

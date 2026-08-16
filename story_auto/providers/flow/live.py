"""Concrete Flow CDP adapter. UI assumptions live here and fail closed."""
from __future__ import annotations

import base64
import io
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from story_auto.core.artifacts import atomic_write_bytes, sha256_file
from .cdp import CdpPage
from .page import FlowComposer
from .service import FlowError
from .session import FlowSessionError
from .settings import ResolvedFlowGenerationSettings, resolve_settings
from .validation import validate_image


_VISIBLE = "e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled}"
_EDITOR_JS = """(()=>Array.from(document.querySelectorAll('textarea,[contenteditable="true"]')).filter(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled}).map((e,i)=>({i,text:e.value??e.innerText??'',is_empty:e.tagName==='TEXTAREA'?!e.value:!!e.querySelector('[data-slate-zero-width][data-slate-length="0"]'),tag:e.tagName})))()"""
_CONTROL_JS = """(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable="true"]')).find(visible);if(!editor)return [];let p=editor.parentElement;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button')).filter(e=>visible(e)&&e.type==='submit'&&e.querySelector('i')?.textContent.trim()==='arrow_forward');if(xs.length===1){const e=xs[0],r=e.getBoundingClientRect();return [{label:(e.innerText+' '+(e.getAttribute('aria-label')||'')).trim(),enabled:e.getAttribute('aria-disabled')!=='true',x:r.left+r.width/2,y:r.top+r.height/2}]}if(xs.length>1)return xs.map(e=>({label:e.innerText,enabled:e.getAttribute('aria-disabled')!=='true'}));p=p.parentElement}return []})()"""
_CANDIDATES_JS = """(()=>Array.from(document.querySelectorAll('img,video,video source')).map(e=>e.currentSrc||e.src||e.getAttribute('src')).filter(x=>typeof x==='string'&&x&&!x.startsWith('data:')).filter((x,i,a)=>a.indexOf(x)===i))()"""
_CANDIDATE_RECORDS_JS = """(()=>{const seen=new Set(),out=[];for(const e of document.querySelectorAll('img,video,video source')){const url=e.currentSrc||e.src||e.getAttribute('src');if(typeof url!=='string'||!url||url.startsWith('data:'))continue;let key=url;try{const parsed=new URL(url,location.href);parsed.hash='';key=parsed.href}catch{}if(!seen.has(key)){seen.add(key);out.push({key,url,kind:e.tagName,width:e.naturalWidth||e.videoWidth||0,height:e.naturalHeight||e.videoHeight||0})}}return out})()"""
_ACTIVATE = "e=>{e.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));e.click()}"
_MODEL_TRIGGER = """(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable="true"]')).find(visible);let p=editor;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button[aria-haspopup="menu"]')).filter(visible);if(xs.length===1)return xs[0];p=p.parentElement}return null})()"""

def records_for_media(records, media_type: str):
    allowed = {"IMG"} if media_type == "IMAGE" else {"VIDEO", "SOURCE"}
    return [item for item in records if item.get("kind") in allowed and (media_type != "IMAGE" or int(item.get("width", 0)) >= 512)]

def _dhash_bytes(data: bytes) -> str:
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        sample=image.convert("L").resize((17,16),Image.Resampling.LANCZOS); values=list(sample.getdata())
    bits=0
    for row in range(16):
        for column in range(16): bits=(bits<<1)|(values[row*17+column]>values[row*17+column+1])
    return f"{bits:064x}"


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
        # Flow ignores the trusted pointer sequence while its dedicated Chrome
        # window is minimized.  Foreground the exact CDP page, never another
        # browser profile, immediately before native input.
        try:
            window = self.dom.page.command("Browser.getWindowForTarget")
            if window.get("windowId") is not None:
                self.dom.page.command("Browser.setWindowBounds", {"windowId":window["windowId"],"bounds":{"windowState":"normal"}})
        except Exception:
            pass
        self.dom.page.command("Page.bringToFront")
        receipt = {
            "activation_time": datetime.now(timezone.utc).isoformat(),
            "interaction_method": "CDP_TRUSTED_POINTER",
            "interaction_version": 2,
            "target_resolved_at_activation": False,
            "input_dispatched": False,
            "trusted_click_seen": False,
        }
        self.dom.last_activation_receipt = receipt
        # Flow's floating composer can reflow during the baseline/readiness
        # window. Re-resolve the target and coordinates immediately before
        # input; cached coordinates create a time-of-check/time-of-use defect.
        controls = self.dom.page.evaluate(_CONTROL_JS) or []
        if len(controls) != 1 or not controls[0].get("enabled"):
            raise FlowError("FLOW_PRE_DISPATCH_ACTIVATION_FAILED", "Generate was not uniquely ready at activation")
        receipt["target_resolved_at_activation"] = True
        installed = self.dom.page.evaluate("""(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable=\"true\"]')).find(visible);if(!editor)return false;let p=editor.parentElement,control=null;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button')).filter(e=>visible(e)&&e.type==='submit'&&e.querySelector('i')?.textContent.trim()==='arrow_forward');if(xs.length===1){control=xs[0];break}if(xs.length>1)return false;p=p.parentElement}if(!control)return false;window.__storyAutoFlowActivationV2=[];for(const name of ['pointerdown','mousedown','pointerup','mouseup','click'])control.addEventListener(name,e=>window.__storyAutoFlowActivationV2.push({type:e.type,isTrusted:e.isTrusted,button:e.button,buttons:e.buttons,pointerType:e.pointerType||null,defaultPrevented:e.defaultPrevented}),true);return true})()""")
        if not installed:
            raise FlowError("FLOW_PRE_DISPATCH_ACTIVATION_FAILED", "Generate target changed before input")
        try:
            self.dom.page.click(float(controls[0]["x"]), float(controls[0]["y"]))
            receipt["input_dispatched"] = True
        except Exception as error:
            receipt["transport_error"] = type(error).__name__
            raise FlowError("FLOW_DISPATCH_UNCERTAIN", "native activation transport failed after input began") from error
        time.sleep(.25)
        events = self.dom.page.evaluate("window.__storyAutoFlowActivationV2||[]") or []
        receipt["event_types"] = [item.get("type") for item in events]
        receipt["trusted_click_seen"] = any(item.get("type") == "click" and item.get("isTrusted") is True for item in events)
        self.dom.last_activation_receipt = receipt
        return receipt


class DispatchEvidenceTracker:
    """Conservative, request-local dispatch acknowledgement state machine."""
    def __init__(self):
        self.state = "NOT_CONFIRMED"
        self.signal = None
        self.confirmation_count = 0

    def observe(self, *, input_dispatched: bool, trusted_click_seen: bool = False,
                prompt_transition: bool = False, attributable_job: bool = False,
                attributable_output: bool = False, provider_job_id: str | None = None,
                unrelated_dom_mutation: bool = False, legacy_ack_present: bool | None = None) -> str:
        del unrelated_dom_mutation, legacy_ack_present
        signal = None
        if provider_job_id:
            signal = "provider_job_id"
        elif attributable_job:
            signal = "new_attributable_job_state"
        elif attributable_output:
            signal = "new_attributable_output"
        if signal:
            if self.state != "CONFIRMED": self.confirmation_count += 1
            self.state, self.signal = "CONFIRMED", signal
        elif not input_dispatched:
            self.state, self.signal = "PRE_DISPATCH_FAILURE", "input_not_dispatched"
        elif self.state != "CONFIRMED" and (trusted_click_seen or prompt_transition):
            self.state = "UNCERTAIN"
            self.signal = "composer_transition_after_activation" if prompt_transition else "trusted_click_only"
        return self.state


class FlowBrowserDom:
    def __init__(self, page: CdpPage): self.page = page
    def active_prompt_editors(self): return [_Editor(self, x["i"]) for x in self.page.evaluate(_EDITOR_JS) or []]
    def reset_composer(self, *, timeout_seconds: int = 30) -> None:
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
        actual.update({"requested_model":resolved.model_preference,"requested_output_count":resolved.output_count,"actual_output_count":resolved.output_count,"output_count":resolved.output_count,"aspect_ratio":resolved.aspect_ratio,"workflow_mode":resolved.workflow_mode,"quality_tier":resolved.quality_tier,"reference_mode":resolved.reference_mode,"duration_seconds":resolved.duration_seconds})
        if resolved.media_type == "IMAGE" and not (actual["requested_output_count"] == actual["actual_output_count"] == 1):
            raise FlowError("IMAGE_OUTPUT_COUNT_MISMATCH")
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
        # The only file input belongs to Flow's project media library.  Upload
        # there first, then explicitly select the library item in the active
        # composer's add-media dialog; uploading alone is not an ingredient.
        if len(files) > 1:
            states = [self.add_references([reference]) for reference in files]
            return {"expected": len(files), "committed": all(item.get("committed") for item in states),
                    "method": "library_hash_match_and_composer_attach"}
        count = self.page.evaluate("document.querySelectorAll('input[type=file]').length")
        if count != 1: raise FlowError("FLOW_UI_CHANGED", f"expected one reference input, found {count}")
        local = [str(Path(f).resolve()) for f in files]
        self.page.set_input_files("input[type=file]", local)
        names = [Path(item).name for item in local]
        name = names[0]
        opened = self.page.evaluate("""(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable=\"true\"]')).find(visible);let p=editor;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button')).filter(e=>visible(e)&&e.querySelector('i')?.textContent.trim()==='add_2');if(xs.length===1){xs[0].click();return true}if(xs.length>1)return false;p=p.parentElement}return false})()""")
        if not opened: raise FlowError("FLOW_UI_CHANGED", "composer add-media control was ambiguous")
        target_hash=validate_image(Path(local[0]))["dhash256"]
        deadline=time.monotonic()+25; matched_url=None; matched_alt=None
        while time.monotonic()<deadline and matched_url is None:
            records=self.page.evaluate("""(()=>{const d=document.querySelector('[role=dialog]');if(!d)return [];const tab=Array.from(d.querySelectorAll('button[role=tab]')).find(e=>e.querySelector('i')?.textContent.trim()==='drive_folder_upload');if(tab&&tab.getAttribute('aria-selected')!=='true')tab.click();return Array.from(d.querySelectorAll('img')).filter(e=>e.naturalWidth>=512).map(e=>({url:e.currentSrc||e.src,alt:e.alt||''})).filter(x=>x.url)})()""") or []
            for record in records:
                url=record.get("url")
                payload=self.page.evaluate("""(async()=>{const r=await fetch(%s);if(!r.ok)return null;const b=await r.arrayBuffer();let s='';for(const x of new Uint8Array(b))s+=String.fromCharCode(x);return btoa(s)})()""" % __import__('json').dumps(url))
                if isinstance(payload,str):
                    try: candidate_hash=_dhash_bytes(base64.b64decode(payload,validate=True))
                    except Exception: continue
                    if (int(candidate_hash,16)^int(target_hash,16)).bit_count()<=4: matched_url=url; matched_alt=record.get("alt",""); break
            if matched_url is None: time.sleep(.5)
        if matched_url is None: raise FlowError("FLOW_REFERENCE_UPLOAD_FAILED", "uploaded reference bytes were not identifiable in Flow")
        selected=self.page.evaluate("""(()=>{const alt=%s,d=document.querySelector('[role=dialog]');if(!d)return false;const images=Array.from(d.querySelectorAll('img')).filter(e=>e.naturalWidth>=512&&(e.alt||'')===alt),image=images[images.length-1];if(!image)return false;image.click();return true})()""" % __import__('json').dumps(matched_alt))
        if not selected: raise FlowError("FLOW_REFERENCE_UPLOAD_FAILED", "matched reference could not be selected")
        deadline=time.monotonic()+5; attached=False
        while time.monotonic()<deadline:
            attached=self.page.evaluate("""(()=>{const d=document.querySelector('[role=dialog]');if(!d)return null;const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled};const add=Array.from(d.querySelectorAll('button')).filter(visible).reverse().find(e=>!e.querySelector('i')&&(e.innerText||'').trim());if(!add)return false;add.click();return true})()""")
            if attached is True: break
            time.sleep(.25)
        if not attached: raise FlowError("FLOW_REFERENCE_UPLOAD_FAILED", "matched reference could not be attached")
        deadline=time.monotonic()+6
        while time.monotonic()<deadline:
            if not self.page.evaluate("document.querySelector('[role=dialog]')!==null"):
                return {"expected": 1, "committed": True, "method": "library_hash_match_and_composer_attach"}
            time.sleep(.2)
        raise FlowError("FLOW_UI_CHANGED", "selected Flow reference dialog did not close")
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            selected=self.page.evaluate("""(()=>{const names=%s,d=document.querySelector('[role=dialog]');if(!d)return null;const tab=Array.from(d.querySelectorAll('button[role=tab]')).find(e=>e.querySelector('i')?.textContent.trim()==='drive_folder_upload');if(!tab)return null;if(tab.getAttribute('aria-selected')!=='true')tab.click();const images=names.map(name=>Array.from(d.querySelectorAll('img')).find(e=>e.alt===name));if(images.some(x=>!x))return false;for(const image of images)image.click();const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled};const add=Array.from(d.querySelectorAll('button')).filter(visible).find(e=>/add to prompt|thêm vào câu lệnh/i.test((e.innerText||'').trim()));if(!add)return null;add.click();return true})()""" % __import__('json').dumps(names))
            if selected is True: break
            time.sleep(.5)
        else: raise FlowError("FLOW_REFERENCE_UPLOAD_FAILED", f"uploaded references {names} were not all selectable in Flow")
        deadline=time.monotonic()+6
        while time.monotonic()<deadline:
            if not self.page.evaluate("document.querySelector('[role=dialog]')!==null"): return
            time.sleep(.2)
        raise FlowError("FLOW_UI_CHANGED", "selected Flow reference dialog did not close")
        open_dialog = self.page.evaluate("""(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable=\"true\"]')).find(visible);let p=editor;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button')).filter(e=>visible(e)&&e.querySelector('i')?.textContent.trim()==='add_2');if(xs.length===1){xs[0].click();return true}if(xs.length>1)return false;p=p.parentElement}return false})()""")
        if not open_dialog: raise FlowError("FLOW_UI_CHANGED", "composer add-media control was ambiguous")
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            selected=self.page.evaluate("""(()=>{const d=document.querySelector('[role=dialog]');if(!d)return null;const tab=Array.from(d.querySelectorAll('button[role=tab]')).find(e=>e.querySelector('i')?.textContent.trim()==='drive_folder_upload');if(!tab)return null;if(tab.getAttribute('aria-selected')!=='true')tab.click();const image=Array.from(d.querySelectorAll('img')).find(e=>e.alt===%s);if(!image)return false;image.click();const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled};const add=Array.from(d.querySelectorAll('button')).filter(visible).find(e=>{const text=(e.innerText||'').trim().toLowerCase();const aria=(e.getAttribute('aria-label')||'').toLowerCase();return /add|thêm|ajouter|hinzufügen|añadir/.test(text+' '+aria) && !/upload|tải|cancel|hủy|close|đóng/.test(text+' '+aria)});if(!add)return null;add.click();return true})()""" % __import__('json').dumps(name))
            if selected is True: break
            time.sleep(.5)
        else: raise FlowError("FLOW_REFERENCE_UPLOAD_FAILED", f"uploaded references {names} were not all selectable in Flow")
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if not self.page.evaluate("document.querySelector('[role=dialog]')!==null"):
                if len(files) > 1: self.add_references(files[1:])
                return
            time.sleep(.2)
        raise FlowError("FLOW_UI_CHANGED", "selected Flow reference dialog did not close")
    def media_candidates(self): return self.page.evaluate(_CANDIDATES_JS) or []
    def media_candidate_records(self): return self.page.evaluate(_CANDIDATE_RECORDS_JS) or []
    def newest_exact_image_group(self, expected_count: int):
        groups=self.page.evaluate("""(()=>{const expected=%d;const valid=e=>{const u=e.currentSrc||e.src||e.getAttribute('src');return e.tagName==='IMG'&&e.naturalWidth>=512&&typeof u==='string'&&u&&!u.startsWith('data:')};const images=Array.from(document.querySelectorAll('img')).filter(valid),out=[];for(const image of images){let p=image.parentElement,group=null;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('img')).filter(valid);if(xs.length===expected){group=xs.map(e=>e.currentSrc||e.src||e.getAttribute('src'));break}if(xs.length>expected)break;p=p.parentElement}if(group&&!out.some(x=>JSON.stringify(x)===JSON.stringify(group)))out.push(group)}return out})()""" % expected_count) or []
        return groups[0] if groups and isinstance(groups[0],list) and len(groups[0])==expected_count else None
    def video_candidates(self): return self.page.evaluate("""(()=>Array.from(document.querySelectorAll('video,video source')).map(e=>e.currentSrc||e.src||e.getAttribute('src')).filter(x=>typeof x==='string'&&x&&!x.startsWith('data:')).filter((x,i,a)=>a.indexOf(x)===i))()""") or []


class FlowInspector:
    def __init__(self, runtime): self.runtime = runtime
    def inspect(self, _url):
        page = CdpPage.open(self.runtime)
        try:
            if page.evaluate("document.querySelector('[role=dialog]')!==null"):
                page.command("Page.reload", {"ignoreCache":False}); time.sleep(3)
            state = page.evaluate("""(()=>({url:location.href,text:(document.body?.innerText||'').slice(0,12000),title:document.title}))()""") or {}
            text = (state.get("text", "") + " " + state.get("title", "")).lower()
            marketing_landing = "your ai creative studio built with google" in text and "create with google flow" in text
            login = "accounts.google" in state.get("url", "") or "sign in" in text or marketing_landing
            mode_script = """(async()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable=\"true\"]')).find(visible);let p=editor,trigger=null;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button[aria-haspopup=\"menu\"]')).filter(visible);if(xs.length===1){trigger=xs[0];break}p=p.parentElement}if(!trigger)return [];if(trigger.getAttribute('aria-expanded')!=='true'){(%s)(trigger);await new Promise(r=>setTimeout(r,250));}return Array.from(document.querySelectorAll('button[aria-controls]')).filter(visible).map(e=>e.getAttribute('aria-controls')||'')})()""" % _ACTIVATE
            modes = page.evaluate(mode_script) or []
            if not modes and page.evaluate("document.querySelector('[role=dialog]')!==null"):
                # A failed reference-picker attempt can leave a modal overlay
                # hiding otherwise available mode controls. Reload is a safe,
                # no-dispatch composer reset during preflight.
                page.command("Page.reload", {"ignoreCache":False}); time.sleep(3)
                modes = page.evaluate(mode_script) or []
            image = any("content-IMAGE" in value for value in modes)
            video = any("content-VIDEO" in value for value in modes)
            reference = bool(page.evaluate("document.querySelectorAll('input[type=file]').length"))
            # Project identity is provider runtime configuration, verified from
            # the active project URL rather than story text or current title.
            project_ok = self.runtime.project_identity in state.get("url", "") or state.get("url", "").rstrip("/") == self.runtime.project_url.rstrip("/")
            return {"login_required":login, "project_identity":self.runtime.project_identity if project_ok else "", "image":image, "video":video, "reference_image":reference, "frame_video":reference}
        finally: page.close()


class LiveFlowGenerator:
    def __init__(self, runtime, *, timeout_seconds: int = 480): self.runtime,self.timeout_seconds,self.last_settings,self.dispatch_confirmed,self.dispatch_confirmation_state=runtime,timeout_seconds,None,False,"NOT_ATTEMPTED"
    def __call__(self, request, references, destination: Path):
        # The generator is reused across a batch. Dispatch evidence is local
        # to one request and must never leak from a prior attempt.
        self.dispatch_confirmed = False
        self.dispatch_confirmation_state = "NOT_ATTEMPTED"
        self.last_settings = None
        page=CdpPage.open(self.runtime)
        try:
            dom=FlowBrowserDom(page)
            # Anything visible before the attempt's reload is necessarily
            # historical. Preserve those keys in the attribution baseline;
            # the virtualized grid often hides them during composer reload and
            # reveals them again only after generation starts.
            historical_by_key = {}
            historical_deadline = time.monotonic() + 8.0
            while time.monotonic() < historical_deadline:
                for item in dom.media_candidate_records():
                    historical_by_key[item["key"]] = item
                time.sleep(.5)
            historical_records = list(historical_by_key.values())
            dom.reset_composer(); resolved=resolve_settings(request); self.last_settings=dom.apply_settings(resolved)
            if request["media_type"] == "IMAGE" and not (self.last_settings.get("requested_output_count") == self.last_settings.get("actual_output_count") == 1):
                raise FlowError("IMAGE_OUTPUT_COUNT_MISMATCH")
            before = {item["key"] for item in historical_records}
            before_output = {item["key"] for item in records_for_media(historical_records, request["media_type"])}
            def baseline():
                nonlocal before, before_output
                # Reference attachment and Flow's virtualized grid can lazily
                # reveal or hide historical media. Accumulate the union for a
                # full observation window so a resurfacing old URL cannot
                # masquerade as post-dispatch output.
                deadline = time.monotonic() + 6.0
                while time.monotonic() < deadline:
                    records = dom.media_candidate_records()
                    keys = {item["key"] for item in records}
                    before.update(keys)
                    before_output.update(item["key"] for item in records_for_media(records, request["media_type"]))
                    time.sleep(.5)
                self.last_settings["baseline_candidate_count"] = len(before)
                self.last_settings["baseline_media_candidate_count"] = len(before_output)
            source_references = [Path(x) for x in references if x]
            if len(source_references) > 1:
                omitted=source_references[1:]
                self.last_settings["reference_capacity_limit"]=1
                self.last_settings["omitted_reference_hashes"]=[sha256_file(item) for item in omitted]
                source_references=source_references[:1]
            self.last_settings["attached_reference_hashes"]=[sha256_file(item) for item in source_references]
            with tempfile.TemporaryDirectory(prefix="story-auto-flow-refs-") as staging_directory:
                staged_references = []
                for source in source_references:
                    source_hash=sha256_file(source)
                    staged = Path(staging_directory) / f"ref_{source_hash[:16]}.png"
                    from PIL import Image, PngImagePlugin
                    metadata=PngImagePlugin.PngInfo(); metadata.add_text("StoryAutoReferenceSha256",source_hash)
                    with Image.open(source) as image: image.convert("RGB").save(staged,"PNG",pnginfo=metadata)
                    staged_references.append(str(staged))
                    self.last_settings.setdefault("staged_reference_uploads",[]).append({"source_sha256":source_hash,"upload_sha256":sha256_file(staged)})
                try:
                    submit = FlowComposer(dom).submit(request["prompt"], references=staged_references,
                                                      media_type=request["media_type"], before_dispatch=baseline,
                                                      mode_already_configured=True)
                except (FlowError, FlowSessionError) as error:
                    composer = getattr(dom, "last_composer_ready_state", None)
                    activation = getattr(dom, "last_activation_receipt", None)
                    if isinstance(composer, dict): self.last_settings["composer_ready_state"] = composer
                    if isinstance(activation, dict): self.last_settings["activation"] = activation
                    state = "UNCERTAIN" if error.failure_class == "FLOW_DISPATCH_UNCERTAIN" else "PRE_DISPATCH_FAILURE"
                    self.dispatch_confirmation_state = state
                    self.last_settings.update({"dispatch_confirmation_state":state,
                                               "dispatch_confirmation_signal":"activation_transport_uncertain" if state == "UNCERTAIN" else "input_not_dispatched",
                                               "provider_job_id":None})
                    raise
            self.last_settings.update(submit)
            activation = submit["activation"]
            tracker = DispatchEvidenceTracker()
            tracker.observe(input_dispatched=bool(activation.get("input_dispatched")),
                            trusted_click_seen=bool(activation.get("trusted_click_seen")))
            self.dispatch_confirmation_state = tracker.state
            self.last_settings.update({"dispatch_confirmation_state":tracker.state,
                                       "dispatch_confirmation_signal":tracker.signal,
                                       "provider_job_id":None})
            reference_hashes = []
            if request["media_type"] == "IMAGE":
                for reference in references:
                    try: reference_hashes.append(validate_image(Path(reference))["dhash256"])
                    except Exception: pass
            deadline=time.monotonic()+self.timeout_seconds
            while time.monotonic()<deadline:
                states = page.evaluate(_EDITOR_JS) or []
                prompt_transition = len(states) == 0 or all(item.get("text", "") != request["prompt"] for item in states)
                if prompt_transition:
                    self.last_settings["composer_transition_seen"] = True
                    tracker.observe(input_dispatched=bool(activation.get("input_dispatched")),
                                    trusted_click_seen=bool(activation.get("trusted_click_seen")),
                                    prompt_transition=True)
                pool = dom.media_candidate_records()
                pool = records_for_media(pool, request["media_type"])
                added=[item for item in pool if item["key"] not in before_output]
                self.last_settings["last_observed_media_candidate_count"] = len(pool)
                self.last_settings["last_added_candidate_count"] = len(added)
                if len(added)>resolved.output_count and request["media_type"] == "IMAGE":
                    group=dom.newest_exact_image_group(resolved.output_count)
                    if group and all(url not in before_output for url in group):
                        added=[{"key":url,"url":url,"kind":"IMG"} for url in group]
                        self.last_settings["attribution_method"]="newest_exact_count_group_after_confirmed_dispatch"
                if len(added)==resolved.output_count:
                    self.last_settings["observed_output_count"] = len(added)
                    self.last_settings["selected_candidate_index"] = 0
                    payload=page.evaluate("""(async()=>{const r=await fetch(%s);if(!r.ok)throw Error('fetch');const b=await r.arrayBuffer();let s='';for(const x of new Uint8Array(b))s+=String.fromCharCode(x);return {data:btoa(s),type:r.headers.get('content-type')||''}})()""" % __import__('json').dumps(added[0]["url"]))
                    if not isinstance(payload,dict) or not isinstance(payload.get("data"),str): raise FlowError("ASSET_ACQUISITION_FAILED")
                    atomic_write_bytes(destination, base64.b64decode(payload["data"], validate=True))
                    if request["media_type"] == "IMAGE" and reference_hashes:
                        candidate_hash = validate_image(destination)["dhash256"]
                        if any((int(candidate_hash, 16) ^ int(reference_hash, 16)).bit_count() <= 4
                               for reference_hash in reference_hashes):
                            before_output.add(added[0]["key"])
                            self.last_settings["filtered_reference_echo_count"] = self.last_settings.get("filtered_reference_echo_count", 0) + 1
                            time.sleep(2); continue
                    tracker.observe(input_dispatched=True, attributable_output=True)
                    self.dispatch_confirmed = True
                    self.dispatch_confirmation_state = tracker.state
                    self.last_settings.update({"dispatch_confirmation_state":tracker.state,
                                               "dispatch_confirmation_signal":tracker.signal,
                                               "dispatch_ack_method":tracker.signal})
                    return destination
                if len(added)>resolved.output_count:
                    # Lazy-loaded historical media can appear after the
                    # dispatch baseline. Wait for the newest exact-count group
                    # instead of binding an arbitrary added candidate.
                    time.sleep(2); continue
                time.sleep(2)
            self.dispatch_confirmation_state = tracker.state
            self.last_settings.update({"dispatch_confirmation_state":tracker.state,
                                       "dispatch_confirmation_signal":tracker.signal})
            if tracker.state == "PRE_DISPATCH_FAILURE":
                raise FlowError("FLOW_PRE_DISPATCH_ACTIVATION_FAILED", "no Generate input was dispatched")
            raise FlowError("FLOW_DISPATCH_UNCERTAIN", "activation occurred but no attributable Flow job or output was proven")
        finally: page.close()


def download_latest_image_group_candidate(runtime, destination: Path, *, expected_count: int) -> Path:
    """Acquire one candidate from the newest exact-count Flow image group.

    This is reconciliation only: it never enters a prompt or presses Generate.
    The caller remains responsible for binding human/operator attribution to the
    ambiguous dispatched attempt before adopting the bytes.
    """
    if expected_count < 1:
        raise FlowError("FLOW_RESULT_AMBIGUOUS", "invalid expected output count")
    page = CdpPage.open(runtime)
    try:
        groups = page.evaluate("""(()=>{const expected=%d;const valid=e=>{const u=e.currentSrc||e.src||e.getAttribute('src');return e.tagName==='IMG'&&e.naturalWidth>=512&&typeof u==='string'&&u&&!u.startsWith('data:')};const images=Array.from(document.querySelectorAll('img')).filter(valid),out=[];for(const image of images){let p=image.parentElement,group=null;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('img')).filter(valid);if(xs.length===expected){group=xs.map(e=>e.currentSrc||e.src||e.getAttribute('src'));break}if(xs.length>expected)break;p=p.parentElement}if(group&&!out.some(x=>JSON.stringify(x)===JSON.stringify(group)))out.push(group)}return out})()""" % expected_count) or []
        # Flow prepends the newest result group to the project media grid.
        if not groups or not isinstance(groups[0], list) or len(groups[0]) != expected_count:
            raise FlowError("FLOW_RESULT_AMBIGUOUS", "no newest exact-count image group")
        candidate = groups[0][0]
        payload = page.evaluate("""(async()=>{const r=await fetch(%s);if(!r.ok)throw Error('fetch');const b=await r.arrayBuffer();let s='';for(const x of new Uint8Array(b))s+=String.fromCharCode(x);return {data:btoa(s),type:r.headers.get('content-type')||''}})()""" % __import__('json').dumps(candidate))
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), str):
            raise FlowError("ASSET_ACQUISITION_FAILED")
        atomic_write_bytes(destination, base64.b64decode(payload["data"], validate=True))
        return destination
    finally:
        page.close()

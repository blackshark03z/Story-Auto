"""Gemini Web page objects; all product-specific DOM assumptions live here."""

from __future__ import annotations

from pathlib import Path
import time

from .session import GeminiWebError


_VISIBLE = "e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled}"
_EDITORS = """(()=>Array.from(document.querySelectorAll('textarea,[contenteditable=true]')).filter(%s).map((e,i)=>({i,text:(e.value??e.innerText??'').trim(),tag:e.tagName})))()""" % _VISIBLE
_MEDIA = """(()=>{const out=[];for(const e of document.querySelectorAll('img,video,video source')){if(e.closest('media-gen-template-card,image-generation-zero-state,media-gen-zero-state-shell,.zero-state-container'))continue;const u=e.currentSrc||e.src||e.getAttribute('src');if(typeof u!=='string'||!u||u.startsWith('data:'))continue;if(e.tagName==='IMG'&&(e.naturalWidth||0)<512)continue;let key=u;try{const x=new URL(u,location.href);key=x.origin+x.pathname}catch{}if(!out.some(v=>v.key===key))out.push({key,url:u,kind:e.tagName,width:e.naturalWidth||e.videoWidth||0,height:e.naturalHeight||e.videoHeight||0})}return out})()"""


class GeminiWebDom:
    def __init__(self, page):
        self.page = page

    def editor_state(self) -> dict:
        editors = self.page.evaluate(_EDITORS) or []
        if len(editors) != 1:
            raise GeminiWebError("GEMINI_WEB_UI_CHANGED", f"expected one visible prompt editor, found {len(editors)}")
        return editors[0]

    def set_prompt(self, prompt: str) -> None:
        state = self.editor_state()
        if state["text"]:
            if " ".join(state["text"].split()) == " ".join(prompt.split()):
                return
            raise GeminiWebError("GEMINI_WEB_STALE_COMPOSER", "prompt editor is not empty")
        self.page.evaluate("""(()=>{const xs=Array.from(document.querySelectorAll('textarea,[contenteditable=true]')).filter(%s);if(xs.length!==1)throw Error('editor');xs[0].focus()})()""" % _VISIBLE)
        self.page.insert_text(prompt)
        readback = self.editor_state()["text"]
        if " ".join(readback.split()) != " ".join(prompt.split()):
            raise GeminiWebError("GEMINI_WEB_PROMPT_READBACK_MISMATCH")

    def _open_tools(self) -> None:
        result = self.page.evaluate("""(async()=>{const visible=%s;const xs=Array.from(document.querySelectorAll('button,[role=button]')).filter(visible).filter(e=>/upload and tools|nội dung tải lên và công cụ/i.test(((e.innerText||'')+' '+(e.getAttribute('aria-label')||'')).normalize('NFC')));if(xs.length!==1)return xs.length;if(xs[0].getAttribute('aria-expanded')!=='true'){xs[0].click();await new Promise(r=>setTimeout(r,300));}return 1})()""" % _VISIBLE)
        if result != 1:
            raise GeminiWebError("GEMINI_WEB_UI_CHANGED", "upload/tools control was not unique")

    def select_media_mode(self, media_type: str) -> str:
        self._open_tools()
        terms = (["create image", "generate image", "tạo hình ảnh", "tạo ảnh"]
                 if media_type == "IMAGE" else ["create video", "generate video", "tạo video"])
        result = self.page.evaluate("""(()=>{const terms=%s,visible=%s;const candidates=Array.from(document.querySelectorAll('button,[role=button],[role=menuitem],[role=option]')).filter(visible).map(e=>({e,label:(e.innerText||e.getAttribute('aria-label')||'').trim()})).filter(x=>terms.some(t=>x.label.toLocaleLowerCase().includes(t)));if(candidates.length!==1)return {count:candidates.length};candidates[0].e.click();return {count:1,label:candidates[0].label}})()""" % (__import__('json').dumps(terms), _VISIBLE))
        if not isinstance(result, dict) or result.get("count") != 1:
            raise GeminiWebError("GEMINI_WEB_CAPABILITY_UNAVAILABLE", f"{media_type} mode was not unique")
        return str(result.get("label") or "PRODUCT_LEVEL_MODE")

    def attach_references(self, references: list[Path]) -> None:
        if not references:
            return
        attachment_selector = "gem-media-attachment img[alt=attachment]"
        existing = self.page.evaluate(f"document.querySelectorAll('{attachment_selector}').length") or 0
        if existing == len(references):
            return
        if existing:
            raise GeminiWebError("GEMINI_WEB_REFERENCE_UNAVAILABLE", "unexpected pre-existing reference attachment count")
        self._open_tools()
        opened = self.page.evaluate("""(()=>{const visible=%s;const terms=['upload','add file','attach','tải tệp','thêm tệp'];const xs=Array.from(document.querySelectorAll('button,[role=button]')).filter(visible).filter(e=>terms.some(t=>((e.innerText||'')+' '+(e.getAttribute('aria-label')||'')).toLocaleLowerCase().includes(t)));if(xs.length!==1)return xs.length;xs[0].click();return 1})()""" % _VISIBLE)
        if opened != 1:
            raise GeminiWebError("GEMINI_WEB_REFERENCE_UNAVAILABLE", "reference attachment control was not unique")
        selector = "input[type=file][name=Filedata]"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            count = self.page.evaluate(f"document.querySelectorAll('{selector}').length") or 0
            if count == 1:
                self.page.set_input_files(selector, [str(path.resolve()) for path in references])
                break
            time.sleep(0.25)
        else:
            raise GeminiWebError("GEMINI_WEB_REFERENCE_UNAVAILABLE", "unique media-capable file input did not appear")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            attached = self.page.evaluate(f"document.querySelectorAll('{attachment_selector}').length") or 0
            if attached == len(references):
                return
            time.sleep(0.25)
        raise GeminiWebError("GEMINI_WEB_REFERENCE_UNAVAILABLE", "reference attachment was not acknowledged")

    def media_records(self) -> list[dict]:
        return self.page.evaluate(_MEDIA) or []

    def submit(self) -> dict:
        structural = self.page.evaluate("""(()=>{const xs=Array.from(document.querySelectorAll('input-container button:has(mat-icon[data-mat-icon-name="arrow_upward"])')).filter(%s);if(xs.length!==1)return {count:xs.length};const r=xs[0].getBoundingClientRect();return {count:1,x:r.left+r.width/2,y:r.top+r.height/2,label:xs[0].getAttribute('aria-label')||'SEND'}})()""" % _VISIBLE)
        if isinstance(structural, dict) and structural.get("count") == 1:
            self.page.click(float(structural["x"]), float(structural["y"]))
            return structural
        result = self.page.evaluate("""(()=>{const visible=%s;const editor=Array.from(document.querySelectorAll('textarea,[contenteditable=true]')).find(visible);if(!editor)return {count:0};let p=editor.parentElement;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button')).filter(visible).filter(e=>/send|submit|gửi/i.test((e.innerText||'')+' '+(e.getAttribute('aria-label')||'')));if(xs.length===1){const r=xs[0].getBoundingClientRect();return {count:1,x:r.left+r.width/2,y:r.top+r.height/2,label:(xs[0].innerText||xs[0].getAttribute('aria-label')||'').trim()}}if(xs.length>1)return {count:xs.length};p=p.parentElement}return {count:0}})()""" % _VISIBLE)
        if not isinstance(result, dict) or result.get("count") != 1:
            raise GeminiWebError("GEMINI_WEB_SUBMIT_AMBIGUOUS", f"found {result.get('count') if isinstance(result,dict) else 0} controls")
        self.page.click(float(result["x"]), float(result["y"]))
        return result

    def submit_dom_fallback(self) -> str:
        structural = self.page.evaluate("""(()=>{const xs=Array.from(document.querySelectorAll('input-container button:has(mat-icon[data-mat-icon-name="arrow_upward"])')).filter(%s);if(xs.length!==1)return {count:xs.length};xs[0].click();return {count:1,label:xs[0].getAttribute('aria-label')||'SEND'}})()""" % _VISIBLE)
        if isinstance(structural, dict) and structural.get("count") == 1:
            return str(structural.get("label") or "SEND")
        result = self.page.evaluate("""(()=>{const visible=%s;const editor=Array.from(document.querySelectorAll('textarea,[contenteditable=true]')).find(visible);if(!editor)return {count:0};let p=editor.parentElement;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button')).filter(visible).filter(e=>/send|submit|gá»­i/i.test((e.innerText||'')+' '+(e.getAttribute('aria-label')||'')));if(xs.length===1){const label=(xs[0].innerText||xs[0].getAttribute('aria-label')||'').trim();xs[0].click();return {count:1,label}}if(xs.length>1)return {count:xs.length};p=p.parentElement}return {count:0}})()""" % _VISIBLE)
        if not isinstance(result, dict) or result.get("count") != 1:
            raise GeminiWebError("GEMINI_WEB_SUBMIT_AMBIGUOUS", f"fallback found {result.get('count') if isinstance(result,dict) else 0} controls")
        return str(result.get("label") or "")

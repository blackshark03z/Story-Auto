"""Live, honest Gemini Web capability discovery from visible UI state."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib

from .cdp import GeminiWebPage


@dataclass(frozen=True)
class GeminiWebCapabilities:
    authenticated: bool
    app_identity: bool
    account_session: str
    image: bool
    video: bool
    reference_image: bool
    selectable_modes: tuple[str, ...]
    aspect_ratio_controls: tuple[str, ...]
    output_count_control: str
    video_duration_options: tuple[str, ...]
    observed_mode_identity: str
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_INSPECT = r"""(async()=>{
const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};
const initial=Array.from(document.querySelectorAll('button,[role=button]')).filter(visible);
const tools=initial.filter(e=>/upload and tools|nội dung tải lên và công cụ/i.test(((e.innerText||'')+' '+(e.getAttribute('aria-label')||'')).normalize('NFC')));
if(tools.length===1&&tools[0].getAttribute('aria-expanded')!=='true'){tools[0].click();await new Promise(r=>setTimeout(r,300));}
const text=(document.body?.innerText||'').slice(0,50000);
const controls=Array.from(document.querySelectorAll('button,[role=button],[role=menuitem],[role=option]')).filter(visible).map(e=>(e.innerText||e.getAttribute('aria-label')||'').trim()).filter(Boolean);
const account=Array.from(document.querySelectorAll('button,[role=button],a')).filter(visible).map(e=>(e.getAttribute('aria-label')||e.getAttribute('title')||'').trim()).find(x=>/@|Google Account|Tài khoản Google/i.test(x))||'';
const editors=Array.from(document.querySelectorAll('textarea,[contenteditable=true]')).filter(visible).length;
return {url:location.href,title:document.title,text,controls,account,fileInputs:document.querySelectorAll('input[type=file]').length,editors};
})()"""


def inspect_capabilities(runtime) -> GeminiWebCapabilities:
    page = GeminiWebPage.open(runtime)
    try:
        state = page.evaluate(_INSPECT) or {}
    finally:
        page.close()
    text = " ".join([str(state.get("text", "")), *map(str, state.get("controls", []))])
    lowered = text.casefold()
    url = str(state.get("url", ""))
    login_markers = ("sign in", "đăng nhập", "accounts.google.com")
    authenticated = bool(state.get("account")) and not any(marker in lowered or marker in url for marker in login_markers)
    session = "ACCOUNT_CONTROL_PRESENT" if state.get("account") else "ACCOUNT_CONTROL_MISSING"
    if state.get("account"):
        session += ":" + hashlib.sha256(str(state["account"]).encode("utf-8")).hexdigest()[:12]
    image_terms = ("create image", "generate image", "tạo hình ảnh", "tạo ảnh")
    video_terms = ("create video", "generate video", "tạo video")
    modes = tuple(sorted({
        control for control in map(str, state.get("controls", []))
        if any(term in control.casefold() for term in (*image_terms, *video_terms, "model", "mô hình"))
    }))
    ratios = tuple(value for value in ("16:9", "9:16", "1:1", "4:3", "3:4") if value in text)
    durations = tuple(value for value in ("5s", "6s", "8s", "10s") if value in lowered.replace(" ", ""))
    reference_terms = ("upload file", "tải tệp lên", "add from drive", "thêm từ drive")
    return GeminiWebCapabilities(
        authenticated=authenticated,
        app_identity=url.startswith("https://gemini.google.com/"),
        account_session=session,
        image=any(term in lowered for term in image_terms),
        video=any(term in lowered for term in video_terms),
        reference_image=int(state.get("fileInputs", 0) or 0) > 0 or any(term in lowered for term in reference_terms),
        selectable_modes=modes,
        aspect_ratio_controls=ratios,
        output_count_control="OBSERVED_X1" if "x1" in lowered else "NOT_EXPOSED",
        video_duration_options=durations,
        observed_mode_identity=" | ".join(modes) if modes else "PRODUCT_LEVEL_MODE_ONLY",
        detail="" if authenticated else "AUTH_REQUIRED",
    )

"""Concrete Flow CDP adapter. UI assumptions live here and fail closed."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from story_auto.core.artifacts import atomic_write_bytes, atomic_write_json, sha256_file
from .attribution import (
    ATTRIBUTION_METHOD_VERSION,
    RequestAttributionTracker,
    evidence_identity,
    provider_identity,
    records_for_type,
    surface_fingerprint,
)
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
_PROVIDER_SURFACE_JS = """(()=>{const assetId=url=>{try{const parsed=new URL(url,location.href);return parsed.searchParams.get('name')||parsed.origin+parsed.pathname}catch{return url}};const records=[],seen=new Set(),tiles=Array.from(document.querySelectorAll('[data-tile-id]'));for(const tile of tiles){const card_id=tile.getAttribute('data-tile-id'),hasVideo=!!tile.querySelector('video,video source');let ready=0;for(const e of tile.querySelectorAll('img,video,video source')){const url=e.currentSrc||e.src||e.getAttribute('src');if(typeof url!=='string'||!url||url.startsWith('data:'))continue;const kind=e.tagName,thumbnail=/mediaUrlType=MEDIA_URL_TYPE_THUMBNAIL/.test(url)||/video/i.test(e.alt||''),media_type=(hasVideo||kind==='VIDEO'||kind==='SOURCE')?(thumbnail&&kind==='IMG'?'VIDEO_THUMBNAIL':'VIDEO'):'IMAGE',usable=media_type==='VIDEO'?(kind!=='IMG'):(kind==='IMG'&&(e.naturalWidth||0)>=512);if(!usable)continue;const asset_id=assetId(url),key=card_id+'|'+asset_id+'|'+media_type;if(seen.has(key))continue;seen.add(key);records.push({card_id,asset_id,media_type,state:'READY',url,kind,width:e.naturalWidth||e.videoWidth||0,height:e.naturalHeight||e.videoHeight||0});ready++}if(!ready){records.push({card_id,asset_id:null,media_type:null,state:'PENDING',url:null,kind:null,width:0,height:0})}}const readyCards=new Set(records.filter(x=>x.state==='READY').map(x=>x.card_id)),resolved=records.filter(x=>x.state==='READY'||!readyCards.has(x.card_id));const global_pending_count=document.querySelectorAll('[aria-busy=true],[role=progressbar],[data-state=loading]').length;return {records:resolved,global_pending_count}})()"""
_ACTIVATE = "e=>{e.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));e.click()}"
_MODEL_TRIGGER = """(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable="true"]')).find(visible);let p=editor;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button[aria-haspopup="menu"]')).filter(visible);if(xs.length===1)return xs[0];p=p.parentElement}return null})()"""

PROVIDER_SURFACE_EXTRACTOR_VERSION = "flow-provider-surface/2.0.0"
POLL_EVIDENCE_VERSION = "story-auto-flow-poll-evidence/1.1.0"
MAX_POLL_OBSERVATIONS = 2048
MAX_PROVIDER_IDENTITIES_PER_POLL = 256
MAX_CANDIDATE_IDENTITIES_PER_POLL = 64
MAX_QUARANTINED_IDENTITIES_PER_POLL = 64
MAX_POLL_EVIDENCE_BYTES = 16 * 1024 * 1024
POLL_EVIDENCE_OVERFLOW_RESERVE_BYTES = 4096
_PROVIDER_IDENTITY_FIELDS = {
    "baseline_identity_set", "current_identity_set", "identity_delta",
    "job_card_identities_observed", "output_asset_identities_observed",
}

def records_for_media(records, media_type: str):
    if any("media_type" in item for item in records):
        return [item for item in records if item.get("media_type") == media_type]
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


def _merge_surface_records(*groups: list[dict]) -> list[dict]:
    merged = {}
    for group in groups:
        for record in group:
            identity = provider_identity(record)
            if identity:
                merged[identity] = record
    return list(merged.values())


def _json_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _identity_projection(records: list[dict], media_type: str) -> list[dict]:
    projected = {
        provider_identity(record): evidence_identity(record)
        for record in records_for_type(records, media_type)
        if provider_identity(record)
    }
    return [projected[key] for key in sorted(projected)]


class ProviderPollEvidenceTimeline:
    """Bounded, hash-chained poll evidence persisted after every observation.

    The same canonical JSON hash is used by the writer and verifier.  A bounded
    overflow observation is durable evidence of incompleteness; it never leaves
    a partially truncated observation eligible for a decision.
    """

    def __init__(self, path: Path | None = None, *,
                 max_observations: int = MAX_POLL_OBSERVATIONS,
                 max_provider_identities: int = MAX_PROVIDER_IDENTITIES_PER_POLL,
                 max_candidate_identities: int = MAX_CANDIDATE_IDENTITIES_PER_POLL,
                 max_quarantined_identities: int = MAX_QUARANTINED_IDENTITIES_PER_POLL,
                 max_serialized_bytes: int = MAX_POLL_EVIDENCE_BYTES):
        if (max_observations < 1 or max_provider_identities < 1
                or max_candidate_identities < 1 or max_quarantined_identities < 1
                or max_serialized_bytes <= POLL_EVIDENCE_OVERFLOW_RESERVE_BYTES):
            raise ValueError("poll evidence bounds must be positive and retain overflow reserve")
        self.path = path
        self.max_observations = max_observations
        self.max_provider_identities = max_provider_identities
        self.max_candidate_identities = max_candidate_identities
        self.max_quarantined_identities = max_quarantined_identities
        self.max_serialized_bytes = max_serialized_bytes
        self.observations: list[dict] = []
        self.complete = False
        self.evidence_complete = True
        self.terminal_state: str | None = None

    def append(self, value: dict) -> dict:
        if self.complete or len(self.observations) >= self.max_observations:
            raise FlowError("FLOW_POLL_EVIDENCE_LIMIT_EXCEEDED", "provider poll evidence bound reached")
        overflow = self._collection_overflow(value)
        observation = self._observation(value if not overflow else self._overflow_observation(value, overflow))
        if not overflow and self._serialized_size_for(observation) > (
                self.max_serialized_bytes - POLL_EVIDENCE_OVERFLOW_RESERVE_BYTES):
            overflow = [{
                "field": "serialized_timeline_bytes",
                "observed_count": self._serialized_size_for(observation),
                "configured_limit": self.max_serialized_bytes,
                "full_set_sha256": _json_sha256(observation),
            }]
            observation = self._observation(self._overflow_observation(value, overflow))
        if self._serialized_size_for(observation) > self.max_serialized_bytes:
            raise FlowError("FLOW_POLL_EVIDENCE_LIMIT_EXCEEDED", "bounded overflow summary cannot fit")
        if overflow:
            self.evidence_complete = False
        self.observations.append(observation)
        self._persist()
        if overflow:
            raise FlowError("FLOW_POLL_EVIDENCE_LIMIT_EXCEEDED", "provider poll evidence is incomplete")
        return observation

    def _observation(self, value: dict) -> dict:
        observation = dict(value)
        observation.update({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "poll_sequence": len(self.observations) + 1,
            "poll_evidence_version": POLL_EVIDENCE_VERSION,
            "parser_extractor_version": PROVIDER_SURFACE_EXTRACTOR_VERSION,
            "previous_observation_sha256": (
                self.observations[-1]["observation_sha256"] if self.observations else None
            ),
        })
        observation["observation_sha256"] = _json_sha256(observation)
        return observation

    def _collection_overflow(self, value: dict) -> list[dict]:
        limits = {
            **{field: self.max_provider_identities for field in _PROVIDER_IDENTITY_FIELDS},
            "candidate_identities": self.max_candidate_identities,
            "quarantined_identities": self.max_quarantined_identities,
        }
        overflow = []
        for field, limit in limits.items():
            values = value.get(field, [])
            if isinstance(values, list) and len(values) > limit:
                overflow.append({
                    "field": field,
                    "observed_count": len(values),
                    "configured_limit": limit,
                    "full_set_sha256": _json_sha256(values),
                })
        return overflow

    def _overflow_observation(self, value: dict, overflow: list[dict]) -> dict:
        # Keep only scalar decision context.  Full collections are intentionally
        # not truncated into something that could look complete.
        safe = {
            key: value.get(key) for key in (
                "phase", "provider_surface_fingerprint", "baseline_surface_fingerprint",
                "candidate_classification", "stable_poll_count", "provider_busy",
                "dispatch_evidence_state", "dispatch_evidence_signal",
                "dispatch_signal_state", "durable_dispatch_identity",
                "attribution_evidence_state", "lineage_card_id", "input_dispatched",
            )
        }
        safe.update({"evidence_complete": False, "overflow": overflow})
        return safe

    def _serialized_size_for(self, observation: dict) -> int:
        snapshot = self.snapshot(observations=[*self.observations, observation])
        return len(json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    def finish(self, terminal_state: str) -> None:
        self.complete = True
        self.terminal_state = str(terminal_state)
        if self._serialized_size_for_existing() > self.max_serialized_bytes:
            raise FlowError("FLOW_POLL_EVIDENCE_LIMIT_EXCEEDED", "terminal poll evidence bound reached")
        self._persist()

    def _serialized_size_for_existing(self) -> int:
        return len(json.dumps(self.snapshot(), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    def snapshot(self, *, observations: list[dict] | None = None) -> dict:
        snapshot = {
            "schema_version": POLL_EVIDENCE_VERSION,
            "parser_extractor_version": PROVIDER_SURFACE_EXTRACTOR_VERSION,
            "max_observations": self.max_observations,
            "max_provider_identities_per_poll": self.max_provider_identities,
            "max_candidate_identities_per_poll": self.max_candidate_identities,
            "max_quarantined_identities_per_poll": self.max_quarantined_identities,
            "max_serialized_bytes": self.max_serialized_bytes,
            "observation_count": len(self.observations if observations is None else observations),
            "complete": self.complete,
            "evidence_complete": self.evidence_complete,
            "terminal_state": self.terminal_state,
            "timeline_sha256": _json_sha256(self.observations if observations is None else observations),
            "observations": list(self.observations if observations is None else observations),
        }
        snapshot["evidence_head_sha256"] = self._head_sha256(snapshot)
        return snapshot

    @staticmethod
    def _head_sha256(snapshot: dict) -> str:
        return _json_sha256({
            key: snapshot.get(key) for key in (
                "schema_version", "parser_extractor_version", "max_observations",
                "max_provider_identities_per_poll", "max_candidate_identities_per_poll",
                "max_quarantined_identities_per_poll", "max_serialized_bytes",
                "observation_count", "complete", "evidence_complete", "terminal_state",
                "timeline_sha256",
            )
        })

    @classmethod
    def verify_snapshot(cls, snapshot: dict) -> dict:
        """Fail closed unless a persisted timeline is exact and internally coherent."""
        try:
            if not isinstance(snapshot, dict) or snapshot.get("schema_version") != POLL_EVIDENCE_VERSION:
                raise ValueError("schema")
            if snapshot.get("parser_extractor_version") != PROVIDER_SURFACE_EXTRACTOR_VERSION:
                raise ValueError("extractor")
            observations = snapshot.get("observations")
            if not isinstance(observations, list):
                raise ValueError("observations")
            limits = {
                "max_observations": snapshot.get("max_observations"),
                "max_provider_identities_per_poll": snapshot.get("max_provider_identities_per_poll"),
                "max_candidate_identities_per_poll": snapshot.get("max_candidate_identities_per_poll"),
                "max_quarantined_identities_per_poll": snapshot.get("max_quarantined_identities_per_poll"),
                "max_serialized_bytes": snapshot.get("max_serialized_bytes"),
            }
            if any(not isinstance(value, int) or value < 1 for value in limits.values()):
                raise ValueError("limits")
            if (limits["max_observations"] > MAX_POLL_OBSERVATIONS
                    or limits["max_provider_identities_per_poll"] > MAX_PROVIDER_IDENTITIES_PER_POLL
                    or limits["max_candidate_identities_per_poll"] > MAX_CANDIDATE_IDENTITIES_PER_POLL
                    or limits["max_quarantined_identities_per_poll"] > MAX_QUARANTINED_IDENTITIES_PER_POLL
                    or limits["max_serialized_bytes"] > MAX_POLL_EVIDENCE_BYTES
                    or limits["max_serialized_bytes"] <= POLL_EVIDENCE_OVERFLOW_RESERVE_BYTES):
                raise ValueError("limits_outside_supported_range")
            if len(observations) != snapshot.get("observation_count") or len(observations) > limits["max_observations"]:
                raise ValueError("count")
            if not isinstance(snapshot.get("complete"), bool) or not isinstance(snapshot.get("evidence_complete"), bool):
                raise ValueError("completion")
            if snapshot.get("timeline_sha256") != _json_sha256(observations):
                raise ValueError("timeline_hash")
            if snapshot.get("evidence_head_sha256") != cls._head_sha256(snapshot):
                raise ValueError("head_hash")
            previous = None
            incomplete_seen = False
            for index, observation in enumerate(observations, start=1):
                if not isinstance(observation, dict): raise ValueError("observation")
                stored_hash = observation.get("observation_sha256")
                unsigned = dict(observation); unsigned.pop("observation_sha256", None)
                if (not isinstance(stored_hash, str) or _json_sha256(unsigned) != stored_hash
                        or observation.get("poll_sequence") != index
                        or observation.get("poll_evidence_version") != POLL_EVIDENCE_VERSION
                        or observation.get("parser_extractor_version") != PROVIDER_SURFACE_EXTRACTOR_VERSION
                        or observation.get("previous_observation_sha256") != previous):
                    raise ValueError("chain")
                if observation.get("evidence_complete") is False:
                    overflow = observation.get("overflow")
                    if not isinstance(overflow, list) or not overflow or len(overflow) > 7:
                        raise ValueError("overflow")
                    for summary in overflow:
                        if (not isinstance(summary, dict)
                                or not isinstance(summary.get("field"), str)
                                or not isinstance(summary.get("observed_count"), int)
                                or summary["observed_count"] < 0
                                or not isinstance(summary.get("configured_limit"), int)
                                or summary["configured_limit"] < 1
                                or not isinstance(summary.get("full_set_sha256"), str)
                                or len(summary["full_set_sha256"]) != 64):
                            raise ValueError("overflow_summary")
                    incomplete_seen = True
                else:
                    for field in _PROVIDER_IDENTITY_FIELDS:
                        if isinstance(observation.get(field), list) and len(observation[field]) > limits["max_provider_identities_per_poll"]:
                            raise ValueError("provider_bound")
                    if isinstance(observation.get("candidate_identities"), list) and len(observation["candidate_identities"]) > limits["max_candidate_identities_per_poll"]:
                        raise ValueError("candidate_bound")
                    if isinstance(observation.get("quarantined_identities"), list) and len(observation["quarantined_identities"]) > limits["max_quarantined_identities_per_poll"]:
                        raise ValueError("quarantine_bound")
                previous = stored_hash
            if incomplete_seen == snapshot["evidence_complete"]:
                raise ValueError("completeness")
            serialized = len(json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            if serialized > limits["max_serialized_bytes"]:
                raise ValueError("serialized_bound")
            return snapshot
        except FlowError:
            raise
        except Exception as error:
            raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "persisted poll evidence failed verification") from error

    def _persist(self) -> None:
        if self.path is not None:
            atomic_write_json(self.path, self.snapshot())


def _stable_surface(dom, media_type: str, *, seed: list[dict] | None = None,
                    timeout_seconds: float = 12.0, required_stable_polls: int = 3,
                    poll_seconds: float = .5,
                    poll_observer: Callable[[dict, list[dict], int], None] | None = None,
                    capacity_guard: Callable[[], None] | None = None) -> tuple[list[dict], int]:
    """Return a quiescent provider surface using state, not a blind sleep."""
    deadline = time.monotonic() + timeout_seconds
    union = list(seed or [])
    last_fingerprint = None
    stable = 0
    while time.monotonic() < deadline:
        if capacity_guard:
            capacity_guard()
        surface = dom.provider_surface()
        records = surface.get("records", []) if isinstance(surface, dict) else []
        union = _merge_surface_records(union, records)
        typed = records_for_type(records, media_type)
        pending = [record for record in typed if record.get("state") != "READY"]
        fingerprint = surface_fingerprint(typed)
        quiescent = False
        if not pending and not int((surface or {}).get("global_pending_count", 0)):
            stable = stable + 1 if fingerprint == last_fingerprint else 1
            if stable >= required_stable_polls:
                quiescent = True
        else:
            stable = 0
        if poll_observer:
            poll_observer(surface if isinstance(surface, dict) else {}, records, stable)
        if quiescent:
            return union, stable
        last_fingerprint = fingerprint
        time.sleep(poll_seconds)
    raise FlowError("OUTPUT_ATTRIBUTION_NOT_QUIESCENT", "Flow has unresolved provider-visible state")


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
        self.signal_state = "NONE"
        self.durable_identity = None
        self.evidence_poll_sequence = None
        self.confirmation_count = 0

    def observe(self, *, input_dispatched: bool, trusted_click_seen: bool = False,
                prompt_transition: bool = False, attributable_job: bool = False,
                attributable_output: bool = False, provider_job_id: str | None = None,
                durable_job_identity: str | None = None,
                durable_evidence_serialized: bool = False,
                evidence_poll_sequence: int | None = None,
                unrelated_dom_mutation: bool = False, legacy_ack_present: bool | None = None) -> str:
        del unrelated_dom_mutation, legacy_ack_present
        signal = None
        durable_identity = str(provider_job_id or durable_job_identity or "").strip()
        if provider_job_id and durable_evidence_serialized:
            signal = "provider_job_id"
        elif attributable_output:
            signal = "new_attributable_output"
        elif attributable_job and durable_identity and durable_evidence_serialized:
            signal = "durable_attributable_job_identity"
        if signal:
            if self.state != "CONFIRMED": self.confirmation_count += 1
            self.state, self.signal = "CONFIRMED", signal
            self.signal_state = "DISPATCH_CONFIRMED"
            self.durable_identity = durable_identity or self.durable_identity
            self.evidence_poll_sequence = evidence_poll_sequence or self.evidence_poll_sequence
        elif attributable_job:
            # A request-local visual transition is useful evidence, but cannot
            # become a durable confirmation without a serialized stable ID.
            if self.state != "CONFIRMED":
                self.state, self.signal = "UNCERTAIN", "transient_attributable_job_state"
                self.signal_state = "SIGNAL_OBSERVED"
        elif not input_dispatched:
            self.state, self.signal = "PRE_DISPATCH_FAILURE", "input_not_dispatched"
            self.signal_state = "NONE"
        elif self.state != "CONFIRMED" and (trusted_click_seen or prompt_transition):
            self.state = "UNCERTAIN"
            self.signal = "composer_transition_after_activation" if prompt_transition else "trusted_click_only"
            self.signal_state = "SIGNAL_OBSERVED"
        return self.state


def dispatch_timeout_failure(dispatch: DispatchEvidenceTracker) -> str:
    """Classify timeout from durable dispatch proof, never from output absence."""
    if dispatch.state == "PRE_DISPATCH_FAILURE":
        return "FLOW_PRE_DISPATCH_ACTIVATION_FAILED"
    if dispatch.state == "CONFIRMED":
        return "OUTPUT_ATTRIBUTION_UNCERTAIN"
    return "FLOW_DISPATCH_UNCERTAIN"


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
    def provider_surface(self): return self.page.evaluate(_PROVIDER_SURFACE_JS) or {"records": [], "global_pending_count": 0}
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
    def __init__(self, runtime, *, timeout_seconds: int = 480):
        self.runtime = runtime
        self.timeout_seconds = timeout_seconds
        self.last_settings = None
        self.dispatch_confirmed = False
        self.dispatch_confirmation_state = "NOT_ATTEMPTED"
        self._poll_timeline = ProviderPollEvidenceTimeline()

    @staticmethod
    def _fetch_bytes(page, url: str) -> bytes:
        payload = page.evaluate("""(async()=>{const r=await fetch(%s);if(!r.ok)throw Error('fetch');const b=await r.arrayBuffer();let s='';for(const x of new Uint8Array(b))s+=String.fromCharCode(x);return {data:btoa(s),type:r.headers.get('content-type')||''}})()""" % __import__('json').dumps(url))
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), str):
            raise FlowError("ASSET_ACQUISITION_FAILED")
        return base64.b64decode(payload["data"], validate=True)

    def _reset_poll_evidence(self, path: Path) -> None:
        self._poll_timeline = ProviderPollEvidenceTimeline(path)
        self.last_settings = {}
        self._sync_poll_evidence()

    def _ensure_poll_capacity(self) -> None:
        if len(self._poll_timeline.observations) >= self._poll_timeline.max_observations:
            raise FlowError("FLOW_POLL_EVIDENCE_LIMIT_EXCEEDED", "provider poll evidence bound reached")

    def _sync_poll_evidence(self) -> None:
        if not isinstance(self.last_settings, dict):
            self.last_settings = {}
        snapshot = self._poll_timeline.snapshot()
        ProviderPollEvidenceTimeline.verify_snapshot(snapshot)
        self.last_settings.update({
            "provider_poll_evidence": snapshot,
            "poll_evidence_version": POLL_EVIDENCE_VERSION,
            "provider_surface_extractor_version": PROVIDER_SURFACE_EXTRACTOR_VERSION,
            "provider_poll_max_observations": snapshot["max_observations"],
            "provider_poll_max_identities_per_observation": snapshot["max_provider_identities_per_poll"],
            "provider_poll_max_candidates_per_observation": snapshot["max_candidate_identities_per_poll"],
            "provider_poll_max_quarantined_per_observation": snapshot["max_quarantined_identities_per_poll"],
            "provider_poll_max_serialized_bytes": snapshot["max_serialized_bytes"],
            "provider_poll_evidence_complete": snapshot["evidence_complete"],
            "provider_poll_observation_count": snapshot["observation_count"],
            "provider_poll_timeline_sha256": snapshot["timeline_sha256"],
            "provider_poll_timeline_complete": snapshot["complete"],
            "provider_poll_terminal_state": snapshot["terminal_state"],
            "provider_poll_timeline": snapshot["observations"],
        })

    def _finish_poll_evidence(self, terminal_state: str) -> None:
        if not self._poll_timeline.complete:
            self._poll_timeline.finish(terminal_state)
        self._sync_poll_evidence()

    def _poll_evidence_fields(self) -> dict:
        return {
            key: self.last_settings.get(key)
            for key in (
                "poll_evidence_version", "provider_surface_extractor_version",
                "provider_poll_evidence", "provider_poll_max_observations",
                "provider_poll_max_identities_per_observation",
                "provider_poll_max_candidates_per_observation",
                "provider_poll_max_quarantined_per_observation",
                "provider_poll_max_serialized_bytes", "provider_poll_evidence_complete",
                "provider_poll_observation_count", "provider_poll_timeline_sha256",
                "provider_poll_timeline_complete", "provider_poll_terminal_state",
                "provider_poll_timeline",
            )
        }

    def _record_poll(self, *, phase: str, media_type: str, baseline: list[dict],
                     current: list[dict], surface: dict, stable_polls: int,
                     observation=None, dispatch: DispatchEvidenceTracker | None = None,
                     activation: dict | None = None,
                     quarantined: list[dict] | None = None) -> dict:
        baseline_projection = _identity_projection(baseline, media_type)
        current_projection = _identity_projection(current, media_type)
        baseline_ids = {item["identity"] for item in baseline_projection}
        delta = [item for item in current_projection if item["identity"] not in baseline_ids]
        candidates = observation.candidate_identities if observation is not None else delta
        lineage_card_id = observation.lineage_card_id if observation is not None else None
        durable_job_identity = (
            f"card:{lineage_card_id}" if isinstance(lineage_card_id, str) and lineage_card_id else None
        )
        durable_output_identity = None
        if observation is not None and observation.state == "CONFIRMED" and observation.candidate:
            durable_output_identity = provider_identity(observation.candidate) or None
        predicted_dispatch_state = dispatch.state if dispatch is not None else "NOT_CONFIRMED"
        predicted_signal = dispatch.signal if dispatch is not None else None
        predicted_signal_state = dispatch.signal_state if dispatch is not None else "NONE"
        if durable_output_identity and dispatch is not None and dispatch.state != "CONFIRMED":
            predicted_dispatch_state = "CONFIRMED"
            predicted_signal = "new_attributable_output"
            predicted_signal_state = "DISPATCH_CONFIRMED"
        elif durable_job_identity and dispatch is not None and dispatch.state != "CONFIRMED":
            predicted_dispatch_state = "CONFIRMED"
            predicted_signal = "durable_attributable_job_identity"
            predicted_signal_state = "DISPATCH_CONFIRMED"
        value = {
            "phase": phase,
            "provider_surface_fingerprint": surface_fingerprint(records_for_type(current, media_type)),
            "baseline_surface_fingerprint": surface_fingerprint(records_for_type(baseline, media_type)),
            "baseline_identity_set": baseline_projection,
            "current_identity_set": current_projection,
            "identity_delta": delta,
            "job_card_identities_observed": sorted({
                str(item.get("card_id")) for item in current_projection if item.get("card_id")
            }),
            "output_asset_identities_observed": sorted({
                str(item.get("asset_id")) for item in current_projection if item.get("asset_id")
            }),
            "candidate_identities": candidates,
            "candidate_classification": observation.state if observation is not None else "BASELINE_OBSERVATION",
            "quarantined_identities": list(quarantined or []),
            "stable_poll_count": observation.stable_polls if observation is not None else stable_polls,
            "provider_busy": bool(int((surface or {}).get("global_pending_count", 0))),
            "dispatch_evidence_state": predicted_dispatch_state,
            "dispatch_evidence_signal": predicted_signal,
            "dispatch_signal_state": predicted_signal_state,
            "durable_dispatch_identity": durable_output_identity or durable_job_identity or (dispatch.durable_identity if dispatch else None),
            "attribution_evidence_state": observation.state if observation is not None else "NOT_ATTEMPTED",
            "lineage_card_id": lineage_card_id,
            "input_dispatched": bool((activation or {}).get("input_dispatched")),
        }
        persisted = self._poll_timeline.append(value)
        # A dispatch transition may use this poll only after the exact persisted
        # snapshot verifies under the writer's canonical hash contract.
        ProviderPollEvidenceTimeline.verify_snapshot(self._poll_timeline.snapshot())
        if dispatch is not None and dispatch.state != "CONFIRMED":
            if durable_output_identity:
                dispatch.observe(
                    input_dispatched=bool((activation or {}).get("input_dispatched", True)),
                    attributable_output=True,
                    durable_evidence_serialized=True,
                    evidence_poll_sequence=persisted["poll_sequence"],
                )
                dispatch.durable_identity = durable_output_identity
                dispatch.evidence_poll_sequence = persisted["poll_sequence"]
            elif durable_job_identity:
                dispatch.observe(
                    input_dispatched=bool((activation or {}).get("input_dispatched", True)),
                    attributable_job=True,
                    durable_job_identity=durable_job_identity,
                    durable_evidence_serialized=True,
                    evidence_poll_sequence=persisted["poll_sequence"],
                )
        self._sync_poll_evidence()
        return persisted

    @staticmethod
    def _verify_persisted_poll_evidence(settings: dict) -> dict:
        snapshot = settings.get("provider_poll_evidence")
        if not isinstance(snapshot, dict):
            raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "persisted poll evidence is unavailable")
        verified = ProviderPollEvidenceTimeline.verify_snapshot(snapshot)
        if not verified.get("evidence_complete"):
            raise FlowError("FLOW_POLL_EVIDENCE_LIMIT_EXCEEDED", "persisted poll evidence is incomplete")
        return verified

    def _record_observation(self, observation) -> None:
        self.last_settings.update({
            "attribution_method": observation.method,
            "attribution_method_version": ATTRIBUTION_METHOD_VERSION,
            "attribution_state": observation.state,
            "candidate_delta_count": observation.candidate_delta_count,
            "candidate_identities": observation.candidate_identities,
            "foreign_candidate_identities": observation.foreign_candidate_identities,
            "attribution_stable_polls": observation.stable_polls,
        })
        if observation.lineage_card_id:
            self.last_settings["provider_lineage_card_id"] = observation.lineage_card_id

    def _sync_dispatch_state(self, dispatch: DispatchEvidenceTracker) -> None:
        self.dispatch_confirmed = dispatch.state == "CONFIRMED"
        self.dispatch_confirmation_state = dispatch.state
        self.last_settings.update({
            "dispatch_confirmation_state": dispatch.state,
            "dispatch_confirmation_signal": dispatch.signal,
            "dispatch_ack_method": dispatch.signal,
            "dispatch_signal_state": dispatch.signal_state,
            "durable_dispatch_identity": dispatch.durable_identity,
            "dispatch_evidence_poll_sequence": dispatch.evidence_poll_sequence,
        })

    def _reference_echoes(self, page, records: list[dict], observation,
                          reference_hashes: list[str]) -> list[dict]:
        """Identify known input echoes only; never use pixels to select output."""
        if not reference_hashes:
            return []
        candidate_ids = {
            item.get("identity") for item in observation.candidate_identities
            if isinstance(item, dict) and item.get("identity")
        }
        echoes = []
        for record in records:
            if provider_identity(record) not in candidate_ids or not record.get("url"):
                continue
            try:
                candidate_hash = _dhash_bytes(self._fetch_bytes(page, record["url"]))
            except Exception:
                continue
            if any((int(candidate_hash, 16) ^ int(reference_hash, 16)).bit_count() <= 4
                   for reference_hash in reference_hashes):
                echoes.append(record)
        return echoes

    def __call__(self, request, references, destination: Path):
        # The generator is reused across a batch. Dispatch and attribution
        # evidence are request-local and must never leak from a prior attempt.
        self.dispatch_confirmed = False
        self.dispatch_confirmation_state = "NOT_ATTEMPTED"
        self._reset_poll_evidence(destination.parent / "provider_poll_evidence.json")
        page = CdpPage.open(self.runtime)
        try:
            dom = FlowBrowserDom(page)
            identity_history = request.get("_flow_provider_identity_history", [])
            history_seed = identity_history if isinstance(identity_history, list) else []
            historical_records, _ = _stable_surface(
                dom, request["media_type"],
                seed=history_seed,
                capacity_guard=self._ensure_poll_capacity,
                poll_observer=lambda surface, records, stable: self._record_poll(
                    phase="PRE_DISPATCH_DISCOVERY", media_type=request["media_type"],
                    baseline=history_seed, current=records, surface=surface,
                    stable_polls=stable,
                ),
            )
            dom.reset_composer()
            resolved = resolve_settings(request)
            self.last_settings.update(dom.apply_settings(resolved))
            self._sync_poll_evidence()
            if request["media_type"] == "IMAGE" and not (
                    self.last_settings.get("requested_output_count") ==
                    self.last_settings.get("actual_output_count") == 1):
                raise FlowError("IMAGE_OUTPUT_COUNT_MISMATCH")
            baseline_records = list(historical_records)

            def baseline():
                nonlocal baseline_records
                prior_baseline = list(baseline_records)
                baseline_records, stable_polls = _stable_surface(
                    dom, request["media_type"], seed=baseline_records,
                    capacity_guard=self._ensure_poll_capacity,
                    poll_observer=lambda surface, records, stable: self._record_poll(
                        phase="PRE_DISPATCH_BASELINE", media_type=request["media_type"],
                        baseline=prior_baseline, current=records, surface=surface,
                        stable_polls=stable,
                    ),
                )
                typed = records_for_type(baseline_records, request["media_type"])
                self.last_settings.update({
                    "pre_dispatch_baseline_fingerprint": surface_fingerprint(typed),
                    "baseline_provider_identities": [evidence_identity(item) for item in typed],
                    "baseline_stable_polls": stable_polls,
                    "baseline_state": "QUIESCENT",
                })

            source_references = [Path(item) for item in references if item]
            if len(source_references) > 1:
                omitted = source_references[1:]
                self.last_settings["reference_capacity_limit"] = 1
                self.last_settings["omitted_reference_hashes"] = [sha256_file(item) for item in omitted]
                source_references = source_references[:1]
            self.last_settings["attached_reference_hashes"] = [sha256_file(item) for item in source_references]
            with tempfile.TemporaryDirectory(prefix="story-auto-flow-refs-") as staging_directory:
                staged_references = []
                for source in source_references:
                    source_hash = sha256_file(source)
                    staged = Path(staging_directory) / f"ref_{source_hash[:16]}.png"
                    from PIL import Image, PngImagePlugin
                    metadata = PngImagePlugin.PngInfo()
                    metadata.add_text("StoryAutoReferenceSha256", source_hash)
                    with Image.open(source) as image:
                        image.convert("RGB").save(staged, "PNG", pnginfo=metadata)
                    staged_references.append(str(staged))
                    self.last_settings.setdefault("staged_reference_uploads", []).append({
                        "source_sha256": source_hash,
                        "upload_sha256": sha256_file(staged),
                    })
                try:
                    submit = FlowComposer(dom).submit(
                        request["prompt"], references=staged_references,
                        media_type=request["media_type"], before_dispatch=baseline,
                        mode_already_configured=True,
                    )
                except (FlowError, FlowSessionError) as error:
                    composer = getattr(dom, "last_composer_ready_state", None)
                    activation = getattr(dom, "last_activation_receipt", None)
                    if isinstance(composer, dict):
                        self.last_settings["composer_ready_state"] = composer
                    if isinstance(activation, dict):
                        self.last_settings["activation"] = activation
                    uncertain = error.failure_class == "FLOW_DISPATCH_UNCERTAIN"
                    state = "UNCERTAIN" if uncertain else "PRE_DISPATCH_FAILURE"
                    self.dispatch_confirmation_state = state
                    self.last_settings.update({
                        "dispatch_confirmation_state": state,
                        "dispatch_confirmation_signal": "activation_transport_uncertain" if uncertain else "input_not_dispatched",
                        "provider_job_id": None,
                        "attribution_state": "NOT_ATTEMPTED",
                    })
                    raise

            self.last_settings.update(submit)
            activation = submit["activation"]
            dispatch = DispatchEvidenceTracker()
            dispatch.observe(
                input_dispatched=bool(activation.get("input_dispatched")),
                trusted_click_seen=bool(activation.get("trusted_click_seen")),
            )
            attribution = RequestAttributionTracker(
                baseline_records, media_type=request["media_type"],
                expected_count=resolved.output_count,
            )
            self.last_settings.update({
                "dispatch_confirmation_state": dispatch.state,
                "dispatch_confirmation_signal": dispatch.signal,
                "provider_job_id": None,
                "attribution_state": "PENDING",
            })
            reference_hashes = []
            if request["media_type"] == "IMAGE":
                for reference in references:
                    try:
                        reference_hashes.append(validate_image(Path(reference))["dhash256"])
                    except Exception:
                        pass

            deadline = time.monotonic() + self.timeout_seconds
            while time.monotonic() < deadline:
                self._ensure_poll_capacity()
                states = page.evaluate(_EDITOR_JS) or []
                prompt_transition = len(states) == 0 or all(
                    item.get("text", "") != request["prompt"] for item in states
                )
                if prompt_transition:
                    self.last_settings["composer_transition_seen"] = True
                    dispatch.observe(
                        input_dispatched=bool(activation.get("input_dispatched")),
                        trusted_click_seen=bool(activation.get("trusted_click_seen")),
                        prompt_transition=True,
                    )
                surface = dom.provider_surface()
                current = surface.get("records", []) if isinstance(surface, dict) else []
                observation = attribution.observe(
                    current, provider_busy=bool(int((surface or {}).get("global_pending_count", 0)))
                )
                quarantined: list[dict] = []
                if observation.state == "AMBIGUOUS":
                    echoes = self._reference_echoes(page, current, observation, reference_hashes)
                    if echoes:
                        quarantined = [
                            {**evidence_identity(item), "reason": "REFERENCE_INPUT_ECHO"}
                            for item in echoes
                        ]
                        self._record_poll(
                            phase="POST_DISPATCH", media_type=request["media_type"],
                            baseline=baseline_records, current=current, surface=surface,
                            stable_polls=observation.stable_polls, observation=observation,
                            dispatch=dispatch, activation=activation, quarantined=quarantined,
                        )
                        self._record_observation(observation)
                        self._sync_dispatch_state(dispatch)
                        baseline_records = _merge_surface_records(baseline_records, echoes)
                        self.last_settings.setdefault("quarantined_foreign_identities", []).extend(
                            quarantined
                        )
                        attribution = RequestAttributionTracker(
                            baseline_records, media_type=request["media_type"],
                            expected_count=resolved.output_count,
                        )
                        time.sleep(.5)
                        continue
                    self._record_poll(
                        phase="POST_DISPATCH", media_type=request["media_type"],
                        baseline=baseline_records, current=current, surface=surface,
                        stable_polls=observation.stable_polls, observation=observation,
                        dispatch=dispatch, activation=activation,
                    )
                    self._record_observation(observation)
                    self._sync_dispatch_state(dispatch)
                    self.last_settings["attribution_state"] = "AMBIGUOUS"
                    raise FlowError(
                        "OUTPUT_ATTRIBUTION_AMBIGUOUS",
                        "multiple unseen provider candidates had no unique request lineage",
                    )
                if observation.state == "CONFIRMED" and observation.candidate:
                    candidate = observation.candidate
                    data = self._fetch_bytes(page, candidate["url"])
                    if request["media_type"] == "IMAGE" and reference_hashes:
                        candidate_hash = _dhash_bytes(data)
                        if any((int(candidate_hash, 16) ^ int(reference_hash, 16)).bit_count() <= 4
                               for reference_hash in reference_hashes):
                            quarantined = [{**evidence_identity(candidate), "reason": "REFERENCE_INPUT_ECHO"}]
                            self._record_poll(
                                phase="POST_DISPATCH", media_type=request["media_type"],
                                baseline=baseline_records, current=current, surface=surface,
                                stable_polls=observation.stable_polls, observation=observation,
                                dispatch=dispatch, activation=activation, quarantined=quarantined,
                            )
                            self._record_observation(observation)
                            self._sync_dispatch_state(dispatch)
                            self.last_settings.setdefault("quarantined_foreign_identities", []).extend(quarantined)
                            baseline_records = _merge_surface_records(baseline_records, [candidate])
                            attribution = RequestAttributionTracker(
                                baseline_records, media_type=request["media_type"],
                                expected_count=resolved.output_count,
                            )
                            time.sleep(.5)
                            continue
                    self._record_poll(
                        phase="POST_DISPATCH", media_type=request["media_type"],
                        baseline=baseline_records, current=current, surface=surface,
                        stable_polls=observation.stable_polls, observation=observation,
                        dispatch=dispatch, activation=activation,
                    )
                    self._record_observation(observation)
                    self._sync_dispatch_state(dispatch)
                    self.last_settings.update({
                        "attribution_state": "CONFIRMED",
                        "attributed_provider_identity": evidence_identity(candidate),
                        "attribution_confirmation_timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    atomic_write_bytes(destination, data)
                    return destination
                self._record_poll(
                    phase="POST_DISPATCH", media_type=request["media_type"],
                    baseline=baseline_records, current=current, surface=surface,
                    stable_polls=observation.stable_polls, observation=observation,
                    dispatch=dispatch, activation=activation,
                )
                self._record_observation(observation)
                self._sync_dispatch_state(dispatch)
                time.sleep(.5)

            self.dispatch_confirmation_state = dispatch.state
            self.last_settings.update({
                "dispatch_confirmation_state": dispatch.state,
                "dispatch_confirmation_signal": dispatch.signal,
            })
            failure = dispatch_timeout_failure(dispatch)
            if failure == "FLOW_PRE_DISPATCH_ACTIVATION_FAILED":
                raise FlowError("FLOW_PRE_DISPATCH_ACTIVATION_FAILED", "no Generate input was dispatched")
            if failure == "OUTPUT_ATTRIBUTION_UNCERTAIN":
                self.last_settings["attribution_state"] = "UNCERTAIN"
                raise FlowError("OUTPUT_ATTRIBUTION_UNCERTAIN", "dispatch was confirmed but no unique stable output lineage completed")
            raise FlowError("FLOW_DISPATCH_UNCERTAIN", "activation occurred but no attributable Flow job or output was proven")
        finally:
            try:
                self._finish_poll_evidence(
                    str((self.last_settings or {}).get("attribution_state") or self.dispatch_confirmation_state)
                )
            finally:
                page.close()

    def reconcile(self, request, attempt: dict, destination: Path) -> dict:
        """Inspect a prior request baseline without another activation."""
        settings = attempt.get("provider_settings", {}) if isinstance(attempt, dict) else {}
        if not isinstance(settings, dict):
            return {"state": "REMAINS_AMBIGUOUS", "evidence": {"reason": "FLOW_POLL_EVIDENCE_INVALID"}}
        try:
            verified_evidence = self._verify_persisted_poll_evidence(settings)
        except FlowError as error:
            # Never reuse a baseline, durable dispatch identity, or attribution
            # detail from evidence that cannot verify exactly as persisted.
            return {"state": "REMAINS_AMBIGUOUS", "evidence": {"reason": error.failure_class}}
        baseline_observations = [
            observation for observation in verified_evidence["observations"]
            if observation.get("phase") == "PRE_DISPATCH_BASELINE"
        ]
        baseline = baseline_observations[-1].get("current_identity_set") if baseline_observations else None
        history = request.get("_flow_provider_identity_history", [])
        if isinstance(history, list):
            baseline = _merge_surface_records(baseline if isinstance(baseline, list) else [], history)
        if not isinstance(baseline, list) or not baseline:
            return {"state": "REMAINS_AMBIGUOUS", "evidence": {"reason": "LEGACY_BASELINE_IDENTITIES_UNAVAILABLE"}}
        self._reset_poll_evidence(destination.parent / "reconciliation_poll_evidence.json")
        dispatch = DispatchEvidenceTracker()
        activation = settings.get("activation") if isinstance(settings.get("activation"), dict) else {"input_dispatched": True}
        verified_identities = [
            observation.get("durable_dispatch_identity")
            for observation in verified_evidence["observations"]
            if isinstance(observation.get("durable_dispatch_identity"), str)
            and observation.get("durable_dispatch_identity")
        ]
        prior_durable_identity = verified_identities[-1] if verified_identities else None
        if attempt.get("dispatch_confirmed") is True and isinstance(prior_durable_identity, str) and prior_durable_identity:
            dispatch.observe(
                input_dispatched=True, attributable_job=True,
                durable_job_identity=prior_durable_identity,
                durable_evidence_serialized=True,
            )
        elif attempt.get("dispatch_confirmed") is True:
            dispatch.observe(input_dispatched=True, attributable_job=True)
        page = CdpPage.open(self.runtime)
        try:
            dom = FlowBrowserDom(page)
            tracker = RequestAttributionTracker(
                baseline, media_type=request["media_type"],
                expected_count=int(request.get("output_count", 1)),
            )
            reference_hashes = []
            if request["media_type"] == "IMAGE":
                for reference in request.get("_flow_reference_paths", []):
                    try:
                        reference_hashes.append(validate_image(Path(reference))["dhash256"])
                    except Exception:
                        pass
            deadline = time.monotonic() + 12.0
            last = None
            while time.monotonic() < deadline:
                self._ensure_poll_capacity()
                surface = dom.provider_surface()
                records = surface.get("records", []) if isinstance(surface, dict) else []
                busy = bool(int((surface or {}).get("global_pending_count", 0)))
                last = tracker.observe(
                    records, provider_busy=busy
                )
                if last.state == "AMBIGUOUS":
                    echoes = self._reference_echoes(page, records, last, reference_hashes)
                    if echoes:
                        quarantined = [
                            {**evidence_identity(item), "reason": "REFERENCE_INPUT_ECHO"}
                            for item in echoes
                        ]
                        self._record_poll(
                            phase="RECONCILIATION", media_type=request["media_type"],
                            baseline=baseline, current=records, surface=surface,
                            stable_polls=last.stable_polls, observation=last,
                            dispatch=dispatch, activation=activation, quarantined=quarantined,
                        )
                        self._record_observation(last)
                        self._sync_dispatch_state(dispatch)
                        baseline = _merge_surface_records(baseline, echoes)
                        tracker = RequestAttributionTracker(
                            baseline, media_type=request["media_type"],
                            expected_count=int(request.get("output_count", 1)),
                        )
                        time.sleep(.5)
                        continue
                    self._record_poll(
                        phase="RECONCILIATION", media_type=request["media_type"],
                        baseline=baseline, current=records, surface=surface,
                        stable_polls=last.stable_polls, observation=last,
                        dispatch=dispatch, activation=activation,
                    )
                    self._record_observation(last)
                    self._sync_dispatch_state(dispatch)
                    self._finish_poll_evidence("OUTPUT_ATTRIBUTION_AMBIGUOUS")
                    return {"state": "REMAINS_AMBIGUOUS", "evidence": {
                        "reason": "OUTPUT_ATTRIBUTION_AMBIGUOUS",
                        "candidate_delta_count": last.candidate_delta_count,
                        "candidate_identities": last.candidate_identities,
                        **self._poll_evidence_fields(),
                    }}
                if last.state == "CONFIRMED" and last.candidate:
                    self._record_poll(
                        phase="RECONCILIATION", media_type=request["media_type"],
                        baseline=baseline, current=records, surface=surface,
                        stable_polls=last.stable_polls, observation=last,
                        dispatch=dispatch, activation=activation,
                    )
                    self._record_observation(last)
                    self._sync_dispatch_state(dispatch)
                    data = self._fetch_bytes(page, last.candidate["url"])
                    atomic_write_bytes(destination, data)
                    self._finish_poll_evidence("CONFIRMED_OUTPUT")
                    evidence = {
                        "attribution_state": "CONFIRMED",
                        "attribution_method": last.method,
                        "attribution_method_version": ATTRIBUTION_METHOD_VERSION,
                        "attributed_provider_identity": evidence_identity(last.candidate),
                        "candidate_delta_count": last.candidate_delta_count,
                        "candidate_identities": last.candidate_identities,
                        "attribution_confirmation_timestamp": datetime.now(timezone.utc).isoformat(),
                        "pre_dispatch_baseline_fingerprint": settings.get("pre_dispatch_baseline_fingerprint"),
                        "baseline_provider_identities": [evidence_identity(item) for item in baseline],
                        "dispatch_confirmation_state": "CONFIRMED",
                        "dispatch_confirmation_signal": "reconciled_provider_tile_lineage",
                        "durable_dispatch_identity": dispatch.durable_identity,
                        "dispatch_evidence_poll_sequence": dispatch.evidence_poll_sequence,
                        **self._poll_evidence_fields(),
                    }
                    return {"state": "CONFIRMED_OUTPUT", "path": str(destination), "evidence": evidence}
                if last.lineage_card_id and last.state == "WAITING":
                    self._record_poll(
                        phase="RECONCILIATION", media_type=request["media_type"],
                        baseline=baseline, current=records, surface=surface,
                        stable_polls=last.stable_polls, observation=last,
                        dispatch=dispatch, activation=activation,
                    )
                    self._record_observation(last)
                    self._sync_dispatch_state(dispatch)
                    self._finish_poll_evidence("CONFIRMED_DISPATCH")
                    return {"state": "CONFIRMED_DISPATCH", "evidence": {
                        "provider_lineage_card_id": last.lineage_card_id,
                        "candidate_delta_count": last.candidate_delta_count,
                        "candidate_identities": last.candidate_identities,
                        "dispatch_confirmation_state": dispatch.state,
                        "dispatch_confirmation_signal": dispatch.signal,
                        "durable_dispatch_identity": dispatch.durable_identity,
                        "dispatch_evidence_poll_sequence": dispatch.evidence_poll_sequence,
                        **self._poll_evidence_fields(),
                    }}
                self._record_poll(
                    phase="RECONCILIATION", media_type=request["media_type"],
                    baseline=baseline, current=records, surface=surface,
                    stable_polls=last.stable_polls, observation=last,
                    dispatch=dispatch, activation=activation,
                )
                self._record_observation(last)
                self._sync_dispatch_state(dispatch)
                time.sleep(.5)
            self._finish_poll_evidence("NO_UNIQUE_PROVIDER_DELTA")
            return {"state": "REMAINS_AMBIGUOUS", "evidence": {
                "reason": "NO_UNIQUE_PROVIDER_DELTA",
                "candidate_delta_count": last.candidate_delta_count if last else 0,
                "candidate_identities": last.candidate_identities if last else [],
                **self._poll_evidence_fields(),
            }}
        finally:
            try:
                if not self._poll_timeline.complete:
                    self._finish_poll_evidence("RECONCILIATION_EXIT")
            finally:
                page.close()


def download_provider_asset_candidate(runtime, destination: Path, *, provider_asset_id: str) -> Path:
    """Download one operator-specified provider asset identity without dispatch."""
    if not isinstance(provider_asset_id, str) or not provider_asset_id.strip():
        raise FlowError("FLOW_RESULT_AMBIGUOUS", "exact provider asset identity is required")
    page = CdpPage.open(runtime)
    try:
        surface = FlowBrowserDom(page).provider_surface()
        matches = [
            record for record in surface.get("records", [])
            if record.get("asset_id") == provider_asset_id and record.get("state") == "READY"
        ]
        if len(matches) != 1:
            raise FlowError("FLOW_RESULT_AMBIGUOUS", "provider asset identity did not resolve uniquely")
        atomic_write_bytes(destination, LiveFlowGenerator._fetch_bytes(page, matches[0]["url"]))
        return destination
    finally:
        page.close()

"""Concrete Flow CDP adapter. UI assumptions live here and fail closed."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import secrets
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
_PROVIDER_SURFACE_JS = """(()=>{const assetId=url=>{try{const parsed=new URL(url,location.href);return parsed.searchParams.get('name')||parsed.origin+parsed.pathname}catch{return url}};const records=[],seen=new Set(),tiles=Array.from(document.querySelectorAll('[data-tile-id]')),locale=document.documentElement.lang||null;for(const tile of tiles){const card_id=tile.getAttribute('data-tile-id'),provider_job_id=tile.getAttribute('data-job-id')||tile.getAttribute('data-job')||null,hasVideo=!!tile.querySelector('video,video source');let ready=0;for(const e of tile.querySelectorAll('img,video,video source')){const url=e.currentSrc||e.src||e.getAttribute('src');if(typeof url!=='string'||!url||url.startsWith('data:'))continue;const kind=e.tagName,thumbnail=/mediaUrlType=MEDIA_URL_TYPE_THUMBNAIL/.test(url)||/video/i.test(e.alt||''),media_type=(hasVideo||kind==='VIDEO'||kind==='SOURCE')?(thumbnail&&kind==='IMG'?'VIDEO_THUMBNAIL':'VIDEO'):'IMAGE',usable=media_type==='VIDEO'?(kind!=='IMG'):(kind==='IMG'&&(e.naturalWidth||0)>=512);if(!usable)continue;const asset_id=assetId(url),key=card_id+'|'+asset_id+'|'+media_type;if(seen.has(key))continue;seen.add(key);records.push({card_id,asset_id,media_type,state:'READY',url,kind,width:e.naturalWidth||e.videoWidth||0,height:e.naturalHeight||e.videoHeight||0});ready++}if(!ready){const symbols=Array.from(tile.querySelectorAll('i')).map(e=>(e.textContent||'').trim()),terminalFailure=symbols.includes('warning')&&symbols.includes('refresh')&&symbols.includes('delete_forever');records.push({card_id,provider_job_id,asset_id:null,media_type:null,state:terminalFailure?'FAILED':'PENDING',failure_class:terminalFailure?'PROVIDER_VISIBLE_TERMINAL_FAILURE':null,terminal_structural_signals:terminalFailure?['warning','refresh','delete_forever']:[],raw_message:(tile.innerText||'').trim(),locale,url:null,kind:null,width:0,height:0})}}const readyCards=new Set(records.filter(x=>x.state==='READY').map(x=>x.card_id)),resolved=records.filter(x=>x.state==='READY'||!readyCards.has(x.card_id));let best=null;for(const tile of tiles){const key=Object.getOwnPropertyNames(tile).find(x=>x.startsWith('__reactFiber$'));let fiber=key?tile[key]:null;for(let depth=0;fiber&&depth<64;depth++,fiber=fiber.return){for(const props of [fiber.memoizedProps,fiber.pendingProps]){const xs=props&&Array.isArray(props.tiles)?props.tiles:null;if(!xs||!xs.length||!xs.every(x=>x&&typeof x.id==='string'))continue;const unique=new Map();for(const x of xs){const iso=v=>v instanceof Date?v.toISOString():(v&&typeof v.toDate==='function'?v.toDate().toISOString():(typeof v==='string'?v:null));unique.set(x.id,{card_id:x.id,media_type:x.type==null?null:String(x.type),created_at:iso(x.createdTime),modified_at:iso(x.modifiedTime),is_archived:!!x.isArchived})}if(!best||unique.size>best.length)best=Array.from(unique.values())}}}const provider_model_complete=Array.isArray(best)&&best.length>0;const provider_model_tiles=provider_model_complete?best:[];const global_pending_count=document.querySelectorAll('[aria-busy=true],[role=progressbar],[data-state=loading]').length;return {records:resolved,global_pending_count,locale,provider_model_complete,provider_model_tiles}})()"""
_ACTIVATE = "e=>{e.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));e.click()}"
_MODEL_TRIGGER = """(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable="true"]')).find(visible);let p=editor;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button[aria-haspopup="menu"]')).filter(visible);if(xs.length===1)return xs[0];p=p.parentElement}return null})()"""

PROVIDER_SURFACE_EXTRACTOR_VERSION = "flow-provider-surface/2.2.0"
POLL_EVIDENCE_VERSION = "story-auto-flow-poll-evidence/1.3.0"
SUPPORTED_POLL_EVIDENCE_SCHEMAS = {
    "story-auto-flow-poll-evidence/1.2.0": "flow-provider-surface/2.1.0",
    POLL_EVIDENCE_VERSION: PROVIDER_SURFACE_EXTRACTOR_VERSION,
}
MAX_POLL_OBSERVATIONS = 2048
MAX_PROVIDER_IDENTITIES_PER_POLL = 256
MAX_CANDIDATE_IDENTITIES_PER_POLL = 64
MAX_QUARANTINED_IDENTITIES_PER_POLL = 64
MAX_POLL_EVIDENCE_BYTES = 16 * 1024 * 1024
POLL_EVIDENCE_OVERFLOW_RESERVE_BYTES = 4096
_PROVIDER_IDENTITY_FIELDS = {
    "baseline_identity_set", "current_identity_set", "identity_delta",
    "pre_dispatch_asset_identity_set",
    "job_card_identities_observed", "output_asset_identities_observed",
    "pre_dispatch_provider_model_identity_set", "provider_model_identity_set",
    "provider_model_delta", "causal_card_ids", "historical_alias_card_ids",
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


def _asset_identity_projection(records: list[dict]) -> list[dict]:
    """Project stable assets independently of representation or card lineage."""
    projected = {
        provider_identity(record): {
            "identity": provider_identity(record),
            "asset_id": str(record.get("asset_id")),
        }
        for record in records
        if record.get("asset_id") and provider_identity(record)
    }
    return [projected[key] for key in sorted(projected)]


def _provider_model_projection(surface: dict) -> list[dict] | None:
    """Return the complete stable Flow tile model, independent of DOM virtualization."""
    if not isinstance(surface, dict) or surface.get("provider_model_complete") is not True:
        return None
    tiles = surface.get("provider_model_tiles")
    if not isinstance(tiles, list) or not tiles:
        return None
    projected: dict[str, dict] = {}
    for tile in tiles:
        if not isinstance(tile, dict):
            return None
        card_id = str(tile.get("card_id") or "").strip()
        if not card_id:
            return None
        projected[card_id] = {
            "card_id": card_id,
            "media_type": tile.get("media_type"),
            "created_at": tile.get("created_at"),
            "modified_at": tile.get("modified_at"),
            "is_archived": bool(tile.get("is_archived")),
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
                 max_serialized_bytes: int = MAX_POLL_EVIDENCE_BYTES,
                 poll_evidence_version: str = POLL_EVIDENCE_VERSION,
                 parser_extractor_version: str = PROVIDER_SURFACE_EXTRACTOR_VERSION):
        if (max_observations < 1 or max_provider_identities < 1
                or max_candidate_identities < 1 or max_quarantined_identities < 1
                or max_serialized_bytes <= POLL_EVIDENCE_OVERFLOW_RESERVE_BYTES):
            raise ValueError("poll evidence bounds must be positive and retain overflow reserve")
        if SUPPORTED_POLL_EVIDENCE_SCHEMAS.get(poll_evidence_version) != parser_extractor_version:
            raise ValueError("unsupported poll evidence schema pair")
        self.path = path
        self.poll_evidence_version = poll_evidence_version
        self.parser_extractor_version = parser_extractor_version
        self.max_observations = max_observations
        self.max_provider_identities = max_provider_identities
        self.max_candidate_identities = max_candidate_identities
        self.max_quarantined_identities = max_quarantined_identities
        self.max_serialized_bytes = max_serialized_bytes
        self.observations: list[dict] = []
        self.decision_bindings: list[dict] = []
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
            "poll_evidence_version": self.poll_evidence_version,
            "parser_extractor_version": self.parser_extractor_version,
            "previous_observation_sha256": (
                self.observations[-1]["observation_sha256"] if self.observations else None
            ),
        })
        observation["observation_sha256"] = _json_sha256(observation)
        return observation

    def append_decision_binding(self, source: dict, *, dispatch_state: str,
                                dispatch_signal: str | None,
                                dispatch_signal_state: str,
                                attribution_state: str,
                                durable_identity: str | None) -> dict:
        """Persist a derived decision only after its raw source poll verifies."""
        if not self.evidence_complete:
            raise FlowError("FLOW_POLL_EVIDENCE_LIMIT_EXCEEDED", "incomplete evidence cannot bind a decision")
        verified = self.verify_snapshot(self.snapshot())
        source_poll_sequence = source.get("poll_sequence")
        source_hash = source.get("observation_sha256")
        source_observation = next(
            (item for item in verified["observations"] if item.get("poll_sequence") == source_poll_sequence),
            None,
        )
        if (not isinstance(source_observation, dict)
                or source_observation.get("observation_sha256") != source_hash):
            raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "decision source poll is not verified")
        binding = {
            "binding_sequence": len(self.decision_bindings) + 1,
            "source_poll_sequence": source_poll_sequence,
            "source_observation_sha256": source_hash,
            "resulting_dispatch_state": dispatch_state,
            "resulting_dispatch_signal": dispatch_signal,
            "resulting_dispatch_signal_state": dispatch_signal_state,
            "resulting_attribution_state": attribution_state,
            "durable_identity_used": durable_identity,
            "previous_binding_sha256": (
                self.decision_bindings[-1]["binding_sha256"] if self.decision_bindings else None
            ),
        }
        binding["binding_sha256"] = _json_sha256(binding)
        self.decision_bindings.append(binding)
        if self._serialized_size_for_existing() > self.max_serialized_bytes:
            self.decision_bindings.pop()
            self.evidence_complete = False
            self._persist()
            raise FlowError("FLOW_POLL_EVIDENCE_LIMIT_EXCEEDED", "decision binding cannot fit bounded evidence")
        self.verify_snapshot(self.snapshot())
        self._persist()
        return binding

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
            "schema_version": self.poll_evidence_version,
            "parser_extractor_version": self.parser_extractor_version,
            "max_observations": self.max_observations,
            "max_provider_identities_per_poll": self.max_provider_identities,
            "max_candidate_identities_per_poll": self.max_candidate_identities,
            "max_quarantined_identities_per_poll": self.max_quarantined_identities,
            "max_serialized_bytes": self.max_serialized_bytes,
            "observation_count": len(self.observations if observations is None else observations),
            "decision_binding_count": len(self.decision_bindings),
            "decision_bindings_sha256": _json_sha256(self.decision_bindings),
            "decision_bindings": list(self.decision_bindings),
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
                "timeline_sha256", "decision_binding_count", "decision_bindings_sha256",
            )
        })

    @classmethod
    def verify_snapshot(cls, snapshot: dict) -> dict:
        """Fail closed unless a persisted timeline is exact and internally coherent."""
        try:
            if not isinstance(snapshot, dict):
                raise ValueError("schema")
            schema_version = snapshot.get("schema_version")
            parser_version = snapshot.get("parser_extractor_version")
            if SUPPORTED_POLL_EVIDENCE_SCHEMAS.get(schema_version) != parser_version:
                raise ValueError("extractor")
            observations = snapshot.get("observations")
            bindings = snapshot.get("decision_bindings")
            if not isinstance(observations, list) or not isinstance(bindings, list):
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
            if (len(bindings) != snapshot.get("decision_binding_count")
                    or len(bindings) > len(observations)
                    or snapshot.get("decision_bindings_sha256") != _json_sha256(bindings)):
                raise ValueError("binding_count")
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
                        or observation.get("poll_evidence_version") != schema_version
                        or observation.get("parser_extractor_version") != parser_version
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
            previous_binding = None
            source_by_sequence = {item["poll_sequence"]: item for item in observations}
            for index, binding in enumerate(bindings, start=1):
                if not isinstance(binding, dict):
                    raise ValueError("binding")
                stored_hash = binding.get("binding_sha256")
                unsigned = dict(binding); unsigned.pop("binding_sha256", None)
                if (not isinstance(stored_hash, str) or _json_sha256(unsigned) != stored_hash
                        or binding.get("binding_sequence") != index
                        or binding.get("previous_binding_sha256") != previous_binding):
                    raise ValueError("binding_chain")
                source = source_by_sequence.get(binding.get("source_poll_sequence"))
                if (not isinstance(source, dict)
                        or binding.get("source_observation_sha256") != source.get("observation_sha256")):
                    raise ValueError("binding_source")
                dispatch_state = binding.get("resulting_dispatch_state")
                attribution_state = binding.get("resulting_attribution_state")
                durable_identity = binding.get("durable_identity_used")
                if not isinstance(dispatch_state, str) or not isinstance(attribution_state, str):
                    raise ValueError("binding_state")
                source_identities = cls._source_identities(source)
                if durable_identity is not None and (not isinstance(durable_identity, str)
                                                     or durable_identity not in source_identities):
                    raise ValueError("binding_identity")
                if dispatch_state == "CONFIRMED" and not durable_identity:
                    raise ValueError("binding_dispatch_identity")
                if attribution_state == "CONFIRMED":
                    if (source.get("attribution_evidence_state") != "CONFIRMED"
                            or dispatch_state != "CONFIRMED" or not durable_identity):
                        raise ValueError("binding_attribution")
                if source.get("evidence_complete") is False and (
                        dispatch_state == "CONFIRMED" or attribution_state == "CONFIRMED"):
                    raise ValueError("binding_incomplete")
                previous_binding = stored_hash
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

    @staticmethod
    def _source_identities(observation: dict) -> set[str]:
        identities = set()
        for field in (*_PROVIDER_IDENTITY_FIELDS, "candidate_identities", "quarantined_identities"):
            for item in observation.get(field, []) if isinstance(observation.get(field), list) else []:
                if isinstance(item, dict) and isinstance(item.get("identity"), str):
                    identities.add(item["identity"])
        identities.update(f"card:{item}" for item in observation.get("job_card_identities_observed", [])
                          if isinstance(item, str))
        identities.update(f"asset:{item}" for item in observation.get("output_asset_identities_observed", [])
                          if isinstance(item, str))
        for terminal in observation.get("terminal_observations", []):
            if not isinstance(terminal, dict):
                continue
            card_id = terminal.get("card_id")
            provider_job_id = terminal.get("provider_job_id")
            if isinstance(card_id, str) and card_id:
                identities.add(f"card:{card_id}")
            if isinstance(provider_job_id, str) and provider_job_id:
                identities.add(f"job:{provider_job_id}")
        if isinstance(observation.get("durable_dispatch_identity"), str):
            identities.add(observation["durable_dispatch_identity"])
        return identities

    @classmethod
    def verify_authoritative_binding(cls, snapshot: dict) -> dict:
        verified = cls.verify_snapshot(snapshot)
        bindings = verified.get("decision_bindings", [])
        if not bindings:
            raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "authoritative decision binding is unavailable")
        return bindings[-1]

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
        pending = [record for record in typed if record.get("state") == "PENDING"]
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
        self.dom.page.assert_locator_activation_available()
        receipt = {
            "activation_time": datetime.now(timezone.utc).isoformat(),
            "interaction_method": "PLAYWRIGHT_LOCATOR",
            "interaction_version": 3,
            "target_resolved_at_activation": False,
            "activation_attempted": False,
            "activation_verified": False,
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
        activation_token = secrets.token_hex(16)
        installed = self.dom.page.evaluate("""(()=>{const token=%s;const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable=\"true\"]')).find(visible);if(!editor)return false;let p=editor.parentElement,control=null;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button')).filter(e=>visible(e)&&e.type==='submit'&&e.querySelector('i')?.textContent.trim()==='arrow_forward');if(xs.length===1){control=xs[0];break}if(xs.length>1)return false;p=p.parentElement}if(!control)return false;control.setAttribute('data-story-auto-flow-activation',token);window.__storyAutoFlowActivationV3=[];for(const name of ['pointerdown','mousedown','pointerup','mouseup','click'])control.addEventListener(name,e=>window.__storyAutoFlowActivationV3.push({type:e.type,isTrusted:e.isTrusted,button:e.button,buttons:e.buttons,pointerType:e.pointerType||null,defaultPrevented:e.defaultPrevented}),true);return true})()""" % __import__('json').dumps(activation_token))
        if not installed:
            raise FlowError("FLOW_PRE_DISPATCH_ACTIVATION_FAILED", "Generate target changed before input")
        try:
            # This is the one activation authority for the attempt.  Never
            # fall back to raw CDP coordinates after it begins.
            receipt["activation_attempted"] = True
            self.dom.page.locator_click(
                "[data-story-auto-flow-activation=%s]" % __import__('json').dumps(activation_token),
            )
            receipt["input_dispatched"] = True
        except Exception as error:
            receipt["transport_error"] = type(error).__name__
            receipt["input_dispatched"] = bool(receipt["activation_attempted"])
            raise FlowError("FLOW_DISPATCH_UNCERTAIN", "native activation transport failed after input began") from error
        time.sleep(.25)
        events = self.dom.page.evaluate("window.__storyAutoFlowActivationV3||[]") or []
        receipt["event_types"] = [item.get("type") for item in events]
        receipt["trusted_click_seen"] = any(item.get("type") == "click" and item.get("isTrusted") is True for item in events)
        receipt["activation_verified"] = receipt["trusted_click_seen"]
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
                activation_verified: bool = False,
                provider_acceptance_transition: bool = False,
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
        elif (activation_verified and provider_acceptance_transition
              and attributable_output and durable_evidence_serialized):
            signal = "verified_activation_provider_ui_output"
        elif (activation_verified and provider_acceptance_transition and attributable_job
              and durable_identity and durable_evidence_serialized):
            signal = "verified_activation_provider_ui_job"
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
        elif self.state != "CONFIRMED" and (trusted_click_seen or prompt_transition
                                             or attributable_output):
            self.state = "UNCERTAIN"
            if attributable_output:
                self.signal = "unverified_activation_provider_surface_activity"
            else:
                self.signal = "composer_transition_after_activation" if prompt_transition else "trusted_click_only"
            self.signal_state = "SIGNAL_OBSERVED"
        return self.state

    def restore_verified_confirmation(self, durable_identity: str, *, evidence_poll_sequence: int | None = None) -> None:
        """Restore an already-verified historical causal acceptance binding.

        Reconciliation never re-derives dispatch from a new card.  Its caller
        must first verify the prior immutable decision binding.
        """
        if not isinstance(durable_identity, str) or not durable_identity.strip():
            raise FlowError("FLOW_POLL_EVIDENCE_INVALID", "missing durable historical dispatch identity")
        self.state = "CONFIRMED"
        self.signal = "verified_persisted_request_causal_acceptance"
        self.signal_state = "DISPATCH_CONFIRMED"
        self.durable_identity = durable_identity.strip()
        self.evidence_poll_sequence = evidence_poll_sequence
        self.confirmation_count = 1


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
    def inspect_generation_count(self, media_type: str) -> int:
        """Read Flow's count for one media type and leave the menu closed."""
        token = "IMAGE" if media_type == "IMAGE" else "VIDEO"
        # These provider-free UI transitions must not depend on animation
        # frames: Chrome can throttle requestAnimationFrame for an occluded
        # dedicated Flow tab while CDP itself remains connected.
        script = """(async()=>{const activate=e=>{e.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));e.click()};const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable=\"true\"]')).find(visible);let p=editor,trigger=null;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button[aria-haspopup=\"menu\"]')).filter(visible);if(xs.length===1){trigger=xs[0];break}p=p.parentElement}if(!trigger)throw Error('model_trigger');if(trigger.getAttribute('aria-expanded')!=='true'){activate(trigger);await new Promise(r=>setTimeout(r,0))}const tab=value=>Array.from(document.querySelectorAll('button[aria-controls]')).filter(e=>(e.getAttribute('aria-controls')||'').endsWith('content-'+value)&&visible(e));const selected=value=>tab(value).filter(e=>e.getAttribute('aria-selected')==='true').length===1;if(!selected(%s)){const xs=tab(%s);if(xs.length!==1)throw Error('mode:'+xs.length);activate(xs[0]);await new Promise(r=>setTimeout(r,0))}const media=selected(%s),count=[1,2,3,4].find(value=>selected(String(value)))||null;activate(trigger);await new Promise(r=>setTimeout(r,0));return {media,count,menu_closed:trigger.getAttribute('aria-expanded')!=='true'}})()""" % tuple(__import__('json').dumps(value) for value in (token, token, token))
        actual = self.page.evaluate(script)
        if not isinstance(actual, dict) or not actual.get("media") or not actual.get("menu_closed"):
            raise FlowError("FLOW_UI_CHANGED", f"generation-count inspection failed: {actual}")
        if actual.get("count") not in {1, 2, 3, 4}:
            raise FlowError("FLOW_UI_CHANGED", f"generation-count readback was ambiguous: {actual}")
        return int(actual["count"])
    def configure_generation_count(self, media_type: str, count: int) -> None:
        """Mutate only the provider count setting, then let the caller verify it."""
        token = "IMAGE" if media_type == "IMAGE" else "VIDEO"
        if count not in {1, 2, 3, 4}:
            raise FlowError("FLOW_CAPABILITY_UNAVAILABLE", "unsupported Flow generation count")
        script = """(async()=>{const activate=e=>{e.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));e.click()};const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable=\"true\"]')).find(visible);let p=editor,trigger=null;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button[aria-haspopup=\"menu\"]')).filter(visible);if(xs.length===1){trigger=xs[0];break}p=p.parentElement}if(!trigger)throw Error('model_trigger');if(trigger.getAttribute('aria-expanded')!=='true'){activate(trigger);await new Promise(r=>setTimeout(r,0))}const tab=value=>Array.from(document.querySelectorAll('button[aria-controls]')).filter(e=>(e.getAttribute('aria-controls')||'').endsWith('content-'+value)&&visible(e));const selected=value=>tab(value).filter(e=>e.getAttribute('aria-selected')==='true').length===1;for(const value of [%s,%s]){if(!selected(value)){const xs=tab(value);if(xs.length!==1)throw Error('setting:'+value+':'+xs.length);activate(xs[0]);await new Promise(r=>setTimeout(r,0))}}activate(trigger);await new Promise(r=>setTimeout(r,0));return trigger.getAttribute('aria-expanded')!=='true'})()""" % tuple(__import__('json').dumps(value) for value in (token, str(count)))
        if self.page.evaluate(script) is not True:
            raise FlowError("FLOW_UI_CHANGED", "Flow generation-count settings menu did not close")
    def apply_request_settings(self, resolved: ResolvedFlowGenerationSettings) -> dict:
        """Apply request-specific mode and ratio without touching generation count."""
        token = "IMAGE" if resolved.media_type == "IMAGE" else "VIDEO"
        ratio = {"16:9":"LANDSCAPE", "4:3":"LANDSCAPE_4_3", "1:1":"SQUARE", "3:4":"PORTRAIT_3_4", "9:16":"PORTRAIT"}.get(resolved.aspect_ratio)
        if not ratio: raise FlowError("FLOW_CAPABILITY_UNAVAILABLE", "unsupported Flow aspect ratio")
        script = """(async()=>{const activate=e=>{e.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));e.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));e.click()};const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const editor=Array.from(document.querySelectorAll('textarea,[contenteditable=\"true\"]')).find(visible);let p=editor,trigger=null;while(p&&p!==document.body){const xs=Array.from(p.querySelectorAll('button[aria-haspopup=\"menu\"]')).filter(visible);if(xs.length===1){trigger=xs[0];break}p=p.parentElement}if(!trigger)throw Error('model_trigger');if(trigger.getAttribute('aria-expanded')!=='true'){activate(trigger);await new Promise(r=>setTimeout(r,0))}const tab=value=>Array.from(document.querySelectorAll('button[aria-controls]')).filter(e=>(e.getAttribute('aria-controls')||'').endsWith('content-'+value)&&visible(e));const choose=(value,reason)=>{const xs=tab(value);if(xs.length!==1)throw Error(reason+':'+xs.length);const changed=xs[0].getAttribute('aria-selected')!=='true';if(changed)activate(xs[0]);return changed};const mode_mutated=choose(%s,'mode');await new Promise(r=>setTimeout(r,0));const ratio_mutated=choose(%s,'ratio');await new Promise(r=>setTimeout(r,0));const active=value=>tab(value).filter(e=>e.getAttribute('aria-selected')==='true').length===1;const out={media:active(%s),ratio:active(%s),actual_output_count:[1,2,3,4].find(value=>active(String(value)))||null,model:trigger.innerText.trim(),mode_mutated,ratio_mutated};activate(trigger);await new Promise(r=>setTimeout(r,0));out.menu_closed=trigger.getAttribute('aria-expanded')!=='true';return out})()""" % tuple(__import__('json').dumps(value) for value in (token, ratio, token, ratio))
        actual = self.page.evaluate(script)
        if not isinstance(actual, dict) or not all(actual.get(key) for key in ("media", "ratio")):
            raise FlowError("FLOW_UI_CHANGED", f"request settings readback mismatch: {actual}")
        if actual.get("actual_output_count") not in {1, 2, 3, 4}:
            raise FlowError("FLOW_UI_CHANGED", f"request generation-count readback was ambiguous: {actual}")
        if not actual.get("model"): raise FlowError("FLOW_UI_CHANGED", "actual Flow model selector was ambiguous")
        if not actual.pop("menu_closed", False): raise FlowError("FLOW_UI_CHANGED", "Flow settings menu did not close before submit")
        actual.update({"requested_model":resolved.model_preference,"aspect_ratio":resolved.aspect_ratio,"workflow_mode":resolved.workflow_mode,"quality_tier":resolved.quality_tier,"reference_mode":resolved.reference_mode,"duration_seconds":resolved.duration_seconds})
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
        # Flow replaces its upload tile as it finishes decoding. Select the
        # semantic option, not a transient thumbnail node, and wait until the
        # option reports selected before exposing the Add control.
        deadline=time.monotonic()+10; selected=False
        while time.monotonic()<deadline:
            state=self.page.evaluate("""(()=>{const url=%s,alt=%s,d=document.querySelector('[role=dialog]');if(!d)return {state:'DIALOG_MISSING'};const images=Array.from(d.querySelectorAll('img')).filter(e=>e.naturalWidth>=512);const image=images.find(e=>(e.currentSrc||e.src)===url)||images.find(e=>(e.alt||'')===alt);if(!image)return {state:'WAITING_FOR_OPTION'};const option=image.closest('[role=option]');if(!option)return {state:'WAITING_FOR_OPTION'};if(option.getAttribute('aria-selected')!=='true'){(%s)(option);return {state:'SELECTING'}};return {state:'SELECTED'}})()""" % (__import__('json').dumps(matched_url), __import__('json').dumps(matched_alt), _ACTIVATE))
            if isinstance(state,dict) and state.get("state")=="SELECTED":
                selected=True; break
            if isinstance(state,dict) and state.get("state")=="DIALOG_MISSING": break
            time.sleep(.2)
        if not selected: raise FlowError("FLOW_REFERENCE_UPLOAD_FAILED", "matched reference did not become selectable")
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
        self._pre_dispatch_asset_records: list[dict] = []
        self._before_provider_boundary: Callable[[], None] | None = None
        self._generation_count_evidence: dict[tuple[str, ...], dict] = {}
        self._active_request_settings_key: tuple[str, ...] | None = None

    def _generation_count_session_identity(self) -> tuple[str, ...]:
        """Bind setup evidence to the configured Flow project and browser session."""
        if self.runtime is None:
            return ("unbound",)
        return tuple(str(getattr(self.runtime, field, "")) for field in (
            "profile", "cdp_url", "project_url", "project_identity",
        ))

    def _generation_count_key(self, media_type: str, desired_count: int) -> tuple[str, ...]:
        return (*self._generation_count_session_identity(), media_type, str(desired_count))

    def _request_settings_key(self, resolved: ResolvedFlowGenerationSettings) -> tuple[str, ...]:
        return (*self._generation_count_session_identity(), resolved.media_type,
                str(resolved.model_preference), resolved.aspect_ratio, resolved.workflow_mode,
                str(resolved.duration_seconds), str(resolved.reference_mode), resolved.quality_tier)

    def ensure_request_settings(self, dom, resolved: ResolvedFlowGenerationSettings) -> dict | None:
        """Only reopen Flow's settings UI when request semantics actually changed."""
        key = self._request_settings_key(resolved)
        if self._active_request_settings_key == key:
            return None
        settings = dom.apply_request_settings(resolved)
        settings["request_settings_ui_reopened"] = True
        self._active_request_settings_key = key
        return settings

    def record_observed_generation_count(self, media_type: str, actual_count: int,
                                         *, desired_count: int = 1) -> bool:
        """Consume an explicit provider-UI observation without trusting old evidence."""
        key = self._generation_count_key(media_type, desired_count)
        if actual_count != desired_count:
            self._generation_count_evidence.pop(key, None)
            return False
        self._generation_count_evidence[key] = {
            "actual_output_count": actual_count,
            "desired_output_count": desired_count,
            "session_identity": self._generation_count_session_identity(),
        }
        return True

    def ensure_generation_count(self, dom, resolved: ResolvedFlowGenerationSettings) -> dict:
        """Inspect, configure, and verify Flow's count once per proven session setting."""
        media_type, desired_count = resolved.media_type, resolved.output_count
        key = self._generation_count_key(media_type, desired_count)
        evidence = self._generation_count_evidence.get(key)
        if evidence is not None and evidence.get("actual_output_count") == desired_count:
            return {
                "requested_output_count": desired_count,
                "actual_output_count": desired_count,
                "output_count": desired_count,
                "generation_count_preparation": "REUSED_VERIFIED_EVIDENCE",
                # Per-request counters make a live run auditable without
                # mistaking the cached proof for another Flow UI operation.
                "generation_count_setup": {
                    "ui_inspections": 0,
                    "ui_mutations": 0,
                },
            }
        inspection_count = 1
        mutation_count = 0
        actual_count = dom.inspect_generation_count(media_type)
        preparation = "VERIFIED_CURRENT"
        if actual_count != desired_count:
            dom.configure_generation_count(media_type, desired_count)
            mutation_count = 1
            actual_count = dom.inspect_generation_count(media_type)
            inspection_count += 1
            preparation = "CONFIGURED_AND_VERIFIED"
        if actual_count != desired_count:
            raise FlowError("FLOW_GENERATION_COUNT_MISMATCH", "Flow generation-count verification failed")
        self.record_observed_generation_count(media_type, actual_count, desired_count=desired_count)
        return {
            "requested_output_count": desired_count,
            "actual_output_count": actual_count,
            "output_count": desired_count,
            "generation_count_preparation": preparation,
            "generation_count_setup": {
                "ui_inspections": inspection_count,
                "ui_mutations": mutation_count,
            },
        }

    def set_before_provider_boundary(self, callback: Callable[[], None] | None) -> None:
        """Install the service-owned marker invoked immediately before Generate."""
        self._before_provider_boundary = callback

    @staticmethod
    def _fetch_bytes(page, url: str) -> bytes:
        payload = page.evaluate("""(async()=>{const r=await fetch(%s);if(!r.ok)throw Error('fetch');const b=await r.arrayBuffer();let s='';for(const x of new Uint8Array(b))s+=String.fromCharCode(x);return {data:btoa(s),type:r.headers.get('content-type')||''}})()""" % __import__('json').dumps(url))
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), str):
            raise FlowError("ASSET_ACQUISITION_FAILED")
        return base64.b64decode(payload["data"], validate=True)

    def _reset_poll_evidence(self, path: Path) -> None:
        self._poll_timeline = ProviderPollEvidenceTimeline(path)
        self._pre_dispatch_asset_records = []
        self._pre_dispatch_provider_model_tiles: list[dict] = []
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
            "provider_poll_decision_bindings": snapshot["decision_bindings"],
            "provider_poll_authoritative_binding": (
                snapshot["decision_bindings"][-1] if snapshot["decision_bindings"] else None
            ),
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
                "provider_poll_decision_bindings", "provider_poll_authoritative_binding",
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
                     quarantined: list[dict] | None = None,
                     bind_authoritative_output: bool = True) -> dict:
        baseline_projection = _identity_projection(baseline, media_type)
        current_projection = _identity_projection(current, media_type)
        if phase.startswith("PRE_DISPATCH"):
            self._pre_dispatch_asset_records = _merge_surface_records(
                self._pre_dispatch_asset_records, baseline, current,
            )
        elif not self._pre_dispatch_asset_records:
            self._pre_dispatch_asset_records = _merge_surface_records(baseline)
        pre_dispatch_assets = _asset_identity_projection(self._pre_dispatch_asset_records)
        provider_model = _provider_model_projection(surface)
        pre_dispatch_model = list(getattr(self, "_pre_dispatch_provider_model_tiles", []))
        pre_dispatch_model_ids = {item["card_id"] for item in pre_dispatch_model}
        provider_model_delta = (
            [item for item in provider_model if item["card_id"] not in pre_dispatch_model_ids]
            if provider_model is not None else []
        )
        baseline_ids = {item["identity"] for item in baseline_projection}
        delta = [item for item in current_projection if item["identity"] not in baseline_ids]
        candidates = observation.candidate_identities if observation is not None else delta
        raw_terminal_observations = [
            {
                "card_id": record.get("card_id"),
                "provider_job_id": record.get("provider_job_id"),
                "state": record.get("state"),
                "failure_class": record.get("failure_class"),
                "terminal_structural_signals": record.get("terminal_structural_signals"),
                "raw_message": record.get("raw_message"),
                "locale": record.get("locale") or (surface or {}).get("locale"),
            }
            for record in current
            if record.get("failure_class") == "PROVIDER_VISIBLE_TERMINAL_FAILURE"
        ]
        terminal_observations = raw_terminal_observations
        if phase == "POST_DISPATCH":
            historical_card_ids = {
                str(record.get("card_id"))
                for record in self._pre_dispatch_asset_records
                if record.get("card_id")
            }
            historical_job_ids = {
                str(record.get("provider_job_id"))
                for record in self._pre_dispatch_asset_records
                if record.get("provider_job_id")
            }
            terminal_observations = [
                item for item in raw_terminal_observations
                if (
                    (item.get("card_id") or item.get("provider_job_id"))
                    and str(item.get("card_id") or "") not in historical_card_ids
                    and str(item.get("provider_job_id") or "") not in historical_job_ids
                )
            ]
        lineage_card_id = observation.lineage_card_id if observation is not None else None
        durable_job_identity = (
            f"card:{lineage_card_id}" if isinstance(lineage_card_id, str) and lineage_card_id else None
        )
        durable_output_identity = None
        if observation is not None and observation.state == "CONFIRMED" and observation.candidate:
            durable_output_identity = provider_identity(observation.candidate) or None
        # This is raw provider fact only.  A resulting decision is created only
        # after this exact observation is durable and has verified.
        observed_dispatch_state = dispatch.state if dispatch is not None else "NOT_CONFIRMED"
        observed_signal = dispatch.signal if dispatch is not None else None
        observed_signal_state = dispatch.signal_state if dispatch is not None else "NONE"
        value = {
            "phase": phase,
            "provider_surface_fingerprint": surface_fingerprint(records_for_type(current, media_type)),
            "baseline_surface_fingerprint": surface_fingerprint(records_for_type(baseline, media_type)),
            "baseline_identity_set": baseline_projection,
            "current_identity_set": current_projection,
            "identity_delta": delta,
            "pre_dispatch_asset_identity_set": pre_dispatch_assets,
            "pre_dispatch_provider_model_identity_set": pre_dispatch_model,
            "provider_model_identity_set": provider_model or [],
            "provider_model_delta": provider_model_delta,
            "provider_model_complete": provider_model is not None,
            "causal_card_ids": (
                observation.causal_card_ids if observation is not None
                else [item["card_id"] for item in provider_model_delta]
            ),
            "historical_alias_card_ids": (
                observation.historical_alias_card_ids if observation is not None else []
            ),
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
            "dispatch_evidence_state": observed_dispatch_state,
            "dispatch_evidence_signal": observed_signal,
            "dispatch_signal_state": observed_signal_state,
            "durable_dispatch_identity": durable_output_identity or durable_job_identity or (dispatch.durable_identity if dispatch else None),
            "attribution_evidence_state": observation.state if observation is not None else "NOT_ATTEMPTED",
            "lineage_card_id": lineage_card_id,
            "within_group_selection_policy": (
                observation.within_group_selection_policy if observation is not None else None
            ),
            "input_dispatched": bool((activation or {}).get("input_dispatched")),
            "activation_verified": bool((activation or {}).get("activation_verified")),
            "provider_acceptance_transition": bool((activation or {}).get("provider_acceptance_transition")),
            # Raw audit evidence retains every terminal tile visible in this
            # poll, including historical pre-dispatch cards.
            "terminal_observations": raw_terminal_observations,
        }
        persisted = self._poll_timeline.append(value)
        # A dispatch transition may use this poll only after the exact persisted
        # snapshot verifies under the writer's canonical hash contract.
        ProviderPollEvidenceTimeline.verify_snapshot(self._poll_timeline.snapshot())
        binding = None
        if dispatch is not None and dispatch.state != "CONFIRMED":
            if durable_output_identity:
                dispatch.observe(
                    input_dispatched=bool((activation or {}).get("input_dispatched", True)),
                    activation_verified=bool((activation or {}).get("activation_verified")),
                    provider_acceptance_transition=bool((activation or {}).get("provider_acceptance_transition")),
                    attributable_output=True,
                    durable_evidence_serialized=True,
                    evidence_poll_sequence=persisted["poll_sequence"],
                )
                dispatch.durable_identity = durable_output_identity
                dispatch.evidence_poll_sequence = persisted["poll_sequence"]
            elif durable_job_identity:
                dispatch.observe(
                    input_dispatched=bool((activation or {}).get("input_dispatched", True)),
                    activation_verified=bool((activation or {}).get("activation_verified")),
                    provider_acceptance_transition=bool((activation or {}).get("provider_acceptance_transition")),
                    attributable_job=True,
                    durable_job_identity=durable_job_identity,
                    durable_evidence_serialized=True,
                    evidence_poll_sequence=persisted["poll_sequence"],
                )
        # A surface delta is durable observation evidence, not a dispatch
        # decision.  It may be bound only after the causal dispatch rule has
        # actually reached CONFIRMED.  This prevents a late foreign card from
        # becoming a serialized request-acceptance authority.
        if (bind_authoritative_output and dispatch is not None
                and dispatch.state == "CONFIRMED"
                and (durable_output_identity or durable_job_identity)):
            resulting_dispatch_state = dispatch.state if dispatch is not None else "NOT_CONFIRMED"
            resulting_signal = dispatch.signal if dispatch is not None else None
            resulting_signal_state = dispatch.signal_state if dispatch is not None else "NONE"
            durable_identity = durable_output_identity or durable_job_identity
            binding = self._poll_timeline.append_decision_binding(
                persisted,
                dispatch_state=resulting_dispatch_state,
                dispatch_signal=resulting_signal,
                dispatch_signal_state=resulting_signal_state,
                attribution_state=observation.state if observation is not None else "NOT_ATTEMPTED",
                durable_identity=durable_identity,
            )
        self._sync_poll_evidence()
        # These are current-poll convenience projections, never accumulated
        # evidence.  The hash-chained timeline above retains full history.
        self.last_settings["terminal_observations"] = terminal_observations
        self.last_settings["terminal_observation_sources"] = [
            {
                "source_poll_sequence": persisted["poll_sequence"],
                "source_observation_sha256": persisted["observation_sha256"],
                "terminal_observation": dict(item),
            }
            for item in terminal_observations
        ]
        if binding is not None:
            self._sync_bound_decision(binding)
        return persisted

    def _sync_bound_decision(self, binding: dict) -> None:
        """Expose only a decision already bound to a verified raw poll."""
        self.dispatch_confirmed = binding["resulting_dispatch_state"] == "CONFIRMED"
        self.dispatch_confirmation_state = binding["resulting_dispatch_state"]
        self.last_settings.update({
            "dispatch_confirmation_state": binding["resulting_dispatch_state"],
            "dispatch_confirmation_signal": binding["resulting_dispatch_signal"],
            "dispatch_ack_method": binding["resulting_dispatch_signal"],
            "dispatch_signal_state": binding["resulting_dispatch_signal_state"],
            "durable_dispatch_identity": binding["durable_identity_used"],
            "dispatch_evidence_poll_sequence": binding["source_poll_sequence"],
            "attribution_state": binding["resulting_attribution_state"],
            "provider_poll_authoritative_binding": binding,
        })

    def _persist_candidate_observation_before_acquisition(self, *, phase: str, media_type: str,
                                                           baseline: list[dict], current: list[dict], surface: dict,
                                                           observation, dispatch: DispatchEvidenceTracker,
                                                           activation: dict) -> dict:
        """Persist exact candidate evidence without claiming output ownership.

        This is deliberately sufficient to preserve the candidate and keep the
        provider retry barrier closed if byte acquisition fails.  It is not an
        authoritative attribution decision when a later byte-dependent
        exclusion, such as reference-echo detection, remains outstanding.
        """
        persisted = self._record_poll(
            phase=phase, media_type=media_type, baseline=baseline, current=current,
            surface=surface, stable_polls=observation.stable_polls,
            observation=observation, dispatch=dispatch, activation=activation,
            bind_authoritative_output=False,
        )
        self._record_observation(observation)
        self._sync_dispatch_state(dispatch)
        self.last_settings.pop("attributed_provider_identity", None)
        self.last_settings.pop("attribution_confirmation_timestamp", None)
        self.last_settings.update({
            "candidate_observation_state": "DURABLE_OBSERVED",
            "candidate_acquisition_state": "PENDING",
            "durable_candidate_identity": evidence_identity(observation.candidate),
            "candidate_observed_poll_sequence": persisted["poll_sequence"],
            "attribution_state": "PENDING",
            # Do not expose an older dispatch-only decision binding as the
            # authority for this unexcluded candidate.
            "provider_poll_authoritative_binding": None,
        })
        return persisted

    def _confirm_candidate_attribution_after_required_exclusions(self, *, persisted: dict,
                                                                  observation,
                                                                  dispatch: DispatchEvidenceTracker) -> None:
        """Bind CONFIRMED only after every required exclusion has passed."""
        if dispatch.state != "CONFIRMED":
            raise FlowError(
                "FLOW_DISPATCH_UNCERTAIN",
                "candidate observation cannot establish attribution before causal dispatch confirmation",
            )
        durable_identity = provider_identity(observation.candidate) or None
        binding = self._poll_timeline.append_decision_binding(
            persisted,
            dispatch_state=dispatch.state,
            dispatch_signal=dispatch.signal,
            dispatch_signal_state=dispatch.signal_state,
            attribution_state="CONFIRMED",
            durable_identity=durable_identity,
        )
        self._sync_poll_evidence()
        self._sync_bound_decision(binding)
        self.last_settings.update({
            "candidate_acquisition_state": "RESOLVED",
            "attribution_method": observation.method,
            "attribution_method_version": ATTRIBUTION_METHOD_VERSION,
            "attributed_provider_identity": evidence_identity(observation.candidate),
            "candidate_delta_count": observation.candidate_delta_count,
            "candidate_identities": observation.candidate_identities,
            "attribution_confirmation_timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def _quarantine_reference_echo_candidate(self, *, phase: str, media_type: str,
                                              baseline: list[dict], current: list[dict], surface: dict,
                                              observation, dispatch: DispatchEvidenceTracker,
                                              activation: dict) -> list[dict]:
        """Persist a byte-proven input echo without confirming provider ownership."""
        quarantined = [{**evidence_identity(observation.candidate), "reason": "REFERENCE_INPUT_ECHO"}]
        self._record_poll(
            phase=phase, media_type=media_type, baseline=baseline, current=current,
            surface=surface, stable_polls=observation.stable_polls,
            observation=observation, dispatch=dispatch, activation=activation,
            quarantined=quarantined, bind_authoritative_output=False,
        )
        self._record_observation(observation)
        self._sync_dispatch_state(dispatch)
        self.last_settings.pop("attributed_provider_identity", None)
        self.last_settings.pop("attribution_confirmation_timestamp", None)
        self.last_settings.update({
            "candidate_observation_state": "QUARANTINED_REFERENCE_INPUT_ECHO",
            "candidate_acquisition_state": "RESOLVED",
            "attribution_state": "PENDING",
            "provider_poll_authoritative_binding": None,
        })
        self.last_settings.setdefault("quarantined_foreign_identities", []).extend(quarantined)
        return quarantined

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
            "causal_card_ids": observation.causal_card_ids,
            "within_group_selection_policy": observation.within_group_selection_policy,
            "historical_alias_card_ids": observation.historical_alias_card_ids,
        })
        if observation.lineage_card_id:
            self.last_settings["provider_lineage_card_id"] = observation.lineage_card_id

    def _sync_dispatch_state(self, dispatch: DispatchEvidenceTracker) -> None:
        # Runtime state is diagnostic until _record_poll has persisted a binding.
        # Do not let an unbound transition become authoritative in settings.
        binding = self.last_settings.get("provider_poll_authoritative_binding") if isinstance(self.last_settings, dict) else None
        if isinstance(binding, dict):
            return
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
                candidate_is_echo = self._is_reference_input_echo(
                    self._fetch_bytes(page, record["url"]), reference_hashes,
                )
            except Exception:
                continue
            if candidate_is_echo:
                echoes.append(record)
        return echoes

    @staticmethod
    def _is_reference_input_echo(data: bytes, reference_hashes: list[str]) -> bool:
        """Return whether bytes match an attached input closely enough to exclude."""
        candidate_hash = _dhash_bytes(data)
        return any((int(candidate_hash, 16) ^ int(reference_hash, 16)).bit_count() <= 4
                   for reference_hash in reference_hashes)

    def __call__(self, request, references, destination: Path):
        # The generator is reused across a batch. Dispatch and attribution
        # evidence are request-local and must never leak from a prior attempt.
        self.dispatch_confirmed = False
        self.dispatch_confirmation_state = "NOT_ATTEMPTED"
        self.last_settings = {}
        self._reset_poll_evidence(destination.parent / "provider_poll_evidence.json")
        page = CdpPage.open(self.runtime)
        page.enable_pre_dispatch_reconnect()
        try:
            dom = FlowBrowserDom(page)
            identity_history = request.get("_flow_provider_identity_history", [])
            history_seed = identity_history if isinstance(identity_history, list) else []
            provider_model_samples: list[list[dict] | None] = []

            def discovery_observer(surface, records, stable):
                model = _provider_model_projection(surface)
                provider_model_samples.append(model)
                self._record_poll(
                    phase="PRE_DISPATCH_DISCOVERY", media_type=request["media_type"],
                    baseline=history_seed, current=records, surface=surface,
                    stable_polls=stable,
                )

            try:
                historical_records, _ = _stable_surface(
                    dom, request["media_type"],
                    seed=history_seed,
                    capacity_guard=self._ensure_poll_capacity,
                    poll_observer=discovery_observer,
                )
                consecutive = provider_model_samples[-3:]
                if len(consecutive) != 3 or any(sample is None for sample in consecutive):
                    raise FlowError(
                        "OUTPUT_ATTRIBUTION_NOT_QUIESCENT",
                        "complete Flow provider model was unavailable or unstable before Generate",
                    )
                model_id_sets = [tuple(item["card_id"] for item in (sample or []))
                                 for sample in consecutive]
                if len(set(model_id_sets)) != 1:
                    raise FlowError(
                        "OUTPUT_ATTRIBUTION_NOT_QUIESCENT",
                        "complete Flow provider model was unavailable or unstable before Generate",
                    )
                self._pre_dispatch_provider_model_tiles = list(consecutive[-1] or [])
                self.last_settings.update({
                    "pre_dispatch_provider_model_identity_set": list(consecutive[-1] or []),
                    "pre_dispatch_provider_model_stable_polls": 3,
                    "causal_anchor": "COMPLETE_PROVIDER_MODEL_CARD_ID_DELTA",
                })
            except FlowError as error:
                if error.failure_class == "OUTPUT_ATTRIBUTION_NOT_QUIESCENT":
                    # The baseline gate runs before the composer/activation path.
                    # Persist that positive no-dispatch proof; the error name alone
                    # must never make a later retry safe.
                    self.dispatch_confirmation_state = "PRE_DISPATCH_FAILURE"
                    self.last_settings.update({
                        "activation": {"input_dispatched": False,
                                       "proof": "PRE_DISPATCH_BASELINE_NOT_QUIESCENT"},
                        "dispatch_confirmation_state": "PRE_DISPATCH_FAILURE",
                        "dispatch_confirmation_signal": "pre_dispatch_baseline_not_quiescent",
                        "provider_job_id": None,
                        "attribution_state": "NOT_ATTEMPTED",
                    })
                raise
            dom.reset_composer()
            resolved = resolve_settings(request)
            generation_count = self.ensure_generation_count(dom, resolved)
            request_settings = self.ensure_request_settings(dom, resolved) or {}
            if request_settings:
                observed_count = request_settings.pop("actual_output_count")
                # This readback is already available while applying the request's
                # mode/ratio.  A provider-side reset invalidates evidence and
                # requires one fresh configure-and-verify pass before Generate.
                if not self.record_observed_generation_count(
                        resolved.media_type, observed_count, desired_count=resolved.output_count):
                    generation_count = self.ensure_generation_count(dom, resolved)
            self.last_settings.update(request_settings)
            self.last_settings.update(generation_count)
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
                    # From this point FlowComposer may type or activate a
                    # control.  A timeout must remain fail-closed; only the
                    # preceding provider-free surface/setup operations may be
                    # repeated on a fresh CDP connection.
                    page.disable_pre_dispatch_reconnect()
                    submit = FlowComposer(dom).submit(
                        request["prompt"], references=staged_references,
                        media_type=request["media_type"], before_dispatch=baseline,
                        before_generate=self._before_provider_boundary,
                        mode_already_configured=True,
                    )
                except (FlowError, FlowSessionError) as error:
                    composer = getattr(dom, "last_composer_ready_state", None)
                    activation = getattr(dom, "last_activation_receipt", None)
                    if isinstance(composer, dict):
                        self.last_settings["composer_ready_state"] = composer
                    if isinstance(activation, dict):
                        self.last_settings["activation"] = activation
                    elif error.failure_class != "FLOW_DISPATCH_UNCERTAIN":
                        self.last_settings["activation"] = {
                            "input_dispatched": False,
                            "proof": "PRE_DISPATCH_COMPOSER_FAILURE",
                        }
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
                activation_verified=bool(activation.get("activation_verified")),
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
            last_surface: dict = {}
            last_current: list[dict] = []
            last_causal_card_ids: set[str] = set()
            while time.monotonic() < deadline:
                self._ensure_poll_capacity()
                states = page.evaluate(_EDITOR_JS) or []
                prompt_transition = len(states) == 0 or all(
                    item.get("text", "") != request["prompt"] for item in states
                )
                if prompt_transition:
                    self.last_settings["composer_transition_seen"] = True
                    activation["provider_acceptance_transition"] = True
                    dispatch.observe(
                        input_dispatched=bool(activation.get("input_dispatched")),
                        trusted_click_seen=bool(activation.get("trusted_click_seen")),
                        activation_verified=bool(activation.get("activation_verified")),
                        provider_acceptance_transition=True,
                        prompt_transition=True,
                    )
                surface = dom.provider_surface()
                current = surface.get("records", []) if isinstance(surface, dict) else []
                provider_model = _provider_model_projection(surface)
                pre_dispatch_model_ids = {
                    item["card_id"] for item in self._pre_dispatch_provider_model_tiles
                }
                causal_card_ids = {
                    item["card_id"] for item in (provider_model or [])
                    if item["card_id"] not in pre_dispatch_model_ids
                }
                last_surface = surface if isinstance(surface, dict) else {}
                last_current = current
                last_causal_card_ids = causal_card_ids
                observation = attribution.observe(
                    current,
                    provider_busy=bool(int((surface or {}).get("global_pending_count", 0))),
                    causal_card_ids=causal_card_ids,
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
                    persisted = self._persist_candidate_observation_before_acquisition(
                        phase="POST_DISPATCH", media_type=request["media_type"],
                        baseline=baseline_records, current=current, surface=surface,
                        observation=observation, dispatch=dispatch, activation=activation,
                    )
                    if dispatch.state != "CONFIRMED":
                        # Preserve the candidate as provider-surface activity,
                        # but do not fetch, attribute, or promote it while the
                        # activation/acceptance chain remains unproven.
                        self._record_observation(observation)
                        self._sync_dispatch_state(dispatch)
                        self.last_settings.update({
                            "candidate_acquisition_state": "BLOCKED_PENDING_CAUSAL_DISPATCH",
                            "attribution_state": "UNCERTAIN",
                        })
                        time.sleep(.5)
                        continue
                    if request["media_type"] == "IMAGE" and reference_hashes:
                        data = self._fetch_bytes(page, candidate["url"])
                        if self._is_reference_input_echo(data, reference_hashes):
                            self._quarantine_reference_echo_candidate(
                                phase="POST_DISPATCH", media_type=request["media_type"],
                                baseline=baseline_records, current=current, surface=surface,
                                observation=observation, dispatch=dispatch, activation=activation,
                            )
                            baseline_records = _merge_surface_records(baseline_records, [candidate])
                            attribution = RequestAttributionTracker(
                                baseline_records, media_type=request["media_type"],
                                expected_count=resolved.output_count,
                            )
                            time.sleep(.5)
                            continue
                    else:
                        data = None
                    self._confirm_candidate_attribution_after_required_exclusions(
                        persisted=persisted, observation=observation, dispatch=dispatch,
                    )
                    if data is None:
                        data = self._fetch_bytes(page, candidate["url"])
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
                if self.last_settings.get("terminal_observations"):
                    raise FlowError(
                        "PROVIDER_VISIBLE_TERMINAL_FAILURE",
                        "Flow exposed a structurally terminal provider tile",
                    )
                time.sleep(.5)

            self.dispatch_confirmation_state = dispatch.state
            final_observation = attribution.observe(
                last_current, causal_card_ids=last_causal_card_ids,
                causal_anchor_final=True,
            )
            if final_observation.state == "AMBIGUOUS":
                self._record_poll(
                    phase="POST_DISPATCH", media_type=request["media_type"],
                    baseline=baseline_records, current=last_current,
                    surface=last_surface, stable_polls=final_observation.stable_polls,
                    observation=final_observation, dispatch=dispatch,
                    activation=activation,
                )
                self._record_observation(final_observation)
                self._sync_dispatch_state(dispatch)
                raise FlowError(
                    "OUTPUT_ATTRIBUTION_AMBIGUOUS",
                    "no complete causal provider-model card delta was proven after Generate",
                )
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
                self.last_settings["cdp_transport"] = page.transport_diagnostics()
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
            verified_binding = ProviderPollEvidenceTimeline.verify_authoritative_binding(verified_evidence)
        except FlowError as error:
            # Never reuse a baseline, durable dispatch identity, or attribution
            # detail from evidence that cannot verify exactly as persisted.
            return {"state": "REMAINS_AMBIGUOUS", "evidence": {"reason": error.failure_class}}
        if verified_binding.get("resulting_dispatch_state") != "CONFIRMED":
            return {"state": "REMAINS_AMBIGUOUS", "evidence": {"reason": "FLOW_POLL_EVIDENCE_INVALID"}}
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
        prior_durable_identity = verified_binding.get("durable_identity_used")
        if attempt.get("dispatch_confirmed") is True and isinstance(prior_durable_identity, str) and prior_durable_identity:
            dispatch.restore_verified_confirmation(prior_durable_identity)
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
                    persisted = self._persist_candidate_observation_before_acquisition(
                        phase="RECONCILIATION", media_type=request["media_type"],
                        baseline=baseline, current=records, surface=surface,
                        observation=last, dispatch=dispatch, activation=activation,
                    )
                    if request["media_type"] == "IMAGE" and reference_hashes:
                        data = self._fetch_bytes(page, last.candidate["url"])
                        if self._is_reference_input_echo(data, reference_hashes):
                            self._quarantine_reference_echo_candidate(
                                phase="RECONCILIATION", media_type=request["media_type"],
                                baseline=baseline, current=records, surface=surface,
                                observation=last, dispatch=dispatch, activation=activation,
                            )
                            baseline = _merge_surface_records(baseline, [last.candidate])
                            tracker = RequestAttributionTracker(
                                baseline, media_type=request["media_type"],
                                expected_count=int(request.get("output_count", 1)),
                            )
                            time.sleep(.5)
                            continue
                    else:
                        data = None
                    self._confirm_candidate_attribution_after_required_exclusions(
                        persisted=persisted, observation=last, dispatch=dispatch,
                    )
                    if data is None:
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

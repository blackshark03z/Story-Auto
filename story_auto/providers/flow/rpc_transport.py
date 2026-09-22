"""Opt-in Flow RPC transport. Journals uncertainty before every remote write.

This candidate uses the normal authenticated browser session; it never exports
cookies, bypasses interactive challenges or retries a generation POST.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import time
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from story_auto.core.artifacts import atomic_write_bytes, atomic_write_json, sha256_file
from . import rpc_contract as contract
from .validation import validate_video

JOURNAL_NAME = "flow_rpc_attempt.json"
TRANSPORT = "flow-batchexecute/1.0.0"
ORIGIN = "https://flow.google.com"
SITE_KEY = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"


class RpcError(RuntimeError):
    def __init__(self, code):
        self.code = code
        self.failure_class = code
        super().__init__(code)


def enabled(runtime):
    return (os.getenv("STORY_AUTO_FLOW_RPC_EXPERIMENTAL") == "1"
            and os.getenv("STORY_AUTO_FLOW_RPC_PROJECT") == runtime.project_identity)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def submission_diagnostic(response):
    """Type/count evidence only; never authorization to retry or acceptance proof."""
    if not isinstance(response, str):
        return {"classification": "NO_WIRE_RESPONSE"}
    try:
        payload = contract.parse_rpc(response, contract.RPC_VIDEO)
    except Exception:
        return {"classification": "UNPARSEABLE_RESPONSE"}
    counts = dict(null=0, boolean=0, number=0, string=0, array=0, object=0)
    stack, visited = [payload], 0
    while stack and visited < 2048:
        node = stack.pop()
        visited += 1
        if node is None: counts['null'] += 1
        elif isinstance(node, bool): counts['boolean'] += 1
        elif isinstance(node, (int, float)): counts['number'] += 1
        elif isinstance(node, str): counts['string'] += 1
        elif isinstance(node, list):
            counts['array'] += 1
            stack.extend(node[:2048])
        elif isinstance(node, dict):
            counts['object'] += 1
            stack.extend(list(node.values())[:2048])
    return {"classification": "PARSED_NOT_ACCEPTANCE_PROOF", "type_counts": counts,
            "truncated": bool(stack)}


def seal(value):
    plain = {k: v for k, v in value.items() if k != "seal"}
    return {**plain, "seal": digest(plain)}


def verify(value):
    if not isinstance(value, dict) or seal(value) != value:
        raise RpcError("FLOW_RPC_JOURNAL_INVALID")
    return value


def identity(runtime, request, references):
    return {
        "project": runtime.project_identity, "project_url": runtime.project_url,
        "profile": str(Path(runtime.profile).resolve()), "cdp_url": runtime.cdp_url,
        "request_id": request.get("request_id"),
        "request_sha256": digest({k: v for k, v in request.items() if not k.startswith("_")}),
        "references": [sha256_file(Path(p)) for p in references],
    }


def validate_intent(request, references):
    if (request.get("media_type") != "VIDEO" or len(references) != 1
            or request.get("aspect_ratio", "16:9") != "16:9"
            or request.get("output_count", 1) != 1
            or request.get("target_duration") != 8
            or request.get("model_override") not in {None, "abra_r2v_8s"}
            or not isinstance(request.get("prompt"), str) or not request["prompt"].strip()):
        raise RpcError("FLOW_RPC_CAPABILITY_UNSUPPORTED")
    reference = Path(references[0])
    if reference.stat().st_size > 20 * 1024 * 1024:
        raise RpcError("FLOW_RPC_REFERENCE_TOO_LARGE")
    from PIL import Image
    with Image.open(reference) as image:
        if image.format != "PNG":
            raise RpcError("FLOW_RPC_REFERENCE_PNG_REQUIRED")
        image.verify()


class BrowserRpcSession:
    """One short controller attachment; the owner browser remains running."""
    def __init__(self, runtime):
        self.runtime = runtime

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        try:
            browser = self.pw.chromium.connect_over_cdp(self.runtime.cdp_url, timeout=8000)
            pages = [p for c in browser.contexts for p in c.pages
                     if p.url.rstrip("/") == self.runtime.project_url.rstrip("/")]
            if len(pages) != 1:
                raise RpcError("FLOW_RPC_PROJECT_TAB_NOT_UNIQUE")
            self.page = pages[0]
            self.meta()
            return self
        except Exception:
            self.pw.stop()
            raise RpcError("FLOW_RPC_SESSION_UNAVAILABLE") from None

    def __exit__(self, *args):
        self.pw.stop()  # Detach driver, never close the owner browser.

    def meta(self):
        value = self.page.evaluate("""() => {const w=globalThis.WIZ_global_data||{};return {
            host:location.host,source:location.pathname,at:w.SNlM0e||'',sid:w.FdrFJe||'',bl:w.cfb2h||'',
            hl:(document.documentElement.lang||'en').split('-')[0],
            captcha:!!(globalThis.grecaptcha?.enterprise?.execute)}}""")
        contract.validate_session(value, self.runtime.project_identity)
        return value

    def captcha(self, action):
        self.meta()
        token = self.page.evaluate("async x => await grecaptcha.enterprise.execute(x.key,{action:x.action})",
                                   {"key": SITE_KEY, "action": action})
        if not isinstance(token, str) or len(token) < 500:
            raise RpcError("FLOW_RPC_REAUTH_REQUIRED")
        return token

    def rpc(self, rpcid, body):
        meta = self.meta()
        query = urlencode({"rpcids": rpcid, "source-path": meta["source"], "bl": meta["bl"],
                           "f.sid": meta["sid"], "hl": meta["hl"], "rt": "c"})
        response = self.page.context.request.post(ORIGIN + "/_/AiSandboxAngularFrontend/data/batchexecute?" + query,
            data=urlencode({"f.req": body, "at": meta["at"]}),
            headers={"content-type": "application/x-www-form-urlencoded;charset=UTF-8",
                     "x-same-domain": "1", "origin": ORIGIN, "referer": self.runtime.project_url},
            timeout=60000, max_redirects=0, max_retries=0)
        try:
            if response.status != 200:
                raise RpcError("FLOW_RPC_HTTP_FAILED")
            text = response.text()
            if len(text.encode()) > 8 * 1024 * 1024:
                raise RpcError("FLOW_RPC_RESPONSE_TOO_LARGE")
            contract.parse_rpc(text, rpcid)
            return text
        finally:
            response.dispose()

    def catalog(self):
        records = contract.catalog_records(self.rpc("Zzl0ze", contract.build_catalog(self.runtime.project_identity)), self.runtime.project_identity)
        self.observed_fingerprint = contract.validate_catalog_baseline(self.meta(), records, self.runtime.project_identity)
        return records

    def media(self, media_id, kind):
        payload = contract.parse_rpc(self.rpc("as29s", contract.build_media(media_id)), "as29s")
        stack, urls = [payload], set()
        while stack:
            value = stack.pop()
            if isinstance(value, list): stack.extend(value)
            elif isinstance(value, dict): stack.extend(value.values())
            elif isinstance(value, str) and value.startswith("https://"):
                parsed = urlsplit(value)
                if parsed.hostname == "flow-content.google" and parsed.path.startswith(f"/{kind}/"):
                    urls.add(value)
        if not urls:
            return None
        if len(urls) != 1:
            raise RpcError("FLOW_RPC_MEDIA_AMBIGUOUS")
        response = self.page.context.request.get(next(iter(urls)), timeout=60000, max_redirects=0, max_retries=0)
        try:
            if response.status != 200:
                raise RpcError("FLOW_RPC_MEDIA_UNAVAILABLE")
            if int(response.headers.get("content-length", "0")) > 256 * 1024 * 1024:
                raise RpcError("FLOW_RPC_MEDIA_TOO_LARGE")
            data = response.body()
            if not data or len(data) > 256 * 1024 * 1024:
                raise RpcError("FLOW_RPC_MEDIA_INVALID")
            return data
        finally:
            response.dispose()

    def upload(self, path, attempt_id):
        text = self.rpc("maseQ", contract.build_upload(self.runtime.project_identity, Path(path).read_bytes(),
                            self.captcha("IMAGE_GENERATION"), attempt_id))
        payload = contract.parse_rpc(text, "maseQ")
        try:
            media_id = payload[0][0]
            from uuid import UUID
            UUID(media_id)
        except Exception:
            raise RpcError("FLOW_RPC_UPLOAD_ID_INVALID") from None
        returned = self.media(media_id, "image")
        from PIL import Image, ImageChops, ImageStat
        with Image.open(path) as source, Image.open(io.BytesIO(returned or b"")) as observed:
            left = source.convert("RGB").resize((64, 64))
            right = observed.convert("RGB").resize((64, 64))
            if max(ImageStat.Stat(ImageChops.difference(left, right)).mean) > 8:
                raise RpcError("FLOW_RPC_UPLOAD_READBACK_MISMATCH")
        return media_id

    def submit(self, prompt, reference, attempt_id):
        return self.rpc("MZZa6b", contract.build_video(self.runtime.project_identity, prompt, reference,
                            self.captcha("VIDEO_GENERATION"), attempt_id))


class FlowRpcGenerator:
    def __init__(self, runtime, *, session_factory=BrowserRpcSession, timeout_seconds=120):
        self.runtime, self.session_factory = runtime, session_factory
        self.timeout_seconds = timeout_seconds
        self.last_settings = {"transport": TRANSPORT}
        self.dispatch_confirmed = False
        self.dispatch_confirmation_state = "NOT_ATTEMPTED"

    def _save(self, path, journal):
        journal = seal(journal)
        atomic_write_json(path, journal)
        return journal

    def run(self, request, references, destination, *, before_boundary=None, recovery_only=False):
        destination = Path(destination)
        path = destination.parent / JOURNAL_NAME
        try:
            validate_intent(request, references)
            bound = identity(self.runtime, request, references)
            session_binding = getattr(self.session_factory, 'binding', None)
            if session_binding is not None:
                bound['session_binding'] = dict(session_binding)
            bound["attempt_directory"] = str(destination.parent.resolve())
            if path.exists():
                journal = verify(json.loads(path.read_text(encoding="utf-8")))
                if journal.get("identity") != bound:
                    raise RpcError("FLOW_RPC_REQUEST_MISMATCH")
            else:
                if recovery_only:
                    raise RpcError("FLOW_RPC_JOURNAL_MISSING")
                attempt_id = str(uuid4())
                journal = self._save(path, {"transport": TRANSPORT, "identity": bound, "attempt_id": attempt_id,
                    "marker": f"[STORYAUTO-{attempt_id}]", "state": "PREPARING", "upload_attempts": 0,
                    "submit_attempts": 0, "reference_id": None, "output_id": None})
            prompt = request["prompt"].strip() + "\n" + journal["marker"]
            with self.session_factory(self.runtime) as session:
                records = session.catalog()  # Strict drift validation before upload or submit.
                journal["observed_fingerprint"] = getattr(session, "observed_fingerprint", None)
                journal = self._save(path, journal)
                if not journal["reference_id"]:
                    if journal["upload_attempts"] or recovery_only:
                        raise RpcError("FLOW_RPC_UPLOAD_UNCERTAIN")
                    journal.update(state="UPLOADING", upload_attempts=1)
                    journal = self._save(path, journal)
                    reference_id = session.upload(references[0], journal["attempt_id"])
                    journal.update(state="PREPARED", reference_id=reference_id)
                    journal = self._save(path, journal)
                if not journal["submit_attempts"]:
                    if recovery_only:
                        raise RpcError("FLOW_RPC_NOT_SUBMITTED")
                    if contract.match_output(records, self.runtime.project_identity, prompt, journal["reference_id"]):
                        raise RpcError("FLOW_RPC_BASELINE_COLLISION")
                    journal.update(state="SUBMITTING", submit_attempts=1)
                    journal = self._save(path, journal)
                    if not callable(before_boundary):
                        raise RpcError("FLOW_RPC_BOUNDARY_CALLBACK_REQUIRED")
                    before_boundary()
                    response = session.submit(prompt, journal["reference_id"], journal["attempt_id"])
                    journal['submission_diagnostic'] = submission_diagnostic(response)
                    # HTTP 200 is only an acknowledgement; catalog proves acceptance.
                    journal.update(state="RECONCILING")
                    journal = self._save(path, journal)
                deadline = time.monotonic() + self.timeout_seconds
                while True:
                    record = contract.match_output(session.catalog(), self.runtime.project_identity, prompt, journal["reference_id"])
                    if record is not None:
                        prior = request.get("_flow_provider_identity_history", [])
                        if any(isinstance(item, dict) and record[0] in {
                                item.get("identity"), item.get("asset_id"), item.get("card_id")}
                               for item in prior):
                            raise RpcError("FLOW_RPC_OUTPUT_ALREADY_OWNED")
                        if journal["output_id"] not in {None, record[0]}:
                            raise RpcError("FLOW_RPC_OUTPUT_CHANGED")
                        journal.update(state="OUTPUT_IDENTIFIED", output_id=record[0])
                        journal = self._save(path, journal)
                        payload = session.media(record[0], "video")
                        if payload:
                            if destination.exists():
                                if sha256_file(destination) != hashlib.sha256(payload).hexdigest():
                                    raise RpcError("FLOW_RPC_DESTINATION_CONFLICT")
                            else:
                                atomic_write_bytes(destination, payload)
                            metadata = validate_video(destination)
                            if abs(metadata["duration_seconds"] - 8) > .15 or abs(metadata["width"] / metadata["height"] - 16/9) > .03:
                                raise RpcError("FLOW_RPC_OUTPUT_SEMANTICS_MISMATCH")
                            journal.update(state="ACQUIRED", output_sha256=metadata["sha256"])
                            journal = self._save(path, journal)
                            self.dispatch_confirmed = True
                            self.dispatch_confirmation_state = "CONFIRMED"
                            self.last_settings = proof_settings(journal)
                            return destination
                    if time.monotonic() >= deadline:
                        raise RpcError("FLOW_RPC_OUTPUT_PENDING")
                    time.sleep(2)
        except Exception as error:
            self.last_settings = {"transport": TRANSPORT, "dispatch_confirmation_state": "UNCERTAIN",
                                  "attribution_state": "UNCONFIRMED"}
            from .service import FlowError
            code = getattr(error, "code", "FLOW_RPC_UNAVAILABLE")
            # No transport error after possible submit can grant a retry.
            raise FlowError("FLOW_DISPATCH_UNCERTAIN", str(code)) from None


def proof_settings(journal):
    verify(journal)
    return {"transport": TRANSPORT, "rpc_receipt": journal,
            "dispatch_confirmation_state": "CONFIRMED", "dispatch_confirmation_signal": "rpc_catalog_exact_prompt_reference",
            "attribution_state": "CONFIRMED", "attribution_method": "rpc_catalog_exact_prompt_reference",
            "attribution_method_version": TRANSPORT, "attributed_provider_identity": {"identity": journal["output_id"]},
            "candidate_delta_count": 1, "candidate_acquisition_state": "RESOLVED"}


def verify_attribution(settings):
    journal = verify(settings.get("rpc_receipt"))
    if (journal.get("transport") != TRANSPORT or journal.get("state") != "ACQUIRED"
            or journal.get("submit_attempts") != 1 or not journal.get("output_id")
            or not journal.get("output_sha256")
            or settings.get("attributed_provider_identity") != {"identity": journal["output_id"]}):
        raise RpcError("FLOW_RPC_ATTRIBUTION_INVALID")
    return journal

"""Experimental passive decoder for the observed Flow video response model.

The decoder consumes responses initiated by the normal Flow UI. It never
constructs or replays an RPC and does not assign undocumented semantics such as
"job id" to the two provider UUID components. Unknown or colliding shapes fail
closed.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from urllib.parse import urlsplit

from .session import FlowRuntime, FlowSessionError


MAX_RESPONSE_BODY_BYTES = 4 * 1024 * 1024
MAX_DECODE_DEPTH = 8
MAX_DECODE_NODES = 80_000
MAX_OBSERVED_RESPONSES = 240
RESPONSE_MODEL_VERSION = "flow-observed-video-response-model/0.1.0"


class FlowResponseModelError(ValueError):
    """The passive response evidence cannot produce one exact identity."""


@dataclass(frozen=True)
class FlowObservedIdentity:
    component_1: str
    project_identity: str
    component_3: str

    @property
    def identity(self) -> str:
        return f"response-tuple:{self.component_1}:{self.project_identity}:{self.component_3}"


def _is_uuid(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 36:
        return False
    groups = value.split("-")
    if [len(group) for group in groups] != [8, 4, 4, 4, 12]:
        return False
    return all(character in "0123456789abcdefABCDEF" for group in groups for character in group)


def _media_token(url: object) -> str | None:
    if not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or "/asb/" not in parsed.path:
        return None
    token = parsed.path.rsplit("/", 1)[-1]
    return token if len(token) >= 24 else None


class FlowResponseModelDecoder:
    """Accumulate bounded token -> observed identity mappings from UI responses."""

    def __init__(self, project_identity: str):
        if not _is_uuid(project_identity):
            raise ValueError("Flow project identity must be a UUID")
        self.project_identity = project_identity.lower()
        self._token_identities: dict[str, set[FlowObservedIdentity]] = {}
        self.observed_response_count = 0

    @staticmethod
    def _decoded(value, *, depth: int, budget: list[int]):
        budget[0] += 1
        if budget[0] > MAX_DECODE_NODES:
            raise FlowResponseModelError("FLOW_RESPONSE_MODEL_LIMIT_EXCEEDED")
        if depth > MAX_DECODE_DEPTH:
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith(("[", "{")):
                try:
                    nested = json.loads(stripped)
                except (TypeError, ValueError):
                    return value
                return FlowResponseModelDecoder._decoded(
                    nested, depth=depth + 1, budget=budget,
                )
            return value
        if isinstance(value, list):
            return [
                FlowResponseModelDecoder._decoded(item, depth=depth + 1, budget=budget)
                for item in value
            ]
        if isinstance(value, dict):
            return {
                key: FlowResponseModelDecoder._decoded(
                    item, depth=depth + 1, budget=budget,
                )
                for key, item in value.items()
            }
        return value

    @staticmethod
    def _walk(value):
        yield value
        if isinstance(value, list):
            for item in value:
                yield from FlowResponseModelDecoder._walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                yield from FlowResponseModelDecoder._walk(item)

    def observe_body(self, body: str) -> int:
        if not isinstance(body, str):
            raise TypeError("Flow response body must be text")
        if len(body.encode("utf-8")) > MAX_RESPONSE_BODY_BYTES:
            raise FlowResponseModelError("FLOW_RESPONSE_MODEL_LIMIT_EXCEEDED")
        if self.observed_response_count >= MAX_OBSERVED_RESPONSES:
            raise FlowResponseModelError("FLOW_RESPONSE_MODEL_LIMIT_EXCEEDED")
        staged: dict[str, set[FlowObservedIdentity]] = {}
        budget = [0]
        for line in body.splitlines():
            if not line.startswith(("[", "{")):
                continue
            try:
                frame = self._decoded(json.loads(line), depth=0, budget=budget)
            except (TypeError, ValueError) as error:
                if isinstance(error, FlowResponseModelError):
                    raise
                continue
            for value in self._walk(frame):
                if (
                    not isinstance(value, list)
                    or len(value) not in {7, 8}
                    or not all(_is_uuid(item) for item in value[:3])
                    or value[1].lower() != self.project_identity
                ):
                    continue
                identity = FlowObservedIdentity(
                    value[0].lower(), value[1].lower(), value[2].lower(),
                )
                tokens = {
                    token
                    for item in self._walk(value)
                    if (token := _media_token(item)) is not None
                }
                for token in tokens:
                    staged.setdefault(token, set()).add(identity)
        for token, identities in staged.items():
            self._token_identities.setdefault(token, set()).update(identities)
        self.observed_response_count += 1
        return sum(len(identities) for identities in staged.values())

    def resolve_url(self, url: str) -> FlowObservedIdentity | None:
        token = _media_token(url)
        if token is None:
            return None
        identities = self._token_identities.get(token, set())
        if len(identities) > 1:
            raise FlowResponseModelError("FLOW_RESPONSE_IDENTITY_AMBIGUOUS")
        return next(iter(identities)) if identities else None

    def resolve_urls(self, urls: list[str]) -> list[FlowObservedIdentity | None]:
        return [self.resolve_url(url) for url in urls]

    def identities(self) -> set[FlowObservedIdentity]:
        return {
            identity
            for identities in self._token_identities.values()
            for identity in identities
        }


class FlowPassiveResponseObserver:
    """Listen to normal same-project UI responses on an existing Flow tab.

    Raw bodies live only in the Playwright callback long enough to update the
    bounded decoder. Snapshot consumers receive structured identity only.
    """

    def __init__(self, runtime: FlowRuntime):
        self.runtime = runtime
        self.decoder = FlowResponseModelDecoder(runtime.project_identity)
        self._lock = threading.RLock()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._failure_class: str | None = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.close()

    def start(self, *, timeout_seconds: float = 12) -> None:
        if self._thread is not None:
            raise RuntimeError("Flow passive observer already started")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout_seconds):
            self.close()
            raise FlowSessionError(
                "FLOW_PASSIVE_OBSERVER_UNAVAILABLE", "Flow response observer did not start",
            )
        if self._failure_class:
            self.close()
            raise FlowSessionError(
                self._failure_class, "Flow response observer could not attach",
            )

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def resolve_urls(self, urls: list[str]) -> list[FlowObservedIdentity | None]:
        with self._lock:
            if self._failure_class:
                raise FlowSessionError(
                    self._failure_class, "Flow response observer evidence is incomplete",
                )
            return self.decoder.resolve_urls(urls)

    def identities(self) -> set[FlowObservedIdentity]:
        with self._lock:
            if self._failure_class:
                raise FlowSessionError(
                    self._failure_class, "Flow response observer evidence is incomplete",
                )
            return self.decoder.identities()

    @property
    def observed_response_count(self) -> int:
        with self._lock:
            return self.decoder.observed_response_count

    def _run(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(
                    self.runtime.cdp_url, timeout=8_000,
                )
                pages = [
                    page
                    for context in browser.contexts
                    for page in context.pages
                    if page.url.rstrip("/") == self.runtime.project_url.rstrip("/")
                ]
                if len(pages) != 1:
                    self._failure_class = "FLOW_PROJECT_MISMATCH"
                    self._ready.set()
                    return
                page = pages[0]
                project_host = urlsplit(self.runtime.project_url).hostname

                def observe(response) -> None:
                    if response.request.resource_type not in {"xhr", "fetch"}:
                        return
                    if urlsplit(response.url).hostname != project_host:
                        return
                    try:
                        body = response.text()
                        with self._lock:
                            self.decoder.observe_body(body)
                    except FlowResponseModelError:
                        self._failure_class = "FLOW_RESPONSE_MODEL_INVALID"
                        self._stop.set()
                    except Exception:
                        return

                page.on("response", observe)
                self._ready.set()
                while not self._stop.is_set():
                    page.wait_for_timeout(250)
                page.remove_listener("response", observe)
        except Exception:
            self._failure_class = self._failure_class or "FLOW_PASSIVE_OBSERVER_UNAVAILABLE"
            self._ready.set()

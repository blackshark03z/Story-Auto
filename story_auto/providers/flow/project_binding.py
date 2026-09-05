"""Crash-safe, project-owned Google Flow project binding.

The provider adapter is deliberately tiny.  Local state is persisted before
the one external create activation, and every recovery path reconciles by the
deterministic project name without repeating that activation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
import re
import time

from story_auto.core.artifacts import atomic_write_json
from story_auto.core.project import ProjectConfig, RuntimeLayout, load_project
from story_auto.core.project.lock import ProjectLock
from .cdp import CdpPage
from .session import FlowRuntime, FlowSessionError


FLOW_HOME_URL = "https://labs.google/fx/vi/tools/flow"
FLOW_MIGRATED_HOME_URL = "https://flow.google.com"
_PROJECT_PATH = re.compile(r"^/fx/vi/tools/flow/project/([A-Za-z0-9-]+)$")


class FlowProjectBindingError(RuntimeError):
    failure_class = "FLOW_PROJECT_BINDING_INVALID"

    def __init__(self, code: str):
        self.failure_class = code
        super().__init__(code)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def deterministic_project_name(project_id: str) -> str:
    suffix = project_id[4:] if project_id.startswith("prj_") else project_id
    return "StoryAuto_" + suffix[:12]


def managed_flow_settings(settings: dict[str, Any], project_id: str) -> dict[str, Any]:
    result = dict(settings)
    providers = dict(result.get("provider_binding", {}))
    providers["flow"] = {
        "state": "CREATE_INTENT",
        "project_url": None,
        "project_identity": None,
        "created_for_story_project_id": project_id,
        "project_name": deterministic_project_name(project_id),
        "activation_state": "NOT_ATTEMPTED",
        "created_at": _now(),
    }
    result["provider_binding"] = providers
    return result


def managed_binding(config: ProjectConfig) -> dict[str, Any] | None:
    providers = config.settings.get("provider_binding") if isinstance(config.settings, dict) else None
    value = providers.get("flow") if isinstance(providers, dict) else None
    return dict(value) if isinstance(value, dict) else None


def canonical_project(value: dict[str, Any]) -> dict[str, str]:
    name, url, identity = value.get("project_name"), value.get("project_url"), value.get("project_identity")
    if not all(isinstance(item, str) and item.strip() for item in (name, url, identity)):
        raise FlowProjectBindingError("FLOW_PROJECT_BINDING_INVALID")
    parsed = urlsplit(url.strip())
    match = _PROJECT_PATH.fullmatch(parsed.path.rstrip("/"))
    if parsed.scheme != "https" or parsed.netloc.lower() != "labs.google" or parsed.query or parsed.fragment or not match:
        raise FlowProjectBindingError("FLOW_PROJECT_BINDING_INVALID")
    normalized = urlunsplit(("https", "labs.google", parsed.path.rstrip("/"), "", ""))
    if identity.strip() not in {match.group(1), normalized}:
        raise FlowProjectBindingError("FLOW_PROJECT_BINDING_INVALID")
    return {"project_name": name.strip(), "project_url": normalized, "project_identity": identity.strip()}


class FlowProjectBindingService:
    def __init__(self, runtime: RuntimeLayout | Path | str, connections):
        self.runtime = runtime if isinstance(runtime, RuntimeLayout) else RuntimeLayout.from_root(runtime)
        self.connections = connections

    def _save(self, project_id: str, binding: dict[str, Any]) -> dict[str, Any]:
        paths, config = load_project(self.runtime, project_id)
        settings = dict(config.settings)
        providers = dict(settings.get("provider_binding", {}))
        providers["flow"] = dict(binding)
        settings["provider_binding"] = providers
        updated = ProjectConfig(project_id, content_path=config.content_path, render_mode=config.render_mode,
                                settings=settings, schema_version=config.schema_version)
        atomic_write_json(paths.project_file, updated.to_dict())
        return dict(binding)

    def mark_activation_started(self, project_id: str) -> dict[str, Any]:
        with ProjectLock(self.runtime, project_id):
            _paths, config = load_project(self.runtime, project_id)
            binding = managed_binding(config)
            if not binding or binding.get("state") != "CREATE_INTENT":
                raise FlowProjectBindingError("FLOW_PROJECT_CREATE_INTENT_REQUIRED")
            if binding.get("activation_state") == "NOT_ATTEMPTED":
                binding.update({"activation_state": "STARTED", "activation_started_at": _now()})
                self._save(project_id, binding)
            return binding

    @staticmethod
    def _same(expected: dict[str, str], observed: dict[str, Any]) -> bool:
        try:
            actual = canonical_project(observed)
        except FlowProjectBindingError:
            return False
        return actual == expected

    def _bind(self, project_id: str, binding: dict[str, Any], provider: dict[str, Any], adapter) -> dict[str, Any]:
        exact = canonical_project(provider)
        if exact["project_name"] != binding["project_name"]:
            raise FlowProjectBindingError("FLOW_PROJECT_BINDING_MISMATCH")
        created = {**binding, **exact, "state": "CREATED", "created_at_provider": _now()}
        created.pop("last_setup_failure", None)
        created.pop("last_setup_failure_at", None)
        self._save(project_id, created)
        observed = adapter.open_project(exact["project_url"], exact["project_identity"], exact["project_name"])
        if not self._same(exact, observed):
            raise FlowProjectBindingError("FLOW_PROJECT_BINDING_MISMATCH")
        bound = {**created, "state": "BOUND", "bound_at": _now()}
        return self._save(project_id, bound)

    def ensure(self, project_id: str, adapter) -> dict[str, Any]:
        with ProjectLock(self.runtime, project_id):
            _paths, config = load_project(self.runtime, project_id)
            binding = managed_binding(config)
            if binding is None:
                raise FlowProjectBindingError("FLOW_PROJECT_BINDING_LEGACY")
            if binding.get("created_for_story_project_id") != project_id:
                raise FlowProjectBindingError("FLOW_PROJECT_BINDING_INVALID")
            if binding.get("project_name") != deterministic_project_name(project_id):
                raise FlowProjectBindingError("FLOW_PROJECT_BINDING_INVALID")
            if binding.get("state") == "BOUND":
                exact = canonical_project(binding)
                observed = adapter.open_project(exact["project_url"], exact["project_identity"], exact["project_name"])
                if not self._same(exact, observed):
                    raise FlowProjectBindingError("FLOW_PROJECT_BINDING_MISMATCH")
                return binding
            if binding.get("state") == "CREATED":
                return self._bind(project_id, binding, binding, adapter)
            if binding.get("state") != "CREATE_INTENT":
                raise FlowProjectBindingError("FLOW_PROJECT_BINDING_INVALID")
            try:
                matches = [canonical_project(item) for item in adapter.find_projects(binding["project_name"])]
            except FlowProjectBindingError as error:
                if error.failure_class == "FLOW_AUTH_REQUIRED":
                    binding.update({"last_setup_failure": "FLOW_AUTH_REQUIRED", "last_setup_failure_at": _now()})
                    self._save(project_id, binding)
                raise
            matches = [item for item in matches if item["project_name"] == binding["project_name"]]
            if len(matches) == 1:
                return self._bind(project_id, binding, matches[0], adapter)
            if matches or binding.get("activation_state") != "NOT_ATTEMPTED":
                raise FlowProjectBindingError("FLOW_PROJECT_CREATION_RECONCILIATION_REQUIRED")
            binding.update({"activation_state": "STARTED", "activation_started_at": _now()})
            self._save(project_id, binding)  # durable before the external activation
            created = adapter.create_project(binding["project_name"])
            return self._bind(project_id, binding, created, adapter)


class LiveFlowProjects:
    """Minimal UI-only adapter for Flow project creation and exact reopening."""
    def __init__(self, runtime: RuntimeLayout, cdp_url: str = "http://127.0.0.1:9222"):
        self.runtime, self.cdp_url = runtime, cdp_url

    def _page(self) -> CdpPage:
        legacy = FlowRuntime(self.runtime.flow_profile, self.cdp_url, FLOW_HOME_URL, FLOW_HOME_URL)
        try:
            return CdpPage.open(legacy)
        except FlowSessionError as error:
            if error.failure_class != "FLOW_PROJECT_MISMATCH":
                raise
        # Google is rolling Flow from labs.google to flow.google.com. Attach to
        # either host, then drive only the still-supported legacy surface. The
        # runtime is restored to the legacy prefix so trusted locator clicks
        # reconnect to the page after we navigate it back to labs.google.
        migrated = FlowRuntime(self.runtime.flow_profile, self.cdp_url, FLOW_MIGRATED_HOME_URL, FLOW_MIGRATED_HOME_URL)
        page = CdpPage.open(migrated)
        # The new flow.google.com landing page hydrates after the DevTools
        # target is already attachable. Give its account control a short,
        # bounded window to appear before deciding this is merely a host
        # migration. This is read-only and occurs before any provider action.
        deadline = time.monotonic() + 4.0
        signed_out = False
        while time.monotonic() < deadline:
            signed_out = page.evaluate("""(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};return Array.from(document.querySelectorAll('a')).some(a=>visible(a)&&/accounts\\.google\\.com\\/ServiceLogin/i.test(a.href||''))})()""") is True
            if signed_out:
                break
            if page.evaluate("document.readyState") == "complete":
                # One extra turn lets Angular mount header/account controls.
                time.sleep(.25)
            else:
                time.sleep(.2)
        if signed_out:
            page.close()
            raise FlowProjectBindingError("FLOW_AUTH_REQUIRED")
        page.runtime = legacy
        return page

    @staticmethod
    def _navigate_legacy_surface(page: CdpPage, target_url: str, *, ready_expression: str,
                                 attempts: int = 4, timeout_per_attempt: float = 6.0) -> str:
        """Reach one exact legacy Flow surface during the host-migration rollout.

        Hostname alone is insufficient: labs.google can remain visible while
        the old SPA is still loading or is about to redirect. Require the
        caller's exact supported control before any external activation.
        """
        for _attempt in range(attempts):
            page.command("Page.navigate", {"url": target_url})
            deadline = time.monotonic() + timeout_per_attempt
            while time.monotonic() < deadline:
                current = page.evaluate("location.href")
                if isinstance(current, str) and current.startswith(FLOW_MIGRATED_HOME_URL):
                    break
                if isinstance(current, str) and current.startswith("https://labs.google/"):
                    if page.evaluate(ready_expression) is True:
                        return current
                time.sleep(.25)
        raise FlowProjectBindingError("FLOW_HOST_MIGRATED_RETRY_REQUIRED")

    @staticmethod
    def _wait_project(page: CdpPage, timeout: float = 20.0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            url = page.evaluate("location.href")
            if isinstance(url, str) and _PROJECT_PATH.fullmatch(urlsplit(url).path.rstrip("/")):
                return url
            time.sleep(.2)
        raise FlowProjectBindingError("FLOW_PROJECT_CREATE_OUTCOME_UNKNOWN")

    @staticmethod
    def _title(page: CdpPage) -> str | None:
        return page.evaluate("""(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const xs=Array.from(document.querySelectorAll('input[type=text]')).filter(e=>visible(e)&&e.value);return xs.length===1?xs[0].value:null})()""")

    @classmethod
    def _set_title(cls, page: CdpPage, name: str) -> None:
        # The project URL becomes active before Flow finishes mounting the
        # editable title control. Wait for that one exact control rather than
        # treating normal page hydration as a UI ambiguity.
        deadline = time.monotonic() + 10
        focused = False
        while time.monotonic() < deadline:
            focused = page.evaluate("""(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const xs=Array.from(document.querySelectorAll('input[type=text]')).filter(e=>visible(e)&&e.value);if(xs.length!==1)return false;xs[0].focus();xs[0].select();return true})()""")
            if focused is True:
                break
            time.sleep(.2)
        if focused is not True:
            raise FlowProjectBindingError("FLOW_PROJECT_NAME_CONTROL_AMBIGUOUS")
        # Use real DevTools input/keyboard events. Flow's React title control
        # currently ignores synthetic DOM change/KeyboardEvent dispatches.
        page.insert_text(name)
        page.key("Enter")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and cls._title(page) != name:
            time.sleep(.2)
        if cls._title(page) != name:
            raise FlowProjectBindingError("FLOW_PROJECT_NAME_NOT_CONFIRMED")

    def find_projects(self, name: str) -> list[dict[str, str]]:
        page = self._page()
        try:
            self._navigate_legacy_surface(page, FLOW_HOME_URL, ready_expression="""(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled};return Array.from(document.querySelectorAll('button')).filter(b=>visible(b)&&Array.from(b.querySelectorAll('i')).some(i=>(i.textContent||'').trim()==='add_2')).length===1})()""")
            rows = page.evaluate("""(()=>Array.from(document.querySelectorAll('a[href*="/flow/project/"]')).map(a=>({project_url:a.href,project_name:(a.innerText||a.getAttribute('aria-label')||a.parentElement?.innerText||'').trim()})))()""") or []
            found = []
            for row in rows:
                text = str(row.get("project_name", "")).splitlines()
                if name not in text and str(row.get("project_name", "")).strip() != name:
                    continue
                parsed = urlsplit(str(row.get("project_url", "")))
                match = _PROJECT_PATH.fullmatch(parsed.path.rstrip("/"))
                if match:
                    found.append({"project_name": name, "project_url": str(row["project_url"]), "project_identity": match.group(1)})
            unique = {(item["project_url"], item["project_identity"]): item for item in found}
            return list(unique.values())
        finally:
            page.close()

    def create_project(self, name: str) -> dict[str, str]:
        page = self._page()
        try:
            self._navigate_legacy_surface(page, FLOW_HOME_URL, ready_expression="""(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled};return Array.from(document.querySelectorAll('button')).filter(b=>visible(b)&&Array.from(b.querySelectorAll('i')).some(i=>(i.textContent||'').trim()==='add_2')).length===1})()""")
            # Keep project creation on the already-verified legacy CDP page.
            # Reattaching through Playwright creates a race with Google's host
            # migration redirect; native DevTools mouse events are trusted and
            # avoid acting on a different page after that reconnect.
            control = page.evaluate("""(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.disabled};const xs=Array.from(document.querySelectorAll('button')).filter(b=>visible(b)&&Array.from(b.querySelectorAll('i')).some(i=>(i.textContent||'').trim()==='add_2'));return xs.map(b=>{const r=b.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})})()""") or []
            current_url = page.evaluate("location.href")
            if not isinstance(current_url, str) or not current_url.startswith("https://labs.google/"):
                raise FlowProjectBindingError("FLOW_HOST_MIGRATED_RETRY_REQUIRED")
            if not isinstance(control, list) or len(control) != 1:
                raise FlowProjectBindingError("FLOW_PROJECT_CREATE_CONTROL_AMBIGUOUS")
            page.click(float(control[0]["x"]), float(control[0]["y"]))
            url = self._wait_project(page)
            self._set_title(page, name)
            match = _PROJECT_PATH.fullmatch(urlsplit(url).path.rstrip("/"))
            return {"project_name": name, "project_url": url, "project_identity": match.group(1)}
        finally:
            page.close()

    def open_project(self, project_url: str, project_identity: str, project_name: str) -> dict[str, str]:
        exact = canonical_project({"project_name": project_name, "project_url": project_url, "project_identity": project_identity})
        page = self._page()
        try:
            current_url = page.evaluate("location.href")
            if current_url == exact["project_url"]:
                # Re-navigating the exact active Flow project clears the SPA's
                # currently rendered provider surface.  Preserve that live
                # surface across bounded Continue calls; only navigate when a
                # different project/home is actually active.
                deadline = time.monotonic() + 8
                title = self._title(page)
                while time.monotonic() < deadline and title is None:
                    time.sleep(.2); title = self._title(page)
                observed = {"project_name": title or "", "project_url": current_url,
                            "project_identity": urlsplit(current_url).path.rstrip("/").split("/")[-1]}
                if not FlowProjectBindingService._same(exact, observed):
                    raise FlowProjectBindingError("FLOW_PROJECT_BINDING_MISMATCH")
                return observed
            self._navigate_legacy_surface(page, exact["project_url"], ready_expression="""(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};return Array.from(document.querySelectorAll('input[type=text]')).filter(e=>visible(e)&&e.value).length===1})()""")
            actual_url = self._wait_project(page)
            deadline = time.monotonic() + 8
            title = self._title(page)
            while time.monotonic() < deadline and title is None:
                time.sleep(.2); title = self._title(page)
            observed = {"project_name": title or "", "project_url": actual_url, "project_identity": urlsplit(actual_url).path.rstrip("/").split("/")[-1]}
            if not FlowProjectBindingService._same(exact, observed):
                raise FlowProjectBindingError("FLOW_PROJECT_BINDING_MISMATCH")
            return observed
        finally:
            page.close()

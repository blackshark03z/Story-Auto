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
from .project_surface import CURRENT_PROJECT_PATH, LIST_DOM, observed_project_list, list_agrees_with_dom


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
    host = parsed.netloc.lower()
    pattern = CURRENT_PROJECT_PATH if host == "flow.google.com" else _PROJECT_PATH
    match = pattern.fullmatch(parsed.path.rstrip("/"))
    if parsed.scheme != "https" or host not in {"labs.google", "flow.google.com"} or parsed.query or parsed.fragment or not match:
        raise FlowProjectBindingError("FLOW_PROJECT_BINDING_INVALID")
    normalized = urlunsplit(("https", host, parsed.path.rstrip("/"), "", ""))
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
        return (actual["project_name"] == expected["project_name"] and
                actual["project_url"].rsplit("/", 1)[-1] == expected["project_url"].rsplit("/", 1)[-1])

    def _bind(self, project_id: str, binding: dict[str, Any], provider: dict[str, Any], adapter) -> dict[str, Any]:
        exact = canonical_project(provider)
        if exact["project_name"] != binding["project_name"]:
            raise FlowProjectBindingError("FLOW_PROJECT_BINDING_MISMATCH")
        created = {**binding, **exact, "state": "CREATED", "created_at_provider": _now()}
        created.pop("last_setup_failure", None)
        created.pop("last_setup_failure_at", None)
        created.pop("last_setup_failure_phase", None)
        created.pop("name_confirmation_pending", None)
        self._save(project_id, created)
        observed = adapter.open_project(exact["project_url"], exact["project_identity"], exact["project_name"])
        if not self._same(exact, observed):
            raise FlowProjectBindingError("FLOW_PROJECT_BINDING_MISMATCH")
        bound = {**created, **canonical_project(observed), "state": "BOUND", "bound_at": _now()}
        return self._save(project_id, bound)

    def ensure(self, project_id: str, adapter) -> dict[str, Any]:
        with ProjectLock(self.runtime, "flow-project-binding-session"), ProjectLock(self.runtime, project_id):
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
                if canonical_project(observed) != exact:
                    return self._save(project_id, {**binding, **canonical_project(observed)})
                return binding
            if binding.get("state") == "CREATED":
                if binding.get("name_confirmation_pending"):
                    resume = getattr(adapter, "resume_created_project", None)
                    if not callable(resume):
                        raise FlowProjectBindingError("FLOW_PROJECT_NAME_NOT_CONFIRMED")
                    provider = resume(binding["project_url"], binding["project_identity"], binding["project_name"])
                    return self._bind(project_id, binding, provider, adapter)
                return self._bind(project_id, binding, binding, adapter)
            if binding.get("state") != "CREATE_INTENT":
                raise FlowProjectBindingError("FLOW_PROJECT_BINDING_INVALID")
            try:
                matches = [canonical_project(item) for item in adapter.find_projects(binding["project_name"])]
                matches = [item for item in matches if item["project_name"] == binding["project_name"]]
                if len(matches) == 1:
                    return self._bind(project_id, binding, matches[0], adapter)
                if binding.get("activation_state") == "STARTED":
                    reconcile = getattr(adapter, "reconcile_started", None)
                    recovered = reconcile(binding) if callable(reconcile) else None
                    if recovered is not None:
                        return self._bind(project_id, binding, recovered, adapter)
                    raise FlowProjectBindingError("FLOW_PROJECT_CREATION_RECONCILIATION_REQUIRED")
                if matches:
                    # A missing row is not proof of mutation absence (creation
                    # may have succeeded before the deterministic rename).
                    raise FlowProjectBindingError("FLOW_PROJECT_CREATION_RECONCILIATION_REQUIRED")

                def before_activation(evidence=None):
                    if binding.get("activation_state") != "NOT_ATTEMPTED":
                        raise FlowProjectBindingError("FLOW_PROJECT_CREATION_RECONCILIATION_REQUIRED")
                    binding.update({"activation_state": "STARTED", "activation_started_at": _now()})
                    if evidence is not None:
                        ids = evidence.get("project_ids") if isinstance(evidence, dict) else None
                        observed_at = evidence.get("observed_at") if isinstance(evidence, dict) else None
                        if (not isinstance(ids, list) or any(not isinstance(item, str) or not item for item in ids)
                                or len(set(ids)) != len(ids) or not isinstance(observed_at, str) or not observed_at):
                            raise FlowProjectBindingError("FLOW_PROJECT_LIST_UNVERIFIED")
                        binding.update({"activation_baseline_project_ids":sorted(ids),
                                        "activation_baseline_observed_at":observed_at})
                    self._save(project_id, binding)

                def record_created(provider):
                    exact = canonical_project(provider)
                    if binding.get("activation_state") != "STARTED" or exact["project_name"] != binding["project_name"]:
                        raise FlowProjectBindingError("FLOW_PROJECT_BINDING_INVALID")
                    binding.update({**exact, "state":"CREATED", "name_confirmation_pending":True,
                                    "created_at_provider":_now()})
                    self._save(project_id, binding)

                receipt_create = getattr(adapter, "create_project_with_receipt", None)
                controlled_create = getattr(adapter, "create_project_with_activation", None)
                if callable(receipt_create):
                    created = receipt_create(binding["project_name"], before_activation, record_created)
                elif callable(controlled_create):
                    # The adapter calls this after read-only preparation, just
                    # before its single mutation input. Exceptions never reset it.
                    created = controlled_create(binding["project_name"], before_activation)
                else:
                    # Older injected adapters do not report a boundary; retain
                    # their conservative at-most-once contract.
                    before_activation()
                    created = adapter.create_project(binding["project_name"])
                return self._bind(project_id, binding, created, adapter)
            except Exception as error:
                # Reload: _bind may already have persisted CREATED. Do not
                # replace that durable provider identity with the original intent.
                _paths, current = load_project(self.runtime, project_id)
                saved = managed_binding(current)
                phase = ("VERIFY_BINDING" if saved.get("state") == "CREATED" else
                         "MAY_HAVE_ACTIVATED" if saved.get("activation_state") == "STARTED" else "PRE_ACTIVATION")
                saved.update({"last_setup_failure": getattr(error, "failure_class", type(error).__name__),
                              "last_setup_failure_at": _now(), "last_setup_failure_phase": phase})
                self._save(project_id, saved)
                raise



class LiveFlowProjects:
    """Minimal UI-only adapter for Flow project creation and exact reopening."""
    def __init__(self, runtime: RuntimeLayout, cdp_url: str = "http://127.0.0.1:9222"):
        self.runtime, self.cdp_url = runtime, cdp_url

    def _page(self) -> CdpPage:
        if not (self.runtime.flow_profile / "Local State").is_file():
            raise FlowSessionError("FLOW_CDP_UNAVAILABLE", "dedicated Flow profile has not been initialized")
        for url in (FLOW_MIGRATED_HOME_URL, FLOW_HOME_URL):
            runtime = FlowRuntime(self.runtime.flow_profile, self.cdp_url, url, url)
            try:
                return CdpPage.open(runtime)
            except FlowSessionError as error:
                if error.failure_class != "FLOW_PROJECT_MISMATCH":
                    raise
        raise FlowSessionError("FLOW_PROJECT_MISMATCH", "expected one dedicated Flow tab")

    def _current_list(self) -> list[dict[str, str]]:
        """Fresh, complete provider UI response plus matching hydrated DOM."""
        from playwright.sync_api import sync_playwright
        if not (self.runtime.flow_profile / "Local State").is_file():
            raise FlowSessionError("FLOW_CDP_UNAVAILABLE")
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(self.cdp_url)
            try:
                pages = [p for c in browser.contexts for p in c.pages
                         if urlsplit(p.url).hostname in {"flow.google.com", "labs.google"}]
                if len(pages) != 1:
                    raise FlowSessionError("FLOW_PROJECT_MISMATCH", "expected one dedicated Flow tab")
                page = pages[0]
                lists, auth_failures = [], []

                def observe(response):
                    if (urlsplit(response.url).hostname != "flow.google.com" or
                            response.request.resource_type not in {"xhr", "fetch"}):
                        return
                    if response.status == 401:
                        auth_failures.append(401)
                    if response.status != 200:
                        return
                    try:
                        rows = observed_project_list(response.text())
                        if rows is not None:
                            lists.append(rows)
                    except Exception:
                        pass  # unreadable response is never absence proof

                page.on("response", observe)
                page.goto(FLOW_MIGRATED_HOME_URL + "/", wait_until="domcontentloaded", timeout=20000)
                deadline = time.monotonic() + 25
                entered = False
                while time.monotonic() < deadline:
                    if auth_failures or urlsplit(page.url).hostname == "accounts.google.com":
                        raise FlowProjectBindingError("FLOW_AUTH_REQUIRED")
                    if lists and list_agrees_with_dom(lists[-1], page.evaluate(LIST_DOM)):
                        self.last_list_evidence = {"source":"provider-ui-UpteDb-and-projects-grid",
                                                   "observed_at":_now(), "count":len(lists[-1]),
                                                   "projects":lists[-1]}
                        return lists[-1]
                    if urlsplit(page.url).path == "/about" and not entered:
                        entry = page.locator('button[aria-label="Create with Google Flow"]')
                        if entry.count() == 1 and entry.is_visible():
                            page.bring_to_front()
                            entry.click(timeout=5000)
                            entered = True
                    page.wait_for_timeout(200)
                raise FlowProjectBindingError("FLOW_PROJECT_LIST_UNVERIFIED")
            finally:
                browser.close()  # disconnect from CDP; never close the owner browser

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
    def _wait_project(page: CdpPage, timeout: float = 20.0, expected_url: str | None = None) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            url = page.evaluate("location.href")
            if isinstance(url, str) and urlsplit(url).hostname == "flow.google.com" and CURRENT_PROJECT_PATH.fullmatch(urlsplit(url).path.rstrip("/")) and (expected_url is None or url == expected_url):
                return url
            time.sleep(.2)
        raise FlowProjectBindingError("FLOW_PROJECT_CREATE_OUTCOME_UNKNOWN")

    @staticmethod
    def _title(page: CdpPage) -> str | None:
        return page.evaluate("""(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const xs=Array.from(document.querySelectorAll(location.hostname==='flow.google.com'?'flow-navigation-header input.editable-text-input':'input[type=text]')).filter(e=>visible(e)&&e.value);return xs.length===1?xs[0].value:null})()""")

    @classmethod
    def _set_title(cls, page: CdpPage, name: str) -> None:
        # The project URL becomes active before Flow finishes mounting the
        # editable title control. Wait for that one exact control rather than
        # treating normal page hydration as a UI ambiguity.
        deadline = time.monotonic() + 10
        focused = False
        while time.monotonic() < deadline:
            focused = page.evaluate("""(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const xs=Array.from(document.querySelectorAll(location.hostname==='flow.google.com'?'flow-navigation-header input.editable-text-input':'input[type=text]')).filter(e=>visible(e)&&e.value);if(xs.length!==1)return false;xs[0].focus();xs[0].select();return true})()""")
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
        return [row for row in self._current_list() if row["project_name"] == name]

    def create_project(self, name: str) -> dict[str, str]:
        return self.create_project_with_activation(name, lambda: None)

    def create_project_with_activation(self, name: str, before_activation) -> dict[str, str]:
        return self.create_project_with_receipt(name, before_activation, lambda provider: None)

    def create_project_with_receipt(self, name: str, before_activation, record_created) -> dict[str, str]:
        # Recheck authoritative absence on this same page immediately before
        # resolving the one create control. This navigation is pre-activation.
        matches = self.find_projects(name)
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise FlowProjectBindingError("FLOW_PROJECT_CREATION_RECONCILIATION_REQUIRED")
        page = self._page()
        try:
            page.command("Page.bringToFront")
            control = page.evaluate("""(()=>Array.from(document.querySelectorAll('flow-projects-page button.new-project-button')).filter(b=>{const r=b.getBoundingClientRect(),s=getComputedStyle(b);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&!b.disabled}).map(b=>{const r=b.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2;return b.contains(document.elementFromPoint(x,y))?{x,y}:null}).filter(Boolean))()""") or []
            current_url = page.evaluate("location.href")
            if urlsplit(current_url).hostname != "flow.google.com" or urlsplit(current_url).path != "/":
                raise FlowProjectBindingError("FLOW_PROJECT_LIST_UNVERIFIED")
            if len(control) != 1:
                raise FlowProjectBindingError("FLOW_PROJECT_CREATE_CONTROL_AMBIGUOUS")
            evidence = getattr(self, "last_list_evidence", None)
            projects = evidence.get("projects") if isinstance(evidence, dict) else None
            if not isinstance(projects, list):
                raise FlowProjectBindingError("FLOW_PROJECT_LIST_UNVERIFIED")
            before_activation({"project_ids":[row["project_identity"] for row in projects],
                               "observed_at":evidence["observed_at"]})
            page.click(float(control[0]["x"]), float(control[0]["y"]))
            url = self._wait_project(page)
            provider = {"project_name":name, "project_url":url, "project_identity":url.rsplit("/",1)[-1]}
            record_created(provider)  # recover the exact new project even if rename crashes
            self._set_title(page, name)
        finally:
            page.close()
        self._confirm_saved_title(provider)
        return provider

    def reconcile_started(self, binding: dict[str, Any]) -> dict[str, str] | None:
        """Recover a post-click crash only from an exact persisted list delta."""
        baseline = binding.get("activation_baseline_project_ids")
        if not isinstance(baseline, list):
            return None
        rows = self._current_list()
        new_rows = [row for row in rows if row["project_identity"] not in set(baseline)]
        if len(new_rows) != 1:
            return None
        candidate = {"project_name":binding["project_name"],
                     "project_url":new_rows[0]["project_url"],
                     "project_identity":new_rows[0]["project_identity"]}
        return self.resume_created_project(candidate["project_url"], candidate["project_identity"],
                                           candidate["project_name"])

    def _confirm_saved_title(self, provider: dict) -> None:
        matches = self.find_projects(provider["project_name"])
        if len(matches) != 1 or not FlowProjectBindingService._same(provider, matches[0]):
            raise FlowProjectBindingError("FLOW_PROJECT_NAME_NOT_CONFIRMED")

    def resume_created_project(self, project_url: str, project_identity: str, project_name: str) -> dict[str, str]:
        exact = canonical_project({"project_url":project_url, "project_identity":project_identity, "project_name":project_name})
        page = self._page()
        try:
            page.command("Page.navigate", {"url":exact["project_url"]})
            actual = self._wait_project(page, expected_url=exact["project_url"])
            if actual != exact["project_url"]:
                raise FlowProjectBindingError("FLOW_PROJECT_BINDING_MISMATCH")
            self._set_title(page, project_name)
        finally:
            page.close()
        self._confirm_saved_title(exact)
        return exact

    def open_project(self, project_url: str, project_identity: str, project_name: str) -> dict[str, str]:
        exact = canonical_project({"project_name":project_name, "project_url":project_url, "project_identity":project_identity})
        page = self._page()
        try:
            current_url = page.evaluate("location.href")
            if current_url != exact["project_url"]:
                # Legacy IDs are identical on the observed migrated host.
                # Navigate directly to the current route, then verify ID/name.
                target = FLOW_MIGRATED_HOME_URL + "/project/" + exact["project_url"].rsplit("/",1)[-1]
                page.command("Page.navigate", {"url":target})
                current_url = self._wait_project(page, expected_url=target)
            deadline = time.monotonic() + 10
            title = self._title(page)
            while time.monotonic() < deadline and title != project_name:
                time.sleep(.2)
                title = self._title(page)
            observed = {"project_name":title or "", "project_url":current_url,
                        "project_identity":current_url.rstrip("/").rsplit("/",1)[-1]}
            if not FlowProjectBindingService._same(exact, observed):
                raise FlowProjectBindingError("FLOW_PROJECT_BINDING_MISMATCH")
            return observed
        finally:
            page.close()

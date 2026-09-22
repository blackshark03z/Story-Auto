"""Owned ephemeral browser session seeded from an explicitly selected local export.

Experimental session factory only; this does not change production routing.
Cookie values never enter provider journals or exception messages.
"""
from __future__ import annotations

import json
from pathlib import Path
import time

from .rpc_transport import BrowserRpcSession, RpcError

MAX_COOKIE_FILE_BYTES = 1024 * 1024


def read_cookie_export(path: Path, *, now: float | None = None) -> list[dict]:
    try:
        with Path(path).open('rb') as stream:
            data = stream.read(MAX_COOKIE_FILE_BYTES + 1)
        if len(data) > MAX_COOKIE_FILE_BYTES:
            raise ValueError()
        raw = json.loads(data.decode('utf-8-sig'))
    except Exception:
        raise RpcError('FLOW_COOKIE_EXPORT_INVALID') from None
    return normalize_cookie_export(raw, now=now)


def normalize_cookie_export(raw, *, now: float | None = None) -> list[dict]:
    """Validate a file/browser/DPAPI export without writing plaintext to disk."""
    now = time.time() if now is None else now
    try:
        if isinstance(raw, str):
            if len(raw.encode('utf-8')) > MAX_COOKIE_FILE_BYTES:
                raise ValueError()
            raw = json.loads(raw)
        # Callers may send already-decoded JSON, not only a file/string.
        # Apply the same bound to every input form before copying cookie values.
        if len(json.dumps(raw, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) > MAX_COOKIE_FILE_BYTES:
            raise ValueError()
        rows = raw if isinstance(raw, list) else raw.get('cookies')
        if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
            raise ValueError()
        cookies = []
        identities = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError()
            domain = row.get('domain', '')
            if not isinstance(domain, str):
                raise ValueError()
            domain = domain.lower()
            if domain.startswith('..'):
                raise ValueError()
            if domain.lstrip('.') != 'google.com' and not domain.endswith('.google.com'):
                continue
            item = {key: row[key] for key in ('name', 'value', 'domain')}
            item['domain'] = domain
            if any(not isinstance(item[key], str) or not item[key] for key in item):
                raise ValueError()
            item['path'] = row.get('path', '/')
            if not isinstance(item['path'], str) or not item['path'].startswith('/'):
                raise ValueError()
            identity = (item['name'], domain.lstrip('.'), item['path'])
            if identity in identities:
                raise ValueError()
            identities.add(identity)
            for key in ('secure', 'httpOnly'):
                if key in row:
                    if not isinstance(row[key], bool):
                        raise ValueError()
                    item[key] = row[key]
            same = row.get('sameSite')
            if same is not None:
                mapping = {'none':'None', 'no_restriction':'None', 'lax':'Lax', 'strict':'Strict', 'unspecified':None}
                if not isinstance(same, str) or same.lower() not in mapping:
                    raise ValueError()
                if mapping[same.lower()] is not None:
                    item['sameSite'] = mapping[same.lower()]
            if 'expires' in row and 'expirationDate' in row and row['expires'] != row['expirationDate']:
                raise ValueError()
            expires = row.get('expires', row.get('expirationDate'))
            if expires is not None:
                if isinstance(expires, bool) or not isinstance(expires, (int, float)):
                    raise ValueError()
                if expires != -1:
                    import math
                    if not math.isfinite(expires):
                        raise ValueError()
                    if expires <= now:
                        continue
                item['expires'] = expires
            if row.get('partitionKey') is not None:
                # Do not silently flatten partitioned identity into an ordinary cookie.
                raise ValueError()
            cookies.append(item)
        if not cookies:
            raise ValueError()
        return cookies
    except Exception:
        raise RpcError('FLOW_COOKIE_EXPORT_INVALID') from None


class CookieBrowserRpcSession(BrowserRpcSession):
    """Reuse the qualified RPC contract with an owned, non-CDP browser lifetime."""

    def __init__(self, runtime, *, cookie_file: Path | None = None, cookies=None, playwright_factory=None):
        super().__init__(runtime)
        if (cookie_file is None) == (cookies is None):
            raise RpcError('FLOW_COOKIE_SOURCE_REQUIRED')
        self.cookie_file = Path(cookie_file) if cookie_file is not None else None
        self.cookies = cookies
        self.playwright_factory = playwright_factory
        self.browser = None
        self.pw = None

    def __enter__(self):
        from urllib.parse import urlsplit
        parsed = urlsplit(self.runtime.project_url)
        if (parsed.scheme != 'https' or parsed.netloc != 'flow.google.com'
                or parsed.path != '/project/' + self.runtime.project_identity
                or parsed.query or parsed.fragment):
            raise RpcError('FLOW_COOKIE_PROJECT_INVALID')
        cookies = read_cookie_export(self.cookie_file) if self.cookie_file is not None else normalize_cookie_export(self.cookies)
        try:
            if self.playwright_factory is None:
                from playwright.sync_api import sync_playwright
                factory = sync_playwright
            else:
                factory = self.playwright_factory
            self.pw = factory().start()
            self.browser = self.pw.chromium.launch(headless=True)
            context = self.browser.new_context(viewport={'width':1440, 'height':900})
            context.add_cookies(cookies)
            self.page = context.new_page()
            self.page.goto(self.runtime.project_url, wait_until='domcontentloaded', timeout=45000)
            self.page.wait_for_function('() => !!globalThis.WIZ_global_data?.SNlM0e && !!globalThis.grecaptcha?.enterprise?.execute', timeout=15000)
            self.meta()  # RPC compatibility, not a universal browser-login test.
            return self
        except Exception:
            self.__exit__()
            raise RpcError('FLOW_COOKIE_SESSION_UNAVAILABLE') from None

    def __exit__(self, *args):
        browser, driver = self.browser, self.pw
        self.browser = self.pw = None
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if driver is not None:
            try:
                driver.stop()
            except Exception:
                pass


class NamedCookieSessionFactory:
    """Pin a non-secret account/revision in each journal; refresh is not rotation."""

    def __init__(self, account_id: str, revision: int, *, store=None):
        import re
        if (not isinstance(account_id,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}',account_id)
                or isinstance(revision,bool) or not isinstance(revision,int) or revision < 1):
            raise RpcError('FLOW_COOKIE_ACCOUNT_BINDING_INVALID')
        self.account_id, self.revision = account_id, revision
        self.store = store

    @property
    def binding(self):
        return {'mode':'cookie_owned','account_id':self.account_id,'revision':self.revision}

    def __call__(self, runtime):
        from .cookie_accounts import FlowCookieAccountStore
        store = self.store if self.store is not None else FlowCookieAccountStore()
        account = store.get_account(self.account_id)
        if account['revision'] != self.revision:
            raise RpcError('FLOW_COOKIE_ACCOUNT_REVISION_CHANGED')
        return CookieBrowserRpcSession(runtime,cookies=account['cookies'])

"""Isolated cookie-seeded browser diagnostic; no generation or upload."""
import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from story_auto.core.artifacts import atomic_write_json
from story_auto.providers.flow.rpc_transport import BrowserRpcSession


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cookies', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--engine', choices=['chrome','patchright'],default='chrome')
    parser.add_argument('--provider-project')
    args = parser.parse_args()
    if args.output.exists(): raise SystemExit('OUTPUT_EXISTS')
    result = {'scope':'isolated browser seeded from cookie export', 'uploads':0, 'generations':0, 'status':'BLOCKED'}
    try:
        exported = json.loads(args.cookies.read_text(encoding='utf-8-sig'))
        cookies = exported if isinstance(exported,list) else exported['cookies']
        clean = []
        for cookie in cookies:
            if cookie.get('domain','').lstrip('.') not in {'google.com','flow.google.com'}: continue
            item = {key:cookie[key] for key in ('name','value','domain')}
            item.update(path=cookie.get('path','/'), secure=bool(cookie.get('secure',True)), httpOnly=bool(cookie.get('httpOnly',False)))
            same = {'no_restriction':'None','lax':'Lax','strict':'Strict'}.get(cookie.get('sameSite'))
            if same: item['sameSite'] = same
            if cookie.get('expirationDate'): item['expires'] = cookie['expirationDate']
            clean.append(item)
        result['scoped_cookie_count'] = len(clean)
        flow = json.loads(args.project.read_text(encoding='utf-8'))['settings']['provider_binding']['flow']
        if args.provider_project:
            from uuid import UUID
            project_id = str(UUID(args.provider_project))
            flow = {'project_identity':project_id,'project_url':f'https://flow.google.com/project/{project_id}'}
        if urlsplit(flow['project_url']).hostname != 'flow.google.com': raise ValueError('INVALID_TARGET')
        launcher = sync_playwright
        if args.engine == 'patchright':
            from patchright.sync_api import sync_playwright as launcher
        result['engine'] = args.engine
        with launcher() as pw:
            browser = pw.chromium.launch(**({'channel':'chrome','headless':True} if args.engine == 'chrome' else {'headless':True}))
            try:
                context = browser.new_context(viewport={'width':1440,'height':900})
                context.add_cookies(clean)
                page = context.new_page()
                page.goto(flow['project_url'],wait_until='domcontentloaded',timeout=45000)
                try:
                    page.wait_for_function("() => !!globalThis.WIZ_global_data?.SNlM0e",timeout=15000)
                except Exception:
                    pass
                result['session'] = page.evaluate("""() => ({host:location.hostname,
                    project_path:location.pathname.startsWith('/project/'),
                    at_length:(globalThis.WIZ_global_data?.SNlM0e||'').length,
                    login_link:!!document.querySelector('a[href*="accounts.google.com/ServiceLogin"]'),
                    captcha_available:!!globalThis.grecaptcha?.enterprise?.execute})""")
                if result['session']['at_length']:
                    from types import SimpleNamespace
                    session = BrowserRpcSession(SimpleNamespace(project_identity=flow['project_identity'],project_url=flow['project_url']))
                    session.page = page
                    result['catalog_records'] = len(session.catalog())
                    result['status'] = 'READ_PASS'
            finally:
                browser.close()
    except Exception as error:
        result['error_code'] = getattr(error,'code',type(error).__name__)
    atomic_write_json(args.output,result)
    print(json.dumps(result,indent=2))


if __name__ == '__main__': main()

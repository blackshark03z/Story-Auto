"""Read-only HTTP cookie-export probe. Never prints secrets or generates media."""
import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from story_auto.providers.flow.rpc_contract import build_catalog, catalog_records, parse_rpc
from story_auto.core.artifacts import atomic_write_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--cookies', type=Path, required=True)
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists(): raise SystemExit('OUTPUT_EXISTS')
    raw = args.cookies.read_text(encoding='utf-8-sig').strip()
    result = {'scope': 'cookie-only read-only HTTP; no Chrome/CDP', 'uploads': 0, 'generations': 0, 'samples': []}
    try:
        exported = json.loads(raw)
        cookies = exported if isinstance(exported, list) else exported.get('cookies', [])
        result['format'] = 'COOKIE_EDITOR_JSON'
        scoped = []
        accepted = 0
        result['expired_cookie_count'] = 0
        result['session_cookie_count'] = 0
        result['domains'] = sorted({str(c.get('domain', '')) for c in cookies})
        for cookie in cookies:
            domain = str(cookie.get('domain', ''))
            if domain.lstrip('.') not in {'google.com', 'flow.google.com'}: continue
            expires = cookie.get('expirationDate', -1)
            if expires == -1: result['session_cookie_count'] += 1
            elif expires < time.time(): result['expired_cookie_count'] += 1
            same_site = {'no_restriction':'None', 'lax':'Lax', 'strict':'Strict', 'unspecified':'Lax'}.get(str(cookie.get('sameSite','')).lower(), 'Lax')
            scoped.append({'name':cookie['name'], 'value':cookie['value'], 'domain':domain,
                           'path':cookie.get('path','/'), 'secure':bool(cookie.get('secure',True)),
                           'httpOnly':bool(cookie.get('httpOnly',False)), 'expires':expires, 'sameSite':same_site})
            accepted += 1
        result['scoped_cookie_count'] = accepted
        if not accepted: raise ValueError('NO_SCOPED_COOKIES')
        pw = sync_playwright().start()
        session = pw.request.new_context(storage_state={'cookies': scoped, 'origins': []})
        flow = json.loads(args.project.read_text(encoding='utf-8'))['settings']['provider_binding']['flow']
        target = flow['project_url']
        if urlsplit(target).hostname != 'flow.google.com': raise ValueError('TARGET_INVALID')
        for _ in range(3):
            started = time.monotonic()
            response = session.get(target, timeout=25000, max_redirects=0, max_retries=0)
            body = response.text()
            sample = {'page_http': response.status, 'body_bytes':len(body.encode()),
                      'at_field_present': 'SNlM0e' in body,
                      'at_null': bool(re.search(r'"SNlM0e"\s*:\s*null', body)),
                      'login_link_present': 'accounts.google.com/ServiceLogin' in body}
            # Extract only known WIZ fields, keep all values in memory.
            values = {}
            for key in ('SNlM0e', 'FdrFJe', 'cfb2h'):
                match = re.search(r'"' + key + r'"\s*:\s*("(?:[^"\\]|\\.)*")', response.text())
                values[key] = json.loads(match.group(1)) if match else ''
            sample['at_length'] = len(values['SNlM0e'])
            sample['sid_present'] = bool(values['FdrFJe'])
            sample['bl_present'] = bool(values['cfb2h'])
            if response.status == 200 and all(values.values()):
                rpc = session.post('https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute',
                    params={'rpcids': 'Zzl0ze', 'source-path': urlsplit(target).path, 'bl': values['cfb2h'],
                            'f.sid': values['FdrFJe'], 'hl': 'en', 'rt': 'c'},
                    form={'f.req': build_catalog(flow['project_identity']), 'at': values['SNlM0e']},
                    headers={'origin': 'https://flow.google.com', 'referer': target, 'x-same-domain': '1'},
                    timeout=25000, max_redirects=0, max_retries=0)
                sample['catalog_http'] = rpc.status
                if rpc.status == 200:
                    parse_rpc(rpc.text(), 'Zzl0ze')
                    sample['catalog_records'] = len(catalog_records(rpc.text(), flow['project_identity']))
            sample['elapsed_seconds'] = round(time.monotonic()-started, 2)
            result['samples'].append(sample)
        result['status'] = 'READ_PASS' if all(x.get('catalog_records', 0)>0 for x in result['samples']) else 'BLOCKED'
        control = pw.request.new_context()
        control_response = control.get(target, timeout=25000, max_redirects=0, max_retries=0)
        control_body = control_response.text()
        result['unauthenticated_control'] = {'page_http':control_response.status,
            'at_field_present':'SNlM0e' in control_body,
            'at_null':bool(re.search(r'"SNlM0e"\s*:\s*null',control_body)),
            'login_link_present':'accounts.google.com/ServiceLogin' in control_body}
        control.dispose()
        session.dispose()
        pw.stop()
    except Exception as error:
        result['status'] = 'BLOCKED'
        result['error_type'] = type(error).__name__
    atomic_write_json(args.output, result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()

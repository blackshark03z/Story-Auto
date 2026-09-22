"""Explicit local credential export; no navigation, generation or account refresh."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True, type=UUID)
    parser.add_argument('--export', action='store_true')
    args = parser.parse_args()
    if not args.export:
        raise SystemExit('Explicit --export required to save credentials.')
    target = 'https://flow.google.com/project/' + str(args.project)
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp('http://127.0.0.1:9333', timeout=8000)
            matches = [(c, page) for c in browser.contexts for page in c.pages
                       if page.url.split('?')[0].rstrip('/') == target]
            if len(matches) != 1:
                raise ValueError('Expected one exact project tab')
            context, page = matches[0]
            if not page.evaluate('''() => !!globalThis.WIZ_global_data?.SNlM0e &&
                !!document.querySelector('[contenteditable="true"],textarea')'''):
                raise ValueError('Authenticated editor not ready')
            cookies = [c for c in context.cookies() if c['domain'].lstrip('.') == 'google.com'
                       or c['domain'].endswith('.google.com')]
            if not cookies:
                raise ValueError('No scoped cookies')
            folder = Path(r'D:\Story Auto\cookie')
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            output = folder / ('flow_profile_export_' + stamp + '.json')
            with output.open('x', encoding='utf-8') as stream:
                json.dump(cookies, stream)
            stored = json.loads(output.read_text(encoding='utf-8'))
            print(json.dumps({'status':'EXPORTED', 'path':str(output),
                              'cookie_count':len(stored), 'roundtrip_verified':stored == cookies,
                              'generations':0, 'saved_account_changed':False}))
    except Exception as error:
        print(json.dumps({'status':'EXPORT_FAILED', 'error_type':type(error).__name__}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

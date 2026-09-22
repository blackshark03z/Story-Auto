import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from story_auto.providers.flow.cookie_session import CookieBrowserRpcSession, NamedCookieSessionFactory, read_cookie_export
from story_auto.providers.flow.rpc_transport import RpcError


class CookieSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'cookies.json'
        self.row = dict(name='SID', value='test-secret', domain='.google.com', path='/', secure=True, httpOnly=True)

    def write(self, rows):
        self.path.write_text(json.dumps(rows), encoding='utf-8')

    def test_cookie_editor_and_playwright_formats(self):
        for row in [dict(self.row, sameSite='no_restriction', expirationDate=200), dict(self.row, sameSite='None', expires=200)]:
            self.write([row])
            found = read_cookie_export(self.path, now=100)[0]
            self.assertEqual(found['sameSite'], 'None')
            self.assertEqual(found['expires'], 200)
            self.assertTrue(found['httpOnly'])

    def test_foreign_domain_filtered_and_expired_not_revived(self):
        self.write([dict(self.row, expires=99), dict(self.row, domain='.google.com.evil.test')])
        with self.assertRaises(RpcError): read_cookie_export(self.path, now=100)

    def test_session_cookie_preserved(self):
        self.write({'cookies':[dict(self.row, expires=-1)]})
        self.assertEqual(read_cookie_export(self.path, now=100)[0]['expires'], -1)

    def test_invalid_values_and_partition_identity_fail_closed(self):
        for changes in [dict(value=''), dict(path='bad'), dict(sameSite='bad'), dict(expires=float('nan')), dict(partitionKey='https://example.test'), dict(httpOnly='yes')]:
            with self.subTest(changes=list(changes)):
                self.write([dict(self.row, **changes)])
                with self.assertRaisesRegex(RpcError, '^FLOW_COOKIE_EXPORT_INVALID$'):
                    read_cookie_export(self.path)

    def test_duplicates_fail_closed(self):
        for domain in ('.google.com', 'google.com', '.GOOGLE.COM'):
            self.write([self.row,dict(self.row,domain=domain)])
            with self.assertRaises(RpcError): read_cookie_export(self.path)

    def test_conflicting_expiry_cannot_revive_cookie(self):
        for expires in (-1, None, 200):
            self.write([dict(self.row, expires=expires, expirationDate=99)])
            with self.assertRaises(RpcError): read_cookie_export(self.path,now=100)

    def test_falsey_partition_metadata_not_flattened(self):
        for partition in ('', {}, False):
            self.write([dict(self.row, partitionKey=partition)])
            with self.assertRaises(RpcError): read_cookie_export(self.path)

    def test_invalid_file_never_exposes_secret(self):
        self.path.write_text('test-secret invalid json', encoding='utf-8')
        with self.assertRaises(RpcError) as raised: read_cookie_export(self.path)
        self.assertNotIn('test-secret', str(raised.exception))

    def session(self):
        self.write([self.row])
        runtime = SimpleNamespace(project_identity='11111111-2222-3333-4444-555555555555',project_url='https://flow.google.com/project/11111111-2222-3333-4444-555555555555')
        factory = MagicMock()
        session = CookieBrowserRpcSession(runtime,cookie_file=self.path,playwright_factory=factory)
        session.meta = MagicMock(return_value={})
        return session,factory

    def test_session_owns_browser_and_does_not_connect_cdp(self):
        session,factory = self.session()
        driver = factory.return_value.start.return_value
        browser = driver.chromium.launch.return_value
        with session: session.meta.assert_called_once()
        driver.chromium.connect_over_cdp.assert_not_called()
        browser.close.assert_called_once()
        driver.stop.assert_called_once()

    def test_navigation_failure_closes_and_redacts(self):
        session,factory = self.session()
        driver = factory.return_value.start.return_value
        browser = driver.chromium.launch.return_value
        browser.new_context.return_value.new_page.return_value.goto.side_effect = RuntimeError('test-secret')
        with self.assertRaisesRegex(RpcError, '^FLOW_COOKIE_SESSION_UNAVAILABLE$'): session.__enter__()
        browser.close.assert_called_once()
        driver.stop.assert_called_once()

    def test_wrong_origin_stops_before_browser(self):
        session,factory = self.session()
        session.runtime.project_url = 'https://evil.test/project/' + session.runtime.project_identity
        with self.assertRaises(RpcError): session.__enter__()
        factory.assert_not_called()

    def test_cleanup_failure_does_not_skip_driver_or_leak(self):
        session,factory = self.session()
        driver = factory.return_value.start.return_value
        browser = driver.chromium.launch.return_value
        browser.close.side_effect = RuntimeError('test-secret')
        with session: pass
        driver.stop.assert_called_once()
        self.assertIsNone(session.browser)
        self.assertIsNone(session.pw)

    def test_named_factory_pins_revision_and_never_uses_plaintext_file(self):
        store = MagicMock()
        store.get_account.return_value = {'account_id':'daily','revision':1,'cookies':[self.row]}
        factory = NamedCookieSessionFactory('daily',1,store=store)
        session = factory(SimpleNamespace())
        self.assertIsNone(session.cookie_file)
        self.assertEqual(factory.binding,{'mode':'cookie_owned','account_id':'daily','revision':1})
        self.assertNotIn('test-secret',str(factory.binding))
        store.get_account.return_value['revision']=2
        with self.assertRaisesRegex(RpcError,'REVISION_CHANGED'): factory(SimpleNamespace())


if __name__ == '__main__': unittest.main()

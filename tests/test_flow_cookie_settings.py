import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from story_auto.application.operator import OperatorService, OperatorServiceError


class CookieSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service=OperatorService(Path(self.tmp.name))

    def test_configured_is_not_live_verified(self):
        with patch('story_auto.providers.flow.cookie_accounts.FlowCookieAccountStore') as store:
            store.return_value.list_accounts.return_value=[{'account_id':'daily','revision':1,'configured':True}]
            result=self.service.flow_cookie_connection_status()
            self.assertEqual(result['status'],'CONFIGURED')
            self.assertFalse(result['live_verified'])

    def test_generation_gate_requires_enabled_and_exact_valid_project(self):
        project='11111111-2222-3333-4444-555555555555'
        with patch('story_auto.providers.flow.cookie_accounts.FlowCookieAccountStore') as store:
            store.return_value.list_accounts.return_value=[]
            for toggle,identity,expected in [('0',project,False),('1','invalid',False),('1',project,True)]:
                with patch.dict('os.environ',{'STORY_AUTO_FLOW_RPC_EXPERIMENTAL':toggle,'STORY_AUTO_FLOW_RPC_PROJECT':identity}):
                    result=self.service.flow_cookie_connection_status()
                    self.assertEqual(result['generation_enabled'],expected)
                    self.assertEqual(result['generation_project_url'],f'https://flow.google.com/project/{project}' if expected else None)
                    self.assertFalse(result['live_verified'])

    def test_remove_requires_explicit_confirmation_and_pins_displayed_revision(self):
        with patch('story_auto.providers.flow.cookie_accounts.FlowCookieAccountStore') as store:
            with self.assertRaisesRegex(OperatorServiceError,'CONFIRMATION_REQUIRED'):
                self.service.remove_flow_cookie_account('daily',3)
            store.return_value.remove_account.assert_not_called()
            store.return_value.remove_account.return_value={'account_id':'daily','removed':True}
            store.return_value.list_accounts.return_value=[]
            result=self.service.remove_flow_cookie_account('daily',3,confirm_remove=True)
            store.return_value.remove_account.assert_called_once_with('daily',expected_revision=3)
            self.assertTrue(result['removed'])
            self.assertFalse(result['configured'])

    def test_connection_check_cannot_send_cookies_to_other_origin(self):
        for url in ('http://flow.google.com/project/11111111-2222-3333-4444-555555555555',
                    'https://evil.test/project/11111111-2222-3333-4444-555555555555',
                    'https://flow.google.com@evil.test/project/11111111-2222-3333-4444-555555555555'):
            with self.assertRaises(OperatorServiceError): self.service.test_flow_cookie_account('daily',url)

    def test_live_check_is_read_only_and_revision_pinned(self):
        with patch('story_auto.providers.flow.cookie_accounts.FlowCookieAccountStore') as store, \
             patch('story_auto.providers.flow.cookie_session.NamedCookieSessionFactory') as factory:
            store.return_value.get_account.return_value={'revision':3}
            session=factory.return_value.return_value.__enter__.return_value
            session.catalog.return_value=[]
            result=self.service.test_flow_cookie_account('daily','https://flow.google.com/project/11111111-2222-3333-4444-555555555555')
            self.assertEqual(result['status'],'READ_VERIFIED')
            self.assertEqual(result['generations'],0)
            factory.assert_called_once_with('daily',3,store=store.return_value)
            session.upload.assert_not_called(); session.submit.assert_not_called()

    def test_upstream_unknown_exception_not_reflected(self):
        with patch('story_auto.providers.flow.cookie_accounts.FlowCookieAccountStore') as store, \
             patch('story_auto.providers.flow.cookie_session.NamedCookieSessionFactory') as factory:
            store.return_value.get_account.return_value={'revision':1}
            factory.return_value.side_effect=RuntimeError('cookie-secret')
            result=self.service.test_flow_cookie_account('daily','https://flow.google.com/project/11111111-2222-3333-4444-555555555555')
            self.assertNotIn('cookie-secret',str(result))
            self.assertFalse(result['live_verified'])

    def test_http_structured_oversize_export_does_not_write(self):
        import json
        import threading
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        from story_auto.ui import create_server
        from story_auto.providers.flow.cookie_accounts import FlowCookieAccountStore
        target = Path(self.tmp.name)/'isolated-accounts.json'
        store = FlowCookieAccountStore(target)
        server = create_server(self.tmp.name,port=0)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with patch('story_auto.providers.flow.cookie_accounts.FlowCookieAccountStore',return_value=store):
                request = Request(f'http://127.0.0.1:{server.server_address[1]}/api/settings/flow-cookie/save',
                                  data=json.dumps({'account_id':'daily','cookies':[{'name':'SID','domain':'.google.com','value':'x'*(1024*1024+1)}]}).encode(),
                                  headers={'Content-Type':'application/json'})
                with self.assertRaises(HTTPError) as raised: urlopen(request,timeout=5)
                self.assertEqual(raised.exception.code,400)
                result = json.loads(raised.exception.read())
                self.assertEqual(result['error'],'Flow cookie export is invalid or expired.')
                self.assertFalse(target.exists())
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_http_remove_requires_literal_confirmation_and_passes_revision(self):
        import json
        import threading
        from urllib.request import Request, urlopen
        from story_auto.ui import create_server
        server=create_server(self.tmp.name,port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            service=server.RequestHandlerClass.service
            with patch.object(service,'remove_flow_cookie_account',return_value={'removed':False}) as remove:
                for supplied,expected in [(True,True),(False,False),('true',False),(1,False),(None,False)]:
                    request=Request(f'http://127.0.0.1:{server.server_address[1]}/api/settings/flow-cookie/remove',
                        data=json.dumps({'account_id':'daily','expected_revision':7,'confirm_remove':supplied}).encode(),
                        headers={'Content-Type':'application/json'})
                    with urlopen(request,timeout=5) as response:
                        self.assertEqual(response.status,200)
                    remove.assert_called_with('daily',7,confirm_remove=expected)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__=='__main__': unittest.main()

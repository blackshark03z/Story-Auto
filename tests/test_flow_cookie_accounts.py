from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_auto.providers.flow.cookie_accounts import FlowCookieAccountError, FlowCookieAccountStore


def _protect(value: str, entropy: bytes) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _unprotect(value: bytes, entropy: bytes) -> str:
    return value.decode("utf-8")


class FlowCookieAccountStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "flow-cookie-accounts.json"
        self.protect = patch("story_auto.providers.flow.cookie_accounts._protect", _protect)
        self.unprotect = patch("story_auto.providers.flow.cookie_accounts._unprotect", _unprotect)
        self.protect.start(); self.unprotect.start()
        self.addCleanup(self.protect.stop); self.addCleanup(self.unprotect.stop); self.addCleanup(self.temp.cleanup)
        self.row = {"name": "SID", "value": "cookie-secret-one", "domain": ".google.com", "path": "/", "secure": True, "httpOnly": True, "expires": -1}

    def test_save_refresh_list_and_get_are_alias_scoped(self):
        store = FlowCookieAccountStore(self.path)
        self.assertEqual(store.preview_account("daily", [self.row]), {
            "account_id": "daily", "cookie_count": 1, "configured": False, "replacing": False, "current_revision": None,
        })
        self.assertEqual(store.save_account("daily", [self.row]), {"account_id": "daily", "revision": 1})
        changed = dict(self.row, value="cookie-secret-two")
        self.assertEqual(store.save_account("daily", [changed]), {"account_id": "daily", "revision": 2})
        self.assertEqual(store.save_account("backup", [self.row]), {"account_id": "backup", "revision": 1})
        self.assertEqual(store.list_accounts(), [
            {"account_id": "backup", "configured": True, "revision": 1},
            {"account_id": "daily", "configured": True, "revision": 2},
        ])
        got = store.get_account("daily")
        self.assertEqual(got["account_id"], "daily")
        self.assertEqual(got["revision"], 2)
        self.assertEqual(got["cookies"][0]["value"], "cookie-secret-two")
        persisted = self.path.read_text(encoding="utf-8")
        self.assertNotIn("cookie-secret-one", persisted)
        self.assertNotIn("cookie-secret-two", persisted)

    def test_structured_input_cannot_bypass_cookie_size_limit(self):
        store = FlowCookieAccountStore(self.path)
        for value in ([dict(self.row, value='x' * (1024*1024+1))],
                      {'cookies':[dict(self.row, value='x' * (1024*1024+1))]}):
            with self.assertRaises(FlowCookieAccountError):
                store.save_account('daily', value)
        self.assertFalse(self.path.exists())

    def test_remove_erases_secret_preserves_other_alias_and_revision_tombstone(self):
        from story_auto.providers.flow.cookie_session import NamedCookieSessionFactory
        from story_auto.providers.flow.rpc_transport import RpcError
        store=FlowCookieAccountStore(self.path)
        store.save_account('daily',[self.row])
        store.save_account('backup',[self.row])
        old_factory=NamedCookieSessionFactory('daily',1,store=store)
        store.remove_account('daily',expected_revision=1)
        payload=json.loads(self.path.read_text())
        tombstone=next(row for row in payload['accounts'] if row['account_id']=='daily')
        self.assertEqual(tombstone,{'account_id':'daily','revision':2,'removed':True})
        self.assertEqual([a['account_id'] for a in store.list_accounts()],['backup'])
        with self.assertRaises(FlowCookieAccountError): store.get_account('daily')
        self.assertFalse(store.preview_account('daily',[self.row])['replacing'])
        self.assertEqual(store.save_account('daily',[self.row])['revision'],3)
        with self.assertRaisesRegex(RpcError,'REVISION_CHANGED'): old_factory(None)
        self.assertEqual(store.get_account('backup')['revision'],1)

    def test_stale_removal_and_invalid_revision_leave_new_secret_intact(self):
        store=FlowCookieAccountStore(self.path)
        store.save_account('daily',[self.row])
        store.save_account('daily',[dict(self.row,value='new-secret')])
        for revision in (1,True,None,'2'):
            with self.assertRaises(FlowCookieAccountError):
                store.remove_account('daily',expected_revision=revision)
        self.assertEqual(store.get_account('daily')['cookies'][0]['value'],'new-secret')

    def test_tombstone_with_secret_or_invalid_marker_is_rejected(self):
        store=FlowCookieAccountStore(self.path)
        store.save_account('daily',[self.row])
        store.remove_account('daily',expected_revision=1)
        payload=json.loads(self.path.read_text())
        for changes in ({'removed':False},{'blob':'hidden-secret'}):
            damaged=json.loads(json.dumps(payload))
            damaged['accounts'][0].update(changes)
            self.path.write_text(json.dumps(damaged))
            with self.assertRaises(FlowCookieAccountError): store.list_accounts()

    def test_legacy_store_upgrade_retains_revision_and_other_credentials(self):
        store=FlowCookieAccountStore(self.path)
        store.save_account('daily',[self.row])
        store.save_account('backup',[dict(self.row,value='backup-secret')])
        payload=json.loads(self.path.read_text())
        payload['schema_version']='1.0.0'
        payload['accounts'][1]['revision']=7
        self.path.write_text(json.dumps(payload))
        self.assertEqual(store.get_account('daily')['revision'],7)
        store.remove_account('daily',expected_revision=7)
        upgraded=json.loads(self.path.read_text())
        self.assertEqual(upgraded['schema_version'],'1.1.0')
        self.assertEqual(store.get_account('backup')['cookies'][0]['value'],'backup-secret')
        self.assertEqual(store.save_account('daily',[self.row])['revision'],9)

    def test_failed_removal_write_preserves_last_durable_account(self):
        store=FlowCookieAccountStore(self.path)
        store.save_account('daily',[self.row])
        before=self.path.read_bytes()
        with patch('story_auto.providers.flow.cookie_accounts.atomic_write_json',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError): store.remove_account('daily',expected_revision=1)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(store.get_account('daily')['revision'],1)

    def test_rejects_bad_alias_invalid_expired_and_corrupt_exports_without_secret_echo(self):
        store = FlowCookieAccountStore(self.path)
        for account_id in ("", "has space", "../bad"):
            with self.assertRaises(FlowCookieAccountError):
                store.save_account(account_id, [self.row])
        expired = dict(self.row, expires=1, value="do-not-echo")
        with self.assertRaises(FlowCookieAccountError) as raised:
            store.save_account("daily", [expired])
        self.assertNotIn("do-not-echo", str(raised.exception))
        self.path.write_text('{"schema_name":"wrong"}', encoding="utf-8")
        with self.assertRaises(FlowCookieAccountError):
            store.list_accounts()

    def test_corrupt_encrypted_payload_fails_closed_and_get_missing_is_safe(self):
        store = FlowCookieAccountStore(self.path)
        self.path.write_text(json.dumps({"schema_name": "story-auto-flow-cookie-accounts", "schema_version": "1.0.0", "accounts": [{"account_id": "daily", "revision": 1, "blob": "not base64!"}]}), encoding="utf-8")
        with self.assertRaisesRegex(FlowCookieAccountError, "could not be read"):
            store.get_account("daily")
        self.path.unlink()
        with self.assertRaisesRegex(FlowCookieAccountError, "not configured"):
            store.get_account("missing")

    def test_stale_lock_file_is_not_a_lock_and_return_is_detached(self):
        self.path.with_suffix(".json.lock").parent.mkdir(parents=True, exist_ok=True)
        self.path.with_suffix(".json.lock").touch()
        store = FlowCookieAccountStore(self.path)
        store.save_account("daily", [self.row])
        got = store.get_account("daily")
        got["cookies"][0]["value"] = "mutated"
        self.assertEqual(store.get_account("daily")["cookies"][0]["value"], "cookie-secret-one")

    def test_expired_saved_account_can_be_refreshed_without_overwriting_another(self):
        store = FlowCookieAccountStore(self.path)
        future = dict(self.row, expires=200)
        with patch("story_auto.providers.flow.cookie_session.time.time", return_value=100):
            store.save_account("daily", [future])
            store.save_account("backup", [self.row])
        with patch("story_auto.providers.flow.cookie_session.time.time", return_value=201):
            with self.assertRaisesRegex(FlowCookieAccountError, "invalid or expired"):
                store.get_account("daily")
            self.assertEqual(store.list_accounts(), [
                {"account_id": "backup", "configured": True, "revision": 1},
                {"account_id": "daily", "configured": True, "revision": 1},
            ])
            refreshed = dict(self.row, value="cookie-secret-refreshed", expires=300)
            self.assertEqual(store.save_account("daily", [refreshed]), {"account_id": "daily", "revision": 2})
            self.assertEqual(store.get_account("daily")["cookies"][0]["value"], "cookie-secret-refreshed")
            self.assertEqual(store.get_account("backup")["revision"], 1)


if __name__ == "__main__":
    unittest.main()

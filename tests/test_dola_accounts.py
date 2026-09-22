from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_auto.providers.dola_cookie.accounts import DolaAccountError, DolaAccountStore


def _protect(value: str, entropy: bytes) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _unprotect(value: bytes, entropy: bytes) -> str:
    return value.decode("utf-8")


class DolaAccountStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "dola.json"
        self.protect = patch("story_auto.providers.dola_cookie.accounts._protect", _protect)
        self.unprotect = patch("story_auto.providers.dola_cookie.accounts._unprotect", _unprotect)
        self.protect.start(); self.unprotect.start()
        self.addCleanup(self.protect.stop); self.addCleanup(self.unprotect.stop); self.addCleanup(self.temp.cleanup)

    def test_preview_save_rotation_and_secret_free_listing(self):
        store = DolaAccountStore(self.path)
        first = "editor\tsessionid=first; other=value\nbackup\tsessionid=second; x=y"
        self.assertEqual(store.preview_accounts(first), {
            "incoming_count": 2, "new_count": 2, "updated_count": 0,
            "account_ids": ["backup", "editor"],
        })
        self.assertEqual(store.save_accounts(first)["saved_count"], 2)
        self.assertEqual(store.list_accounts(), [
            {"account_id": "backup", "configured": True},
            {"account_id": "editor", "configured": True},
        ])
        self.assertEqual(store.preview_accounts("editor\tsessionid=replaced"), {
            "incoming_count": 1, "new_count": 0, "updated_count": 1, "account_ids": ["editor"],
        })
        store.save_accounts("editor\tsessionid=replaced")
        self.assertEqual(store.get_cookie("editor"), "sessionid=replaced")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("replaced", json.dumps(payload))

    def test_json_format_and_invalid_headers(self):
        store = DolaAccountStore(self.path)
        store.save_accounts('[{"account_id":"main","cookie":"x=1; sessionid=ok"}]')
        self.assertEqual(store.get_cookie("main"), "x=1; sessionid=ok")
        with self.assertRaisesRegex(DolaAccountError, "sessionid"):
            store.save_accounts("main\tx=1")
        with self.assertRaisesRegex(DolaAccountError, "one line"):
            store.save_accounts([["main", "sessionid=one\ntwo"]])

    def test_remove_is_alias_scoped(self):
        store = DolaAccountStore(self.path)
        store.save_accounts("a\tsessionid=one\nb\tsessionid=two")
        self.assertEqual(store.remove_account("a"), {"removed": True, "saved_count": 1})
        self.assertEqual(store.list_accounts(), [{"account_id": "b", "configured": True}])

    def test_leftover_lock_file_does_not_block_restart(self):
        self.path.with_suffix(".json.lock").touch()
        store = DolaAccountStore(self.path)
        store.save_accounts("daily\tsessionid=fresh")
        self.assertEqual(store.get_cookie("daily"), "sessionid=fresh")

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


_TOOL = Path(__file__).parents[1] / "tools" / "goal54_elyum_preflight.py"
_SPEC = importlib.util.spec_from_file_location("goal54_elyum_preflight", _TOOL)
assert _SPEC and _SPEC.loader
_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_mod)


class ElyumPreflightToolTests(unittest.TestCase):
    def test_sse_decoder_returns_json_rpc_payload(self):
        value = _mod._decode_rpc(
            b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n',
            "text/event-stream",
        )
        self.assertEqual(value, {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})

    def test_estimate_args_compile_known_aliases_without_generation(self):
        schema = {
            "type": "object",
            "required": ["model", "duration", "resolution", "mode"],
            "properties": {
                "model": {"type": "string"},
                "duration": {"type": "integer"},
                "resolution": {"type": "string"},
                "mode": {"type": "string", "enum": ["t2v", "i2v"]},
                "count": {"type": "integer", "default": 1},
            },
        }
        args, missing = _mod._estimate_arguments(schema, "seedance-2-mini", 4, "480p")
        self.assertEqual(missing, [])
        self.assertEqual(args, {"model": "seedance-2-mini", "duration": 4, "resolution": "480p", "mode": "t2v", "count": 1})

    def test_estimate_args_infers_i2v_for_i2v_and_reference_models(self):
        schema = {
            "type": "object",
            "required": ["kind"],
            "properties": {
                "kind": {"type": "string", "enum": ["image", "video"]},
                "mode": {"type": "string", "enum": ["t2v", "i2v", "ugc", "clone"]},
                "model": {"type": "string"},
                "duration": {"type": "integer"},
            },
        }
        i2v, missing_i2v = _mod._estimate_arguments(schema, "seedance-2-fast-i2v", 4, "480p")
        ref, missing_ref = _mod._estimate_arguments(schema, "seedance-2.5-reference", 4, "480p")
        self.assertEqual(missing_i2v, [])
        self.assertEqual(missing_ref, [])
        self.assertEqual((i2v["kind"], i2v["mode"]), ("video", "i2v"))
        self.assertEqual((ref["kind"], ref["mode"]), ("video", "i2v"))

    def test_account_sanitizer_drops_identity_and_secret_fields(self):
        result = _mod._safe_account({
            "email": "owner@example.invalid",
            "apiKey": "ek_live_secret",
            "plan": "free",
            "balanceCredits": 150,
            "key": {"scopes": ["read"], "dailyCap": 50, "token": "secret"},
            "killsLeft": 1,
        })
        text = repr(result)
        self.assertNotIn("owner@example.invalid", text)
        self.assertNotIn("ek_live_secret", text)
        self.assertNotIn("secret", text)
        self.assertIn("150", text)
        self.assertIn("free", text)
        self.assertIn("1", text)

    def test_seedance_filter_excludes_unrelated_models(self):
        models = {"video": [
            {"slug": "seedance-2-mini", "name": "Seedance 2.0 Mini", "resolutions": ["480p", "720p"]},
            {"slug": "other-video", "name": "Other Video"},
        ]}
        rows = _mod._seedance_models(models)
        self.assertTrue(rows)
        self.assertTrue(all("seedance" in repr(row).lower() for row in rows))
        self.assertNotIn("Other Video", repr(rows))


if __name__ == "__main__":
    unittest.main()

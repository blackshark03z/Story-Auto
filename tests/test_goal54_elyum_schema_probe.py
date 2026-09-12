from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


TOOLS = Path(__file__).parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
_SPEC = importlib.util.spec_from_file_location("goal54_elyum_schema_probe", TOOLS / "goal54_elyum_schema_probe.py")
assert _SPEC and _SPEC.loader
_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_mod)


class ElyumSchemaProbeTests(unittest.TestCase):
    def test_selects_only_target_schemas(self):
        tools = [
            {"name": "elyum_generate", "description": "create job", "inputSchema": {"type": "object", "required": ["model"]}},
            {"name": "elyum_account", "description": "read account", "inputSchema": {"type": "object"}},
            {"name": "elyum_keep", "description": "charge held credits", "inputSchema": {"type": "object", "required": ["jobId"]}},
        ]
        result = _mod.select_tool_schemas(tools)
        self.assertEqual(set(result), {"elyum_keep"})
        self.assertEqual(result["elyum_keep"]["inputSchema"]["required"], ["jobId"])
        self.assertNotIn("elyum_generate", result)
        self.assertNotIn("elyum_account", result)

    def test_does_not_copy_unrelated_tool_metadata(self):
        tools = [{"name": "elyum_kill", "description": 123, "inputSchema": "not-a-schema", "secret": "never-copy"}]
        result = _mod.select_tool_schemas(tools)
        self.assertEqual(result, {"elyum_kill": {"description": None, "inputSchema": {}}})
        self.assertNotIn("secret", repr(result))

    def test_discovers_make_video_candidates_without_invoking_them(self):
        tools = [
            {"name": "elyum_make_video", "description": "make video", "inputSchema": {"type": "object"}},
            {"name": "elyum_account", "description": "read", "inputSchema": {"type": "object"}},
        ]
        result = _mod.select_creation_candidates(tools)
        self.assertEqual(set(result), {"elyum_make_video"})
        self.assertEqual(result["elyum_make_video"]["description"], "make video")


if __name__ == "__main__":
    unittest.main()

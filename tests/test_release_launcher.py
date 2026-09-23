from __future__ import annotations

import importlib.util
import tempfile
import threading
import unittest
from pathlib import Path

from story_auto.ui.server import create_server


class ReleaseLauncherTests(unittest.TestCase):
    def test_same_code_with_other_runtime_is_not_this_installation(self):
        launcher_path=Path(__file__).resolve().parents[1]/"tools"/"launch_story_auto.py"
        spec=importlib.util.spec_from_file_location("story_auto_release_launcher_test",launcher_path)
        assert spec and spec.loader
        launcher=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        with tempfile.TemporaryDirectory() as served, tempfile.TemporaryDirectory() as other:
            server=create_server(served,port=0)
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            try:
                launcher.PORT=server.server_address[1]
                launcher.RUNTIME_ROOT=Path(other)
                self.assertEqual(launcher.listener_state(),"occupied")
                launcher.RUNTIME_ROOT=Path(served)
                self.assertEqual(launcher.listener_state(),"this_release")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()

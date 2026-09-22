import io
import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from story_auto.providers.flow.cdp import CdpPage
from story_auto.providers.flow.session import FlowRuntime


class HandshakeTests(unittest.TestCase):
    def connect(self, host, ws_host=None, ws_port=9333, target_suffix=''):
        runtime = FlowRuntime(Path('.'), f'http://{host}:9333',
                              'https://flow.google.com/project/test', 'test')
        address = f'ws://{ws_host or host}:{ws_port}/devtools/page/test'
        opener = Mock(return_value=io.BytesIO(json.dumps([{
            'type':'page', 'url':runtime.project_url + target_suffix,
            'webSocketDebuggerUrl':address, 'id':'test'}]).encode()))
        connect = Mock()
        CdpPage.open(runtime, opener=opener, ws_connect=connect)
        return connect

    def test_native_loopback_has_no_synthetic_origin(self):
        self.connect('127.0.0.1').assert_called_once_with(
            'ws://127.0.0.1:9333/devtools/page/test', timeout=30, suppress_origin=True)

    def test_remote_behavior_unchanged(self):
        self.connect('remote.example').assert_called_once_with(
            'ws://remote.example:9333/devtools/page/test', timeout=30)

    def test_mismatched_address_does_not_get_loopback_option(self):
        self.connect('127.0.0.1', 'remote.example').assert_called_once_with(
            'ws://remote.example:9333/devtools/page/test', timeout=30)

    def test_different_port_does_not_get_loopback_option(self):
        self.connect('127.0.0.1', ws_port=9444).assert_called_once_with(
            'ws://127.0.0.1:9444/devtools/page/test', timeout=30)

    def test_prefix_collision_rejected(self):
        from story_auto.providers.flow.session import FlowSessionError
        with self.assertRaises(FlowSessionError):
            self.connect('127.0.0.1', target_suffix='-evil')

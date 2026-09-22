import tempfile
import threading
import unittest
from http.client import HTTPConnection

from story_auto.core.project import ProjectConfig, RuntimeLayout, create_project
from story_auto.ui.server import create_server


class AssetRangeTests(unittest.TestCase):
    def test_video_asset_supports_seek_ranges_and_invalid_range(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = RuntimeLayout.from_root(directory)
            paths = create_project(runtime, ProjectConfig('prj_range'))
            payload = bytes(range(256)) * 20
            paths.artifact_path('output/final.mp4').write_bytes(payload)
            server = create_server(directory, port=0)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                url = '/api/projects/prj_range/asset?path=output%2Ffinal.mp4'
                connection = HTTPConnection('127.0.0.1', server.server_address[1])
                for range_header, status, content_range, expected in (
                    ('bytes=100-199', 206, 'bytes 100-199/5120', payload[100:200]),
                    ('bytes=5000-', 206, 'bytes 5000-5119/5120', payload[5000:]),
                    ('bytes=-32', 206, 'bytes 5088-5119/5120', payload[-32:]),
                    ('bytes=99999-', 416, 'bytes */5120', b''),
                ):
                    with self.subTest(range_header=range_header):
                        connection.request('GET', url, headers={'Range':range_header})
                        response = connection.getresponse()
                        self.assertEqual(response.status, status)
                        self.assertEqual(response.getheader('Content-Range'), content_range)
                        self.assertEqual(response.read(), expected)
                connection.request('GET', url)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader('Accept-Ranges'), 'bytes')
                self.assertEqual(response.read(), payload)
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                worker.join(5)

import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from rodent_watch.ui import Monitor, make_server


class UITests(unittest.TestCase):
    def test_preview_hides_stale_frames(self):
        m = Monitor(Path('.cache'), Path('output'))
        class Source:
            error = ''
            def snapshot(self): return 1, time.monotonic()-10, b'old'
        m.source = Source()
        self.assertIsNone(m.preview())
        m.source.snapshot = lambda: (2, time.monotonic(), b'current')
        self.assertEqual(m.preview(), b'current')

    def test_start_rejects_duplicate_and_stop_releases_worker(self):
        m = Monitor(Path('.cache'), Path('output'))
        def fake(args, stop_event, observer): stop_event.wait(3)
        with patch('rodent_watch.ui.run_live', fake):
            m.start({'camera_id': 'phone'})
            with self.assertRaisesRegex(ValueError, 'already running'): m.start({'camera_id': 'phone'})
            m.stop()
            m.thread.join(2)
            self.assertFalse(m.state()['active'])
            self.assertEqual(m.state()['status'], 'Stopped')

    def test_http_access_controls_and_no_arbitrary_file_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            m = Monitor(Path(temp), Path(temp))
            server = make_server(m, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
            try:
                conn.request('GET', '/')
                r = conn.getresponse()
                self.assertEqual(r.status, 200)
                self.assertIn(m.token.encode(), r.read())
                conn.request('POST', '/api/start', '{}')
                r = conn.getresponse(); self.assertEqual(r.status, 403); r.read()
                conn.request('GET', '/', headers={'Host': 'evil.example'})
                r = conn.getresponse(); self.assertEqual(r.status, 403); r.read()
                conn.request('GET', '/sighting/../../pyproject.toml')
                r = conn.getresponse(); self.assertEqual(r.status, 404); r.read()
                conn.request('POST', '/api/start', json.dumps({'camera_id': 'phone', 'threshold': 'nan'}),
                             {'X-Monitor-Token': m.token})
                r = conn.getresponse(); self.assertEqual(r.status, 400); r.read()
                self.assertIsNone(m.thread)
            finally:
                conn.close(); server.shutdown(); server.server_close(); thread.join()

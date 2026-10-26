import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from PIL import Image

from rodent_watch.cli import parser
from rodent_watch.live import LatestCamera, run_live


def jpeg():
    buffer = io.BytesIO()
    Image.new('RGB', (160, 120), 'grey').save(buffer, format='JPEG')
    return buffer.getvalue()


class LiveTests(unittest.TestCase):
    def test_capture_drains_to_latest_frame_and_stops_child(self):
        line = json.dumps(dict(jpeg=base64.b64encode(jpeg()).decode()))
        code = f'import time\nfor i in range(100): print({line!r}, flush=True)\ntime.sleep(10)'
        camera = LatestCamera('fake', command=[sys.executable, '-u', '-c', code])
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                snapshot = camera.snapshot()
                if snapshot and snapshot[0] == 100:
                    break
                time.sleep(0.01)
            self.assertEqual(camera.snapshot()[0], 100)
            self.assertEqual(camera.snapshot()[2], jpeg())
        finally:
            camera.close()
        self.assertIsNotNone(camera.process.poll())
        self.assertFalse(camera.reader.is_alive())

    def test_live_reconnect_preserves_active_sighting_and_writes_only_stills(self):
        sources = []
        class Source:
            def __init__(self, camera_id):
                self.camera_id = camera_id
                self.process = self
                self.error = 'simulated disconnect'
                self.frames = 0
                self.closed = False
                sources.append(self)
            def snapshot(self):
                self.frames += 1
                return self.frames, time.monotonic(), jpeg()
            def poll(self):
                return 1 if self.frames > 3 else None
            def close(self):
                self.closed = True
        class Detector:
            def __init__(self, *args): pass
            def detect(self, image):
                return [dict(label='rodent', phrase='fake', confidence=0.9, box=[10, 20, 80, 90])]
        with tempfile.TemporaryDirectory() as temp:
            args = parser().parse_args(['live', '--camera-id', 'camera-test-id',
                                       '--output', temp, '--max-seconds', '0.5',
                                       '--retry-seconds', '0.05', '--sample-fps', '100', '--cooldown', '0'])
            folder = run_live(args, detector_factory=Detector, source_factory=Source)
            summary = json.loads((folder / 'summary.json').read_text())
            self.assertGreaterEqual(summary['reconnects'], 1)
            self.assertNotIn('camera_id', summary)
            self.assertNotIn('camera-test-id', (folder / 'report.html').read_text())
            self.assertEqual(summary['alerts'], 1)
            self.assertGreater(summary['frames_analysed'], 1)
            self.assertTrue(all(s.closed for s in sources))
            self.assertTrue(all(s.camera_id == 'camera-test-id' for s in sources))
            self.assertEqual({p.suffix for p in folder.iterdir()}, {'.html', '.json', '.jsonl', '.jpg'})
            self.assertIn('Live elapsed', (folder / 'report.html').read_text())

    def test_stalled_camera_retries_and_exits_at_duration_limit(self):
        sources = []
        class Stalled:
            def __init__(self, camera_id):
                self.process = self
                self.error = ''
                self.closed = False
                sources.append(self)
            def snapshot(self): return None
            def poll(self): return None
            def close(self): self.closed = True
        class Detector:
            def __init__(self, *args): pass
            def detect(self, image): raise AssertionError('No frame should be analysed')
        with tempfile.TemporaryDirectory() as temp:
            args = parser().parse_args(['live', '--camera-id', 'fake', '--output', temp,
                                       '--max-seconds', '.3', '--stall-timeout', '.05', '--retry-seconds', '.05'])
            folder = run_live(args, detector_factory=Detector, source_factory=Stalled)
            summary = json.loads((folder / 'summary.json').read_text())
            self.assertEqual(summary['frames_analysed'], 0)
            self.assertGreater(summary['reconnects'], 0)
            self.assertTrue(all(s.closed for s in sources))

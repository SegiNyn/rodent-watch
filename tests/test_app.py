import json
from pathlib import Path
import tempfile
import unittest

from rodent_watch.events import SightingGate
from rodent_watch.detector import iou
from rodent_watch.cli import analyse, parser


class GateTests(unittest.TestCase):
    def test_continuous_sighting_never_repeats(self):
        gate = SightingGate(5, 30)
        self.assertTrue(gate.update(0, True))
        for t in range(1, 300):
            self.assertFalse(gate.update(t, True))

    def test_flicker_clear_and_cooldown(self):
        gate = SightingGate(5, 30)
        self.assertTrue(gate.update(0, True))
        gate.update(1, False)
        self.assertFalse(gate.update(3, True))
        gate.update(4, False)
        gate.update(9, False)
        self.assertFalse(gate.update(10, True))
        self.assertTrue(gate.update(30, True))
        self.assertFalse(gate.update(90, True))

    def test_iou(self):
        self.assertEqual(iou([0, 0, 10, 10], [0, 0, 10, 10]), 1)
        self.assertEqual(iou([0, 0, 10, 10], [20, 20, 30, 30]), 0)


class PipelineTests(unittest.TestCase):
    def test_video_sampling_images_and_logs_without_video_output(self):
        import cv2
        import numpy as np
        from PIL import Image

        class FakeDetector:
            def __init__(self, *args):
                self.index = 0

            def detect(self, image):
                self.index += 1
                # 0, 0.5, 1s positive; clear frames 1.5 through 3s; positive at 3.5s.
                if self.index in (1, 2, 3, 8):
                    return [dict(label="rodent", phrase="test only", confidence=0.8,
                                 box=[20, 20, 80, 80])]
                return []

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = root / "synthetic.avi"
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (160, 120))
            self.assertTrue(writer.isOpened())
            for _ in range(40):
                writer.write(np.zeros((120, 160, 3), dtype=np.uint8))
            writer.release()
            args = parser().parse_args(["video", str(video), "--output", str(root / "results"),
                                       "--clear-seconds", "1", "--cooldown", "0"])
            folder = analyse(args, detector_factory=FakeDetector)
            summary = json.loads((folder / "summary.json").read_text())
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["input"], "<local video>")
            self.assertNotIn(str(video), (folder / "report.html").read_text())
            self.assertEqual(summary["frames_analysed"], 8)
            self.assertEqual(summary["alerts"], 2)
            self.assertEqual(summary["positive_frames"], 4)
            images = list(folder.glob("*.jpg"))
            self.assertEqual(len(images), 2)
            with Image.open(images[0]) as image:
                self.assertEqual(image.size, (160, 120))
                self.assertGreater(max(image.getpixel((20, 40))), 50)
            self.assertEqual({f.suffix for f in folder.iterdir()}, {".jpg", ".json", ".jsonl", ".html"})
            self.assertEqual(len((folder / "frames.jsonl").read_text().splitlines()), 8)

    def test_missing_video_is_rejected_before_loading_model(self):
        args = parser().parse_args(["video", "/not/a/real/video.mp4"])
        with self.assertRaisesRegex(ValueError, "does not exist"):
            analyse(args)


if __name__ == "__main__":
    unittest.main()

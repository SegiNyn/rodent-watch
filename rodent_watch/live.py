"""Native macOS camera frames, bounded to one latest frame in memory."""
import base64
from datetime import datetime
import io
import json
from pathlib import Path
import subprocess
import threading
import time
from uuid import uuid4

from .detector import MODEL_ID, PROMPT, RodentDetector
from .events import SightingGate

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / '.cache/Rodent Watch Camera.app/Contents/MacOS/RodentWatchCapture'


def helper_path():
    if not HELPER.is_file():
        raise ValueError('Build camera support first: ./scripts/build-camera.sh')
    return HELPER


def list_cameras():
    result = subprocess.run([str(helper_path()), '--list'], capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'Camera discovery failed')
    cameras = [json.loads(line) for line in result.stdout.splitlines() if line]
    for camera in cameras:
        print(f"{camera['name']}\n  ID: {camera['id']}\n  Type: {camera['type']}")
    if not cameras:
        print('No cameras found. Enable Continuity Camera, lock and mount your iPhone near the Mac, then retry.')
    return cameras


class LatestCamera:
    """Drain capture independently of inference. No video or temporary frames on disk."""
    def __init__(self, camera_id, command=None):
        self.lock = threading.Lock()
        self.latest = None
        self.sequence = 0
        self.error = ''
        self.process = subprocess.Popen(command or [str(helper_path()), '--camera', camera_id],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.errors = threading.Thread(target=self._errors, daemon=True)
        self.reader.start()
        self.errors.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                record = json.loads(line)
                jpeg = base64.b64decode(record['jpeg'], validate=True)
                with self.lock:
                    self.sequence += 1
                    self.latest = (self.sequence, time.monotonic(), jpeg)
        except Exception as exc:
            self.error = f'Camera stream error: {exc}'

    def _errors(self):
        for line in self.process.stderr:
            self.error = line.decode(errors='replace').strip()[:2000]
            print(f'Camera: {self.error}', flush=True)

    def snapshot(self):
        with self.lock:
            return self.latest

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.reader.join(timeout=2)
        self.errors.join(timeout=2)
        self.process.stdout.close()
        self.process.stderr.close()


def run_live(args, detector_factory=RodentDetector, source_factory=LatestCamera,
             stop_event=None, observer=None):
    from PIL import Image
    from .cli import annotate, write_report
    stop_event = stop_event or threading.Event()
    observer = observer or (lambda *args: None)
    observer('status', {'status': 'Loading model'})
    print('Loading local model before opening the camera...', flush=True)
    detector = detector_factory(args.cache, args.threshold, args.text_threshold, args.device)
    if stop_event.is_set():
        return None
    folder = args.output / ('live-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:6])
    folder.mkdir(parents=True)
    started = time.monotonic()
    summary = dict(status='waiting for camera', mode='live',
                   model=MODEL_ID, prompt=PROMPT, threshold=args.threshold,
                   text_threshold=args.text_threshold, sample_fps=args.sample_fps,
                   device=args.device, cooldown_seconds=args.cooldown,
                   clear_seconds=args.clear_seconds, frames_analysed=0, alerts=0,
                   positive_frames=0, reconnects=0, started_at=datetime.now().astimezone().isoformat(),
                   timestamp_note='Elapsed monotonic seconds since live capture started; wall time recorded per frame.')
    observer('folder', folder)
    events = []
    gate = SightingGate(args.clear_seconds, args.cooldown)
    source = None
    last_frame_time = None
    last_progress = started
    try:
        with (folder / 'frames.jsonl').open('w') as log, (folder / 'events.jsonl').open('w') as event_log:
            while not stop_event.is_set() and (args.max_seconds is None or time.monotonic() - started < args.max_seconds):
                source = source_factory(args.camera_id)
                observer('source', source)
                opened = time.monotonic()
                last_received = opened
                last_sequence = 0
                last_inference = float('-inf')
                summary['status'] = 'waiting for camera'
                observer('status', dict(summary))
                write_report(folder, summary, events)
                print('Waiting for selected camera. Allow the macOS Camera permission prompt if shown.', flush=True)
                try:
                    while not stop_event.is_set() and (args.max_seconds is None or time.monotonic() - started < args.max_seconds):
                        now = time.monotonic()
                        snapshot = source.snapshot()
                        if snapshot is not None:
                            sequence, received, jpeg = snapshot
                            last_received = received
                        if source.process.poll() is not None or now - last_received > args.stall_timeout:
                            summary['status'] = 'disconnected; retrying selected camera'
                            print(f"Camera unavailable or stalled. {source.error} Retrying in {args.retry_seconds:g}s.", flush=True)
                            # Unknown intervals cannot count as observed animal absence.
                            gate.absent_since = None
                            observer('status', {**summary, 'error': source.error})
                            write_report(folder, summary, events)
                            break
                        if snapshot is None or sequence == last_sequence or now - last_inference < 1 / args.sample_fps:
                            time.sleep(0.05)
                            continue
                        last_sequence = sequence
                        last_inference = now
                        if last_frame_time is not None and received - last_frame_time > args.stall_timeout:
                            gate.absent_since = None
                        last_frame_time = received
                        timestamp = received - started
                        with Image.open(io.BytesIO(jpeg)) as decoded:
                            image = decoded.convert('RGB')
                        inference_start = time.monotonic()
                        detections = detector.detect(image)
                        inference_seconds = time.monotonic() - inference_start
                        summary['status'] = 'running'
                        summary['frames_analysed'] += 1
                        summary['positive_frames'] += bool(detections)
                        summary['last_frame_at'] = datetime.now().astimezone().isoformat()
                        summary['last_inference_seconds'] = round(inference_seconds, 3)
                        record = dict(frame=sequence, video_seconds=timestamp,
                                      captured_at=datetime.fromtimestamp(time.time() - (time.monotonic() - received)).astimezone().isoformat(),
                                      detections=detections, inference_seconds=inference_seconds)
                        observer('result', (image, record, dict(summary)))
                        log.write(json.dumps(record) + '\n')
                        log.flush()
                        if gate.update(timestamp, bool(detections)):
                            name = f'sighting-{len(events) + 1:04d}-{timestamp:010.2f}s.jpg'
                            annotate(image, detections, timestamp, live=True).save(folder / name, quality=92)
                            event = dict(**record, image=name)
                            events.append(event)
                            event_log.write(json.dumps(event) + '\n')
                            event_log.flush()
                            summary['alerts'] = len(events)
                            observer('event', event)
                            print(f"\aDETECTION: {folder / name}", flush=True)
                            write_report(folder, summary, events)
                        if time.monotonic() - last_progress >= 10:
                            print(f"Live: {summary['frames_analysed']} frames analysed, {len(events)} sightings; last inference {inference_seconds:.2f}s", flush=True)
                            write_report(folder, summary, events)
                            last_progress = time.monotonic()
                finally:
                    source.close()
                    source = None
                    observer('source', None)
                if stop_event.is_set() or (args.max_seconds is not None and time.monotonic() - started >= args.max_seconds):
                    break
                summary['reconnects'] += 1
                # Preserve active sighting and cooldown across connection loss.
                deadline = time.monotonic() + args.retry_seconds
                while not stop_event.is_set() and time.monotonic() < deadline:
                    if stop_event.is_set() or (args.max_seconds is not None and time.monotonic() - started >= args.max_seconds):
                        break
                    time.sleep(0.05)
            summary['status'] = ('stopped by user' if stop_event.is_set() else
                                 'duration limit reached' if summary['frames_analysed'] else
                                 'duration limit reached; no camera frames received — check camera permission and iPhone readiness')
    except KeyboardInterrupt:
        summary['status'] = 'stopped by user'
    except Exception:
        summary['status'] = 'failed; partial results'
        raise
    finally:
        if source is not None:
            source.close()
        summary['elapsed_seconds'] = round(time.monotonic() - started, 2)
        observer('status', dict(summary))
        write_report(folder, summary, events)
        print(f"{summary['status']}. Report: {folder / 'report.html'}", flush=True)
    return folder

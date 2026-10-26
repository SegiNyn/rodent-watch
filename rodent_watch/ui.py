"""Loopback-only browser UI. Camera frames remain in memory."""
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit
import webbrowser

from .cli import parser, annotate
from .live import list_cameras, run_live


class Monitor:
    def __init__(self, cache, output):
        self.cache, self.output = cache, output
        self.lock = threading.RLock()
        self.thread = None
        self.stop_event = threading.Event()
        self.source = None
        self.folder = None
        self.result = None
        self.events = []
        self.info = {'status': 'Ready', 'frames_analysed': 0, 'alerts': 0}
        self.token = secrets.token_urlsafe(32)

    def update(self, kind, value):
        with self.lock:
            if kind == 'source': self.source = value
            elif kind == 'folder': self.folder = value
            elif kind == 'status': self.info.update(value)
            elif kind == 'event':
                self.events.append(value)
                self.info['alerts'] = len(self.events)
            elif kind == 'result':
                image, record, summary = value
                out = io.BytesIO()
                annotate(image, record['detections'], record['video_seconds'], live=True).save(out, format='JPEG', quality=85)
                self.result = out.getvalue()
                self.info.update(summary)
                self.info['last_result'] = record['captured_at']
                self.info['error'] = ''

    def start(self, data):
        # Use the CLI validators for both interfaces; do not accept arbitrary paths from HTTP.
        argv = ['--cache', str(self.cache), 'live', '--camera-id', str(data.get('camera_id', '')),
                '--output', str(self.output)]
        if not data.get('camera_id'): raise ValueError('Choose a camera first.')
        for key in ('threshold', 'sample_fps', 'cooldown', 'clear_seconds'):
            if key in data: argv += ['--' + key.replace('_', '-'), str(data[key])]
        try: args = parser().parse_args(argv)
        except SystemExit: raise ValueError('Check the threshold, sample rate and timing values.')
        with self.lock:
            if self.thread and self.thread.is_alive(): raise ValueError('Monitoring is already running or stopping.')
            self.stop_event = threading.Event()
            self.folder = self.result = self.source = None
            self.events = []
            self.info = {'status': 'Loading model', 'frames_analysed': 0, 'alerts': 0}
            def worker():
                try: run_live(args, stop_event=self.stop_event, observer=self.update)
                except Exception as exc: self.update('status', {'status': 'Error', 'error': str(exc)})
                finally:
                    with self.lock:
                        self.source = None
                        if self.stop_event.is_set(): self.info['status'] = 'Stopped'
            self.thread = threading.Thread(target=worker, daemon=True)
            self.thread.start()

    def stop(self):
        with self.lock:
            self.stop_event.set()
            if self.thread and self.thread.is_alive(): self.info['status'] = 'Stopping after current analysis'

    def state(self):
        with self.lock:
            snap = self.source.snapshot() if self.source else None
            age = time.monotonic() - snap[1] if snap else None
            return dict(self.info, active=bool(self.thread and self.thread.is_alive()),
                        stopping=self.stop_event.is_set(), preview_age=age,
                        camera_error=self.source.error if self.source else '',
                        events=list(reversed(self.events[-30:])), folder=str(self.folder or ''))

    def preview(self):
        with self.lock:
            snap = self.source.snapshot() if self.source else None
            return snap[2] if snap and time.monotonic() - snap[1] < 3 else None


def make_server(monitor, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def allowed(self):
            host = self.headers.get('Host', '')
            return host in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')
        def send(self, status, content=b'', mime='application/json'):
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' blob:; frame-ancestors 'none'; connect-src 'self'")
            self.end_headers()
            try: self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError): pass
        def json(self, value, status=200): self.send(status, json.dumps(value).encode())
        def do_GET(self):
            if not self.allowed(): return self.send(403)
            path = urlsplit(self.path).path
            if path == '/':
                page = Path(__file__).with_name('web').joinpath('index.html').read_text()
                return self.send(200, page.replace('__TOKEN__', monitor.token).encode(), 'text/html; charset=utf-8')
            if path == '/api/state': return self.json(monitor.state())
            if path == '/api/cameras':
                try: return self.json(list_cameras())
                except Exception as exc: return self.json({'error': str(exc)}, 500)
            if path == '/preview.jpg':
                data = monitor.preview()
                return self.send(200 if data else 204, data or b'', 'image/jpeg')
            if path == '/analysed.jpg':
                with monitor.lock: data = monitor.result
                return self.send(200 if data else 204, data or b'', 'image/jpeg')
            if path.startswith('/sighting/'):
                name = path.removeprefix('/sighting/')
                with monitor.lock:
                    folder = monitor.folder
                    valid = any(e['image'] == name for e in monitor.events)
                if valid and folder:
                    return self.send(200, (folder / name).read_bytes(), 'image/jpeg')
            self.send(404)
        def do_POST(self):
            if not self.allowed() or self.headers.get('X-Monitor-Token') != monitor.token:
                return self.send(403)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 <= size <= 4096: raise ValueError('Invalid request size')
                data = json.loads(self.rfile.read(size) or b'{}')
                if not isinstance(data, dict): raise ValueError('Invalid settings')
                if self.path == '/api/start': monitor.start(data)
                elif self.path == '/api/stop': monitor.stop()
                else: return self.send(404)
                self.json({'ok': True})
            except (ValueError, TypeError) as exc: self.json({'error': str(exc)}, 400)
    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def serve(args):
    monitor = Monitor(args.cache, args.output)
    server = make_server(monitor, args.port)
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Open Rodent Watch: {url}\nCtrl-C stops the server and camera.', flush=True)
    if not args.no_open: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        monitor.stop()
        if monitor.thread: monitor.thread.join()
        server.server_close()

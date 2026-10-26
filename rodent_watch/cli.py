import argparse
from datetime import datetime
import html
import json
import math
from pathlib import Path
import sys
import time
from uuid import uuid4

from .detector import MODEL_ID, PROMPT, RodentDetector
from .events import SightingGate

ROOT = Path(__file__).resolve().parent.parent


def number(value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("must be a finite nonnegative number")
    return value


def probability(value):
    value = number(value)
    if not 0 < value < 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1 (exclusive)")
    return value


def positive(value):
    value = number(value)
    if value == 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return value


def parser():
    p = argparse.ArgumentParser(description="Experimental local rodent detection; saves stills only.")
    p.add_argument("--cache", type=Path, default=ROOT / ".cache/models")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("download-model", help="Download weights once (internet required; no video uploaded)")
    v = sub.add_parser("video", help="Analyse an existing local video offline")
    v.add_argument("input", type=Path)
    v.add_argument("--output", type=Path, default=ROOT / "output")
    v.add_argument("--threshold", type=probability, default=0.35)
    v.add_argument("--text-threshold", type=probability, default=0.25)
    v.add_argument("--sample-fps", type=positive, default=2.0)
    v.add_argument("--clear-seconds", type=positive, default=5.0)
    v.add_argument("--cooldown", type=number, default=30.0)
    v.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    v.add_argument("--max-seconds", type=positive, help="Analyse only the beginning of the clip")
    sub.add_parser("cameras", help="List available macOS cameras, including nearby iPhones")
    live = sub.add_parser("live", help="Analyse a selected camera locally; saves stills only")
    live.add_argument("--camera-id", required=True, help="Exact stable ID from rodent-watch cameras")
    live.add_argument("--output", type=Path, default=ROOT / "output")
    live.add_argument("--threshold", type=probability, default=0.35)
    live.add_argument("--text-threshold", type=probability, default=0.25)
    live.add_argument("--sample-fps", type=positive, default=2.0)
    live.add_argument("--clear-seconds", type=positive, default=5.0)
    live.add_argument("--cooldown", type=number, default=30.0)
    live.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    live.add_argument("--max-seconds", type=positive, help="Stop after this many live seconds")
    live.add_argument("--stall-timeout", type=positive, default=30.0)
    live.add_argument("--retry-seconds", type=positive, default=5.0)
    ui = sub.add_parser("ui", help="Open the local live camera interface")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--output", type=Path, default=ROOT / "output")
    ui.add_argument("--no-open", action="store_true", help="Do not launch the default browser")
    return p


def annotate(image, detections, timestamp, live=False):
    from PIL import ImageDraw
    image = image.copy()
    draw = ImageDraw.Draw(image)
    for d in detections:
        box = d["box"]
        draw.rectangle(box, outline="#ff5533", width=3)
        label = f"rodent {d['confidence']:.2f}"
        x, y = box[0], max(0, box[1] - 16)
        draw.rectangle(draw.textbbox((x, y), label), fill="black")
        draw.text((x, y), label, fill="white")
    draw.rectangle((0, 0, 250, 18), fill="black")
    draw.text((4, 3), f"Candidate rodent | {'live' if live else 'video'} {timestamp:.2f}s", fill="white")
    return image


def write_report(folder, summary, events):
    (folder / "summary.json").write_text(json.dumps(summary, indent=2))
    time_label = "Live elapsed" if summary.get("mode") == "live" else "Video"
    cards = "".join(
        f'<article><h2>{time_label} {e["video_seconds"]:.2f}s</h2>'
        f'<p>Candidate rodent · score {max(d["confidence"] for d in e["detections"]):.2f}</p>'
        f'<a href="{e["image"]}"><img src="{e["image"]}" alt="Annotated candidate rodent"></a></article>'
        for e in events)
    (folder / "report.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Rodent Watch results</title>'
        '<style>body{font:18px system-ui;max-width:1000px;margin:40px auto;padding:20px;background:#f4f4f1;color:#222}'
        'img{max-width:100%}article{background:white;padding:20px;margin:20px 0}pre{white-space:pre-wrap}</style>'
        f'<h1>{len(events)} candidate sighting(s)</h1>'
        '<p>Experimental results: review each image. Scores are not calibrated probabilities. '
        'No detections does not prove that no animals were present.</p>'
        f'<p>Status: {html.escape(summary["status"])}</p>' + cards +
        '<h2>Run details</h2><pre>' + html.escape(json.dumps(summary, indent=2)) + '</pre></html>')


def analyse(args, detector_factory=RodentDetector):
    import cv2
    from PIL import Image
    if not args.input.is_file():
        raise ValueError(f"Video does not exist: {args.input}")
    cap = cv2.VideoCapture(str(args.input.resolve()))
    if not cap.isOpened():
        cap.release()
        raise ValueError("Cannot open video. Try exporting it as an H.264 MP4.")
    folder = None
    summary = {}
    events = []
    started = time.monotonic()
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("Video has no usable frame rate; export a constant-frame-rate H.264 MP4.")
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        ok, frame = cap.read()
        if not ok:
            raise ValueError("Video opened but no frames could be decoded.")
        print("Loading local model (CPU can be slow)...", flush=True)
        detector = detector_factory(args.cache, args.threshold, args.text_threshold, args.device)
        folder = args.output / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6])
        folder.mkdir(parents=True)
        summary = dict(status="running", input="<local video>", model=MODEL_ID,
                       prompt=PROMPT, threshold=args.threshold, text_threshold=args.text_threshold,
                       sample_fps=args.sample_fps, source_fps=fps, source_frames=count,
                       clear_seconds=args.clear_seconds, cooldown_seconds=args.cooldown,
                       device=args.device, frames_decoded=0, frames_analysed=0,
                       positive_frames=0, alerts=0,
                       timestamp_note="Frame index / nominal FPS; variable-frame-rate times are approximate.")
        gate = SightingGate(args.clear_seconds, args.cooldown)
        next_sample = 0.0
        with (folder / "frames.jsonl").open("w") as log, (folder / "events.jsonl").open("w") as event_log:
            index = 0
            while ok:
                timestamp = index / fps
                if args.max_seconds is not None and timestamp >= args.max_seconds:
                    summary["status"] = "limited by --max-seconds"
                    break
                summary["frames_decoded"] += 1
                if timestamp + 1e-8 >= next_sample:
                    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    detections = detector.detect(image)
                    summary["frames_analysed"] += 1
                    summary["positive_frames"] += bool(detections)
                    record = dict(frame=index, video_seconds=timestamp, detections=detections)
                    log.write(json.dumps(record) + "\n")
                    log.flush()
                    if gate.update(timestamp, bool(detections)):
                        name = f"sighting-{len(events) + 1:04d}-{timestamp:010.2f}s.jpg"
                        annotate(image, detections, timestamp).save(folder / name, quality=92)
                        event = dict(**record, image=name)
                        events.append(event)
                        event_log.write(json.dumps(event) + "\n")
                        event_log.flush()
                        summary["alerts"] = len(events)
                        write_report(folder, summary, events)
                        print(f"\aDETECTION at {timestamp:.2f}s: {folder / name}", flush=True)
                    if summary["frames_analysed"] % 10 == 0:
                        print(f"Analysed {timestamp:.1f}s of video; {len(events)} sighting(s)", flush=True)
                    next_sample = (math.floor(timestamp * args.sample_fps + 1e-8) + 1) / args.sample_fps
                index += 1
                ok, frame = cap.read()
            else:
                summary["status"] = "completed"
                if count > 0 and index < count - 1:
                    summary["status"] = "warning: decode ended before reported final frame"
    except KeyboardInterrupt:
        if folder:
            summary["status"] = "interrupted; partial results"
        raise
    except Exception:
        if folder:
            summary["status"] = "failed; partial results"
        raise
    finally:
        cap.release()
        if folder:
            summary["elapsed_seconds"] = round(time.monotonic() - started, 2)
            write_report(folder, summary, events)
            print(f"{summary['status']}: {len(events)} candidate sighting(s). Report: {folder / 'report.html'}", flush=True)
    return folder


def main():
    args = parser().parse_args()
    try:
        if args.command == "download-model":
            print("Downloading model weights; no images or video are sent.", flush=True)
            RodentDetector(args.cache, 0.35, 0.25, download=True)
            print(f"Model ready in {args.cache}. Video analysis now works offline.")
        elif args.command == "ui":
            from .ui import serve
            serve(args)
        elif args.command == "cameras":
            from .live import list_cameras
            list_cameras()
        elif args.command == "live":
            from .live import run_live
            run_live(args)
        else:
            analyse(args)
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}\nIf weights are missing, run: rodent-watch download-model", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

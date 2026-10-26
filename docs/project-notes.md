# Rodent Watch — project notes

These notes preserve the original development plan, implementation history and detailed operating guidance. For current installation and everyday use, see the [README](../README.md).

Phase 1: analyse a local video on your Mac, save annotated still images, and open a local results gallery. No continuous recording, no copy of the input video, no image uploads. This is an **experimental detector**, not a validated overnight monitoring system.

## Model choice and limits

This uses [Grounding DINO tiny](https://huggingface.co/IDEA-Research/grounding-dino-tiny), an Apache-2.0 open-vocabulary detector. The model accepts text descriptions instead of a fixed COCO class list. We query `a mouse animal. a rat animal. a rodent.` and report a single `rodent` label. COCO's computer-mouse class is not used. The [official implementation](https://github.com/huggingface/transformers/blob/v4.57.1/src/transformers/models/grounding_dino/processing_grounding_dino.py) supplies boxes, text matches and scores.

This verifies that animal rodent descriptions can be queried, **not that rodent recognition is reliable**. The model card does not provide a rodent-specific accuracy guarantee. Small distant animals, motion blur, occlusion, shadows and clutter may cause misses or false positives. Scores are model matching scores, not calibrated probabilities. If this baseline fails on representative video, collect annotated examples and evaluate a rodent-specific detector, or fine-tune one on those examples with a separate held-out test set. Do not substitute a generic COCO detector.

## Setup on macOS

Apple Silicon is the initial target. CPU is the conservative default; Intel Macs may need older compatible PyTorch wheels and have not been tested. Allow several GB of free disk space for the environment and weights. Initial setup needs internet access to download Python packages and model weights; video inference does not.

From Terminal:

```sh
cd /path/to/mice-detection
# Install uv if needed: brew install uv
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python uv sync --frozen --python 3.12
source .venv/bin/activate
rodent-watch download-model
```

The project uses Python 3.12 for compatible model dependencies. Dependencies are locked in `uv.lock`. Model files are cached under `.cache/models`. The download step contacts Hugging Face; it does not send footage. The application disables Hugging Face telemetry and uses offline, local-only model loading during `video` runs. No cloud inference, camera access, or phone service is enabled.

## Run a short test first

Put a sample in `videos/` (create the directory if needed), or use its existing absolute path. Paths containing spaces must be quoted. Video files remain local.

```sh
source .venv/bin/activate
rodent-watch video "/absolute/path/to/sample.mp4" --max-seconds 20
```

The terminal prints `DETECTION` and the picture path for each candidate sighting. At the end it prints the path to `report.html`; open that file in Finder or use `open "/path/printed/by/the/app/report.html"`. This local gallery shows the saved full-resolution images with boxes, label and score. A terminal bell may sound if enabled. There is no phone notification in phase 1.

For the whole clip:

```sh
rodent-watch video "/absolute/path/to/sample.mp4" --threshold 0.35 --sample-fps 2 --clear-seconds 5 --cooldown 30
```

- `--threshold`: detection score cutoff. Lower it (e.g. 0.25) to explore missed animals; raise it (e.g. 0.45) to reduce weak matches. Neither guarantees accuracy.
- `--text-threshold`: text matching cutoff, default 0.25. Normally leave this alone.
- `--sample-fps`: frames analysed per video second, default 2. Fast crossings between samples can be missed; try 5 or 10 for short clips. Cannot exceed source frame rate in practice. More samples take longer.
- `--clear-seconds`: re-arm only after sampled frames show no detections for this period. Default 5 seconds.
- `--cooldown`: at least this many **video seconds** between alerts. Default 30. A continuous detection never repeats merely because cooldown expires. A return during cooldown can alert once cooldown expires. Two separate animals close together may be grouped as one sighting; this is temporal grouping, not identity tracking.
- `--device mps`: optional Apple GPU experiment. CPU is tested first; if MPS reports an unsupported operation, rerun with `--device cpu`. MPS speed and correctness need evaluation on your Mac.
- `--output PATH`: choose output parent folder. Every run gets a unique subfolder.
- `--max-seconds 20`: limit analysis to the first 20 video seconds.

Processing can be slower than playback; no frames are dropped because inference is slow. Sampling intentionally skips frames. Times are based on frame index and nominal FPS; variable-frame-rate video timestamps may be approximate. For precise timing, export constant-frame-rate H.264 MP4. Unsupported or corrupted codecs may need re-exporting. Ctrl-C stops analysis and preserves partial results.

## Outputs and assessment

Each run saves only:

- `sighting-*.jpg`: first alert frame of each grouped sighting, annotated.
- `events.jsonl`: alert times, scores, boxes and picture names.
- `frames.jsonl`: predictions for each sampled frame, including empty results, for reviewing misses and suppressed detections. No frame images here.
- `summary.json`: settings, counts, status and elapsed time.
- `report.html`: offline image gallery; no external scripts or assets.

Review the original clip yourself and note the start/end of every visible rodent appearance. Compare those intervals with `frames.jsonl` and the saved alerts. Record true alerts, false alerts, and visible animals with no matching detection. Try a positive clip and a representative empty-room clip, including distant animals and normal clutter. A zero-alert result alone proves nothing. Save settings with each assessment and evaluate new thresholds on additional footage, not just the clip used for tuning.

## Validation status

See [validation results](../VALIDATION.md) for actual checks and remaining gaps. Rodent recall, false-positive rate and suitability for overnight use remain unestablished.

Run software tests:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

The synthetic pipeline test uses a fake detector to check sampling, grouping and output files. It is **not** a rodent recognition test.

## Phase 2 planning notes (original prototype)

The source loop, model adapter and sighting gate are separate so a later camera source and notification sink can reuse them. Live camera capture is now available below. Measure inference throughput on representative live footage; this model may be too slow for brief live crossings, requiring a smaller rodent-specific model.

For any prospective camera, verify platform compatibility, field of view, focus at the required distance and visible animal size before purchase. Compatibility must be assessed for each device. Test live capture and disconnect/reconnect handling after phase 1 passes. Keep the Mac on power and awake (for example, a later launch command wrapped with `caffeinate -i`); do not assume closing the lid keeps it running.

A practical later phone option is [Pushover](https://pushover.net/api), whose API accepts an image attachment. This requires an account/app setup and an internet connection. Alert pictures would leave the Mac and pass through Pushover to your phone; video recognition would remain local. Review its current pricing and privacy terms before enabling it. Only alert stills would be transmitted. We would add retry limits and delivery failure reporting, retain local pictures if offline, and apply the same sighting suppression before sending. Nothing is sent by this prototype.

## Live camera capture

Live mode uses a native AVFoundation capture helper with explicit camera discovery and privacy declarations. It selects the device ID supplied at runtime, including after reconnection, rather than silently switching cameras. No additional Python dependencies are required.

### Connect a camera

1. Connect a compatible camera using a supported wired or wireless method. Follow the manufacturer's setup and platform requirements.
2. Position the camera securely, aim it at the monitored area, and provide continuous power for extended sessions.
3. Close other applications using the camera and disable effects that alter framing or obscure the scene.
4. Keep the host computer awake and connected to power. Wireless stability and overnight operation require testing.

### Build and select a camera

Build the helper with Xcode Command Line Tools installed:

```sh
cd /path/to/mice-detection
./scripts/build-camera.sh
```

List cameras (listing does not start capture):

```sh
source .venv/bin/activate
rodent-watch cameras
```

Copy the **ID** of the selected camera and run a short test:

```sh
rodent-watch live --camera-id "PASTE_CAMERA_ID_HERE" --max-seconds 60
```

Accept the macOS camera permission prompt. If denied, check **System Settings → Privacy & Security → Camera** for Rodent Watch Camera or the terminal app used to launch it. If you need longer to respond to permission prompts, add `--stall-timeout 120`. No microphone permission is requested or used.

For an ongoing session:

```sh
caffeinate -i .venv/bin/rodent-watch live --camera-id "PASTE_CAMERA_ID_HERE" --threshold 0.35 --sample-fps 2 --clear-seconds 5 --cooldown 30
```

Stop with Ctrl-C. The selected camera helper shuts down and the results report is finalised. Do not assume capture will continue while the host computer is asleep.

### Live behaviour and limitations

- Native capture aims for 720p and passes at most 10 frames/second in memory. Python drains these continuously into a single latest-frame slot. Slow inference skips older frames; it does not build a video backlog. `--sample-fps` is a requested upper rate, not guaranteed throughput. Short crossings can be missed.
- `DETECTION` messages, annotated JPEGs and the local HTML report work as in video mode. Live captions show elapsed live time. JSON records include wall-clock timestamps and inference duration. The terminal prints progress about every 10 seconds, subject to inference time; refresh the HTML report manually.
- If no new frames arrive for `--stall-timeout` seconds (default 30), or the helper exits, the app closes capture and retries the same camera after `--retry-seconds` (default 5). Errors and connection states are shown in the terminal and report. Initial camera absence also retries until stopped. Permissions must be fixed manually; retries cannot bypass them.
- Disconnect time does not count as observed absence. The current sighting/cooldown survives reconnects to avoid a new alert simply because the connection returned.
- `--max-seconds` limits live duration after model loading, subject to a currently running inference and camera shutdown finishing. Long model calls cannot be instantly cancelled by that limit.
- Only detection JPEGs and text/JSON/HTML results are written. No continuous video, temporary video, audio, or non-alert frame images are saved. Frames travel from the selected camera to the host computer; no third-party inference service is used.
- Phone notifications are still a separate next step; this release alerts in the terminal and saves local pictures only.

If the selected camera is absent from `cameras`, check its connection and setup, confirm that the operating system can discover it, then retry. Camera discovery may be blocked in restricted environments; run the commands in a normal Terminal session. A successful compilation or simulated test does not establish hardware capture or overnight reliability.

## Browser interface

Run:

```sh
cd /path/to/mice-detection
source .venv/bin/activate
caffeinate -i rodent-watch ui
```

This opens **http://127.0.0.1:8765** in your browser. Select a camera and click **Start monitoring**. The interface includes a live preview, a separate latest analysed frame with boxes, recent sighting pictures, camera status, analysis duration, and threshold/sampling/alert controls. Settings can be changed while stopped. Click **Stop monitoring** before switching settings or cameras; an in-progress model analysis finishes first. Closing the tab does **not** stop capture. Ctrl-C in the launching Terminal shuts down the server and camera.

The preview refreshes up to about five times per second, independently of model speed. It deliberately has no detection overlay: boxes are shown on the exact analysed frame below, so delayed results are never overlaid on a newer live image. Frames older than three seconds disappear from the live preview instead of looking like a healthy feed. Recent sightings shows up to 30 pictures from the current session; all saved alerts remain in the run's output folder/report. A new run starts a new session, and restarting the UI does not load past session galleries.

The server listens only on your Mac's loopback address, uses no external web assets, and adds no cloud service. Preview frames remain in memory and HTTP responses use `no-store`. Only alert pictures and existing run metadata are saved. The browser interface is for this Mac, not for opening remotely on your phone. Phone notifications remain unimplemented.

If port 8765 is occupied, use `rodent-watch ui --port 8766`. Add `--no-open` to prevent automatic browser launch. Stop any existing command-line live capture first so two processes do not compete for the same camera.

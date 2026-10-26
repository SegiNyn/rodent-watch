# Rodent Watch 🤮

Rodent Watch detects mice and rats in local video files or a live camera feed on your Mac. It uses Grounding DINO Tiny with animal-rodent prompts and saves detection pictures with bounding boxes, a `rodent` label and confidence scores.

You can use it from Terminal or a local browser interface with a live preview, camera selection, start/stop controls and a sighting gallery. It supports an iPhone connected wirelessly through Apple's Continuity Camera.

Video analysis runs locally. The app saves alert pictures and detection logs, not continuous video. Repeated alerts for the same sighting are suppressed. Phone notifications are not implemented. Detection is experimental: false positives and missed animals are possible.

## Install

### Requirements

- An Apple Silicon Mac. Intel Macs have not been tested with the pinned dependencies.
- macOS 14 or later for the app's explicit Continuity Camera discovery.
- Several GB of free disk space and internet access for initial downloads.
- [uv](https://docs.astral.sh/uv/) to install Python and the project dependencies.
- Xcode Command Line Tools for live-camera support.

Download or clone this project, then open Terminal in its folder. Replace `/path/to/mice-detection` below with your checkout's location.

If you use [Homebrew](https://brew.sh/), install uv with:

```sh
brew install uv
```

Alternatively, follow the [uv installation instructions](https://docs.astral.sh/uv/getting-started/installation/).

Install the application and download the pretrained model:

```sh
cd /path/to/mice-detection
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python uv sync --frozen --python 3.12
source .venv/bin/activate
rodent-watch download-model
```

uv installs Python 3.12 if needed and the locked dependencies, including PyTorch, Transformers, OpenCV and Pillow. No separate system Python installation is required. The model is stored in `.cache/models`; subsequent analysis works offline and does not upload frames.

For live cameras and the browser UI, install the command-line tools if they are not already installed, finish the macOS installation dialog, then build the camera helper:

```sh
xcode-select --install
# After installation finishes:
./scripts/build-camera.sh
```

You can skip the camera helper if you only analyse prerecorded files.

## Connect your iPhone

1. Use a Continuity Camera-compatible iPhone and sign in to the same Apple Account on your iPhone and Mac, with two-factor authentication enabled.
2. Turn on Wi-Fi and Bluetooth on both devices. Enable **Settings → General → AirPlay & Continuity → Continuity Camera** on iPhone; older iOS versions may call the menu **AirPlay & Handoff**.
3. Keep the iPhone near the Mac, mounted in landscape, locked and charging, with its rear camera facing the area you want to monitor.
4. Close other apps using the camera and disable iPhone Mirroring. Allow the macOS camera permission prompt when starting capture.

See [Apple's Continuity Camera requirements and setup](https://support.apple.com/en-us/102546). If access was denied, check **System Settings → Privacy & Security → Camera** for the camera helper or the Terminal app used to launch it.

## Run from Terminal

In each new Terminal session, enter the project folder and activate its environment:

```sh
cd /path/to/mice-detection
source .venv/bin/activate
```

### Analyse a video file

```sh
rodent-watch video "/path/to/sample.mp4"
```

For a short test with a custom threshold:

```sh
rodent-watch video "/path/to/sample.mp4" --max-seconds 20 --threshold 0.35
```

### Monitor a live camera

List available cameras:

```sh
rodent-watch cameras
```

Copy the ID printed beneath your chosen camera, then run:

```sh
caffeinate -i rodent-watch live --camera-id "PASTE_CAMERA_ID_HERE"
```

`caffeinate -i` prevents idle sleep while the command runs. Keep the Mac plugged in with its lid open. Press **Ctrl-C** to stop capture and finalise the report. For a short test, add `--max-seconds 60`.

Both `video` and `live` accept these settings:

| Option | Default | Purpose |
| --- | --- | --- |
| `--threshold` | `0.35` | Score cutoff; lower accepts weaker matches, higher rejects more of them. |
| `--sample-fps` | `2` | Requested analysis rate; actual live speed depends on your Mac. |
| `--clear-seconds` | `5` | Observed absence required before another sighting can alert. |
| `--cooldown` | `30` | Minimum time between alerts. |
| `--output` | `output/` in the project | Parent folder for run results. |

Use `rodent-watch video --help` or `rodent-watch live --help` for all options. Live capture retries the selected camera if it disconnects. Slow live inference skips older frames rather than building a backlog.

## Run the UI

From the project folder with the environment activated:

```sh
caffeinate -i rodent-watch ui
```

Your browser opens [http://127.0.0.1:8765](http://127.0.0.1:8765). Select your camera and click **Start monitoring**.

- **Live preview** shows the incoming camera feed.
- **Latest analysed frame** shows detection boxes on the frame the model actually examined.
- **Recent sightings** shows saved pictures from the current session.
- **Controls** let you change the threshold, sampling rate and alert timing while monitoring is stopped.

Click **Stop monitoring** to release the camera. An analysis already in progress finishes first. Closing the browser tab does **not** stop monitoring; press **Ctrl-C** in Terminal to shut down the UI server and camera.

The UI currently handles live cameras; use the Terminal `video` command for prerecorded files. Stop any existing live command before starting capture in the UI.

If port 8765 is busy, run `rodent-watch ui --port 8766`. Use `--no-open` if you prefer to open the browser yourself. The UI is accessible only on this Mac, not from other devices on your network.

## Find your results

Each run creates a folder under `output/` containing:

- `sighting-*.jpg`: annotated detection pictures.
- `report.html`: a local gallery you can open in your browser.
- `events.jsonl`, `frames.jsonl` and `summary.json`: detection times, predictions and run settings.

The app prints the report location in Terminal. Saved results remain after you stop monitoring. Preview frames are kept in memory and are not recorded.

## Further details

- [Project notes and development history](docs/project-notes.md)
- [Validation results and known limitations](VALIDATION.md)

To run the software tests:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Saved reports omit source video paths and camera identifiers. Local detection pictures and timestamps may still contain private information; `output/`, local environments and caches are excluded from Git. Share source files rather than the entire working folder.

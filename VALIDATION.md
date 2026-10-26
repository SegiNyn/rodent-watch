# Validation

The application has been exercised with CPU inference on macOS. Dependencies are recorded in `uv.lock`. Personal device names, identifiers, filesystem paths, test dates and scene descriptions are omitted from this document.

## Software checks

The recorded test suite contains 11 passing tests covering:

- Suppression of repeated alerts during a continuous sighting.
- Re-arming after observed absence and enforcing an alert cooldown.
- Bounding-box overlap calculations.
- Rejecting missing video inputs before loading the model.
- Video decoding, sampling, annotated stills and logs without video output.
- Keeping only the latest camera frame and terminating capture cleanly.
- Reconnecting to the same selected camera without duplicate alerts.
- Stalled-camera retries, cleanup and duration limits.
- Hiding stale preview frames.
- Rejecting concurrent monitoring sessions and stopping the worker.
- HTTP access controls, settings validation and preventing arbitrary file reads.

Synthetic tests inject fake detections where appropriate. They verify application behaviour, not rodent recognition accuracy. HTTP tests require permission to bind a local loopback port.

Run the suite with:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

## Model and capture checks

- The cached model successfully processed a synthetic blank frame offline and returned zero detections at a threshold of 0.35. This is an execution check, not a real-scene false-positive benchmark.
- The native camera helper compiled and was locally signed.
- A browser-driven live capture successfully displayed incoming video and analysed frames, saved a candidate alert, and stopped capture through the UI.
- The live check included an apparent false positive. It establishes the capture and interface workflow, not reliable animal recognition.

## Remaining limitations

Rodent recall, real-world false-positive rates, missed animals and overnight reliability have not been established through a representative labelled evaluation. Hardware compatibility and wireless recovery need testing for each setup. Optional GPU inference and Intel compatibility remain unverified. Phone notifications are not implemented.

Evaluate positive and empty-scene footage, compare detections against visible animal appearances, and use separate footage for tuning and assessment.

import os
from pathlib import Path
import re

MODEL_ID = "IDEA-Research/grounding-dino-tiny"
PROMPT = "a mouse animal. a rat animal. a rodent."


class RodentDetector:
    def __init__(self, cache: Path, threshold: float, text_threshold: float,
                 device: str = "cpu", download: bool = False):
        # No hosted inference or telemetry. Only explicit setup may download weights.
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        if not download:
            os.environ["HF_HUB_OFFLINE"] = "1"
        import torch
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
        self.torch = torch
        self.device = device
        if device == "mps" and not torch.backends.mps.is_available():
            raise ValueError("MPS is unavailable on this Mac. Use --device cpu.")
        kwargs = dict(cache_dir=str(cache), local_files_only=not download)
        self.processor = AutoProcessor.from_pretrained(MODEL_ID, **kwargs)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(
            MODEL_ID, use_safetensors=True, **kwargs).to(device).eval()
        self.threshold = threshold
        self.text_threshold = text_threshold

    def detect(self, image):
        inputs = self.processor(images=image, text=PROMPT, return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            outputs = self.model(**inputs)
        result = self.processor.post_process_grounded_object_detection(
            outputs, inputs.input_ids, threshold=self.threshold,
            text_threshold=self.text_threshold, target_sizes=[image.size[::-1]])[0]
        detections = []
        for box, score, phrase in zip(result["boxes"], result["scores"], result["text_labels"]):
            if not re.search(r"\b(mouse|rat|rodent)\b", phrase):
                continue
            x1, y1, x2, y2 = box.cpu().tolist()
            w, h = image.size
            box = [max(0, min(w - 1, x1)), max(0, min(h - 1, y1)),
                   max(0, min(w - 1, x2)), max(0, min(h - 1, y2))]
            if box[2] > box[0] and box[3] > box[1]:
                detections.append(dict(label="rodent", phrase=phrase,
                                       confidence=float(score.cpu()), box=box))
        # Merge overlapping predictions from synonymous prompts.
        kept = []
        for detection in sorted(detections, key=lambda d: d["confidence"], reverse=True):
            if all(iou(detection["box"], d["box"]) < 0.5 for d in kept):
                kept.append(detection)
        return kept


def iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union else 0

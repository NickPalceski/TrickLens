"""YOLOX object detection on ONNX Runtime (step 6b).

YOLOX (Megvii, Apache-2.0) is trained on COCO, which already has `person`
and `skateboard` classes, so it's used as-is with no training. Not
Ultralytics YOLOv8: that's AGPL-3.0 (docs/ARCHITECTURE.md, Decisions).

The pre/post-processing here is what the Ultralytics package would
otherwise do for us. It matches YOLOX's own ONNX demo for the 0.1.1rc0
weights:
- input: letterboxed BGR, padded with 114, raw 0-255 floats (no mean/std);
- output: one row per anchor point (cx, cy, w, h, objectness, 80 class
  scores), still in grid units, decoded here;
- non-max suppression per class.
"""

from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
import onnxruntime as ort

# COCO class indices (the 80-class order YOLOX was trained on).
PERSON = 0
SKATEBOARD = 36
CLASS_NAMES = {PERSON: "person", SKATEBOARD: "skateboard"}

_STRIDES = (8, 16, 32)
_PAD_VALUE = 114


@dataclass(frozen=True)
class Detection:
    """One box in the *original frame's* pixel coordinates."""

    cls: int
    score: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2

    def offset(self, dx: float, dy: float) -> "Detection":
        return Detection(
            self.cls, self.score, self.x1 + dx, self.y1 + dy, self.x2 + dx, self.y2 + dy
        )


class Detector:
    def __init__(self, model_path: str) -> None:
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(
            model_path, sess_options=opts, providers=["CPUExecutionProvider"]
        )
        inp = self._session.get_inputs()[0]
        self._input_name = inp.name
        # Fixed by the exported model: 416x416 for Tiny/Nano, 640x640 for S+.
        self.input_hw: tuple[int, int] = (int(inp.shape[2]), int(inp.shape[3]))
        self._grids, self._grid_strides = _make_grids(self.input_hw)

    def detect(
        self,
        frame_bgr: np.ndarray,
        classes: tuple[int, ...] = (PERSON, SKATEBOARD),
        min_score: float = 0.25,
        nms_iou: float = 0.45,
    ) -> list[Detection]:
        blob, ratio = letterbox(frame_bgr, self.input_hw)
        raw = self._session.run(None, {self._input_name: blob[None]})[0][0]
        return postprocess(raw, ratio, self._grids, self._grid_strides, classes, min_score, nms_iou)


@lru_cache
def get_detector(model_path: str) -> Detector:
    """One ONNX Runtime session per model, per Lambda container. Built on
    first use, not at import, so cold-start init stays cheap
    (docs/components/analyzer.md, Worker)."""
    return Detector(model_path)


def letterbox(frame_bgr: np.ndarray, input_hw: tuple[int, int]) -> tuple[np.ndarray, float]:
    """Resize preserving aspect ratio into the top-left of a padded square.
    Returns the CHW float32 blob and the scale ratio (input px per frame px)."""
    ih, iw = input_hw
    h, w = frame_bgr.shape[:2]
    ratio = min(ih / h, iw / w)
    nh, nw = int(round(h * ratio)), int(round(w * ratio))
    padded = np.full((ih, iw, 3), _PAD_VALUE, dtype=np.uint8)
    padded[:nh, :nw] = cv2.resize(frame_bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
    return np.ascontiguousarray(padded.transpose(2, 0, 1), dtype=np.float32), ratio


def _make_grids(input_hw: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    grids, strides = [], []
    for stride in _STRIDES:
        gh, gw = input_hw[0] // stride, input_hw[1] // stride
        xv, yv = np.meshgrid(np.arange(gw), np.arange(gh))
        grids.append(np.stack((xv, yv), axis=2).reshape(-1, 2))
        strides.append(np.full((gh * gw, 1), stride))
    return np.concatenate(grids).astype(np.float32), np.concatenate(strides).astype(np.float32)


def postprocess(
    raw: np.ndarray,
    ratio: float,
    grids: np.ndarray,
    grid_strides: np.ndarray,
    classes: tuple[int, ...],
    min_score: float,
    nms_iou: float,
) -> list[Detection]:
    """Decode YOLOX's raw (N, 85) output into frame-space boxes, per-class NMS."""
    xy = (raw[:, :2] + grids) * grid_strides
    wh = np.exp(raw[:, 2:4]) * grid_strides
    boxes = np.concatenate((xy - wh / 2, xy + wh / 2), axis=1) / ratio
    objectness = raw[:, 4]

    out: list[Detection] = []
    for cls in classes:
        scores = objectness * raw[:, 5 + cls]
        keep = scores >= min_score
        if not keep.any():
            continue
        cls_boxes, cls_scores = boxes[keep], scores[keep]
        xywh = np.concatenate((cls_boxes[:, :2], cls_boxes[:, 2:] - cls_boxes[:, :2]), axis=1)
        idx = cv2.dnn.NMSBoxes(xywh.tolist(), cls_scores.tolist(), min_score, nms_iou)
        for i in np.array(idx).reshape(-1):
            x1, y1, x2, y2 = cls_boxes[i]
            out.append(
                Detection(cls, float(cls_scores[i]), float(x1), float(y1), float(x2), float(y2))
            )
    return out

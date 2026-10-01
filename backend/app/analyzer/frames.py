"""Decode frames from the processed clip at a chosen sample rate (step 6b).

Reads the worker's own 720p transcode, never the raw upload. It's already
upright, constant-frame-rate and capped at 30s (media.py), so a frame index
here maps to an exact timestamp: index / fps.

Frames come from an ffmpeg pipe as raw BGR, the channel order YOLOX and
OpenCV expect, rather than from cv2.VideoCapture. ffmpeg's `fps` filter does
the resampling, so timestamps match what media.py's transcode produced.
"""

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Frame:
    index: int
    t_ms: float
    image: np.ndarray  # HxWx3 uint8, BGR


def iter_frames(path: str, width: int, height: int, fps: float) -> Iterator[Frame]:
    """Yield every frame of `path` resampled to `fps`.

    `width`/`height` must be the file's real dimensions (media.probe() on
    the processed file), since raw frames carry no header to read them from.
    """
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps={fps}",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )  # fmt: skip
    frame_bytes = width * height * 3
    index = 0
    try:
        assert proc.stdout is not None
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            image = np.frombuffer(buf, dtype=np.uint8).reshape(height, width, 3)
            yield Frame(index=index, t_ms=index * 1000.0 / fps, image=image)
            index += 1
    finally:
        proc.stdout.close()
        stderr = proc.stderr.read().decode() if proc.stderr else ""
        if proc.wait() != 0 and index == 0:
            raise RuntimeError(f"ffmpeg frame decode failed: {stderr.strip()}")

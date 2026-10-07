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


def iter_frames(
    path: str,
    width: int,
    height: int,
    fps: float,
    start_ms: float = 0.0,
    end_ms: float | None = None,
) -> Iterator[Frame]:
    """Yield every frame of `path` resampled to `fps`, optionally only those
    in [start_ms, end_ms]. Stage B (6c) decodes just a trick's window this
    way instead of the whole clip.

    `width`/`height` must be the file's real dimensions (media.probe() on
    the processed file), since raw frames carry no header to read them from.
    Frame t_ms values are on the same grid either way: the window starts on
    the first `fps` tick at or after start_ms.
    """
    # Snap the start to the sampling grid, so a windowed decode's
    # timestamps line up with a whole-clip decode's.
    step = 1000.0 / fps
    first = int(-(-start_ms // step)) if start_ms > 0 else 0
    seek_ms = first * step
    cmd = ["ffmpeg", "-v", "error"]
    if seek_ms > 0:
        cmd += ["-ss", f"{seek_ms / 1000:.6f}"]
    cmd += ["-i", path]
    if end_ms is not None:
        cmd += ["-t", f"{max(0.0, end_ms - seek_ms) / 1000 + 1e-3:.6f}"]
    cmd += ["-vf", f"fps={fps}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frame_bytes = width * height * 3
    index = 0
    try:
        assert proc.stdout is not None
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            image = np.frombuffer(buf, dtype=np.uint8).reshape(height, width, 3)
            yield Frame(index=first + index, t_ms=(first + index) * step, image=image)
            index += 1
    finally:
        proc.stdout.close()
        stderr = proc.stderr.read().decode() if proc.stderr else ""
        if proc.wait() != 0 and index == 0:
            raise RuntimeError(f"ffmpeg frame decode failed: {stderr.strip()}")

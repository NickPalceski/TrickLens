"""Build-time check for Dockerfile.worker: can a *non-root* user load the
models the way the worker Lambda will?

Run as root during `docker build`. It drops to uid/gid 65534 first, because
Lambda runs functions as a non-root user, and two real bugs hid behind
root-only checks:
- 6b: `ADD --chmod` left the models directory untraversable (errno 13);
- 6c: MediaPipe's native library needs libEGL, which an `import mediapipe`
  never loads.

Any failure exits non-zero and fails the image build.
"""

import os
import sys

models = sys.argv[1]

os.setgroups([])
os.setgid(65534)
os.setuid(65534)

import onnxruntime as ort  # noqa: E402
from mediapipe.tasks.python import BaseOptions, vision  # noqa: E402

ort.InferenceSession(f"{models}/yolox_tiny.onnx", providers=["CPUExecutionProvider"])
landmarker = vision.PoseLandmarker.create_from_options(
    vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=f"{models}/pose_landmarker_full.task"),
        running_mode=vision.RunningMode.VIDEO,
    )
)
landmarker.close()
print("models load as non-root: yolox_tiny.onnx, pose_landmarker_full.task")

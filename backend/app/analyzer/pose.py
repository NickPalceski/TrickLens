"""MediaPipe body pose over a trick window (step 6c).

BlazePose GHUM ("full" variant, Apache-2.0) via MediaPipe's Tasks API in
VIDEO mode. It runs its own person detector and then tracks frame to frame,
which is why it gets the *full* frame rather than a crop: on the real clips
cropping around the skater made no difference to detection or foot
confidence. One landmarker per window, because VIDEO mode needs strictly
increasing timestamps, and is closed explicitly. Relying on __del__ at
interpreter shutdown raises inside MediaPipe.

Two landmark sets per frame:
- image landmarks: 33 points in frame pixels, plus a visibility score;
- world landmarks: the same 33 points in metres, centred on the hips. They
  don't depend on how far away the camera is, which makes them the right
  basis for body-shape measurements like compactness (6c-3).
"""

from dataclasses import dataclass

import numpy as np

# BlazePose landmark indices used by Stage B.
L_SHOULDER, R_SHOULDER = 11, 12
L_WRIST, R_WRIST = 15, 16
L_HIP, R_HIP = 23, 24
L_KNEE, R_KNEE = 25, 26
L_ANKLE, R_ANKLE = 27, 28
L_HEEL, R_HEEL = 29, 30
L_TOE, R_TOE = 31, 32
FEET = (L_ANKLE, R_ANKLE, L_HEEL, R_HEEL, L_TOE, R_TOE)
N_LANDMARKS = 33


@dataclass
class PoseTrack:
    """Pose for every decoded frame of one window. Rows where no pose was
    found are NaN (and `found` is False)."""

    t_ms: np.ndarray  # (N,)
    image: np.ndarray  # (N, 33, 3): x px, y px, visibility
    world: np.ndarray  # (N, 33, 3): x, y, z metres (hip-centred, y down)
    found: np.ndarray  # (N,) bool

    @property
    def found_frac(self) -> float:
        return float(self.found.mean()) if len(self.found) else 0.0

    def feet_visibility(self) -> float:
        """Mean visibility of the six foot points over frames with a pose."""
        if not self.found.any():
            return 0.0
        return float(np.nanmean(self.image[self.found][:, FEET, 2]))


def run_pose(frames, width: int, height: int, model_path: str) -> PoseTrack:
    """Pose for each Frame in `frames` (BGR, increasing t_ms)."""
    import mediapipe as mp  # lazy: native libs load on first use, not at import
    from mediapipe.tasks.python import BaseOptions, vision

    t, img, world, found = [], [], [], []
    landmarker = vision.PoseLandmarker.create_from_options(
        vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=vision.RunningMode.VIDEO,
        )
    )
    try:
        for f in frames:
            rgb = np.ascontiguousarray(f.image[:, :, ::-1])
            res = landmarker.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), int(round(f.t_ms))
            )
            t.append(f.t_ms)
            if res.pose_landmarks:
                img.append(
                    [(p.x * width, p.y * height, p.visibility) for p in res.pose_landmarks[0]]
                )
                world.append([(p.x, p.y, p.z) for p in res.pose_world_landmarks[0]])
                found.append(True)
            else:
                img.append(np.full((N_LANDMARKS, 3), np.nan))
                world.append(np.full((N_LANDMARKS, 3), np.nan))
                found.append(False)
    finally:
        landmarker.close()
    return PoseTrack(
        t_ms=np.asarray(t, dtype=float),
        image=np.asarray(img, dtype=float).reshape(-1, N_LANDMARKS, 3),
        world=np.asarray(world, dtype=float).reshape(-1, N_LANDMARKS, 3),
        found=np.asarray(found, dtype=bool),
    )

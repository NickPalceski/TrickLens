"""User-facing reasons a clip is `unanalyzable` after the analyzer ran
(steps 6c-2 on). Shown to the user as-is, so each says what to fix.

The file-level reasons from the media step ("unreadable video file", "no
video stream found", "clip too short") live in media.py, and the worker's
"analysis failed" in app/worker.py. See docs/components/analyzer.md, The
confidence gate, as built (6c-2).
"""

TOO_DARK = "too dark"
NO_AIRTIME = "no clean airtime found"
TOO_FAR = "skater too far from camera"
LEFT_FRAME = "trick left the frame"
BODY_NOT_VISIBLE = "body not clearly visible"
CLIP_ENDS = "clip ends too soon after the landing"
NO_LANDING = "no landed trick detected"

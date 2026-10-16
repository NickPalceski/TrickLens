"""User-facing reasons a clip is `unanalyzable` after the analyzer ran
(steps 6c-2 on). Shown to the user as-is, so each says what to fix.

The file-level reasons from the media step ("unreadable video file", "no
video stream found", "clip too short") live in media.py. See
docs/components/analyzer.md, The confidence gate, as built (6c-2).

Pure constants, no imports: app/worker.py and app/sweep.py import this
module in the API image too, unlike the rest of app.analyzer.
"""

TOO_DARK = "too dark"
NO_AIRTIME = "no clean airtime found"
TOO_FAR = "skater too far from camera"
LEFT_FRAME = "trick left the frame"
BODY_NOT_VISIBLE = "body not clearly visible"
CLIP_ENDS = "clip ends too soon after the landing"
NO_LANDING = "no landed trick detected"

# The analyzer itself broke, not the clip (6c-3). The whole clip: a crash
# outside the per-trick work, every trick crashing, the worker's last-receive
# give-up, or app/sweep.py. One trick: that trick is left out like a bail
# and the rest are still scored. See docs/components/analyzer.md, Worker.
ANALYSIS_FAILED = "analysis failed"
TRICK_FAILED = "analysis failed for this trick"

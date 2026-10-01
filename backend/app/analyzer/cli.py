"""Run the analyzer on a local clip and see what it saw (step 6b).

    make analyze-clip FILE=tests/fixtures/clips/kickflip_sketchy_60fps.mov

Same path as the worker: probe + transcode the file exactly as media.py
does, then Stage A on the transcode. It prints the trick windows and
timings, and writes a debug video next to the input (under `_debug/`).
The debug video has:
- the skater's box (green), the board (orange), other people (grey);
- the elevation curves along the bottom: feet (blue), board (orange), and
  the airborne signal both must agree on (white), against the pop
  threshold;
- each trick window shaded, with pop/apex/landing marked.

That video is the real check on Stage A until calibration (6d): watch it
and confirm it found your pop.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

import cv2
import numpy as np

from app.analyzer import localize, media
from app.analyzer.frames import iter_frames
from app.config import get_settings

_GREEN, _ORANGE, _GREY = (80, 220, 80), (0, 140, 255), (160, 160, 160)
_BLUE, _WHITE, _RED = (255, 160, 60), (255, 255, 255), (60, 60, 255)
_PLOT_H = 170
_PLOT_MAX = 0.5  # elevation shown at the top of the plot, in skater heights


def _box(img, d, color, label):
    p1, p2 = (int(d.x1), int(d.y1)), (int(d.x2), int(d.y2))
    cv2.rectangle(img, p1, p2, color, 2)
    if label:
        cv2.putText(
            img, label, (p1[0], max(12, p1[1] - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1
        )


def _plot(width: int, r: localize.StageAResult, cursor: int) -> np.ndarray:
    s = r.signals
    n = len(s.t_ms)
    img = np.zeros((_PLOT_H, width, 3), np.uint8)

    def xy(i, v):
        x = int(i * (width - 1) / max(1, n - 1))
        y = int((_PLOT_H - 12) * (1 - np.clip(v, -0.05, _PLOT_MAX) / _PLOT_MAX))
        return x, y

    for w in r.windows:
        i0, i1 = (int(t * localize.SAMPLE_FPS / 1000) for t in (w.start_ms, w.end_ms))
        cv2.rectangle(img, (xy(i0, 0)[0], 0), (xy(i1, 0)[0], _PLOT_H), (60, 60, 60), -1)
    thr = xy(0, localize.MIN_POP)[1]
    cv2.line(img, (0, thr), (width, thr), _RED, 1)
    cv2.putText(img, f"pop threshold {localize.MIN_POP}", (4, thr - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, _RED, 1)  # fmt: skip
    for series, color in ((s.elev_feet, _BLUE), (s.elev_board, _ORANGE), (s.elev_air, _WHITE)):
        pts = [xy(i, v) for i, v in enumerate(series) if not np.isnan(v)]
        if len(pts) > 1:
            cv2.polylines(img, [np.array(pts, np.int32)], False, color, 2 if color == _WHITE else 1)
    cx = xy(cursor, 0)[0]
    cv2.line(img, (cx, 0), (cx, _PLOT_H), (0, 255, 255), 1)
    cv2.putText(img, "feet", (width - 150, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, _BLUE, 1)
    cv2.putText(img, "board", (width - 110, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, _ORANGE, 1)
    cv2.putText(img, "both", (width - 60, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, _WHITE, 1)
    return img


def write_debug_video(
    processed: str, info: media.VideoInfo, r: localize.StageAResult, out: str
) -> None:
    w, h = info.width, info.height
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{w}x{h + _PLOT_H}", "-r", str(localize.SAMPLE_FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out],
        stdin=subprocess.PIPE,
    )  # fmt: skip
    assert enc.stdin is not None
    for f in iter_frames(processed, w, h, localize.SAMPLE_FPS):
        i = f.index
        if i >= len(r.skater):
            break
        img = f.image.copy()
        for o in r.others[i]:
            _box(img, o, _GREY, "")
        if r.skater[i] is not None:
            _box(img, r.skater[i], _GREEN, "skater")
        if r.board[i] is not None:
            _box(img, r.board[i], _ORANGE, "board")
        label = f"t={f.t_ms / 1000:.2f}s"
        for n, win in enumerate(r.windows, 1):
            if win.start_ms <= f.t_ms <= win.end_ms:
                phase = (
                    "POP" if abs(f.t_ms - win.pop_ms) < 40
                    else "APEX" if abs(f.t_ms - win.apex_ms) < 40
                    else "LAND" if abs(f.t_ms - win.land_ms) < 40
                    else "in air" if win.pop_ms < f.t_ms < win.land_ms
                    else ""
                )  # fmt: skip
                label += f"  trick {n} {phase}"
        cv2.rectangle(img, (0, 0), (w, 28), (0, 0, 0), -1)
        cv2.putText(img, label, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        enc.stdin.write(np.vstack([img, _plot(w, r, i)]).tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("debug video encode failed")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("file")
    ap.add_argument("--no-video", action="store_true", help="skip writing the debug video")
    args = ap.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="tricklens-cli-") as tmp:
        processed = os.path.join(tmp, "processed.mp4")
        info = media.probe(args.file)
        media.transcode(args.file, processed, info)
        pinfo = media.probe(processed)
        r = localize.analyze(processed, pinfo, get_settings().yolox_model_path)

        print(json.dumps({
            "file": args.file,
            "source": {"fps": round(info.fps, 2), "duration_ms": info.duration_ms},
            "processed": {"size": f"{pinfo.width}x{pinfo.height}", "fps": pinfo.output_fps},
            "skater_coverage": round(r.skater_coverage, 2),
            "skater_height_frac": round(r.skater_height_frac, 3),
            "tricks": [
                {"pop_ms": round(w.pop_ms), "apex_ms": round(w.apex_ms),
                 "land_ms": round(w.land_ms), "airtime_ms": round(w.airtime_ms),
                 "peak_elevation": round(w.peak_elevation, 3),
                 "window_ms": [round(w.start_ms), round(w.end_ms)]}
                for w in r.windows
            ],
            "timings_s": {k: round(v, 2) for k, v in r.timings_s.items()},
        }, indent=2))  # fmt: skip

        if not args.no_video:
            out_dir = os.path.join(os.path.dirname(os.path.abspath(args.file)), "_debug")
            os.makedirs(out_dir, exist_ok=True)
            stem = os.path.splitext(os.path.basename(args.file))[0]
            out = os.path.join(out_dir, f"{stem}.debug.mp4")
            write_debug_video(processed, pinfo, r, out)
            # Relative to backend/ (the container's /var/task), which is how
            # the file is reached on the host.
            print(f"debug video: backend/{os.path.relpath(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

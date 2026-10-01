"""YOLOX pre/post-processing and the person tracker (step 6b).

No model file needed: postprocess() is fed a hand-built raw output, so this
runs in CI. The model itself is exercised by test_analyzer_real_clips.py
(local only) and `make analyze-clip`.

Worker image only (needs numpy/OpenCV). It skips under `make test`.
"""

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from app.analyzer.detect import (  # noqa: E402
    PERSON,
    SKATEBOARD,
    Detection,
    _make_grids,
    letterbox,
    postprocess,
)
from app.analyzer.track import pick_skater, track_people  # noqa: E402

INPUT_HW = (416, 416)


def test_letterbox_keeps_aspect_and_pads_with_114():
    frame = np.zeros((1280, 720, 3), np.uint8)  # portrait 720p
    blob, ratio = letterbox(frame, INPUT_HW)
    assert blob.shape == (3, 416, 416) and blob.dtype == np.float32
    assert ratio == pytest.approx(416 / 1280)
    resized_w = round(720 * ratio)  # 234
    assert (blob[:, :, :resized_w] == 0).all()  # the (black) frame, top-left
    assert (blob[:, :, resized_w + 1 :] == 114).all()  # padding


def _raw_with(boxes: list[tuple[int, float, float, float, float, float]]) -> np.ndarray:
    """A raw YOLOX output where anchor rows encode the given boxes exactly.

    Each box: (class, score, cx, cy, w, h) in *input* pixels. It's placed on
    a stride-8 grid cell, with the raw values inverted from decode:
    xy = (raw + grid) * stride, wh = exp(raw) * stride.
    """
    grids, strides = _make_grids(INPUT_HW)
    raw = np.zeros((len(grids), 85), np.float32)
    raw[:, 2:4] = -10  # every unused anchor: a vanishing box
    for row, (cls, score, cx, cy, w, h) in enumerate(boxes):
        i = row * 7 + 3  # any distinct stride-8 anchors
        s = strides[i, 0]
        raw[i, 0] = cx / s - grids[i, 0]
        raw[i, 1] = cy / s - grids[i, 1]
        raw[i, 2:4] = np.log([w / s, h / s])
        raw[i, 4] = 1.0  # objectness
        raw[i, 5 + cls] = score
    return raw, grids, strides


def test_postprocess_decodes_boxes_back_to_frame_pixels():
    ratio = 0.5  # the frame was twice the input size
    raw, grids, strides = _raw_with(
        [(PERSON, 0.9, 100, 80, 40, 120), (SKATEBOARD, 0.7, 104, 150, 50, 12)]
    )
    dets = postprocess(raw, ratio, grids, strides, (PERSON, SKATEBOARD), 0.25, 0.45)
    by_cls = {d.cls: d for d in dets}
    p = by_cls[PERSON]
    assert p.score == pytest.approx(0.9)
    assert (p.x1, p.y1, p.x2, p.y2) == pytest.approx((160, 40, 240, 280), abs=0.5)  # /0.5
    assert by_cls[SKATEBOARD].center == pytest.approx((208, 300), abs=0.5)


def test_postprocess_filters_class_and_score():
    raw, grids, strides = _raw_with(
        [(PERSON, 0.9, 100, 80, 40, 120), (SKATEBOARD, 0.1, 104, 150, 50, 12)]
    )
    dets = postprocess(raw, 1.0, grids, strides, (SKATEBOARD,), 0.25, 0.45)
    assert dets == []  # person filtered by class, board by score


def test_postprocess_nms_merges_duplicates():
    raw, grids, strides = _raw_with(
        [(PERSON, 0.9, 100, 80, 40, 120), (PERSON, 0.8, 102, 82, 40, 120)]
    )
    assert len(postprocess(raw, 1.0, grids, strides, (PERSON,), 0.25, 0.45)) == 1


def _person(x: float, y: float = 600, h: float = 200) -> Detection:
    return Detection(PERSON, 0.9, x, y, x + h * 0.4, y + h)


def test_tracker_follows_a_moving_person_through_a_short_miss():
    frames = [[_person(100 + 6 * i)] for i in range(20)]
    for i in (8, 9, 10):  # detector misses mid-trick
        frames[i] = []
    tracks = track_people(frames)
    assert len(tracks) == 1
    assert len(tracks[0].boxes) == 17


def test_tracker_separates_two_people():
    frames = [[_person(100 + 2 * i), _person(500 - 2 * i)] for i in range(10)]
    assert len(track_people(frames)) == 2


def test_skater_is_the_person_with_the_board_not_the_biggest():
    """A bystander nearer the camera (taller box) vs the skater with a board."""
    frames = [[_person(100, h=200), _person(500, h=300)] for _ in range(10)]
    tracks = track_people(frames)
    skater_track = next(t for t in tracks if t.last.x1 == 100)
    has_board = {(skater_track.id, i): True for i in range(10)}
    assert pick_skater(tracks, has_board) is skater_track

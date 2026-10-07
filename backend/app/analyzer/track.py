"""Follow people across frames, and pick the skater (step 6b).

A small greedy IoU tracker, not ByteTrack. The plan named supervision's
ByteTrack, but supervision deprecated it in 0.28 and removes it in 0.31.
Its successor package (`trackers`) pulls in the non-headless OpenCV again,
the same libGL problem Dockerfile.worker already works around for
mediapipe. ByteTrack's strengths (recovering low-score detections, many
objects crossing in a crowd) also aren't what this needs: one skater,
followed at ~15fps, usually alone or with a few bystanders. See
docs/components/analyzer.md.

Boards aren't tracked at all. localize.py picks, per frame, the board
nearest the skater's feet.
"""

from dataclasses import dataclass, field

from app.analyzer.detect import Detection

# A track survives this many missed frames (~0.5s at 15fps) before it ends:
# long enough to bridge a detector miss mid-trick, short enough that a new
# person walking into the same spot doesn't inherit the old track.
MAX_MISSED = 8
MIN_IOU = 0.2


def iou(a: Detection, b: Detection) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    union = a.width * a.height + b.width * b.height - inter
    return inter / union if union > 0 else 0.0


@dataclass
class Track:
    id: int
    boxes: dict[int, Detection] = field(default_factory=dict)  # frame index -> box
    missed: int = 0

    @property
    def last(self) -> Detection:
        return self.boxes[max(self.boxes)]


def track_people(per_frame: list[list[Detection]]) -> list[Track]:
    """Greedy IoU association, highest-overlap pairs first.

    `per_frame[i]` is frame i's person detections. Returns every track,
    finished or not.
    """
    active: list[Track] = []
    finished: list[Track] = []
    next_id = 0
    for i, dets in enumerate(per_frame):
        pairs = sorted(
            ((iou(t.last, d), ti, di) for ti, t in enumerate(active) for di, d in enumerate(dets)),
            reverse=True,
        )
        used_t: set[int] = set()
        used_d: set[int] = set()
        for score, ti, di in pairs:
            if score < MIN_IOU:
                break
            if ti in used_t or di in used_d:
                continue
            active[ti].boxes[i] = dets[di]
            active[ti].missed = 0
            used_t.add(ti)
            used_d.add(di)

        still: list[Track] = []
        for ti, t in enumerate(active):
            if ti not in used_t:
                t.missed += 1
            (still if t.missed <= MAX_MISSED else finished).append(t)
        active = still
        for di, d in enumerate(dets):
            if di not in used_d:
                active.append(Track(id=next_id, boxes={i: d}))
                next_id += 1
    return finished + active


def pick_skater(tracks: list[Track], has_board_near: dict[tuple[int, int], bool]) -> Track | None:
    """The skater is the person who is big, present a lot, and *has a board
    at their feet*. That last part is what beats a bystander standing
    closer to the camera.

    `has_board_near[(track_id, frame_index)]` says whether a board was
    detected near that track's feet in that frame.
    """

    def score(t: Track) -> float:
        return sum(
            box.height * (3.0 if has_board_near.get((t.id, i), False) else 1.0)
            for i, box in t.boxes.items()
        )

    return max(tracks, key=score, default=None)

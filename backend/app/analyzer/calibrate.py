"""Tune calibration.py against hand-judged clips (step 6d).

    make calibrate

Reads `judgments.toml` next to the real clips (gitignored, like them), runs
the analyzer once per judged clip, then reports:
- **verdicts**: the analyzer's landed / bailed / failed against yours, per
  trick, plus tricks it missed or found extra;
- **subscores**: on tricks you both call landed, how far each subscore is
  from yours now, after fitting, and after fitting with that trick left out
  (leave-one-out: with ~20 tricks, overfitting is the real risk);
- **each measurement**: how well it tracks your score, and the ramp a fit
  proposes for it;
- **clip scores**: yours (the average of your subscores, the same way the
  analyzer averages) against the analyzer's, now and proposed.

It ends with proposed constants to paste into calibration.py. Nothing is
changed automatically: a person reviews the report first.

The analyzer's output per clip is cached as `_debug/<clip>.analysis.json`,
keyed by a hash of the analyzer's code (everything but calibration.py and
this file) and the clip file, so re-fitting is instant and a change to
measure.py re-runs the clips by itself.

**Fitting.** Each measurement is fitted on its own against the subscore it
feeds: least squares on (measurement, your score), turned back into a ramp
that keeps the current end scores (e.g. 20 → 100) and moves the
measurements where they're reached. A subscore with several measurements is
still their mean, each fitted against the same score: fewer parameters than
a joint fit, which matters with this little data. A measurement is left as
it is when it has too few points, tracks your score too weakly, or would
flip direction (better pop scoring lower), and the report says which. Tricks
with a foot down are left out of the roll-away fit, since their score is
FOOT_DOWN_CAP whatever the ramp says.

See docs/components/analyzer.md, Calibration (6d), for the judgments format.
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from statistics import fmean

from app.analyzer import calibration as C

CLIPS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "fixtures", "clips")
JUDGMENTS = "judgments.toml"

MIN_POINTS = 5  # per measurement, to fit at all
MIN_CORRELATION = 0.3  # |r| below this: too weak to move the ramp
MATCH_WITHIN_S = 0.75  # a judged trick's `at` vs a detected pop

# Outcomes you can give a trick. "landed-push" is landed, with a foot put
# down to push too early: the push rule's test case (6d-2).
OUTCOMES = ("landed", "landed-push", "bailed")
NA = "n/a"

# Analyzer code whose change invalidates the cache: everything that
# decides verdicts and measurements, but not how they're scored.
_CODE = (
    "media", "frames", "detect", "track", "localize", "pose",
    "stage_b", "landed", "gate", "measure", "pipeline", "reasons",
)  # fmt: skip


# --- judgments ------------------------------------------------------------------


@dataclass
class JudgedTrick:
    outcome: str
    at_s: float | None  # roughly when the pop is; needed when a clip has several
    scores: dict[str, float | None]  # subscore -> yours; None = n/a; absent = not judged

    @property
    def landed(self) -> bool:
        return self.outcome in ("landed", "landed-push")


@dataclass
class JudgedClip:
    file: str
    tricks: list[JudgedTrick]
    note: str = ""


def parse_judgments(data: Mapping) -> list[JudgedClip]:
    """judgments.toml, already parsed. Raises ValueError on a mistake, naming
    the clip, so a typo can't silently drop a judgment."""
    clips = []
    for c in data.get("clip", []):
        name = c.get("file")
        if not name:
            raise ValueError("every [[clip]] needs a file")
        tricks = []
        for i, t in enumerate(c.get("trick", []), 1):
            where = f"{name} trick {i}"
            outcome = t.get("outcome")
            if outcome not in OUTCOMES:
                raise ValueError(f"{where}: outcome must be one of {OUTCOMES}, got {outcome!r}")
            unknown = set(t) - {"outcome", "at", *C.SUBSCORES}
            if unknown:
                raise ValueError(f"{where}: unknown keys {sorted(unknown)}")
            scores: dict[str, float | None] = {}
            for s in C.SUBSCORES:
                if s not in t:
                    continue
                v = t[s]
                if v == NA:
                    scores[s] = None
                elif isinstance(v, int | float) and 0 <= v <= 100:
                    scores[s] = float(v)
                else:
                    raise ValueError(f'{where}: {s} must be 0-100 or "n/a", got {v!r}')
            if scores and outcome == "bailed":
                raise ValueError(f"{where}: bails aren't scored, so leave out its subscores")
            tricks.append(JudgedTrick(outcome, t.get("at"), scores))
        if not tricks:
            raise ValueError(f"{name}: needs at least one [[clip.trick]]")
        if len(tricks) > 1 and any(t.at_s is None for t in tricks):
            raise ValueError(f"{name}: with several tricks, give each one `at` (seconds)")
        clips.append(JudgedClip(name, tricks, c.get("note", "")))
    return clips


# --- pairing judged tricks with what the analyzer found ----------------------------


@dataclass
class Pair:
    clip: str
    judged: JudgedTrick | None  # None: the analyzer found a trick you didn't judge
    found: dict | None  # a details["tricks"] entry; None: the analyzer missed it


def pair_tricks(clip: JudgedClip, found: Sequence[dict]) -> list[Pair]:
    """Match by order when every judged trick lacks `at` and the counts
    agree; otherwise each judged trick takes the nearest unused pop within
    MATCH_WITHIN_S."""
    if all(t.at_s is None for t in clip.tricks) and len(clip.tricks) == len(found):
        return [Pair(clip.file, j, f) for j, f in zip(clip.tricks, found, strict=True)]
    unused = list(found)
    pairs = []
    for j in clip.tricks:
        best = None
        if j.at_s is not None and unused:
            best = min(unused, key=lambda f: abs(f["pop_ms"] / 1000 - j.at_s))
            if abs(best["pop_ms"] / 1000 - j.at_s) > MATCH_WITHIN_S:
                best = None
        elif j.at_s is None and len(clip.tricks) == 1 and len(unused) == 1:
            best = unused[0]
        if best is not None:
            unused.remove(best)
        pairs.append(Pair(clip.file, j, best))
    pairs += [Pair(clip.file, None, f) for f in unused]
    return pairs


# --- fitting ---------------------------------------------------------------------


@dataclass
class Fit:
    measurement: str
    ramp_name: str
    n: int
    r: float | None
    status: str  # "fitted", "too few", "weak", "flips direction", "flat"
    proposed: C.Ramp  # the current ramp unless status == "fitted"


def _linear(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float, float | None]:
    """(intercept, slope, correlation) of the least-squares line."""
    mx, my = fmean(xs), fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    if sxx == 0:
        return my, 0.0, None
    slope = sxy / sxx
    r = sxy / (sxx * syy) ** 0.5 if syy > 0 else None
    return my - slope * mx, slope, r


def fit_ramp(measurement: str, ramp_name: str, points: Sequence[tuple[float, float]]) -> Fit:
    """Fit one measurement's ramp to (measurement, your score) points."""
    current = C.current_ramps()[ramp_name]
    n = len(points)
    if n < MIN_POINTS:
        return Fit(measurement, ramp_name, n, None, "too few", current)
    a, b, r = _linear([p[0] for p in points], [p[1] for p in points])
    xa, sa, xb, sb = current
    direction = (sb - sa) / (xb - xa)
    if b == 0 or r is None:
        return Fit(measurement, ramp_name, n, r, "flat", current)
    # Weak first: noise that happens to slope the wrong way is "weak", and
    # "flips direction" means a clear trend the opposite way.
    if abs(r) < MIN_CORRELATION:
        return Fit(measurement, ramp_name, n, r, "weak", current)
    if (b > 0) != (direction > 0):
        return Fit(measurement, ramp_name, n, r, "flips direction", current)
    return Fit(measurement, ramp_name, n, r, "fitted", ((sa - a) / b, sa, (sb - a) / b, sb))


def training_points(pairs: Iterable[Pair], subscore: str, measurement: str):
    """(measurement, your score) on tricks you both call landed."""
    pts = []
    for p in pairs:
        if not (p.judged and p.found and p.judged.landed and p.found["outcome"] == "landed"):
            continue
        m = p.found.get("measurements") or {}
        y = p.judged.scores.get(subscore)
        if m.get(measurement) is None or y is None:
            continue
        if subscore == "roll_away" and m.get("foot_down"):
            continue  # capped at FOOT_DOWN_CAP whatever the ramp says
        pts.append((float(m[measurement]), y))
    return pts


def fit_all(pairs: Sequence[Pair]) -> dict[str, Fit]:
    """One Fit per ramp constant."""
    return {
        ramp_name: fit_ramp(key, ramp_name, training_points(pairs, sub, key))
        for sub, comps in C.COMPONENTS.items()
        for key, ramp_name in comps
    }


def _scored(pairs: Sequence[Pair]) -> list[Pair]:
    return [
        p
        for p in pairs
        if p.judged and p.found and p.judged.landed and p.found["outcome"] == "landed"
    ]


def errors(pairs: Sequence[Pair], ramps: Mapping[str, C.Ramp]) -> dict[str, float | None]:
    """Mean absolute error per subscore, scoring with `ramps`."""
    out = {}
    for sub in C.SUBSCORES:
        diffs = []
        for p in _scored(pairs):
            y = p.judged.scores.get(sub)
            pred = C.subscores(p.found.get("measurements") or {}, ramps)[sub]
            if y is not None and pred is not None:
                diffs.append(abs(pred - y))
        out[sub] = fmean(diffs) if diffs else None
    return out


def leave_one_out(pairs: Sequence[Pair]) -> dict[str, float | None]:
    """Mean absolute error per subscore when each trick is scored by a fit
    made without it: what to expect on a clip the fit hasn't seen."""
    scored = _scored(pairs)
    diffs: dict[str, list[float]] = {s: [] for s in C.SUBSCORES}
    for held in scored:
        rest = [p for p in pairs if p is not held]
        ramps = {name: f.proposed for name, f in fit_all(rest).items()}
        pred = C.subscores(held.found.get("measurements") or {}, ramps)
        for sub in C.SUBSCORES:
            y = held.judged.scores.get(sub)
            if y is not None and pred[sub] is not None:
                diffs[sub].append(abs(pred[sub] - y))
    return {s: fmean(d) if d else None for s, d in diffs.items()}


def clip_scores(clip: str, pairs: Sequence[Pair], ramps: Mapping[str, C.Ramp]):
    """(yours, analyzer's) steeze for one clip, both averaged over the landed
    tricks the way calibration.aggregate does. None where there's nothing."""
    mine = [p.judged.scores for p in pairs if p.clip == clip and p.judged and p.judged.landed]
    theirs = [
        C.subscores(p.found.get("measurements") or {}, ramps)
        for p in pairs
        if p.clip == clip and p.found and p.found["outcome"] == "landed"
    ]
    yours = C.aggregate([{s: m.get(s) for s in C.SUBSCORES} for m in mine])[1] if mine else None
    return yours, C.aggregate(theirs)[1] if theirs else None


# --- the report --------------------------------------------------------------------


def _f(v: float | None, nd: int = 1) -> str:
    return "-" if v is None else f"{v:.{nd}f}"


def _outcome(p: Pair) -> tuple[str, str]:
    yours = p.judged.outcome if p.judged else "(not judged)"
    theirs = p.found["outcome"] if p.found else "(missed)"
    return yours, theirs


def _agrees(p: Pair) -> bool:
    if not (p.judged and p.found):
        return False
    return p.judged.landed == (p.found["outcome"] == "landed")


def report(clips: Sequence[JudgedClip], pairs: Sequence[Pair]) -> str:
    lines: list[str] = []
    add = lines.append
    fits = fit_all(pairs)
    proposed = {name: f.proposed for name, f in fits.items()}
    now = C.current_ramps()

    add(f"== Verdicts ({len(clips)} clips)")
    add(f"{'clip':40} {'at':>6}  {'you':14} analyzer")
    for p in pairs:
        yours, theirs = _outcome(p)
        at = p.found["pop_ms"] / 1000 if p.found else (p.judged.at_s if p.judged else None)
        flag = "" if _agrees(p) else "   <-- differs"
        add(f"{p.clip[:40]:40} {_f(at, 2):>6}  {yours:14} {theirs}{flag}")
    both = [p for p in pairs if p.judged and p.found]
    add(
        f"agree on landed vs not: {sum(_agrees(p) for p in both)}/{len(both)}; "
        f"missed {sum(1 for p in pairs if p.judged and not p.found)}, "
        f"extra {sum(1 for p in pairs if p.found and not p.judged)}"
    )
    pushes = [p for p in pairs if p.judged and p.judged.outcome == "landed-push"]
    if pushes:
        add(
            f"early pushes: {len(pushes)}, called landed by the analyzer: "
            f"{sum(1 for p in pushes if p.found and p.found['outcome'] == 'landed')}"
        )

    scored = _scored(pairs)
    e_now, e_fit, e_loo = errors(pairs, now), errors(pairs, proposed), leave_one_out(pairs)
    add("")
    add(f"== Subscores (tricks you both call landed: {len(scored)}), mean error in points")
    add(f"{'subscore':18} {'now':>6} {'fitted':>7} {'left-out':>9}")
    for s in C.SUBSCORES:
        add(f"{s:18} {_f(e_now[s]):>6} {_f(e_fit[s]):>7} {_f(e_loo[s]):>9}")
    add("A fitted error far below the left-out one means the fit memorised these clips.")

    add("")
    add("== Measurements")
    add(f"{'ramp':18} {'measurement':24} {'n':>3} {'r':>6}  status")
    for name, f in fits.items():
        add(f"{name:18} {f.measurement:24} {f.n:>3} {_f(f.r, 2):>6}  {f.status}")
    down = [
        p.judged.scores["roll_away"]
        for p in scored
        if (p.found.get("measurements") or {}).get("foot_down")
        and p.judged.scores.get("roll_away") is not None
    ]
    if down:
        add(f"foot down: your roll-away averages {fmean(down):.0f} (cap is {C.FOOT_DOWN_CAP:.0f})")

    add("")
    add("== Clip scores (steeze)")
    add(f"{'clip':40} {'you':>6} {'now':>6} {'proposed':>9}")
    for c in clips:
        yours, before = clip_scores(c.file, pairs, now)
        _, after = clip_scores(c.file, pairs, proposed)
        add(f"{c.file[:40]:40} {_f(yours):>6} {_f(before):>6} {_f(after):>9}")

    add("")
    add("== Proposed constants (review, then paste into calibration.py)")
    for name, f in fits.items():
        r = tuple(round(v, 4) for v in f.proposed)
        add(f"{name} = {r}" + ("" if f.status == "fitted" else f"  # unchanged: {f.status}"))
    return "\n".join(lines)


# --- running the analyzer (worker image only) ----------------------------------------


def code_hash() -> str:
    here = os.path.dirname(__file__)
    h = hashlib.sha256()
    for mod in _CODE:
        with open(os.path.join(here, f"{mod}.py"), "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:16]


def analyze_cached(path: str, cache_dir: str, code: str) -> dict:
    """The analyzer's details for one clip, from cache when nothing changed."""
    st = os.stat(path)
    key = f"{code}:{st.st_size}:{int(st.st_mtime)}"
    stem = os.path.splitext(os.path.basename(path))[0]
    cache = os.path.join(cache_dir, f"{stem}.analysis.json")
    if os.path.exists(cache):
        with open(cache) as f:
            hit = json.load(f)
        if hit.get("key") == key:
            print(f"{stem}: from cache", file=sys.stderr)
            return hit["details"]

    print(f"{stem}: analyzing (not cached, or the analyzer changed) ...", file=sys.stderr)
    from app.analyzer import media, pipeline  # lazy: the CV stack
    from app.config import get_settings

    settings = get_settings()
    with tempfile.TemporaryDirectory(prefix="tricklens-calibrate-") as tmp:
        processed = os.path.join(tmp, "processed.mp4")
        media.transcode(path, processed, media.probe(path))
        res = pipeline.analyze(processed, settings.yolox_model_path, settings.pose_model_path, stem)
    details = res.details()
    os.makedirs(cache_dir, exist_ok=True)
    with open(cache, "w") as f:
        json.dump({"key": key, "details": details}, f, indent=1)
    return details


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--clips", default=CLIPS_DIR, help="folder with the clips and judgments.toml")
    args = ap.parse_args(argv)

    path = os.path.join(args.clips, JUDGMENTS)
    if not os.path.exists(path):
        print(f"no {path}: see docs/components/analyzer.md, Calibration (6d)", file=sys.stderr)
        return 1
    with open(path, "rb") as f:
        clips = parse_judgments(tomllib.load(f))

    code = code_hash()
    pairs: list[Pair] = []
    for c in clips:
        clip_path = os.path.join(args.clips, c.file)
        if not os.path.exists(clip_path):
            print(f"{c.file}: not in {args.clips}", file=sys.stderr)
            return 1
        details = analyze_cached(clip_path, os.path.join(args.clips, "_debug"), code)
        pairs += pair_tricks(c, details["tricks"])
    print(report(clips, pairs))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Analyzer and worker

Everything that happens to a clip after upload: the worker that picks it
up, the media step (verify, transcode, thumbnail), and the steeze analyzer
(find the tricks, then measure them). Code: `backend/app/worker.py`,
`backend/app/analyzer/`, `backend/Dockerfile.worker`.

← Back to the [architecture overview](../ARCHITECTURE.md).

**Status:** media (6a), Stage A (6b), Stage B (6c-1) and the landed
check and confidence gate (6c-2) are live. 6c-3 (measurements,
calibration, scoring, the stub off) is live and verified in prod. 6d-2,
the MVP pass over the user's seven real clips, fixed what they showed
(`steeze-v0.2-uncalibrated`, see [Calibration (6d)](#calibration-6d)); the
constants are still guesses until hand-judged scores exist. The gate
decides the clip's status and calibration.py its score; the stub only runs
where `ANALYZER=stub` (the API image and CI).
See the [build order](../ARCHITECTURE.md#build-order).

## What the worker does with one clip

```mermaid
flowchart TD
    msg(["SQS message {clip_id}"])
    claim{"Atomic claim:<br/>queued, or analyzing<br/>with an expired lease?"}
    skip(["Skip: finished,<br/>or another run owns it"])
    mode{"ANALYZER?"}
    stub["Stub score<br/>(API image, tests)"]
    dl["Download raw/ upload to /tmp"]
    probe["ffprobe: real duration + fps"]
    bad(["unanalyzable<br/>'unreadable video file' /<br/>'no video stream found' /<br/>'clip too short'"])
    tx["ffmpeg: 720p, upright,<br/>constant fps ≤ 60, ≤ 30s"]
    sa["Stage A: find the pops<br/>(15fps, YOLOX + tracker)"]
    sb["Stage B per trick: pose +<br/>board + take-off/touch-down<br/>(native fps)"]
    gt["Landed check per trick +<br/>confidence gate"]
    meas["Measure each judged trick,<br/>score the landed ones,<br/>average them"]
    crash["Analyzer crash:<br/>'analysis failed'"]
    thumb["Thumbnail at the biggest<br/>pop's apex (else mid-clip)"]
    up["Upload processed/ + thumbs/"]
    write(["analyses row (+ details) +<br/>clip status analyzed / unanalyzable"])

    msg --> claim
    claim -- no --> skip
    claim -- "yes: status = analyzing" --> mode
    mode -- "stub" --> stub --> write
    mode -- "real (worker image)" --> dl --> probe
    probe -- "bad file" --> bad
    probe --> tx --> sa --> sb --> gt --> meas --> thumb
    sa -. "exception" .-> crash
    gt -. "exception" .-> crash
    crash --> thumb
    thumb --> up --> write
```

Since 6c-3 the analyzer decides the clip's status and score (until then
Stage A, Stage B and the gate were advisory: logged, with the stub
deciding). Each step logs a line: `media: …`, `stage A: …`, `stage B
trick N: …`, `landing trick N: …`, `scores trick N: {…}` for a landed
trick, then `gate: scored N landed trick(s), steeze …` or `gate: failed:
…`, and finally `-> analyzed` or `-> unanalyzable (reason)`. A crash in
one trick's Stage B or measurements fails only that trick (see
[Worker](#worker), Errors).

## Inside the analyzer

```mermaid
flowchart LR
    proc[("processed.mp4<br/>720p, constant fps")]

    subgraph stageA ["Stage A: localize.py (whole clip, 15fps)"]
        fa["frames.py<br/>decode samples"]
        det["detect.py<br/>YOLOX-Tiny on ONNX Runtime<br/>person + skateboard"]
        crop["zoomed board pass<br/>around the skater's feet"]
        trk["track.py<br/>IoU tracker, pick the skater"]
        sig["signals: feet y, board centre y,<br/>skater height"]
        pops["elevation above local ground<br/>→ pops → trick windows"]
    end

    subgraph stageB ["Stage B: stage_b.py (one window, native fps)"]
        fb["frames.py<br/>decode the window only"]
        pose["pose.py<br/>MediaPipe BlazePose 'full'"]
        bb["board every other frame,<br/>every 4th after the landing<br/>(full frame + zoomed crop)"]
        ref["refine_contacts()<br/>take-off / touch-down"]
    end

    subgraph judge ["6c-2: judge it"]
        landed["landed.py<br/>feet over the board after<br/>touch-down, stance width"]
        gate["gate.py<br/>clip checks, reasons,<br/>confidence"]
    end

    subgraph score ["6c-3: score it"]
        meas["measure.py<br/>raw measurements<br/>per judged trick"]
        cal["calibration.py<br/>subscores, averaged over<br/>the landed tricks"]
    end

    proc --> fa --> det --> trk --> sig --> pops
    det --> crop --> sig
    pops -- "window" --> fb
    proc --> fb --> pose --> ref
    fb --> bb
    ref --> landed
    bb --> landed
    landed --> gate
    pops -- "brightness, skater size" --> gate
    gate -- "judged tricks" --> meas --> cal
```

`pipeline.py` runs all of this for one clip, and both the worker and `make
analyze-clip` call it.

| Module | Job |
|---|---|
| `media.py` | ffprobe / ffmpeg wrappers: probe, transcode, thumbnail. Raises `MediaError` with a user-facing reason when the *file* is the problem |
| `frames.py` | Decodes the processed clip at a chosen rate through an ffmpeg pipe, optionally only a time window. Windowed decodes land on the same timestamp grid as whole-clip ones |
| `detect.py` | YOLOX-Tiny via ONNX Runtime: letterbox, decode the raw output, per-class NMS. One session per container, built on first use |
| `track.py` | Greedy IoU person tracker, and `pick_skater()`: the big, frequently-present person with a board at their feet |
| `localize.py` | Stage A: two detection passes, the elevation signals, pop finding, trick windows |
| `pose.py` | MediaPipe pose over a window: image landmarks (px + visibility) and hip-centred world landmarks (metres) |
| `stage_b.py` | Stage B: pose + board per window, refined take-off / touch-down |
| `landed.py` | Per trick: landed, bailed or unclear, from the feet and the board just after touch-down |
| `gate.py` | Per clip: which tricks count, the failure reason when none do, and a confidence |
| `measure.py` | Per judged trick: the raw measurements the subscores come from (6c-3) |
| `calibration.py` | Measurements → 0–100 subscores → the clip's breakdown and steeze score. Pure Python, so the API image (and 6d) can import it |
| `calibrate.py` | `make calibrate` (6d): runs the analyzer on hand-judged clips and proposes new `calibration.py` constants. A tool, not part of the worker |
| `pipeline.py` | The whole analyzer on one processed clip, with per-trick crash handling. Called by the worker and the CLI |
| `reasons.py` | The user-facing failure reasons the gate can give. Pure constants |
| `cli.py` | `make analyze-clip`: the worker's exact path on a local file, plus debug videos |

## Worker

**Triggers.** Locally, `python -m app.worker` long-polls SQS in a loop (the
Compose `worker` service). In production, an SQS event-source mapping
invokes `app.worker.lambda_handler` once per message (`batch_size = 1`).
The processing function is the same either way; only the trigger differs.

**`ANALYZER=stub|real`.** The worker image (`Dockerfile.worker`) sets
`real` itself, because it's the image that has ffmpeg and the CV stack. The
API image leaves the default, `stub`, which skips media processing and
fabricates a score. That's why `make test` (API image) can still exercise
the whole clip flow, while `make test-worker` runs the media and analyzer
tests in the worker image.

**The claim and the lease.** One `UPDATE ... WHERE status = 'queued' OR
(status = 'analyzing' AND updated_at < now() - 360s) RETURNING id` decides
ownership, so two consumers can never process the same clip at once (SQS is
at-least-once). The lease is what recovers a crashed run. A Lambda timeout
mid-transcode leaves the clip `analyzing`, and SQS redelivers after its
visibility timeout. The stub worker skipped anything not `queued`, which
would strand it forever; now a clip still `analyzing` past the lease is
reclaimed, since it outlived the 300s Lambda timeout. Every output key is
deterministic per clip, so reprocessing just overwrites them. The ordering
matters: 300s Lambda timeout < 360s lease < SQS visibility timeout (1800s
prod, 600s local). A redelivery that arrived *inside* the lease would be
skipped and deleted.

**Errors.** A bad *file* becomes `unanalyzable` with a specific reason.
An exception in the analyzer itself (6c-3) is a code bug that would fail
the same way on every retry, so it isn't retried:
- one trick's Stage B or measurements crashing leaves that trick out as
  *analysis failed for this trick*, like a bail, and the clip's other
  tricks are still judged and scored;
- a crash anywhere else (Stage A, the gate) marks the clip *analysis
  failed*;
- if no trick landed and one crashed, the clip is *analysis failed* too,
  not *no landed trick detected*: the crashed trick might have been the
  landed one.

Either way the traceback is logged, and the processed clip and thumbnail
are still uploaded so the owner can watch it. Any other exception (S3,
database) propagates, so SQS retries the message (3 receives, then the
dead-letter queue). `pipeline.analyze` has no S3 or database access, which
keeps the two kinds apart.

**A run that dies is given up on at the last receive.** A crash inside
native code (a C++ `CHECK`, a segfault) kills the whole process, so no
`except` runs and Lambda reports `Runtime.ExitError`. A Lambda timeout is
the same from the clip's side. Either way the clip is left `analyzing` with
no analysis row. SQS redelivers after the visibility timeout (1800s), the
expired lease lets the redelivery reclaim the clip, and a crash usually
repeats. The first 6c-1 prod run went this way (see
[MediaPipe 1.0's tcmalloc aborts on Lambda](#mediapipe-10s-tcmalloc-aborts-on-lambda-6c)).
Before this fix, the third crash sent the message to the DLQ with the clip
stuck in `analyzing` for good.

So the worker reads SQS's `ApproximateReceiveCount` (Lambda's record
attributes, or `receive_count` from `AnalysisQueue.receive_messages`
locally). On the delivery that reaches `MAX_RECEIVES` (3, the queue's
`maxReceiveCount`), a clip that's still `analyzing` past its lease isn't run
again. One atomic `UPDATE` marks it `unanalyzable` with an `"analysis failed"`
analysis row, and the message is deleted normally. A clip still `queued` on
its last receive has never been claimed (the earlier deliveries failed
before reaching it, e.g. the database was down), so it's processed as
usual. The trade-off: a run that hits a transient S3/database error twice
also ends up `unanalyzable` on the third receive, not retried a third time.
That's the right side to fail on, because the alternative is a clip stuck
forever.

`MAX_RECEIVES` in `app/worker.py` must match `maxReceiveCount` in
`infra/sqs.tf` and `scripts/localstack-init.sh`.

**Stuck clips are swept (6c-3).** The give-up only helps a clip some run
already claimed. A message whose every receive fails *before* the claim
(the database down, say) lands in the DLQ and leaves its clip `queued`
with nothing left to come back for it. `app/sweep.py` marks any clip still
`queued` or `analyzing` after 2 hours `unanalyzable`, with an *analysis
failed* row stamped `model_version: sweep`. Two hours is well past
anything SQS can still do (3 receives × 1800s visibility = 90 minutes).
It fails the clip rather than re-enqueuing it, because a retry would need
a counter to avoid looping forever. It runs on the rankings Lambda's
30-minute EventBridge tick (`app.rankings.lambda_handler` calls it), so
it has no infrastructure of its own; locally, `make sweep`.

**The worker image** (`backend/Dockerfile.worker`): the API's Lambda base
image plus
- a static ffmpeg/ffprobe, copied from the pinned `mwader/static-ffmpeg`
  image, so no package manager is involved;
- the CV stack in `requirements-worker.txt`: ONNX Runtime, MediaPipe,
  headless OpenCV, NumPy, SciPy;
- `mesa-libEGL` + `libglvnd-gles`, which MediaPipe's native library needs;
- the YOLOX-Tiny and pose model weights, pinned by checksum.

It's 2.73GB locally against the API's 1GB, which is why it's a separate
image in its own ECR repo. It still reuses `app.db`, `app.models` and
`app.services` exactly like the API, because it's built from the same
`backend/app/` source.

**Lambda sizing:** 3008MB, 300s timeout, 2GB `/tmp`. Memory is really the
CPU knob (Lambda allocates ~1 vCPU per 1769MB), and 3008MB is the cap new
AWS accounts start with. At most 5 runs go at once: the SQS trigger's
maximum concurrency caps it, so a burst of clips waits in the queue
instead of growing the bill (why that and not reserved concurrency:
[infrastructure](infrastructure.md#sqs-timings)).

**Measured in prod:**
- A routine cold start initializes in ~1.7s. The first invocation of a
  *newly deployed* image hits Lambda's 10s init limit once
  (`INIT_REPORT … Status: timeout`). Lambda re-runs init inside the
  invocation, so the clip still succeeds, just slower. Lambda loads
  container images lazily, so that first run reads every imported file from
  an empty cache. It happens once per deploy, not per cold start.
- 6a (media only): the 2.7s clip took 6.5s end to end, ~400MB.
- 6b (Stage A): the 4.7s kickflip took 10.7s of detection (5.86s full
  frame + 4.84s zoomed pass), about 5× local, or **~2.3s per second of
  clip**. Whole job 31.6s, 568MB. A 30s clip is therefore ~70s of Stage A
  within the 300s timeout.
- 6c-1 (Stage B): the 2.7s bail took 7.1s of Stage A and **8.9s of
  Stage B** (4.1s of it board detection), 23.4s end to end, 763MB, an
  ordinary 1.5s cold start. The kickflip, the first clip after the
  deploy, was much slower everywhere: 67.8s end to end, ~33s of it media
  before Stage A, and 23.1s of Stage B, of which ~12.5s passed before
  MediaPipe's thread pool even started (the import and landmarker
  creation). That's the same once-per-deploy cold image cache as the 10s
  init timeout above, not a per-container cost: the bail's run was a
  fresh container too and showed none of it. `pose_and_board` includes
  the MediaPipe import, because `run_pose` imports lazily.
- 6c-2 (longer window, landed check, gate): the bail took 5.0s of media
  (download 0.35s, probe + transcode 4.7s), 10.1s of Stage A and 13.0s of
  Stage B (7.4s of it board detection, up from 4.1s with the shorter
  window), 32.1s end to end, 762MB, 3.7s init. Same verdicts as local on
  both clips.
- 6c-3 (window to landing + 1.3s for roll-away): locally, Stage B went
  from ~3s to ~4.2s per trick on the kickflip; measuring and scoring take
  under 10ms. In the prod check (no CloudWatch access from the dev user,
  so wall time from `complete` to a final status): the bail took 28s, the
  kickflip 103s as the first run after the deploy (cold image cache).
- **The same clip can score a little differently in prod and locally**,
  because the transcodes differ (x264 output depends on the thread
  count). After the partial-box fix, prod's kickflip file gives 79.7 and
  the local one 77.5, with every subscore within a few points.
- The rule that follows: keep the heavy CV imports (cv2, onnxruntime,
  mediapipe) inside the handler path, never at module level, or every cold
  start pays for them during init.

## Media (6a)

`media.py` turns the raw upload into the file everything else reads:

| Decision | Why |
|---|---|
| Short side scaled to 720, never upscaled | 720p is enough for phone playback and for the detectors. Short side rather than height, so portrait clips aren't squashed to 405 wide |
| Phone rotation applied (ffmpeg auto-rotate), output has no rotation metadata | Phones store portrait video as landscape pixels plus a rotation flag. Baking the rotation in means every consumer (players, the detector) sees upright frames |
| Constant frame rate at the source rate, capped at 60 | Phone footage is usually variable-frame-rate. Stage A and B turn frame indices into milliseconds, which needs evenly spaced frames. The cap keeps 120/240fps slow-mo files a sane size; `source_fps` still records the real rate |
| Capped at 30s | Clips are 30s max; this enforces it on the actual file, not just the client's claim |
| Unreadable file / no video stream / under 0.5s → `unanalyzable` with that reason | Same fail-safe rule as the scorer: the user gets a specific reason, never a guess |
| Poster frame at the apex of the biggest pop, else the middle of the clip | The most representative frame of a skate clip is the trick in the air |
| `duration_ms` / `source_fps` overwritten with ffprobe's values | The client's values (read off its `<video>` element) are only a placeholder for drafts |

Clips play from `processed/` through the CDN once it exists. That fixed a
real production bug: `raw/` expires after 7 days, so before 6a every
published clip's video died a week after upload. Pre-6a clips were not
backfilled.

## The steeze score

### What it is not

The system does **not** identify tricks. Trick classification from video is a
research-grade problem — there is no large public labeled dataset, and the
published work is mostly IMU/accelerometer-based, which does not transfer to
phone footage. It was cut deliberately.

### What it is

An **explainable heuristic** over pretrained models. No training data, no
GPUs, fully deterministic.

**Pipeline:**

1. **ffmpeg** *(6a, done)*: verify, normalize to 720p at a constant frame
   rate, cap at 30s. See [Media](#media-6a).
2. **Detect and track** *(6b, done)*: YOLOX-Tiny on ONNX Runtime finds
   people and skateboards. It's COCO-trained, which already has both
   classes, so no training is needed. Not Ultralytics YOLOv8, for licensing
   reasons (see [Decisions](../ARCHITECTURE.md#yolox-on-onnx-runtime-not-ultralytics-yolov8--licensing)).
   A small IoU tracker follows each person, and the **skater** is the big,
   frequently-present person with a board at their feet, which beats a
   bystander nearer the camera.
3. **Localize — Stage A** *(6b, done)*: at 15fps over the whole clip, find
   the **pops**, then cut a ~1.2s window around each.
4. **Stage B** *(6c-1)*: only inside those windows, at native fps, using
   MediaPipe pose, then the landed check and the gate *(6c-2)*.
5. **Score** *(6c-3)*: raw measurements per trick, turned into subscores by
   `calibration.py` and averaged over the landed tricks. See
   [Subscores, as built](#subscores-as-built-6c-3).

> Two-stage localization is what makes 30s clips affordable: full-cost
> processing runs on roughly 5% of frames, and multi-trick lines come free.

### Stage A, as built (6b)

Two decode passes over the processed 720p clip, at `SAMPLE_FPS = 15`:

1. **Full frame:** people and boards in every sample, then track people and
   pick the skater.
2. **Zoomed board pass:** crop a square of 1.4 skater-heights around the
   skater's feet and detect boards in it, merging with the full-frame boards
   (IoU dedupe). On the tripod kickflip, where the skater is ~13% of the
   frame height, full-frame-only found the board in 30/59 frames, and full
   frame + crop found it in 56/59, including mid-flip with the board
   upside-down. That matches YOLOX-S at about a quarter of the cost
   (~23ms/frame for both passes vs ~90ms). The full-frame pass still
   matters: when the board shoots away in a bail, only it sees the board.

Then, per sample, three numbers: the skater's **feet** (bottom of their
box, i.e. the lowest foot), the **board's centre**, and the skater's
**height**. From those:

- **Ground is estimated locally**: a rolling 80th percentile of each
  signal's own y over 1.5s (image y grows downward, so high y is the
  ground). The plan was to cancel camera motion instead, but measuring the
  follow-cam bail showed that motion estimated from background features
  (distant trees) made the ground drift *worse*: 40px over 1.4s, against
  23px uncorrected. The background isn't the surface the skater rolls on,
  and the skater also moves toward the camera. The local estimate absorbs
  slow camera drift and approach/recede without modelling the camera.
- **Elevation = (ground − y) ÷ standing height**, so it's in skater heights
  and camera-distance invariant. Standing height is a rolling median, not
  per frame, because the box grows mid-trick (arms up: 194 → 242px).
- **Airborne = min(feet elevation, board elevation).** On the ground the
  board box jitters by ~0.1 of the skater's height, as much as a small pop,
  while the feet are steadier. Requiring both means noise in one can't fake
  a pop, a carried board can't (feet down), and a hop off the board can't
  (board down). Where the board is missed for a few samples (edge-on
  mid-flip), the feet stand in, but each pop still needs the board itself
  to rise ≥ 0.06 somewhere.
- **The board's centre, not its bottom edge.** On a low pop the tail stays
  near the ground while the nose lifts: the bail's board bottom rose for one
  sample, while its centre rose a steady ~0.12 over four.
- **Pops** are peaks of the airborne signal ≥ `MIN_POP = 0.08`, with
  pop/landing where it crosses 30% of the peak, 130–1500ms of airtime, and
  ≥ 0.6s apart. Each becomes a window of [pop − 0.4s, landing + 1.3s].
  The end was max(pop + 0.8s, landing + 0.4s) until 6c-2, which stopped
  short of the landed check's span on both real clips, then landing +
  0.8s until 6c-3 extended it for roll-away (0.6–1.2s after touch-down).
- **6d-2:** a pop in a clip's first 0.3s, or airborne from its first
  sample, is skipped (`MIN_LEAD_MS`): the clip starts mid-action, with no
  take-off to judge. The nose-grind clip opens with the board thrown down
  and hopped on, which had scored as a landed trick. And windows whose
  airborne spans overlap merge into one (`merge_overlapping`): a grind's
  two peaks (onto the ledge, off its end) had found the same landing and
  scored the trick twice.

**On the real clips**, also checked by eye in the debug video:

| Clip | Pop | Apex | Landing | Peak | Notes |
|---|---|---|---|---|---|
| Tripod kickflip | 1.23s | 1.47s | 1.57s | 0.32 | board caught mid-flip |
| Follow-cam bail | 1.10s | 1.13s | 1.30s | 0.093 | lands *without* the board at 1.33s, which is the evidence 6c's landed check will use |

In prod the kickflip found the identical window `(1233, 1467, 1567)`.

### Stage B, as built so far (6c-1)

For each Stage A window, `stage_b.py` decodes **just that window** at the
clip's native rate (60fps for phone footage), and in one pass:
- runs **pose** on every frame (`pose.py`): MediaPipe's BlazePose GHUM
  "full" model in VIDEO mode, on the full frame;
- runs the **board** detector on every other frame from 0.2s before the
  pop to Stage A's landing + 0.8s, with Stage A's full-frame + zoomed-crop
  merge. That covers the air and the landed check. From there to the end
  of the window (roll-away, 6c-3) it's every 4th frame, which halves what
  the longer window costs;
- **refines take-off and touch-down** from the lowest foot point's height
  above its own resting level. The level before the pop is the deck; the
  level after landing is the deck or the ground (a bail), joined by a
  line. Take-off and touch-down are where the feet cross 0.04 skater-heights.

Choices made by measuring the real clips:
- **"full" pose model:** of lite / full / heavy, heavy cost 3× (~37ms vs
  ~11ms per frame locally) for no visible gain, and full was more
  confident on the feet than lite.
- **Full frame, not a crop:** MediaPipe runs its own person detector and
  then tracks frame to frame. Cropping around the skater changed nothing.
- **Visual check:** skeletons drawn on the key frames land on the real
  joints and feet, for both the small tripod skater and the follow-cam one.

| Clip | Stage A pop / land | Stage B take-off / touch-down | Pose / feet / board found |
|---|---|---|---|
| Tripod kickflip | 1.23s / 1.57s | **1.25s / 1.65s**, matching the frames (feet reach the board ~1.62–1.65s) | 92% / 0.92 / 93% |
| Follow-cam bail | 1.10s / 1.30s | **1.08s / 1.33s**, down without the board | 100% / 0.95 / 100% |

Stage B costs ~2.3–2.6s per trick locally (decode + pose ~1.7s, board
~0.9s), ~2.7–3.3s since 6c-2 lengthened the window by up to 0.4s. On Lambda it measured **~9–11s per trick** (see
[Worker](#worker), Measured in prod), within the ~12s estimate. A 30s line
with five tricks would then be ~70s of Stage A + ~50s of Stage B, inside
the 300s timeout.

The same clips in prod (6c-1, after the tcmalloc fix) gave the same
results: the kickflip at 1.27s / 1.65s (take-off one 60fps frame later),
pose 92%, feet 0.95, board 97%; the bail at exactly 1.08s / 1.33s, pose
100%, feet 0.95, board 90%. The small differences are floating-point
differences from a different CPU.

### The landed check, as built (6c-2)

`landed.py` judges each trick over the span **0.1–0.6s after touch-down**
(Stage B's touch-down, or Stage A's landing when Stage B couldn't refine
one). On every frame in that span where the board was sampled, the
skater is *on the board* when:
- the board box is plausible: at most **0.6 skater-heights** long. In the
  bail the detector sometimes boxed the board together with something
  beside it, 0.71 skater-heights wide, and both feet fit inside;
- both feet are over it: each foot's centre (mean x of ankle, heel and toe)
  within the board's x-span, give or take 0.05 skater-heights;
- both feet are on it: each foot's lowest point within 0.15 skater-heights
  of the board's top edge.

Separately, the **stance** (horizontal gap between the feet) can rule a
landing out on its own: wider than 0.45 skater-heights, the feet can't both
be on a board.

| Verdict | When |
|---|---|
| bailed | stance > 0.45, or on the board in ≤ 30% of the judged frames (with the push rule, below: one-foot frames count as on, and the stance test is skipped) |
| landed | on the board in ≥ 70% of the judged frames |
| unclear | fewer than half the sampled frames could be judged, or in between. Reason "no landed trick detected" |
| unclear | less than 0.4s of footage after touch-down. Reason "clip ends too soon after the landing" |

Measured on the real clips before building it, from a per-frame dump of the
landing span:

| Clip | On the board | Stance (median / max) | Implausible board boxes |
|---|---|---|---|
| Tripod kickflip (landed) | **30/30** frames | 0.27 / 0.30 | 0 |
| Follow-cam bail | **2/20** frames | 0.55 / 0.71 | 8 of 30 |

As built (board sampled on every other frame), the check gives:

| Clip | Verdict | On the board (judged / sampled) | Implausible boxes | Stance | Board offset range |
|---|---|---|---|---|---|
| Tripod kickflip | **landed**, confidence 0.92 | 16/16 of 16 | 0 | 0.26 | 0.05 |
| Follow-cam bail | **bailed**, confidence 0.89 | 2/13 of 16 | 3 | 0.54 | 0.27 |

The debug videos confirm it frame by frame: green feet on the kickflip's
deck, red feet either side of the bail's flipped board.

"Board moving along with the skater" was part of the plan. It's logged as
`board offset range` (how far the board's centre drifts relative to the
feet, in skater heights) but not used in the verdict. It does separate
these two clips (0.05 vs 0.27), but two clips can't tell whether it holds
up against camera motion, so it waits for more footage.

**From behind (6d-2):** a foot counts as on the deck anywhere from the
box's top edge (less 0.15 skater heights) to its bottom. Side-on the box
is thin, so that's the original test. Filmed from behind or above, the box
is tall, because the board's length runs away from the camera, and the
nearer foot stands well below its top edge: the pyramid ollie's back foot
was 0.16 skater heights below it, and a ridden-away landing read as a
bail. A true head-on clip is still untested.

**The push rule (6d-2, asked for by the user).** Putting a foot down to
push too soon after landing should cost roll-away, not the landing. In a
push one foot stays on the board, always the same one, so the judged
frames are "both feet on" or "one foot on". A bail mostly has neither: the
follow-cam bail had both on in 4 of 16 judged frames, one in 3, neither in
9, and its first 100ms read "both on", so "both first, then one" alone
isn't enough. So when the one-foot frames are all the same foot and at
most 15% of judged frames have neither foot on (`PUSH_MAX_NEITHER`), the
one-foot frames count as on the board, the pushing foot's wide stance
isn't a bail, and the trick is marked `pushed`, which caps roll-away at
`FOOT_DOWN_CAP` (40). There was no real early-push clip to build it on:
it's tested on synthetic feet, and on the real nose-grind clip, where it
applies (see Known limits).

### The confidence gate, as built (6c-2)

`gate.py` decides per trick, in order: skater missing from > 30% of the
trick (pop to touch-down + 0.6s) → *trick left the frame*; pose found in
< 60% of frames, or feet visibility < 0.5 → *body not clearly visible*;
otherwise the landed check. Landed tricks get scored; bailed and unclear
tricks are left out, not zeroed.

Per clip: no pops → *no clean airtime found*; skater < 0.08 of the frame
height → *skater too far from camera* (even if a trick landed: too few
pixels to score). If nothing landed, the clip fails with the most
actionable reason among its tricks: *trick left the frame*, then *body not
clearly visible*, then *clip ends too soon after the landing*, then *no
landed trick detected* (bails included).

**"Too dark" only explains, never fails.** Stage A records the mean luma of
its samples. A dark clip whose skater still tracks and lands is scored;
when a dark clip (mean luma < 40/255) fails anyway, "too dark" replaces the
reason, because it's the likely cause and the thing to fix.

**Confidence** summarises the same evidence in [0, 1]. Each factor maps its
gate threshold to 0.5 and a "clearly good" level to 1.0: skater size (0.08
→ 0.15 of the frame), frame rate (24 → 50fps), pose found (0.6 → 0.95),
feet visibility (0.5 → 0.9), landing frames judged (0.5 → 0.9). A trick's
confidence is its weakest factor; the clip's is the mean over its landed
tricks. The checks decide pass/fail, the number doesn't.

Every threshold is an uncalibrated guess at the top of `gate.py` and
`landed.py`. Both real clips pass every non-landing check by a wide margin,
so none of them has been tested against a clip near its edge.

**Live since 6c-3.** Until then the worker only logged the outcome the
clip *would* get. Now the gate's outcome is the clip's status, and a trick
whose analysis crashed comes in as *analysis failed for this trick* (see
[Worker](#worker), Errors).

### Decisions for the rest of 6c

- **Landed**: see [The landed check, as built](#the-landed-check-as-built-6c-2).
  "Board near the feet" isn't enough: in the bail the flipped board lies
  *between* the feet at 1.45s.
- **Subscores that can't apply are left out** of the average and shown as
  n/a: catch when the feet never left the board (an ollie), and stomp when
  the board is seen end-on, so its length can't be measured.
- **New failure reason "body not clearly visible"**, for when pose can't
  follow the skater. It's more honest than reusing "no clean airtime found".
- **An analyzer crash isn't retried** and logs the traceback. A code bug
  fails the same way on every retry, so retrying would only park the clip
  in the DLQ, stuck at `analyzing`. Decided for 6c-3: a crash in one
  trick fails only that trick ("analysis failed for this trick") when the
  clip's other tricks could be analyzed; a crash outside the per-trick
  work fails the clip ("analysis failed"). Infrastructure errors (S3,
  database) still raise and get SQS retries. The backstop for crashes that
  kill the process outright (native aborts, timeouts) is the last-receive
  give-up under [Worker](#worker).
- **Milestones:**
  - 6c-1: pose + refined contacts, deployed advisory to prove MediaPipe on
    Lambda;
  - 6c-2: landed check + confidence gate, advisory (built);
  - 6c-3: measurements, `calibration.py`, averaging, migration `0009`
    (`analyses.details`), API, stub off, the stuck-clip sweep (live,
    verified in prod: kickflip analyzed at 79.7, bail "no landed trick
    detected").

### Subscores

Ranked by how reliably they compute from phone footage:

| Subscore | Signal | Robustness |
|---|---|---|
| Pop | Board apex height, normalized by skater pixel-height | High |
| Landing stability | Knee/hip oscillation, torso recovery time post-impact | High |
| Roll-away | Horizontal velocity maintained, no foot down | High |
| Stomp | Feet over bolts at impact vs. tail/nose | Medium |
| Compactness | Limb extension vs. torso during air (flail penalty) | Medium |
| Catch | How early the feet are back on the board before touch-down | Medium |

Normalizing by skater pixel-height is what makes scores camera-distance
invariant.

**Scoring a clip with several tricks** *(decided, built in 6c)*: each
subscore is averaged across the clip's **landed** tricks, and
`steeze_score` is the mean of those averages. Bails are excluded, not
averaged in as zeros, so one bail in a line doesn't sink the clip, but a
weak landed trick does pull it down. Per-trick detail is stored alongside
the breakdown for the UI.

**Calibration comes after the pipeline** *(decided)*. No public dataset
rates execution quality, so turning a raw measurement (pop height ÷ skater
height, airtime in ms, ...) into a 0–100 subscore needs constants tuned
against real, hand-judged clips. Those clips don't exist yet. So:
- 6c ships with reasonable guesses, all in one module (`calibration.py`),
  and stamps its analyses `model_version = "steeze-v0-uncalibrated"`.
- It stores each trick's **raw measurements**, not just the resulting
  scores.
- 6d tunes the constants once the clips exist, bumps the version, and
  recalculates existing analyses from those stored measurements (see
  [Calibration (6d)](#calibration-6d)). That
  needs no video re-run, and works even for clips whose raw upload has
  expired.

**The breakdown is always shown.** A bare number reads as a bug; a visible
breakdown reads as an opinion the user can argue with.

### Subscores, as built (6c-3)

`measure.py` turns each judged trick (landed or bailed) into raw
measurements, from the observations Stage B already made, so it adds no
decoding. Distances are in skater heights, body shapes in torso lengths
from MediaPipe's world landmarks, which don't depend on camera distance.
Then `calibration.py` maps each measurement onto 0–100 with a clamped
linear ramp between two guessed points, and averages where a subscore
reads more than one. Only landed tricks are scored; a bail's measurements
are stored for 6d anyway.

| Subscore | Measurement | Ramp (guessed) | n/a when |
|---|---|---|---|
| Pop | `pop_height`: the lowest foot's peak above its resting level, in the air (Stage A's peak as a fallback) | 0.08 → 20, 0.50 → 100 | never |
| Landing stability | over 0–0.6s after touch-down: `settle_ms` until the hips stay within 0.03 of their riding level; `torso_sway_deg` (std of the signed lean); `arm_flail` (how far the arms swing) | 100ms → 100, 600ms → 20; 2° → 100, 15° → 20; 0.2 → 100, 0.8 → 20 | too little pose |
| Roll-away | over 0.6–1.2s after touch-down: `rollaway_on_board_frac`, and `foot_down` (two judged samples in a row off the board, or a too-wide stance), which caps it at 40 | 0.5 → 20, 1.0 → 100 | under 0.3s of footage, or < 3 judged samples |
| Stomp | over the first 0.2s: each foot's position along the board, and `stomp_error`, the worse foot's distance from its bolt line (0.28 / 0.72 of the board) | 0 → 100, 0.25 board lengths → 20 | board seen end-on (shorter than 0.3 skater heights) |
| Compactness | in the air: `leg_ratio` (hip to ankle) and `arm_ratio` (hips to the farther wrist) | 1.0 → 100, 1.6 → 30; 1.2 → 100, 2.2 → 40 | too little pose in the air |
| Catch | `catch_frac`: how much of the airtime both feet were back on the board before touch-down, skipping partial board boxes | 0 → 30, 0.7 → 100 | the feet never left the board (an ollie), or the "airtime" is over 950ms, so it includes time on an obstacle or ramp (6d-2) |

Choices made by measuring the clips first (a frame-by-frame dump of every
candidate signal):
- **The board box's top edge is the nose while the board is tilted.** At
  the kickflip's pop the back foot sat 0.39 skater heights *below* the
  box top. So the catch doesn't use the gap to the box top. The feet left
  the board when a foot left the box's x-span or the stance widened by
  0.12 over the pre-pop stance (the flick: 0.29 → 0.50). Caught is the
  start of the last run of on-board samples before touch-down.
- **A partial board box is skipped, not read as feet off** (found in
  the first 6c-3 prod check). Prod's kickflip scored catch 30, not 80:
  one sample before touch-down, the detector boxed only part of the board
  (0.23 skater heights against ~0.5), both feet fell outside it, and the
  catch reset to touch-down. Running the analyzer locally on prod's own
  processed file reproduced it exactly, so the cause is the transcode,
  not the analyzer: x264's output depends on the thread count, and Lambda
  has 2 vCPUs. Catch now skips a box shorter than 0.6× the trick's median
  box (a kickflip turns the board about its long axis, so its length
  doesn't really shrink). Prod's file then gives catch 233ms (91).
- **Hip height above the lowest foot**, not hip position in the frame, for
  settling: it cancels camera motion and the skater rolling across.
- **Signed torso lean in the image plane**, not unsigned lean in 3D:
  swaying forward and back cancels out of an unsigned angle, and depth is
  MediaPipe's noisiest axis (the kickflip: 5.7° unsigned, 2.1° signed).
- **Speed for roll-away is not measured.** A follow-cam keeps the skater
  centred, so their speed in the frame means nothing without modelling
  the camera. Roll-away is "rode away on the board, no foot down".

**The sanity anchor** is the tripod kickflip, which its skater calls
sketchy. The trick debug video shows why: a clean catch and roll-away, but
the arms windmill for balance after landing (`arm_flail` 0.62), and the
front foot lands toward the nose (0.84 along the board against the bolt
at 0.72). Without `arm_flail` the guessed ramps gave landing stability 89,
so it was added. As built:

| | Pop | Landing stability | Roll-away | Stomp | Compactness | Catch | **Steeze** |
|---|---|---|---|---|---|---|---|
| Measured | 0.38 | 50ms, 2.1°, 0.62 | 1.0, no foot down | 0.12 | 1.21, 1.93 | 200 of 400ms | |
| Subscore | 77 | 81 | 100 | 61 | 66 | 80 | **77.5** |

The follow-cam bail isn't scored ("no landed trick detected"), and its
measurements show what happened: a foot down, on the board for 45% of the
roll-away, and no catch (the board flipped after landing, not in the air).

**Stored as `analyses.details`** (migration `0009`; shape in
[data-model.md](data-model.md)): per trick, its times, outcome, the
landed check's counts, the measurements and the subscores. The API shows
the per-trick outcome, times and subscores as `analysis.tricks`
([api.md](api.md)). The model version was `steeze-v0-uncalibrated` until
6d-2's verdict fixes made it `steeze-v0.2-uncalibrated`; `steeze-v1` is
the first one fitted to hand-judged scores.

### Calibration (6d)

6d turns the guessed constants into ones fitted to real judgments. It's
split in two, because the judgments need clips that only get filmed now
that the analyzer is live:
- **6d-1 (built):** the tooling below, which needs no new clips.
- **6d-2 (done for the MVP, live, 2026-10-26):** the verdicts checked
  against the user's notes on seven real clips, and fixed; the push rule
  built. Verified in prod on five of them: 50-50 66.4, pyramid ollie
  72.9, nose grind 51.9 (a landed push), kickflip 79.7, bail "no landed
  trick detected"; prod's transcodes put scores within ~2 points of
  local.
  No subscores were judged, so nothing was fitted: the constants stay the
  6c-3 guesses, and `steeze-v1` waits for judged scores (from the user or
  from users' clips later).

**The 6d-2 clips** (the user's notes are in `test_video_details.md` next
to them; `judgments.toml` is kept in step with those notes):

| Clip | Notes | Analyzer, before → after 6d-2 |
|---|---|---|
| Tripod kickflip (60fps) | landed, sketchy | landed 77.5 → same |
| Follow-cam bail (60fps) | bail | bailed → same |
| Ollie gap, follow side-on (30fps) | landed ~3.5s | landed 79.3, plus a phantom trick for the run-up at 0s → run-up skipped |
| Ollie over a pyramid, from behind (30fps) | landed ~2.0s | **bailed** (board seen from behind) → landed 74.3 |
| Boardslide, then a failed half cab (30fps, 10s) | slide landed; half cab fails ~9.5s | landed 73.9 with a catch scored → 68.2, catch n/a; the half cab is still missed |
| 50-50 on a ledge, follow side-on (60fps) | landed ~3.0s | landed 64.2 → same |
| Nose grind on a ledge, follow side-on (60fps) | **fail** ~4.2s | **scored 57.2**: the hop-on at 0s as a landed trick, the grind twice → one trick, landed with a push, 50.8 (the lowest) |

What changed, each found in these clips: pops in a clip's first 0.3s are
skipped and overlapping windows merge ([Stage A](#stage-a-as-built-6b));
feet count as on the deck anywhere within the board box's height, and the
push rule ([the landed check](#the-landed-check-as-built-6c-2)); catch is
n/a over 950ms of "airtime" ([Subscores](#subscores-as-built-6c-3)). The
nose grind is a known limit, below.

**Judging.** The user records each clip in
`backend/tests/fixtures/clips/judgments.toml`, gitignored like the clips:

```toml
[[clip]]
file = "kickflip_sketchy_60fps.mov"
note = "tripod, side-on, portrait"

  [[clip.trick]]            # one per trick, in clip order
  outcome = "landed"        # "landed", "landed-push" or "bailed"
  at = 1.2                  # roughly when the pop is, in seconds (required with several tricks)
  pop = 75                  # each subscore 0-100 for a landed trick,
  landing_stability = 55    # or "n/a" where it doesn't apply;
  roll_away = 85            # bails get no scores
  stomp = 60
  compactness = 65
  catch = 80
```

All six subscores per landed trick, decided with the user: an overall
score alone could only tune the scale, not show which subscore is off. The
clip's score is the average, the same way the analyzer averages, so it
isn't entered separately. `landed-push` is a landing with a foot put down
to push too early, the push rule's test case.

**`make calibrate`** (`calibrate.py`) runs the analyzer once per judged clip
and caches the result (`_debug/<clip>.analysis.json`), keyed by a hash of
the analyzer's code and the clip file, so re-fitting is instant and a
change to `measure.py` re-runs the clips by itself. Judged tricks are
matched to found ones by order, or by `at` within 0.75s. The report:
- **Verdicts:** yours against the analyzer's per trick, how many agree on
  landed vs not, tricks it missed or found extra, and how it handled early
  pushes.
- **Subscores:** on tricks you both call landed, the mean error in points
  now, after fitting, and *left out* (each trick scored by a fit made
  without it). A fitted error far below the left-out one means the fit
  memorised the clips.
- **Measurements:** how well each tracks your score (r), and whether it
  was fitted.
- **Clip scores:** yours against the analyzer's, now and proposed.
- **Proposed constants** to paste into `calibration.py` after review.
  Nothing changes automatically.

**Fitting.** Each measurement is fitted on its own against the subscore it
feeds: least squares on (measurement, your score), turned back into a ramp
that keeps the current end scores (e.g. 20 → 100) and moves where they're
reached. A subscore with several measurements stays their mean, each
fitted against the same score: fewer parameters than a joint fit, which
matters with ~20 tricks. A measurement keeps its current ramp, and the
report says why, with fewer than 5 points, a correlation under 0.3
("weak"), or a clear trend the wrong way ("flips direction", e.g. higher
pop scoring lower, which would mean the measurement is broken).
Foot-down tricks stay out of the roll-away fit: they score
`FOOT_DOWN_CAP` whatever the ramp says, and so do pushes (6d-2).

**Shipping it:** paste the reviewed constants, bump `MODEL_VERSION` to
`steeze-v1`, deploy, then rescore.

**Rescoring** (`app/rescore.py`, `make rescore` locally, the manual
`rescore.yml` job in prod). Without it, every clip analyzed before the
change keeps its old-constant score, so old and new clips would be ranked
against each other on two different scales: in Discover, on profiles and
in team averages. The measurements behind every score are stored in
`analyses.details`, so rescoring recomputes the subscores from them with
no video (the raw uploads expire after 7 days anyway). For each analyzed
or published clip whose latest analysis has measurements and another
model version, it appends a new analysis row (the old one stays as
history) and updates the clip's score. Verdicts don't change, since those
need the video. A dry run lists old → new first, and a second run finds
nothing to do. Every later recalibration (v2, v3, …) reuses it. Run it
after the deploy that ships the constants: before it, the worker would
still score new clips with the old ones.

### The confidence gate

Low confidence returns `unanalyzable` with a **specific** reason, never a
guess: *skater too far from camera*, *trick left the frame*, *too dark*, *no
clean airtime found*, *no landed trick detected*, and (6c) *body not
clearly visible* and *clip ends too soon after the landing*. How each is
decided: [The confidence gate, as built](#the-confidence-gate-as-built-6c-2). The media step adds the file-level reasons that come
before any scoring: *unreadable video file*, *no video stream found*, *clip
too short*.

Bails are handled by scoring only landed tricks. A clip with zero landed
tricks is rejected — rather than rejecting any clip that *contains* a bail,
which would false-positive on scuffed-but-landed tricks with no user recourse.

The analyzer itself can also fail: *analysis failed* for the whole clip,
and *analysis failed for this trick* per trick (see [Worker](#worker),
Errors).

The **stub scorer** (`ANALYZER=stub`: the API image and CI, and every
clip before 6c-3) deliberately fails ~10% of clips with one of these
reasons, decided by the clip id (`random.Random(clip_id.int)`). An
`unanalyzable` result with `model_version: stub-v1` isn't a pipeline
failure.

### Known limits

- Steeze has no ground truth, and different tricks are not really on one
  scale — a tre flip has more ways to go wrong than an ollie. Because tricks
  are user-tagged, a later version can normalize within trick type.
- Board flips complete in ~100ms. At 30fps that is ~3 frames. Clips should be
  shot at **60fps**; source fps is stored and confidence is reduced for 30fps
  footage.
- **The bail's Stage A peak (0.093) is just over `MIN_POP` (0.08).** A
  lower pop would be missed. The threshold can't safely drop without clips
  that show what false alarms look like.
- **Terrain changes aren't modelled.** The rolling ground adopts any level
  held longer than ~0.75s. An ollie up onto a ledge or manual pad registers
  as one pop (reasonable), but on a drop or stair set the pop is found
  while the landing time and peak aren't trustworthy, because the skater
  lands lower than they took off. `MAX_AIRTIME_MS` is only a backstop.
- **A shaky handheld clip** may need real camera-shake cancelling. Neither
  test clip has it.
- **The subscore ramps are still guesses** (6c-3), anchored on one
  landed clip; 6d-2 had seven clips but no judged scores to fit. A true
  head-on clip, a real early push, a foot-down landing and a multi-trick
  line on flat ground are still untested.
- **Trick intent isn't visible.** The analyzer judges whether the skater
  came down on the board and rode; it can't know what trick was meant.
  The nose grind the user calls a fail lost the grind halfway, came down
  on the board, and stepped off a foot at a time. That reads as a
  landing with a push, so it's scored, lowest of the set (50.8, roll-away
  20). Tricks are named after analysis, so the user can still leave it
  unposted.
- **Ramps and banks distort the timing.** On the pyramid the ollie's
  landing reads as ~2.6s (reaching flat ground) instead of ~2.0s, and
  its pop and compactness include the ramp. Rolling down a bank toward the
  camera hides a pop: the failed half cab at ~9.3s isn't found at all. A
  missed *failed* trick changes no score.
- **A trick near the clip's end** shows up as "clip ends too soon after
  the landing" (stepping off at the end, rolling off after a gap). It
  never affects the score.
- **Roll-away doesn't measure speed** (see
  [Subscores, as built](#subscores-as-built-6c-3)), and almost any landed
  trick rides away on the board, so it separates little until a
  foot-down clip exists.
- **The push rule has never seen a real early push** (6d-2): it was built
  on synthetic feet and the nose grind's step-off. A real push clip should
  be the first thing to check it against.

### The flywheel

Every published clip carries a human-supplied trick label from the person who
did the trick. Stored alongside the analysis, these accumulate into exactly
the labeled dataset a future classifier would need. Trick recognition is
deferred, not abandoned.

## Analyzer-specific decisions

### A small in-house IoU tracker, not ByteTrack (6b)

The plan named `supervision`'s ByteTrack. While building 6b it turned out
supervision deprecated ByteTrack in 0.28 and removes it in 0.31. Its
successor, Roboflow's `trackers` package (Apache-2.0), depends on the
non-headless `opencv-python`, which is the same libGL problem
`Dockerfile.worker` already works around for mediapipe, plus `rich`,
`requests` and more. ByteTrack's strengths (recovering low-score
detections, many objects crossing in a crowd) also aren't what this needs.
The job is following one skater at 15fps, usually alone or with a few
bystanders, with the board matched per frame rather than tracked.

`app/analyzer/track.py` is a greedy IoU tracker (~60 lines) that survives
an 8-sample (~0.5s) miss. `supervision` was dropped from
`requirements-worker.txt`. If crowded skatepark footage ever breaks it, the
tracker is one module to swap.

### mediapipe's OpenCV is swapped for the headless build

mediapipe depends on `opencv-contrib-python`, which needs `libGL`, and the
Lambda base image doesn't have it. The Dockerfile uninstalls it,
force-reinstalls `opencv-contrib-python-headless`, and then imports every
CV library as a build step, so a broken swap fails the build, not the first
invocation.

### The model weights are built into the image, and permissions matter

`Dockerfile.worker` downloads Megvii's official `yolox_tiny.onnx`
(0.1.1rc0) and MediaPipe's `pose_landmarker_full.task` with
`ADD --checksum`, so a changed upstream file fails the build instead of
silently changing results. Both are Apache-2.0 (the pose model per the
BlazePose GHUM model card). Lambda runs the function as a **non-root**
user, and the first attempt broke exactly there:
- `ADD` from a URL writes the file `600`, root-owned;
- `--chmod=644` also applies to any directory `ADD` creates, so `models/`
  became untraversable.

Loading the model as a non-root user failed with errno 13, which is exactly
what the worker Lambda would have hit. The directory is now created `755`
first. The weights load on first use per container (`get_detector()` is
cached), not at import, which keeps cold-start init cheap.

### MediaPipe needs libEGL, and the build proves the models load (6c)

MediaPipe's native Tasks library links against `libEGL`/`libGLESv2`
even when it only runs on the CPU, and the Lambda base image has neither.
6a's build check only *imported* mediapipe, which loads that library
lazily, so the first real pose call would have failed in prod with
`OSError: libEGL.so.1`. Found during 6c planning, before anything shipped.

`Dockerfile.worker` now:
- installs `mesa-libEGL` + `libglvnd-gles` (with the image's `microdnf`,
  which has no `-q` flag);
- runs `backend/scripts/check_models.py` **as uid 65534**, which opens the
  YOLOX session *and creates a pose landmarker*.

That check exercises every native library and file the worker Lambda
touches, as the kind of user Lambda runs as, so this class of bug now fails
the build. It can't catch problems that only exist in Lambda's sandbox,
though. The next section is one.

### MediaPipe 1.0's tcmalloc aborts on Lambda (6c)

The first 6c-1 prod run died right after Stage A, the first time MediaPipe
ran in Lambda:

```
third_party/tcmalloc/internal/sysinfo.h:76] CHECK in NumCPUs: maybe_cpus.has_value() (false)
REPORT ... Status: error  Error Type: Runtime.ExitError
```

MediaPipe **1.0.0 onward** statically bundles Google's tcmalloc in
`libmediapipe.so`. tcmalloc reads the CPU count from
`/sys/devices/system/cpu`, which Lambda's sandbox doesn't expose, and
treats a failed read as fatal. Docker always exposes `/sys`, so the
build-time landmarker check and every local run passed. 0.10.x has no
tcmalloc. Confirmed by searching each wheel's `libmediapipe.so`:
`maybe_cpus` first appears in 1.0.0 and is absent from 0.10.33/0.10.35.

Fix: `mediapipe==0.10.35`, which has the same `mediapipe.tasks.python` API,
the same dependencies, and the same libEGL/libGLESv2 needs.
`check_models.py` now also fails the build if `libmediapipe.so` contains
`maybe_cpus`, so a future bump can't bring it back silently. The same run
also logged matplotlib (imported by mediapipe) failing to create a config
dir in Lambda's read-only home. The image now sets
`MPLCONFIGDIR=/tmp/matplotlib`.

## Seeing what it saw

`make analyze-clip FILE=tests/fixtures/clips/<clip>` runs exactly the
worker's path on a local file (`pipeline.analyze`). It prints the windows,
Stage B per trick, each trick's landing verdict, measurements and
subscores, the clip's breakdown, steeze score and timings, and writes
debug videos under `tests/fixtures/clips/_debug/`:

- `<clip>.debug.mp4` (Stage A): skater and board boxes, the elevation
  curves (feet, board, both) against the pop threshold, and the trick
  windows;
- `<clip>.trick<N>.debug.mp4` (Stage B): the window at full rate, played at
  1/3 speed, with the pose skeleton, feet, board and take-off/touch-down
  marked. In the landed check's span the feet turn green (on the board) or
  red (off it), and the bottom lines show the trick's verdict, the clip's
  outcome and the trick's subscores.

Those videos are the real check on the analyzer until calibration (6d).
The README's sneak-peek GIFs are made from them.

**Tests:** synthetic signal tests for Stage A and Stage B, synthetic
feet/board observations for the landed check and every gate reason,
synthetic bodies and boards for every measurement and for the pipeline's
per-trick crash handling (no models, run in CI), detector/tracker tests
with a hand-built model output, `calibration.py` tests in the API image,
and tests on the real clips in the gitignored
`backend/tests/fixtures/clips/` (local only). See the [development guide](../development.md#tests).

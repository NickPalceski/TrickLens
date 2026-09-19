# TrickLens — Architecture

Conceptual overview of the system: what each component is, what it does, and
how it connects to the others. Kept current as the build progresses.

**Current state: step 4 done — social app. 4a (follows + home feed), 4b
(likes + comments), 4c (teams), and 4d (Discover) all built and verified.**
Sections marked *(planned)* are designed but not yet built.

---

## 1. What the system does

1. A skater uploads a clip (≤30s).
2. The clip is analyzed asynchronously for **execution quality** — not trick
   identity.
3. The skater **tags the trick themselves**, reviews the score, and publishes.
4. Published clips appear in followers' feeds and compete on Discover.
5. Teams aggregate their members' scores.

---

## 2. Component map

```
                    ┌──────────────────┐
                    │  Next.js (Vercel)│
                    └────────┬─────────┘
                             │ HTTPS
                             ▼
   ┌─────────────────────────────────────────────┐
   │  API — FastAPI on Lambda (container image)   │
   └──┬──────────────┬──────────────┬─────────────┘
      │              │              │
      │ presign      │ enqueue      │ SQL
      ▼              ▼              ▼
   ┌──────┐      ┌───────┐    ┌──────────┐
   │  S3  │      │  SQS  │    │ Postgres │
   └──┬───┘      └───┬───┘    └────▲─────┘
      │              │ triggers    │
      │              ▼             │
      │      ┌───────────────┐     │
      └─────►│  ML Worker    ├─────┘
    read/    │  (Lambda,     │  writes analysis
    write    │   fat image)  │
             └───────────────┘
      │
      ▼
 ┌────────────┐
 │ CloudFront │──► video delivery
 └────────────┘

 EventBridge ──(every 15 min)──► Rankings Lambda ──► Postgres
```

### What each piece is for

| Component | Role | Why it is here |
|---|---|---|
| **Next.js** | UI | Deploys free on Vercel; shadcn/ui gives a good-looking baseline without deep frontend work |
| **API Lambda** | HTTP, auth, CRUD, presigning | Scales to zero — no idle cost |
| **Worker Lambda** | Video analysis | Separate image (~2GB vs ~200MB) and separate scaling from the API — *from step 6*; the step 3 stub shares the API's image (see §10) |
| **Postgres** | All relational state | The domain is deeply relational: follows, teams, likes, comments |
| **S3** | Video and image bytes | Never in the database — the DB stores keys only |
| **CloudFront** | Media delivery | Speed, *and* the 1TB/mo always-free egress tier. Without it, bandwidth would be the largest bill |
| **SQS** | Upload → analysis buffer | Structural: analysis takes 30–90s, API Gateway caps at 29s |
| **Cognito** | Identity | Never store passwords; email verification and reset come free |
| **EventBridge** | Scheduler | Rebuilds Discover rankings and snapshots team scores |
| **Terraform** | Infrastructure as code | Reproducible, reviewable, and the emergency "stop all billing" button |

---

## 3. The upload → publish flow

```
1. POST /clips                → row created (status=draft), presigned S3 URL returned
2. PUT <presigned url>        → browser uploads DIRECTLY to S3 under raw/
3. POST /clips/{id}/complete  → API verifies the object exists, status=queued,
                                message onto SQS
4. SQS triggers worker        → status=analyzing
                                (stub, step 3) fabricates a scored breakdown
                                (real, step 6) ffmpeg normalize → localize
                                tricks → score → writes processed/ + thumbs/
                                status=analyzed (or unanalyzable + reason)
5. GET /clips/{id}            → client polls until terminal status
6. POST /clips/{id}/tricks    → user tags trick(s), reviews score
7. POST /clips/{id}/publish   → requires ≥1 tagged trick, status=published
                                (does not yet "enter feeds" — that's step 4)
```

**Why the browser uploads directly to S3:** routing a 30s video through the
API would exceed Lambda's payload limit and burn compute for a pure byte
relay. The API issues a short-lived signed URL and steps out of the way.

**Why a clip stays a draft until published:** a failed analysis must never
reach a feed, and the user gets to correct the trick tag first.

**Two step-3 scoping calls, both revisited later:**

- **`duration_ms`/`source_fps` are client-reported, not server-verified.**
  The step-3 worker has no ffmpeg/ffprobe — that's step 6's fat image — so
  the browser reads them off its `<video>` element and sends them in
  `POST /clips`. Not a trust boundary that matters yet; step 6 can
  cross-check them once the worker actually decodes the video.
- **No `processed/` video exists yet.** `GET /clips/{id}` presigns the *raw*
  key regardless of status — there's no transcode step until step 6, so
  `thumb_key` just stays null.

---

## 4. The steeze score *(planned, step 6)*

### What it is not

The system does **not** identify tricks. Trick classification from video is a
research-grade problem — there is no large public labeled dataset, and the
published work is mostly IMU/accelerometer-based, which does not transfer to
phone footage. It was cut deliberately.

### What it is

An **explainable heuristic** over pretrained models. No training data, no
GPUs, fully deterministic.

**Pipeline:**

1. **ffmpeg** — normalize to 720p, cap at 30s.
2. **YOLOv8-nano** — detect and track skater + board. COCO already includes
   both `person` and `skateboard` classes, so this needs no training.
3. **Localize (stage A, cheap)** — at ~10fps, find pops from the board's
   vertical trajectory and foot–board separation.
4. **Score (stage B, expensive)** — only on the ~1.2s window around each pop,
   at native fps, using MediaPipe pose.

> Two-stage localization is what makes 30s clips affordable: full-cost
> processing runs on roughly 5% of frames, and multi-trick lines come free.

**Subscores**, ranked by how reliably they compute from phone footage:

| Subscore | Signal | Robustness |
|---|---|---|
| Pop | Board apex height, normalized by skater pixel-height | High |
| Landing stability | Knee/hip oscillation, torso recovery time post-impact | High |
| Roll-away | Horizontal velocity maintained, no foot down | High |
| Stomp | Feet over bolts at impact vs. tail/nose | Medium |
| Compactness | Limb extension vs. torso during air (flail penalty) | Medium |
| Catch | Airtime between feet-off and feet-back-on | Medium |

Normalizing by skater pixel-height is what makes scores camera-distance
invariant.

**The breakdown is always shown.** A bare number reads as a bug; a visible
breakdown reads as an opinion the user can argue with.

### The confidence gate

Low confidence returns `unanalyzable` with a **specific** reason, never a
guess: *skater too far from camera*, *trick left the frame*, *too dark*, *no
clean airtime found*, *no landed trick detected*.

Bails are handled by scoring only landed tricks. A clip with zero landed
tricks is rejected — rather than rejecting any clip that *contains* a bail,
which would false-positive on scuffed-but-landed tricks with no user recourse.

### Known limits

- Steeze has no ground truth, and different tricks are not really on one
  scale — a tre flip has more ways to go wrong than an ollie. Because tricks
  are user-tagged, a later version can normalize within trick type.
- Board flips complete in ~100ms. At 30fps that is ~3 frames. Clips should be
  shot at **60fps**; source fps is stored and confidence is reduced for 30fps
  footage.

### The flywheel

Every published clip carries a human-supplied trick label from the person who
did the trick. Stored alongside the analysis, these accumulate into exactly
the labeled dataset a future classifier would need. Trick recognition is
deferred, not abandoned.

---

## 5. Auth flow

```
1. Client → Cognito directly: SignUp, ConfirmSignUp (email verification),
   InitiateAuth (USER_PASSWORD_AUTH)     → IdToken, AccessToken, RefreshToken
2. POST /users  Authorization: Bearer <IdToken>  {username}
                                        → verifies token, no row yet for this
                                          sub → creates it → 201 UserMe
3. Every later request: Authorization: Bearer <IdToken>
                                        → verifies token, row exists → 200
```

**Why the client talks to Cognito directly, not through this API.** The app
client is public — no secret, since a browser can't hide one — so there is
nothing for the API to mediate. Proxying signup/login would be an extra hop
with no security benefit, and would need the API to hold broader Cognito IAM
permissions than the credential-free verification it does today (JWKS
endpoints are public; checking a token needs no AWS access at all).

**Why a separate `POST /users` step, instead of a Cognito trigger
auto-creating the row.** Cognito has no idea what the app's `username` is —
that's chosen by the user and unique in this database, not in the pool. A
post-confirmation Lambda trigger could create a placeholder row, but
registration would still need a second call to set the username, plus
handling for the placeholder already existing. One JIT endpoint after first
login is simpler than both put together.

**Why the id token, not the access token, is the bearer credential.** The id
token carries `email`; the access token does not. Using it means JIT
registration and `GET /users/me` get `email` for free, at the cost of
departing from the more common pattern of access-token-for-API,
id-token-for-client.

---

## 6. Data model

**Built (steps 1–4d):**

```
users     id, cognito_sub (not null, unique), username, display_name, bio,
          avatar_key, timestamps
profiles  user_id → users, stance, style, board, board_size, wheels,
          wheel_size, trucks, bearings
clips     id, user_id, status, s3_key, thumb_key?, duration_ms?, source_fps?,
          steeze_score?, published_at?, team_id?, score_included, timestamps
          (team_id, score_included: 4c — see below)
analyses  id, clip_id, model_version, confidence,
          steeze_breakdown jsonb?, failure_reason?, created_at
tricks    id, canonical_name (unique), aliases[]
clip_tricks  clip_id, trick_id, position   (pk: clip_id+position; source: user_tagged)
follows   id, follower_id → users,
          followee_user_id → users?, followee_team_id → teams?,   (4a; FK completed in 4c)
          CHECK exactly one followee set
likes     user_id → users, clip_id → clips   (pk: user_id+clip_id; 4b)
comments  id, clip_id → clips, user_id → users, body,
          parent_id → comments?, created_at   (4b; one level of replies — see below)
teams              id, name, slug (unique), description, level, join_policy,
                   owner_id → users, founded_at?, timestamps   (4c — see below)
team_members       team_id, user_id, role, joined_at   (pk: team_id+user_id; 4c)
team_join_requests team_id, user_id, kind, created_at  (pk: team_id+user_id; 4c)
clip_views         id, clip_id, user_id?, viewed_at   (4d — see below)
clip_rankings      clip_id, steeze_score?, score_included, like_count,
                   comment_count, view_count, engagement_score, captured_at
                   (pk: clip_id; 4d — materialized, rebuilt by app/rankings.py)
team_score_history id, team_id, score?, captured_at   (4d — append-only)
```

### Design notes

- **UUID primary keys** — IDs appear in public URLs; sequential integers leak
  counts and allow enumeration.
- **`profiles` is a separate table** — every field is optional and rarely
  read, and `users` is joined on nearly every query.
- **`avatar_key`, not `avatar_url`** — storing URLs breaks every row the day
  a CDN is introduced.
- **`email` is never stored in `users`** — Cognito is the system of record
  for identity attributes. The API reads it off the verified id token per
  request instead of duplicating it and risking drift.
- **`cognito_sub` is non-nullable as of step 2.** Step 1 left it nullable on
  purpose, before auth existed to populate it; every row now comes through
  JIT registration with a sub already in hand.
- **`clips.team_id` (4c)** is nullable and `ON DELETE SET NULL`, unlike
  `user_id`'s `CASCADE` — a team disbanding should detach the credit from a
  clip, not delete the clip. It's set via `PATCH /clips/{id}/team`, which
  only accepts a team the caller is currently a member of, and only while
  `status == ANALYZED` — a one-time, pre-publish decision, locked after
  that (a team tag is credit for a specific roster at a point in time, not
  something that makes sense to reassign later).
- **`tricks.canonical_name` is a plain unique column, not a functional
  `lower()` index like `users.username`.** The API pre-normalizes it before
  insert, and — unlike a username — there's no display casing worth
  preserving for a trick name.
- **`clip_tricks`' primary key is `(clip_id, position)`, not `(clip_id,
  trick_id)`.** Position is what actually needs to be unique per clip (one
  trick per slot in a line); a trick could in principle repeat.
- **`follows` targets a user *or* a team, as two nullable FKs + a check
  constraint** — not the untyped `(followee_type, followee_id)` pair earlier
  drafts of this doc sketched. The home feed pulls clips from followed users
  *and* teams, so the target genuinely is polymorphic; two real FK columns
  keep Postgres enforcing referential integrity and cascade-deletes on both
  sides, which a bare `followee_id` couldn't. The column and check landed in
  4a's migration before `teams` existed; 4c's migration adds the deferred FK
  constraint now that it does.
- **`likes` has no surrogate id** — `(user_id, clip_id)` is the primary key
  directly, same reasoning as `clip_tricks`: a like has no identity beyond
  "this user liked this clip", so a separate UUID plus a unique constraint
  would just be a redundant second index.
- **`comments.parent_id` threads exactly one level deep** — a reply's
  `parent_id` must reference a top-level comment, never another reply. That
  rule is a cross-row condition (the referenced row's own `parent_id` must
  be null), which a plain `CHECK` constraint can't express without a
  trigger; this codebase has no procedural DB logic anywhere else (the
  closest precedent is `app/models/enums.py` pushing enum-value mapping into
  Python rather than the database), so it's enforced in `routes/clips.py`
  instead. `parent_id`'s `ondelete="CASCADE"` means deleting a top-level
  comment deletes its replies too.
- **A team isn't "real" until `founded_at` is set** — null from creation
  until every founding invite is accepted, same idiom as `Clip.published_at`
  marking a not-yet-live row rather than a separate status enum. `POST
  /teams` requires at least 2 founding invitees (a floor, not a cap) in
  addition to the owner; while `founded_at IS NULL` the team is invisible to
  everyone but the owner and those invitees (same 404-not-403 rule as clip
  drafts), and can't be joined, followed, or tagged onto a clip. Accepting
  the last outstanding founding invite stamps `founded_at`; rejecting *any*
  founding invite — or the owner cancelling, which is the same
  `DELETE /teams/{slug}` call whether the team is pending or live — deletes
  the whole `Team` row via `ON DELETE CASCADE`, undoing the attempt entirely
  rather than leaving a partially-formed team behind. The name/slug are free
  again immediately, so it can be redone from scratch.
- **`team_join_requests` serves two directions through one table**, not two
  near-identical ones: `kind = request` is a user asking to join (an
  owner/admin resolves it), `kind = invite` is an owner/admin asking a user
  to join — including the founding invites above — which only that user can
  accept or reject. There's no `status` column: a row's existence means
  pending, and resolution either deletes it (reject) or deletes it while
  inserting a `team_members` row (accept) — the same hard-delete idiom
  `follows`/`likes` already use, no history kept.
- **`team_members.role` is `owner`/`admin`/`member`.** Exactly one row per
  team holds `owner`, mirroring `teams.owner_id`. An admin can approve/reject
  join requests and remove a plain member, but not another admin or the
  owner; only the owner changes roles, sends founding-adjacent settings
  changes, or deletes the team. There's no ownership-transfer flow yet — an
  owner can't leave, only delete the team outright.
- **A hard cap of 20 `team_members` rows per team**, enforced in the route
  layer at every membership-creating call (open join, invite-accept,
  request-accept) — not expressible as a `CHECK` constraint, since it's a
  count over a related table, not a property of one row.
- **`clips.score_included` (4c)**, unlike `team_id`, stays editable forever
  — including indefinitely after publishing, as an edit to the post, via
  `PATCH /clips/{id}/score-inclusion`. It never touches `analyses`; the
  existing scoring pass is reused as-is either way. This exists because
  skate clips are often shot from angles the analyzer scores unreliably, and
  the app doesn't want users choosing between a visually great clip and
  their average — a clip can publish and be watched regardless of this
  flag, it just won't count toward a personal or team average.
- **`team_score_history` exists because Discover ranks teams by score
  *increase*.** A delta is uncomputable without history, and this is painful
  to retrofit.
- **Team score = average of the team's top 10 clips.** Summing everything
  would mean the largest team always wins and scores could never fall. A
  user's own `average_score` (4d) has no analogous fairness problem, so it's
  an uncapped average across every published, score-included clip. Both live
  in `app/scoring.py`, shared by `api/serializers.py` (live display on
  `UserPublic`/`TeamOut`) and `app/rankings.py` (the `team_score_history`
  snapshot) — one definition, so the two can't quietly drift apart.
- **`clip_views` (4d) is a plain append-only event log, not deduped like
  `Like`.** A rewatch counts again — `view_count` is a raw play-count, same
  as most platforms show, not a unique-viewer count. The clip owner's own
  views are never inserted at all: unlike a like, capped at +1/user by
  construction, a raw view endpoint has no such limit, so self-view spam
  would otherwise be a trivial way to inflate the Discover engagement
  ranking below.
- **`clip_rankings` (4d) is fully truncated and reinserted on every
  `app/rankings.py` run**, one row per clip published in the last 7 days —
  the same "no surrogate id" reasoning as `likes`, since the table's only
  meaning is "this week's snapshot." It carries its own copies of
  `steeze_score`/`score_included` and the three engagement counts rather
  than joining back to `clips`, so a rebuild is one clean pass with nothing
  to reconcile. Reading it back (`routes/discover.py`) re-fetches the live
  `Clip` rows it names, in the order it says — display data is always
  current even though the *ordering* is only as fresh as the last rebuild.
- **Discover's engagement ranking blends three signals with different
  weights** — `view_count×1 + like_count×5 + comment_count×10`
  (`app/rankings.py`'s `ENGAGEMENT_WEIGHTS`) — rather than exposing three
  separate sort orders. Comments weighted highest and views lowest: a view
  costs a viewer nothing, a like takes one tap, a comment takes real effort.
  The numbers are a starting heuristic, not derived from data; they're
  centralized as named constants specifically so they're a one-line change,
  not a redesign, once real usage suggests better ones. This ranking has no
  relation to the `score` ranking's `score_included` filter — engagement is
  a deliberately separate signal from the steeze score, for skaters who'd
  rather browse what looks good than what scored well.

---

## 7. Feed and ranking strategy

**Home feed — fan-out-on-read.** `GET /feed` queries `clips` directly,
filters to `published`, orders by `(published_at, id)` descending,
keyset-paginated: the response carries a `next_cursor` (`"<published_at>|<id>"`)
that the client passes back as `?cursor=`, becoming `WHERE (published_at, id)
< (?, ?)`. Keyset rather than `OFFSET` because offset pagination degrades
linearly and skips rows when new clips arrive mid-scroll. One extra row is
fetched per page (`LIMIT n+1`) purely to know whether `next_cursor` should be
set. A clip embeds its `author` (a `UserBrief`) so the feed needs no
follow-up lookup per row.

**Team follows (4c)** are folded in as `Clip.user_id.in_(followed users)
OR Clip.team_id.in_(followed teams)` — two `IN` subqueries against `follows`,
not a `JOIN` on that OR condition. A join would emit a clip twice when both
its author *and* its tagged team are followed; de-duping a joined result
afterward is more awkward than just not producing the duplicate in the first
place.

Fan-out-on-*write* (precomputed per-user timelines) is the standard answer at
large scale, but it costs a write per follower per post and needs backfill
logic. At this scale it is unjustified complexity.

**Discover — precomputed (4d).** `app/rankings.py`'s `run()` rebuilds
`clip_rankings` (this week's clips, ranked) and appends one `team_score_history`
row per founded team, in a single pass. Discover is a hot page and ranking
live — sorting the whole `clips` table on every load — would be an expensive
query; reading a small pre-sorted snapshot instead is cheap regardless of how
many clips exist.

`GET /discover/clips?sort=score|engagement` reads `clip_rankings` directly,
plain offset-paginated rather than keyset: unlike the home feed, this reads a
snapshot that's frozen between rebuilds, so keyset's usual justification
(rows shifting under a paginating client) doesn't apply, and jumping to an
arbitrary page of a ranked list is a reasonable thing to want.
`GET /discover/teams` is the one live-computed exception — ranked by score
*increase* (latest `team_score_history` snapshot minus the one closest to 7
days earlier, per team), computed at request time because the number of
teams is small enough that this is cheap, unlike sorting every clip. A team
with no snapshot from that far back (brand new) is excluded rather than
credited a fake increase-from-zero, which would otherwise let any
freshly-founded team trivially top the list.

**Same dev/prod trigger split as `app/worker.py`**: locally, `make rankings`
runs the rebuild on demand (`app/rankings.py`'s `lambda_handler` entrypoint
is unused until then); in production (step 5) an EventBridge rule invokes it
on a schedule instead. Nothing runs this automatically in dev — there's no
scheduler in docker-compose to do it.

---

## 8. Engagement counts

Likes and comments (step 4b) add three fields to `ClipOut`: `like_count`,
`comment_count`, `liked_by_me`. `view_count` (4d, backed by `clip_views` and
`POST /clips/{id}/view`) joined them as a fourth. All four are computed in
`api/serializers.py`'s `clip_out()`, which takes `db` and an optional
`viewer`, plus optional precomputed values for each.

**Single-clip routes** (everything in `routes/clips.py`) let `clip_out`
query directly — one `COUNT` per metric, one lookup for `liked_by_me` — the
same per-call cost `user_public()` already pays for
`follower_count`/`following_count`/`followed_by_me`.

**The feed and Discover are different**: both call `clip_out` in a loop over
up to 50 clips per page, so paying a query per clip per metric there would
mean hundreds of queries per page load. `clip_engagement()` batches all four
into one grouped query per metric for the whole page — `GROUP BY clip_id`
for the three counts, one `IN (...)` lookup for the viewer's likes — and
`feed.py`/`routes/discover.py` pass the results into `clip_out` as
precomputed values, skipping its default per-clip queries entirely.

Comment listing (`GET /clips/{id}/comments`) doesn't need the same
treatment: it returns *comments*, not clips, and a comment's replies load via
`.options(selectinload(Comment.replies))` on the query — SQLAlchemy's own
batched-eager-load strategy, so a page of top-level comments plus every reply
on it is two queries total, not N+1, with no hand-written batching needed.
Note this has to be requested explicitly in the query, unlike
`Clip.analyses`/`Clip.clip_tricks`: SQLAlchemy never auto-applies a
relationship's default `lazy=` strategy when it's self-referential, the way
`Comment.replies` is — see the gotcha in `CLAUDE.md` and the comment on
`Comment.replies` in `app/models/social.py`.

---

## 9. Environments

The seam between local and cloud is **`AWS_ENDPOINT_URL`** — for S3, SQS, and
Postgres. Cognito is the one exception: it's always the real service, dev
included (see §5 and the decision below), so dev and prod differ only in
*which pool* `COGNITO_USER_POOL_ID`/`COGNITO_CLIENT_ID` point at.

| | Local | Production |
|---|---|---|
| Database | Postgres container | Neon |
| S3 / SQS | LocalStack | Real AWS |
| Cognito | Real AWS, `tricklens-dev` pool | Real AWS, prod pool (Terraform, step 5) |
| `AWS_ENDPOINT_URL` | `http://localstack:4566` | *(empty)* |
| API process | uvicorn `--reload` | Lambda runtime |
| Image | `backend/Dockerfile` | **the same image** |

No application code branches on environment. `app/services/storage.py`,
`app/services/queue.py`, and `app/services/auth.py` are the only modules
aware AWS exists; everything else goes through them.

One wrinkle in `storage.py`: presigned URLs are *signed* against
`AWS_ENDPOINT_URL` (LocalStack's Docker-network hostname, needed for the
signature to be valid) but are handed to callers *outside* that network —
curl, Postman, a browser. `AWS_PUBLIC_ENDPOINT_URL` (`http://localhost:4566`
in dev, empty in prod) is a second, narrower env var used only to rewrite
the host on the way out. Production doesn't need it: the real S3 endpoint is
already externally reachable, so there's nothing to rewrite.

The worker (`app/worker.py`) has its own small seam, orthogonal to the
above: locally it long-polls SQS in a loop; in production (from step 5) an
SQS event-source-mapping invokes `app.worker.lambda_handler` once per
message instead. Same processing function either way — only the trigger
differs.

---

## 10. Decisions

### Neon instead of RDS

Lambda reaches RDS privately by joining a VPC — but a Lambda in a VPC loses
default internet access, so it can no longer reach S3, SQS, or Cognito.
Restoring that needs either VPC endpoints or a **NAT gateway at ~$32/month**,
billed 24/7 and in no free tier. That single line item would exceed the cost
of everything else combined.

Neon is reachable over public TLS, so Lambda stays out of the VPC entirely —
no NAT, no endpoints, no VPC cold-start penalty. It also scales to zero and
supports per-branch databases for CI.

Since the stack is SQLAlchemy + Alembic, Postgres is Postgres; moving to RDS
later is a connection-string change.

### Lambda instead of ECS Fargate or EC2

- **EC2 + docker-compose** — simplest, but a `t3.micro` cannot handle video
  inference, and it costs money while idle.
- **Fargate** — the most production-shaped answer and the natural upgrade
  path, but ~$15–30/month with zero traffic.
- **Lambda containers** — genuinely free at this scale, scales to zero, and
  supports 10GB images (the ML worker needs ~2GB, far past the 250MB zip
  limit). Cold starts (~1–2s API, ~15s worker) are acceptable because
  analysis is already asynchronous.

Fargate is the documented migration path if sustained traffic ever makes cold
starts or per-invocation billing the wrong trade.

### Cognito is real everywhere, not LocalStack

LocalStack only emulates Cognito on a paid plan — `cognito-idp` isn't in the
free tier's service list at all. Even on Pro, its JWKS endpoint has a known
bug (every key reports the same hardcoded `kid`), and issuer/signature
validation coverage has had documented gaps — exactly the surface this app's
token verification depends on being correct. Meanwhile Cognito's own free
tier (50k MAU, no 12-month expiry unlike S3's) removes any cost motive to
emulate it: there is nothing to save by faking a free service.

So dev and prod both use real Cognito — two different pools, created
directly (`scripts/cognito-bootstrap.sh` for dev, Terraform for prod in step
5) rather than through the `AWS_ENDPOINT_URL` seam every other AWS service
uses.

**Trade-off:** local dev now needs a real AWS account and network access for
auth specifically, breaking the "fresh clone, zero AWS account" property
LocalStack gives every other service. Accepted, since Cognito is the one
service here where faithful local emulation isn't actually available for
free.

### The worker shares the API's image until step 6, not a separate one

The component map above describes the worker as a separate ~2GB image from
the API — that's the step-6 target state, once real CV dependencies
(ffmpeg, YOLO, MediaPipe) actually make it fat. A stub needs none of that,
so splitting the image now would be premature: `app/worker.py` reuses
`app.db`, `app.models`, and `app.services.queue`/`storage` exactly like
every API route does, and ships in the same Docker image, with a third
entrypoint alongside the API's two (uvicorn locally, `app.lambda_handler`
in Lambda) — see the Environments section above. The image only needs to
actually split when step 6 adds the dependencies that make it necessary.

### Trick classification deferred

Covered in §4. Users tag their own tricks; the analyzer scores execution
only. This removes the project's only research-grade risk while still
accumulating the dataset that would make classification possible later.

### One image for dev and production

`backend/Dockerfile` builds on `public.ecr.aws/lambda/python:3.12`. Locally,
Compose overrides the entrypoint to run uvicorn with hot-reload; in
production the Lambda runtime invokes `app.lambda_handler.handler`. Identical
layers and digest in both places, so environment drift cannot be a source of
bugs.

---

## 11. Cost

| Service | Free allowance | Expected |
|---|---|---|
| Lambda | 1M requests + 400k GB-s/mo, always free | $0 |
| SQS | 1M requests/mo, always free | $0 |
| CloudFront | 1TB egress/mo, always free | $0 |
| Cognito | 50k MAU, always free — dev and prod pools both count against this | $0 |
| EventBridge | Free | $0 |
| S3 | 5GB free 12mo, then ~$0.023/GB | ~$0.20 |
| ECR | 500MB free 12mo | ~$0.40 |
| Neon | Free tier | $0 |
| **Total** | | **~$0.60/mo** |

Controls: S3 lifecycle rule expiring `raw/` drafts after 7 days, ECR lifecycle
policy keeping the last 5 images, and an AWS Budget alarm at $5.

---

## 12. Build order

| Step | Scope | Status |
|---|---|---|
| 1 | Local dev foundation — Compose, Postgres, LocalStack, FastAPI, Alembic | **done** |
| 2 | Auth (Cognito) + users + profiles | **done** |
| 3 | Upload → S3 → SQS → worker with a **stubbed** analyzer | **done** |
| 4 | Social app — feed, likes, comments, teams, discover | **done** |
| 5 | Terraform + GitHub Actions → deploy to AWS | |
| 6 | Replace the stub with the real steeze analyzer | |

Step 3 deliberately stubs the analyzer so that a complete, deployed, working
product exists before the hardest component is attempted.

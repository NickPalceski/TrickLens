# TrickLens — Project Instructions

## What this is

A skate-clip social app. Users upload clips; a Python ML worker scores the
*execution quality* ("steeze") of the tricks in the clip. Trick **names are
supplied by the user**, not predicted — see Decisions below.

## Standing rules

### Documentation (always)

After **any** change to code, database schema, or infrastructure, update both:

- `README.md` — setup, how to run, current state of the build
- `docs/ARCHITECTURE.md` — component overview, data flow, and the *why*
  behind decisions

Treat these as part of the change, not as follow-up work. A change that
alters behaviour but leaves the docs stale is incomplete.

### Conventions

- **Config**: everything comes from `app.config.get_settings()`. Never read
  `os.environ` directly outside that module.
- **AWS access**: only through `app/services/storage.py`,
  `app/services/queue.py`, `app/services/auth.py`, and (step 5)
  `app/services/secrets.py`. The first two are the dev↔prod seam (LocalStack
  vs real AWS is an env var, nothing more); `auth.py` is the exception —
  Cognito is always the real service, dev included, because LocalStack only
  emulates it on a paid plan and even then has known JWKS bugs.
  `secrets.py` is a narrower exception: it resolves `DATABASE_URL` out of
  SSM Parameter Store in production, and has to read `os.environ` directly
  (not via `get_settings()`) because it runs *before* `Settings()` can be
  constructed — see its docstring and `app/config.py`'s. See
  ARCHITECTURE.md §10.
- **Prod migrations must be backward-compatible within a single deploy**
  (step 5, `.github/workflows/deploy.yml`): `alembic upgrade head` runs
  before the new Lambda image goes live, so the still-live *old* code briefly
  runs against the *new* schema — never the other way around. New columns
  must be nullable-first (or have a server default); never drop or rename a
  column the still-deploying old code reads. See ARCHITECTURE.md §12.
- **Serialization**: never return ORM objects from a route. Always go
  through a Pydantic schema in `app/schemas/`.
- **Media**: store S3 *keys* in the database, never full URLs. URLs are
  built at response time from `CDN_BASE_URL`.
- **IDs**: UUID primary keys on anything user-facing (IDs appear in public
  URLs; sequential integers leak counts and allow enumeration).
- **Migrations**: schema changes always ship with an Alembic migration.

## Environment

Developed from three machines: a Windows/WSL2 box, a native-Linux (Omarchy)
dual-boot, and a MacBook. They're independent clones, not a synced setup —
each needs its own `git clone` and its own `.env` (gitignored, regenerate
with `make init`). The two things worth carrying over rather than redoing:
the Cognito dev pool (copy `COGNITO_USER_POOL_ID`/`COGNITO_CLIENT_ID` into the
new `.env`, or re-run `cognito-bootstrap.sh` — it finds the existing pool by
name instead of duplicating it) and, optionally, the same AWS CLI access
key. Postgres/LocalStack state is throwaway container state either way;
`make up` rebuilds it from nothing on all three.

### Windows/WSL2

- **Repo lives inside WSL2**: `~/git-repos/TrickLens` on the Ubuntu distro.
  Never work from `/mnt/c` — bind mounts across the Windows↔Linux boundary
  make file watching slow and cannot set the executable bit that
  `scripts/localstack-init.sh` needs.
- Docker Desktop with the WSL2 backend, integration enabled for Ubuntu.
- `make` may not be installed (`sudo apt install make`). Every target is a
  thin wrapper; raw `docker compose` equivalents are in the README.

### Native Linux (Omarchy / Arch)

None of the WSL-specific friction above applies — there's no Windows↔Linux
filesystem boundary, so file watching, executable bits, and shell quoting
all behave normally wherever the repo is cloned.

- Install Docker directly rather than Docker Desktop: `sudo pacman -S docker`
  (the `docker compose` plugin comes with it), then
  `sudo systemctl enable --now docker` and `sudo usermod -aG docker $USER`
  (re-login after). No "WSL integration" step exists.
- `make`, `git`, `aws-cli` likewise via `pacman`/AUR instead of `apt`.
- The flaky-first-boot-DNS and `wsl.exe` shell-quoting gotchas below are
  specific to WSL2's virtualized networking and the `wsl.exe` bridge — they
  don't occur on bare metal.

### macOS

Also no Windows↔Linux filesystem boundary — same as native Linux, the repo
can live anywhere.

- `make` comes with the Xcode Command Line Tools (`xcode-select --install`),
  not preinstalled otherwise.
- Docker Desktop for Mac; no WSL-equivalent integration step.
- `aws` CLI isn't preinstalled — `brew install awscli` before running
  `scripts/cognito-bootstrap.sh` or `aws configure`.
- Watch for **port 5432 already in use** if a native (non-Docker) Postgres —
  notably the postgresql.org/EDB installer, which runs as an always-on
  system service — is also on the machine. See the gotcha below.

### Gotchas already hit — do not rediscover these

- **Postgres enums in Alembic.** If you create an enum explicitly *and*
  reference the same object in `create_table()`, SQLAlchemy emits `CREATE
  TYPE` twice and the migration dies on "type already exists". Use
  `postgresql.ENUM(..., create_type=False)` and call `.create(bind,
  checkfirst=True)` yourself. Hit this for real in migration 0003
  (`clip_status`) — same fix as `stance`/`skate_style` in 0001.
- **`unique=True` already builds an index.** Adding `index=True` alongside it
  creates a second, redundant one.
- **SQLAlchemy `Enum` sends the Python member's `.name`, not `.value`, by
  default** — even for a `StrEnum`. Every enum here (`Stance`, `SkateStyle`,
  `ClipStatus`) has uppercase names but lowercase values matching what the
  Postgres enum type actually contains, so without `values_callable` every
  insert of a non-null enum column fails with `invalid input value for enum
  ...: "DRAFT"`. Fixed once, centrally, via `app.models.enums.sa_enum()` —
  use that helper for any new enum column instead of `SAEnum(...)` directly.
- **Shell quoting through `wsl.exe`.** Multi-line commands and nested quotes
  get mangled. Write a script file and execute it instead. Prefix Bash-tool
  calls with `MSYS_NO_PATHCONV=1` or Git Bash rewrites `/home/...` paths.
- **First WSL boot has flaky DNS.** A Docker pull may fail to resolve
  `public.ecr.aws`; it resolves a minute later. Retry before debugging.
- **Presigned S3 URLs come back unreachable from outside Docker.**
  `boto3.generate_presigned_url()` bakes in whatever endpoint the client was
  configured with — `AWS_ENDPOINT_URL`'s Docker-network `localstack`
  hostname, which curl/Postman/a browser on the host can't resolve. Fixed by
  `Storage._externalize()` swapping in `AWS_PUBLIC_ENDPOINT_URL`
  (`http://localhost:4566`) before the URL leaves the API. Any new code that
  hands a presigned URL to an external caller needs to go through it.
- **SQLAlchemy never auto-applies a relationship's default `lazy=` strategy
  when it's self-referential** — confirmed with a minimal repro outside this
  codebase too, so it's a general SQLAlchemy behavior, not something specific
  to this model. `Comment.replies` (`app/models/social.py`) pointed this at
  `parent_id` on the same table; declaring it `lazy="selectin"` did nothing —
  a plain `select(Comment)` left `replies` unloaded, and touching it crashed
  async SQLAlchemy with an opaque `MissingGreenlet` instead of a real error.
  Non-self-referential relationships on the very same model (`Comment.author`)
  auto-load fine, so this only bites the self-referential case — presumably
  SQLAlchemy's guard against unbounded recursive eager-loading on tree-shaped
  data. Fixed by setting `lazy="raise_on_sql"` (fails loudly if a query
  forgets it, rather than crashing obscurely) and adding an explicit
  `.options(selectinload(Comment.replies))` at both call sites in
  `routes/clips.py` that need it (`add_comment`, `list_comments`).
- **A `viewonly=True` relationship silently drops writes instead of erroring.**
  `Clip.team` (`app/models/clip.py`) was copy-pasted from `Clip.user` — a
  genuinely read-only, never-reassigned relationship — with `viewonly=True`
  carried over even though `routes/clips.py`'s `set_clip_team` assigns
  through it (`clip.team = team`) specifically so `clip_out()` doesn't need
  a re-fetch. With `viewonly=True`, that assignment updates the in-memory
  object (so the very next line's `clip_out()` call, and the PATCH
  response, looked completely correct) but SQLAlchemy never emits the
  `UPDATE` — the write vanishes the moment the session closes. Caught by
  the manual Postman/curl walkthrough (`GET /feed` came back empty after a
  publish that should have shown up via a team follow), not by the
  automated test, because the original assertion only checked the PATCH
  response's JSON rather than re-fetching in a new request/session
  afterward — `tests/test_teams.py`'s team-tag test now does both. Any
  relationship a route assigns to (not just reads) must not be
  `viewonly=True`.
- **This dev database is shared, persistent state across every manual
  verification session and every `pytest` run — a test for anything global
  and unscoped must not assert an exact result list.** Discover (4d) ranks
  across *all* published clips/teams, unlike the home feed (scoped to one
  viewer's follows) or a single profile's `average_score` (scoped to one
  user) — by the time `tests/test_discover.py` was written, 200+ real clips
  and dozens of real teams already existed from every earlier step's manual
  curl verification, and a plain `GET /discover/clips` with the default
  `limit` doesn't guarantee a freshly-inserted test clip lands on page 1.
  Worse, this compounds *between* automated and manual runs: hand-verifying
  4d's `GET /discover/teams` by inserting a real, deliberately backdated
  `team_score_history` row (there's no endpoint that fabricates 7-day-old
  history, so a real row was the only way to exercise the delta ranking by
  hand) left that team permanently eligible for the ranking afterward,
  which broke `test_discover_teams_ranked_by_increase_new_team_excluded`'s
  original exact-list assertion on the very next `pytest` run. Fixed by
  walking every page and asserting presence/relative order among the
  specific ids a test controls, never an exact full list — same fix already
  applied to the clip-ranking tests for the same underlying reason.
- **Port 5432 collides with a native Postgres install, on macOS specifically.**
  The postgresql.org/EDB macOS installer sets Postgres up as an always-on
  system `launchd` daemon (`RunAtLoad: true`), unlike Homebrew's postgres
  (opt-in via `brew services start`) or Postgres.app (only runs while the app
  is open) — so `docker compose up`'s own Postgres fails to bind 5432 with
  "address already in use" the moment that installer is present, without
  ever touching Docker. Check `lsof -nP -iTCP:5432 -sTCP:LISTEN` /
  `ps aux | grep postgres` for `/Library/PostgreSQL/*/bin/postgres` if `make
  up` fails this way. `sudo launchctl disable system/postgresql-<version>`
  disables it permanently (`sudo launchctl bootout system/postgresql-<version>`
  stops it just for the current boot).

- **GitHub OIDC `sub` claim uses the immutable format on this repo.** The repo
  has GitHub's immutable subject enabled, so Actions tokens carry
  `sub = repo:NickPalceski@128099643/TrickLens@1306046704:ref:refs/heads/main`,
  not `repo:NickPalceski/TrickLens:...`. The first deploy's
  `configure-aws-credentials` step failed with a bare "Not authorized to
  perform sts:AssumeRoleWithWebIdentity" even though the role ARN secret was
  correct. The trust policies now use `var.github_oidc_sub_prefix`
  (`infra/variables.tf`). Check the real prefix with
  `curl -s https://api.github.com/repos/NickPalceski/TrickLens/actions/oidc/customization/sub`.
  A fix to these roles can't go through CI, because CI can't assume the
  broken role: apply it locally with
  `-target=aws_iam_role.gha_deploy -target=aws_iam_role.gha_plan`.
- **The CI roles need DynamoDB on the Terraform lock table.** Nothing in
  `infra/` references `tricklens-terraform-locks`, because the bootstrap
  script creates it outside Terraform. So the deploy role was originally
  missing `dynamodb:GetItem`/`PutItem`/`DeleteItem`, and the first CI
  `terraform apply` died on "Error acquiring the state lock". Fixed in
  `infra/iam.tf` (`local.tf_lock_table_arn`). Same chicken-and-egg as the
  OIDC fix: a CI role's own permissions must be fixed with a local
  `-target=aws_iam_role_policy.gha_deploy -target=aws_iam_role_policy.gha_plan`
  apply. While in there, the roles also got the read calls the AWS provider
  makes that the original wildcards missed: `ssm:DescribeParameters`/
  `ListTagsForResource`, `s3:Get*` instead of `s3:GetBucket*` (bucket reads
  hit `GetLifecycleConfiguration` etc.), and `cognito-idp:GetUserPoolMfaConfig`.
  If CI apply hits another `AccessDenied`, fix it the same way. Don't widen
  locally and forget to commit.
- **The first deploy's `migrate` job was green but migrated nothing.**
  `alembic/env.py` called `get_settings()`, which requires
  S3/SQS/CDN settings the runner doesn't have (it only has
  `ALEMBIC_DATABASE_URL`). So every attempt failed with a pydantic
  `ValidationError`. The retry loop ended on `sleep 5` (exit 0), so the step
  passed anyway. Fixed: `env.py` uses the DB-only
  `get_migration_settings()`, and the last retry attempt runs outside the
  loop so its exit code is the step's. Keep migrations free of any
  non-DB config, and never end a CI retry loop on a command that can't
  fail.
  `/health/deep`'s postgres check now also compares `alembic_version` with
  the image's Alembic head, so the post-deploy smoke test fails loudly on
  an unmigrated schema (`tests/test_health.py`).

## Current state

**Steps 1–5 complete and verified: step 4's 4a (follows + home feed), 4b
(likes + comments), 4c (teams) and 4d (Discover) are all done, and step 5
(Terraform + GitHub Actions) is live in AWS.**
Running locally:

```bash
cd ~/git-repos/TrickLens
docker compose up -d
curl -s localhost:8000/health/deep    # expect 200, all four checks green
                                      # (postgres also checks alembic_version == head)
```

- `postgres`, `localstack` (S3 + SQS), `api` (FastAPI on the Lambda base
  image), a `worker` (SQS poll loop, stubbed analyzer), and a one-shot
  `migrate` service, all under Compose.
- Schema at revision `0007`: `users` + `profiles` (step 1–2); `clips`,
  `analyses`, `tricks`, `clip_tricks` (step 3, `team_id`/`score_included`
  added in 4c); `follows` (step 4a — two nullable FKs + XOR check,
  `followee_team_id`'s FK completed in 4c); `likes`, `comments` (step 4b);
  `teams`, `team_members`, `team_join_requests` (step 4c); `clip_views`,
  `clip_rankings`, `team_score_history` (step 4d — see below). Enum types
  `stance`, `skate_style`, `clip_status`, `team_level`, `join_policy`,
  `team_role`, `join_request_kind`.
- LocalStack self-provisions the `tricklens-media` bucket (CORS + 7-day
  `raw/` lifecycle rule) and the `tricklens-analysis` queue with a DLQ.
- A real Cognito dev pool (`scripts/cognito-bootstrap.sh`) backs auth — see
  README's Auth setup. JWT verification, JIT registration (`POST /users`),
  and `/users/me`, `/users/me/profile`, `/users/{username}` are live and
  verified end-to-end (sign-up → confirm → login → register → read).
- `/clips` endpoints (create → complete → worker → tag → publish) and
  `app/worker.py`'s stub analyzer are live and verified end-to-end via the
  Postman collection (`postman/TrickLens.postman_collection.json`): a real
  clip went draft → queued → analyzed (correct six-subscore breakdown,
  `steeze_score` matching the average) → tagged → published.
- Presigned S3 URLs are rewritten from the internal `localstack` Docker
  hostname to `AWS_PUBLIC_ENDPOINT_URL` before leaving the API — see the
  gotcha above. Required for *any* external client (Postman, curl, the
  eventual frontend) to be able to actually use them.
- **Step 4a (follows + home feed)** live and verified end-to-end via the
  Postman collection (Social folder): `POST/DELETE /users/{username}/follow`,
  `GET /feed` (keyset-paginated, `next_cursor`), and
  `followed_by_me`/`follower_count`/`following_count` on `UserPublic`.
  ORM→schema conversion moved into `app/api/serializers.py`. `get_optional_user`
  in deps.py is the viewer path for public routes.
- **Step 4b (likes + comments)** migration `0005` applied, the full test
  suite (`tests/test_engagement.py` plus a re-run of every earlier test file)
  passes against real Postgres/LocalStack — 30/30 — and verified end-to-end
  by hand against real Cognito (curl, not yet Postman itself, but the same
  requests the Engagement folder makes): a real published clip was liked
  (`like_count`/`liked_by_me` correct, double-like 409s, unlike idempotent),
  commented on with one level of nested replies (`comment_count` counts
  replies too), and a comment was deleted by the clip's owner rather than
  its author (moderation) with the reply cascading away and a re-delete
  404ing. `POST/DELETE /clips/{id}/like` and `POST /clips/{id}/comments`,
  `GET /clips/{id}/comments` (keyset-paginated, one level of reply nesting),
  `DELETE /clips/{id}/comments/{comment_id}` (author or clip owner only);
  `like_count`/`comment_count`/`liked_by_me` on `ClipOut`. `clip_out()` now
  takes `db`/`viewer` and optional precomputed engagement values; feed.py
  batches them per-page via `clip_engagement()` instead of paying per-clip
  queries. Keyset cursor encode/decode factored out of feed.py into
  `app/api/pagination.py`, shared with comment listing.
- **Step 4c (teams)** migration `0006` applied; `tests/test_teams.py` plus a
  re-run of every earlier test file passes against real Postgres/LocalStack
  — 42/42 — and verified end-to-end by hand against real Cognito (curl, not
  yet Postman itself, but the same requests the new Teams folder makes; see
  the gotcha above for a real bug this pass caught and fixed). Covers:
  founding (`POST /teams` requires ≥2 invitees beyond the owner; the team is
  invisible/unjoinable until every founding invite is accepted via
  `POST /teams/{slug}/invites/mine/accept`; rejecting one, or the owner
  cancelling via `DELETE /teams/{slug}` while pending, deletes the whole
  attempt); roles (`owner`/`admin`/`member` via
  `PATCH /teams/{slug}/members/{username}`); all three `join_policy` values
  (`open`/`request`/`invite_only`) with their own join/invite/accept/reject
  routes; a hard 20-member cap; team follows
  (`POST/DELETE /teams/{slug}/follow`); `PATCH /clips/{id}/team` (member-only,
  `status == ANALYZED` only, locked after publish) and
  `PATCH /clips/{id}/score-inclusion` (toggle whether `steeze_score` counts
  toward a future average — editable anytime, including after publishing,
  never touches `Analysis`). The home feed's `follows` join became two
  `IN`-subqueries (`Clip.user_id`/`Clip.team_id`) to avoid double-counting a
  clip whose author *and* tagged team are both followed. The frontend design
  canvas (see below) was extended in the same session to cover these flows.
- **Step 4d (Discover)** migration `0007` applied; `tests/test_discover.py`
  plus a re-run of every earlier test file passes against real
  Postgres/LocalStack — 49/49 — and verified end-to-end by hand against real
  Cognito (curl, not yet Postman itself, but the same requests the new
  Discover folder makes): two real published clips (one high-score/no-
  engagement, one low-score/liked-and-commented-and-viewed) proved
  `sort=score` and `sort=engagement` rank oppositely as designed, that
  `score_included=false` drops a clip from `sort=score` while leaving it on
  `sort=engagement`, and that a real team's `GET /discover/teams` delta
  matched its two `team_score_history` snapshots exactly (see the gotcha
  above for what hand-verifying that ranking did to the shared dev DB, and
  what it broke in the automated suite as a result — now fixed). Adds
  `POST /clips/{id}/view` (append-only, not deduped — a rewatch counts
  again; the clip owner's own views are silently dropped rather than
  counted, since unlike a like a raw view has no natural per-user cap) and
  `view_count` on `ClipOut`; `average_score` on `UserPublic` (uncapped) and
  `TeamOut` (top-10-of-eligible-clips), both live-computed via the new
  `app/scoring.py`, shared with the rankings job so the live number and the
  historical snapshot can't drift apart. `app/rankings.py`'s `run()`
  rebuilds `clip_rankings` (this week's published clips, snapshotting
  steeze_score/score_included/like_count/comment_count/view_count/
  engagement_score) and appends one `team_score_history` row per founded
  team — `make rankings` runs it on demand locally; nothing schedules it
  automatically until step 5's EventBridge rule exists.
  `GET /discover/clips?sort=score|engagement` reads the snapshot
  (offset-paginated, not keyset — see docs/ARCHITECTURE.md §7 for why that's
  fine here); `sort=score` filters to `score_included`, `sort=engagement`
  doesn't (`view_count*1 + like_count*5 + comment_count*10`, tunable
  constants in `app/rankings.py`). `GET /discover/teams` stays a live query
  over `team_score_history` instead (cheap — few teams), ranking by score
  increase over ~7 days; a team with no snapshot that old is excluded
  rather than credited a fake increase-from-zero.
- Hot-reload verified at ~850ms. `ruff check`/`ruff format` clean as of 4d's
  files; step 2 is the last point the full suite was confirmed clean
  end-to-end — steps 3/4a/4b/4c haven't been re-run standalone (they do pass
  as part of the full 49-test suite above). Migration upgrade/downgrade
  round trip verified through `0002`; `0003`–`0007` applied and exercised
  (fresh `docker compose up` ran all seven in order against real Postgres),
  not round-tripped (`downgrade` untested).
- **Step 5 (Terraform + GitHub Actions) is live in AWS and verified.** The
  one-time bootstrap is done: prod Neon DB, Terraform state bucket/lock
  table, GitHub OIDC provider and roles, and the two-phase first apply (see
  README's Deployment section). A push to `main` then ran the full
  `deploy.yml` pipeline green end to end: test, build/push image, migrate,
  `terraform apply`, and the `/health/deep` smoke test against the real API
  Gateway URL, with all checks green and the postgres check reporting
  `revision: 0007` from prod Neon. The SSM `DATABASE_URL` (Lambdas) and the
  `ALEMBIC_DATABASE_URL` GitHub secret (migrate job) both point at the same
  Neon database. Getting there took three fixes, all recorded in the
  gotchas above: the OIDC `sub` claim format, the CI roles' missing
  lock-table and provider-read permissions, and the migrate job's silent
  failure. Test suite: 51/51.
  - **What step 5 added, concretely:** `infra/` (Terraform: ECR, 3 Lambda
    functions sharing one image via `image_config.command` overrides,
    IAM roles, API Gateway HTTP API, SQS+DLQ, S3+CloudFront+OAC, a prod
    Cognito pool, EventBridge schedule for rankings, an SSM SecureString
    for `DATABASE_URL`, a $5 AWS Budget alarm, GitHub OIDC + two IAM roles
    for CI); `.github/workflows/{_test,ci,deploy}.yml` (test on every
    push/PR, `terraform plan` commented on PRs, and on push to `main`:
    test → build/push image → `alembic upgrade head` against Neon directly
    from the runner → `terraform apply` → `/health/deep` smoke test, in
    that strict order — see the migration ordering rule above);
    `scripts/terraform-bootstrap.sh` (one-time state bucket/lock table,
    same idiom as `cognito-bootstrap.sh`); `app/services/secrets.py` (new —
    resolves `DATABASE_URL` from SSM before `Settings()` is built, a no-op
    locally); `make tf-init`/`tf-plan`/`tf-apply` targets.

**Not done yet:** no frontend code in this repo (a visual prototype exists as
a separate Artifact canvas, outside the repo — now covers auth/profile/
upload/clip-status *and* the 4c team flows above, added in the same session).

## Build order

1. ✅ Local dev foundation — compose, Postgres, LocalStack, FastAPI, Alembic
2. ✅ Auth (Cognito) + users + profiles
3. ✅ Upload → S3 → SQS → worker (stubbed analyzer)
4. ✅ Social app — built in sub-phases:
   - 4a ✅ follows + home feed *(verified)*
   - 4b ✅ likes + comments *(verified)*
   - 4c ✅ teams (+ `clips.team_id`/`score_included`, `follows.followee_team_id`
     FK, migration `0006`) *(verified)*
   - 4d ✅ Discover (precomputed rankings + team score history) *(verified)*
5. ✅ Terraform + GitHub Actions → deploy to AWS *(live, verified)*
6. ⬜ Replace the stub with the real steeze analyzer

Steps are sequential. Do not start a step before the previous one's
acceptance criteria pass.

## Decisions (short form — full reasoning in docs/ARCHITECTURE.md)

- **Neon, not RDS.** Reaching RDS from Lambda requires a VPC, which costs a
  NAT gateway (~$32/mo) to restore S3/SQS access. Neon is reachable over
  public TLS, so Lambda stays out of the VPC.
- **Queue, not inline analysis.** Analysis takes 30–90s; API Gateway caps
  requests at 29s. SQS is structural, not an optimization.
- **User-tagged tricks.** Trick classification from video is research-grade
  and was cut. Users tag their own tricks; the analyzer only scores
  execution. Tagged clips accumulate as a labeled dataset for a future
  classifier.
- **Heuristic steeze.** Explainable subscores (pop, landing stability,
  roll-away, stomp, compactness, catch), always shown broken down. A bare
  number reads as a bug; a breakdown reads as an opinion.
- **Fail safe.** Low confidence returns `unanalyzable` with a *specific*
  reason, never a guess.

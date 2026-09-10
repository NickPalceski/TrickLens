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
  `app/services/queue.py`, and `app/services/auth.py`. The first two are the
  dev↔prod seam (LocalStack vs real AWS is an env var, nothing more);
  `auth.py` is the exception — Cognito is always the real service, dev
  included, because LocalStack only emulates it on a paid plan and even then
  has known JWKS bugs. See ARCHITECTURE.md §9.
- **Serialization**: never return ORM objects from a route. Always go
  through a Pydantic schema in `app/schemas/`.
- **Media**: store S3 *keys* in the database, never full URLs. URLs are
  built at response time from `CDN_BASE_URL`.
- **IDs**: UUID primary keys on anything user-facing (IDs appear in public
  URLs; sequential integers leak counts and allow enumeration).
- **Migrations**: schema changes always ship with an Alembic migration.

## Environment

Developed from two machines: a Windows/WSL2 box and a native-Linux (Omarchy)
dual-boot. They're independent clones, not a synced setup — dual-booting
means one physical machine can't see the other OS's filesystem, so each side
needs its own `git clone` and its own `.env` (gitignored, regenerate with
`make init`). The two things worth carrying over rather than redoing: the
Cognito dev pool (copy `COGNITO_USER_POOL_ID`/`COGNITO_CLIENT_ID` into the
new `.env`, or re-run `cognito-bootstrap.sh` — it finds the existing pool by
name instead of duplicating it) and, optionally, the same AWS CLI access
key. Postgres/LocalStack state is throwaway container state either way;
`make up` rebuilds it from nothing on both.

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

## Current state

**Steps 1–3 complete and verified; step 4 in progress — 4a (follows + home
feed) done and verified.** Running locally:

```bash
cd ~/git-repos/TrickLens
docker compose up -d
curl -s localhost:8000/health/deep    # expect 200, all four checks green
```

- `postgres`, `localstack` (S3 + SQS), `api` (FastAPI on the Lambda base
  image), a `worker` (SQS poll loop, stubbed analyzer), and a one-shot
  `migrate` service, all under Compose.
- Schema at revision `0004`: `users` + `profiles` (step 1–2); `clips`,
  `analyses`, `tricks`, `clip_tricks` (step 3, no `team_id` yet); `follows`
  (step 4a — two nullable FKs + XOR check, `followee_team_id`'s FK deferred
  to 4c). Enum types `stance`, `skate_style`, `clip_status`.
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
- Hot-reload verified at ~850ms. `ruff check` clean as of step 2; not
  re-run over step 3 or 4a's files — run `make fmt`. Migration
  upgrade/downgrade round trip verified through `0002`; `0003`/`0004`
  applied and exercised, not round-tripped.

**Not done yet:** no frontend code (a visual prototype exists as a separate
Artifact canvas, outside the repo), no Terraform.

## Build order

1. ✅ Local dev foundation — compose, Postgres, LocalStack, FastAPI, Alembic
2. ✅ Auth (Cognito) + users + profiles
3. ✅ Upload → S3 → SQS → worker (stubbed analyzer)
4. 🔶 Social app  ← in progress, built in sub-phases:
   - 4a ✅ follows + home feed *(verified)*
   - 4b ⬜ likes + comments
   - 4c ⬜ teams (+ `clips.team_id`, `follows.followee_team_id` FK)
   - 4d ⬜ Discover (precomputed rankings + team score history)
5. ⬜ Terraform + GitHub Actions → deploy to AWS
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

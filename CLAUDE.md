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

- **Repo lives inside WSL2**: `~/git-repos/TrickLens` on the Ubuntu distro.
  Never work from `/mnt/c` — bind mounts across the Windows↔Linux boundary
  make file watching slow and cannot set the executable bit that
  `scripts/localstack-init.sh` needs.
- Docker Desktop with the WSL2 backend, integration enabled for Ubuntu.
- `make` may not be installed (`sudo apt install make`). Every target is a
  thin wrapper; raw `docker compose` equivalents are in the README.

### Gotchas already hit — do not rediscover these

- **Postgres enums in Alembic.** If you create an enum explicitly *and*
  reference the same object in `create_table()`, SQLAlchemy emits `CREATE
  TYPE` twice and the migration dies on "type already exists". Use
  `postgresql.ENUM(..., create_type=False)` and call `.create(bind,
  checkfirst=True)` yourself. `ClipStatus` will hit this in step 3.
- **`unique=True` already builds an index.** Adding `index=True` alongside it
  creates a second, redundant one.
- **Shell quoting through `wsl.exe`.** Multi-line commands and nested quotes
  get mangled. Write a script file and execute it instead. Prefix Bash-tool
  calls with `MSYS_NO_PATHCONV=1` or Git Bash rewrites `/home/...` paths.
- **First WSL boot has flaky DNS.** A Docker pull may fail to resolve
  `public.ecr.aws`; it resolves a minute later. Retry before debugging.

## Current state

**Steps 1–2 complete and verified** (see Build order below). Running locally:

```bash
cd ~/git-repos/TrickLens
docker compose up -d
curl -s localhost:8000/health/deep    # expect 200, all four checks green
```

- `postgres`, `localstack` (S3 + SQS), `api` (FastAPI on the Lambda base
  image), and a one-shot `migrate` service, all under Compose.
- Schema at revision `0002`: `users` (`cognito_sub` now required) +
  `profiles`, enum types `stance` and `skate_style`, functional unique index
  on `lower(username)`.
- LocalStack self-provisions the `tricklens-media` bucket (CORS + 7-day
  `raw/` lifecycle rule) and the `tricklens-analysis` queue with a DLQ.
- A real Cognito dev pool (`scripts/cognito-bootstrap.sh`) backs auth — see
  README's Auth setup. JWT verification, JIT registration (`POST /users`),
  and `/users/me`, `/users/me/profile`, `/users/{username}` are live and
  verified end-to-end (sign-up → confirm → login → register → read).
- Hot-reload verified at ~850ms. `ruff check` clean. Migration
  upgrade/downgrade round trip verified.

**Not done yet:** no uploads, no frontend, no Terraform.

## Build order

1. ✅ Local dev foundation — compose, Postgres, LocalStack, FastAPI, Alembic
2. ✅ Auth (Cognito) + users + profiles
3. ⬜ Upload → S3 → SQS → worker (stubbed analyzer)  ← next
4. ⬜ Social app: feed, likes, comments, teams, discover
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

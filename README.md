# TrickLens

Skate clip sharing with automated execution scoring.

Upload a clip, tag the trick, and get a **steeze score** — a breakdown of how
cleanly it was landed (pop, landing stability, roll-away, stomp, body
compactness, catch). Follow skaters and teams, and see the week's best on
Discover.

> **Status: step 4 in progress — the social app.** Steps 1–3 are done and
> verified (local dev foundation, Cognito auth/users/profiles, a clip's full
> path from draft through a stubbed analysis to published). Step 4a
> (following users + the home feed) is done and verified end-to-end. Step 4b
> (likes + comments) is done and verified end-to-end too. See
> [Clips](#clips), [Feed & follows](#feed--follows), and
> [Likes & comments](#likes--comments) to try it, and
> [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js + Tailwind + shadcn/ui *(step 4)* |
| API | Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic |
| ML worker | Python (stubbed scorer, step 3); ffmpeg, YOLOv8, MediaPipe *(step 6)* |
| Database | PostgreSQL — Neon in production |
| Media | S3 + CloudFront |
| Queue | SQS |
| Compute | Lambda (container images) |
| Auth | AWS Cognito *(step 2)* |
| Infra | Terraform, GitHub Actions, ECR *(step 5)* |
| Local dev | Docker Compose + LocalStack |

## Prerequisites

- **Windows:** WSL2 with an Ubuntu distro, and **the repo must live inside
  the WSL filesystem** (`~/git-repos/TrickLens`), not on `/mnt/c`. Bind
  mounts across the Windows↔Linux boundary make file watching slow and
  unreliable, and Windows cannot set the executable bit that
  `scripts/localstack-init.sh` needs.
- **Docker Desktop** with the WSL2 backend, and WSL integration enabled for
  your Ubuntu distro (*Settings → Resources → WSL Integration*).
- `make` — **not installed by default on Ubuntu**:

  ```bash
  sudo apt update && sudo apt install -y make
  ```

  Every `make` target is a thin wrapper; if you would rather not install it,
  the equivalent `docker compose` commands are in the table below.
- **An AWS account, for Cognito only.** Everything else (Postgres, S3, SQS)
  runs locally with zero AWS account needed. Cognito is the one exception —
  see [Auth setup](#auth-setup) for why and what it costs (nothing, at this
  scale).

## Quick start

```bash
make init    # creates .env from .env.example
make up      # build + start everything
make health  # verify all dependencies are reachable
```

Then open <http://localhost:8000/docs>.

A healthy `make health` looks like:

```json
{
  "status": "ok",
  "env": "dev",
  "checks": [
    { "name": "postgres", "ok": true, "ms": 2.1 },
    { "name": "s3",       "ok": true, "ms": 8.4 },
    { "name": "sqs",      "ok": true, "ms": 6.9, "detail": { "waiting": 0, "in_flight": 0 } },
    { "name": "cognito",  "ok": true, "ms": 41.2 }
  ]
}
```

## Auth setup

Cognito is the one piece of AWS that isn't emulated locally — LocalStack only
emulates it on a paid plan, and even there its JWKS support has known bugs.
Cognito's own free tier is 50k MAU forever, so there's no cost reason to
emulate it either; dev and prod just use two different real pools. Do this
once, on the host (not in Docker):

1. Create an AWS account and an IAM user with Cognito permissions (the
   `AmazonCognitoPowerUser` managed policy is enough), then `aws configure`
   with that user's access key.
2. Run the bootstrap script — creates a `tricklens-dev` user pool and a
   public app client, and is safe to re-run (it reuses what already exists):
   ```bash
   ./scripts/cognito-bootstrap.sh
   ```
3. Paste the two IDs it prints into `.env`:
   ```
   COGNITO_USER_POOL_ID=...
   COGNITO_CLIENT_ID=...
   ```
4. Restart the API (`make down && make up`) so it picks up the new env vars.

**Creating a test user**, since there's no frontend yet (step 4):

```bash
aws cognito-idp sign-up --client-id "$COGNITO_CLIENT_ID" \
  --username skater@example.com --password 'Sk8-or-die1' \
  --user-attributes Name=email,Value=skater@example.com

# Skips real email verification — fine for a dev pool.
aws cognito-idp admin-confirm-sign-up --user-pool-id "$COGNITO_USER_POOL_ID" \
  --username skater@example.com

aws cognito-idp initiate-auth --client-id "$COGNITO_CLIENT_ID" \
  --auth-flow USER_PASSWORD_AUTH \
  --auth-parameters USERNAME=skater@example.com,PASSWORD='Sk8-or-die1'
# → AuthenticationResult.IdToken is the bearer token below
```

```bash
curl -X POST localhost:8000/users \
  -H "Authorization: Bearer $ID_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username": "nick"}'

curl localhost:8000/users/me -H "Authorization: Bearer $ID_TOKEN"
```

## Clips

**Postman collection** (recommended): [`postman/TrickLens.postman_collection.json`](postman/TrickLens.postman_collection.json)
covers the whole flow — login, register, and each clip step — with response
values (token, clip id, upload URL) auto-saved into the next request's
variables via each request's Tests script, so there's no manual copy-pasting
between steps.

1. **Import:** Postman → *Import* → select the file (or drag it in). It's a
   single collection with variables, not a separate environment.
2. **Fill in variables:** collection → *...* → *Edit* → *Variables* tab.
   Required: `cognito_client_id` (from `.env`'s `COGNITO_CLIENT_ID`). The
   rest have working defaults matching the Auth setup section below.
3. **Make a user:** run the *New User* folder (1 → 4). Sign-up is
   credential-free; the *Admin Confirm* step uses Postman's AWS Signature
   auth, so fill `aws_access_key_id` / `aws_secret_access_key` (the same
   keys `aws configure` uses) and `cognito_user_pool_id` first — put the AWS
   keys in the **Current Value** column only, never Initial Value, which
   syncs to Postman's cloud. Prefer not to? Skip step 2 and run
   `aws cognito-idp admin-confirm-sign-up --user-pool-id $COGNITO_USER_POOL_ID --username <new_user_email>`
   instead. Re-run the folder with different `new_user_*` values for more
   users.
4. **Run it:** *Auth → Login*, then *Users → Register* (once — 409 after
   that is fine), then *Clips* 1 through 6 in order. Re-send *4. Get Clip
   Status* to poll — `docker compose logs -f worker` alongside it shows the
   same transition server-side. The *Social* folder (follow / unfollow /
   home feed) needs `follow_username` set to another registered user's name
   (e.g. `new_username`'s value).

**Without Postman**, the equivalent curl flow, continuing from an
`$ID_TOKEN` obtained as in [Auth setup](#auth-setup):

```bash
# 1. Create a draft + get a presigned upload URL
resp=$(curl -s -X POST localhost:8000/clips \
  -H "Authorization: Bearer $ID_TOKEN" -H "Content-Type: application/json" \
  -d '{"content_type": "video/mp4", "duration_ms": 5000, "source_fps": 60}')
clip_id=$(echo "$resp" | python3 -c 'import json,sys;print(json.load(sys.stdin)["clip"]["id"])')
upload_url=$(echo "$resp" | python3 -c 'import json,sys;print(json.load(sys.stdin)["upload_url"])')

# 2. Upload straight to S3 (LocalStack) — a real video isn't required for the stub
curl -X PUT "$upload_url" -H "Content-Type: video/mp4" --data-binary @/path/to/clip.mp4

# 3. Confirm the upload landed and queue it for analysis
curl -X POST "localhost:8000/clips/$clip_id/complete" -H "Authorization: Bearer $ID_TOKEN"

# 4. Poll until the worker (docker compose logs -f worker) has picked it up
curl "localhost:8000/clips/$clip_id" -H "Authorization: Bearer $ID_TOKEN"

# 5. Once status is "analyzed", tag it and publish
curl -X POST "localhost:8000/clips/$clip_id/tricks" \
  -H "Authorization: Bearer $ID_TOKEN" -H "Content-Type: application/json" \
  -d '{"tricks": ["kickflip"]}'
curl -X POST "localhost:8000/clips/$clip_id/publish" -H "Authorization: Bearer $ID_TOKEN"
```

The scorer is a stub (see docs/ARCHITECTURE.md §4/§5) — it fabricates a
plausible six-subscore breakdown (or, ~10% of the time, an `unanalyzable`
result with a specific reason) rather than actually analyzing the video.
Real analysis is step 6.

## Feed & follows

The Postman collection's **Social** folder covers this; the `follow_username`
variable needs a second registered username. By curl, with two `$ID_TOKEN`s:

```bash
# nick follows another user
curl -X POST localhost:8000/users/otheruser/follow -H "Authorization: Bearer $ID_TOKEN"

# nick's home feed — published clips from everyone nick follows, newest first
curl "localhost:8000/feed?limit=20" -H "Authorization: Bearer $ID_TOKEN"

# page: pass the previous response's next_cursor back
curl "localhost:8000/feed?limit=20&cursor=<next_cursor>" -H "Authorization: Bearer $ID_TOKEN"

curl -X DELETE localhost:8000/users/otheruser/follow -H "Authorization: Bearer $ID_TOKEN"
```

`GET /users/{username}` now also reports `follower_count`, `following_count`,
and (when called with a token) `followed_by_me`. Team follows and Discover
come in the rest of step 4.

## Likes & comments

The Postman collection's **Engagement** folder covers this, reusing
`clip_id` from the Clips folder. By curl, continuing from an `$ID_TOKEN`:

```bash
# like a published clip
curl -X POST "localhost:8000/clips/$clip_id/like" -H "Authorization: Bearer $ID_TOKEN"

curl -X DELETE "localhost:8000/clips/$clip_id/like" -H "Authorization: Bearer $ID_TOKEN"

# top-level comment
resp=$(curl -s -X POST "localhost:8000/clips/$clip_id/comments" \
  -H "Authorization: Bearer $ID_TOKEN" -H "Content-Type: application/json" \
  -d '{"body": "clean landing!"}')
comment_id=$(echo "$resp" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')

# reply — one level deep only; replying to a reply is a 422
curl -X POST "localhost:8000/clips/$clip_id/comments" \
  -H "Authorization: Bearer $ID_TOKEN" -H "Content-Type: application/json" \
  -d "{\"body\": \"for real\", \"parent_id\": \"$comment_id\"}"

# newest-first, top-level comments with replies nested inline, keyset-paginated
curl "localhost:8000/clips/$clip_id/comments?limit=20" -H "Authorization: Bearer $ID_TOKEN"

# the comment's author or the clip's owner can delete it
curl -X DELETE "localhost:8000/clips/$clip_id/comments/$comment_id" -H "Authorization: Bearer $ID_TOKEN"
```

`GET /clips/{id}` (and every other clip payload) now also reports
`like_count`, `comment_count`, and `liked_by_me`. Both like and comment
routes require the clip to be `published` — a 404 if you can't see it at
all (someone else's draft), a 409 if you can (your own draft).

## Commands

| Command | Does | Without `make` |
|---|---|---|
| `make up` | Build and start all services | `docker compose up -d --build` |
| `make down` | Stop (keeps data) | `docker compose down` |
| `make clean` | Stop and delete volumes — full reset | `docker compose down -v` |
| `make logs` | Tail API logs | `docker compose logs -f api` |
| `make health` | Check every dependency | `curl -s localhost:8000/health/deep` |
| `make migrate` | Apply pending migrations | `docker compose run --rm migrate python -m alembic upgrade head` |
| `make revision m="..."` | Create a new migration | `docker compose run --rm migrate python -m alembic revision -m "..."` |
| `make psql` | Open a psql session | `docker compose exec postgres psql -U tricklens -d tricklens` |
| `make shell` | Bash into the API container | `docker compose exec api /bin/bash` |
| `make fmt` | Format and lint | `docker compose run --rm api python -m ruff format app` |
| `make test` | Run the test suite | `docker compose run --rm api python -m pytest` |

## Services

| Service | Port | Purpose |
|---|---|---|
| `api` | 8000 | FastAPI |
| `postgres` | 5432 | Local database |
| `localstack` | 4566 | Emulated S3 + SQS |
| `migrate` | — | One-shot; runs `alembic upgrade head` and exits |
| `worker` | — | Long-polls SQS and runs the (stubbed) analyzer; `docker compose logs -f worker` to watch it |

`docker compose up` is self-provisioning: `scripts/localstack-init.sh` creates
the bucket (with CORS and a lifecycle rule) and both queues automatically, and
`migrate` runs before the API starts. A fresh clone needs no manual setup
*except* Cognito — `scripts/cognito-bootstrap.sh` touches a real AWS account,
so unlike LocalStack it's a one-time step you run by hand. See
[Auth setup](#auth-setup).

## Layout

```
backend/
  app/
    config.py          Settings — the only place env vars are read
    db.py              Async engine + session dependency
    main.py            FastAPI assembly
    lambda_handler.py  Production entrypoint (Mangum)
    worker.py          SQS consumer + stubbed analyzer (dev: poll loop,
                       prod: app.worker.lambda_handler per message)
    models/            SQLAlchemy models
    schemas/           Pydantic request/response models
    api/routes/        Endpoints
    api/serializers.py ORM model -> response schema conversion, defined once
    services/          storage.py (S3), queue.py (SQS), auth.py (Cognito) —
                       the only AWS-aware code
  alembic/             Migrations
docs/ARCHITECTURE.md   System design and decisions
scripts/               LocalStack + Cognito bootstrap
postman/               Postman collection for manual API testing
```

## Notes

- **One image, two entrypoints.** `backend/Dockerfile` builds on the AWS
  Lambda base image. Locally, Compose overrides the entrypoint to run uvicorn
  with hot-reload; in production the Lambda runtime invokes
  `app.lambda_handler.handler`. Same image, same digest, both places.
- **Two database URLs.** The app uses `asyncpg`, Alembic uses `psycopg`. Same
  database, two drivers. Expected, not a bug.
- **`AWS_ENDPOINT_URL` is the whole local↔cloud seam — except Cognito.** Set,
  boto3 talks to LocalStack for S3/SQS. Empty, it talks to real AWS. Cognito
  is always real AWS, dev included (see [Auth setup](#auth-setup)); dev and
  prod are just two different pools, both set explicitly via
  `COGNITO_USER_POOL_ID`.
- **The id token, not the access token, is the bearer credential.** Chosen so
  `email` comes from the token itself — no extra Cognito call needed the
  first time a user registers.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `localstack` never becomes healthy | `scripts/localstack-init.sh` is not executable. `make up` chmods it; if the repo is on `/mnt/c` this cannot work — move it into WSL. |
| `api` exits immediately | `migrate` failed. Check `docker compose logs migrate`. |
| Edits do not hot-reload | Repo is on the Windows filesystem. Move it into WSL. |
| `/health/deep` returns 503 | Read the failing check's `error` field — it names the specific dependency. |
| `cognito` check fails in `/health/deep`, or every request 401s | `COGNITO_USER_POOL_ID`/`COGNITO_CLIENT_ID` are empty or wrong. Run `./scripts/cognito-bootstrap.sh` (see [Auth setup](#auth-setup)) and restart. |
| A clip never leaves `queued` | Check `docker compose logs -f worker` — it should log `polling <queue url>` on startup and one line per message it processes. |
| Uploading to the presigned URL fails to connect / DNS error | `AWS_PUBLIC_ENDPOINT_URL` is missing from `.env` (needs `http://localhost:4566`) or the API wasn't restarted after adding it. Presigned URLs are signed against the Docker-network `localstack` hostname, which nothing outside `docker compose` can resolve — see CLAUDE.md's gotchas. |

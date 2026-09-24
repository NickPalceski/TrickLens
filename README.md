# TrickLens

Skate clip sharing with automated execution scoring.

Upload a clip, tag the trick, and get a **steeze score** — a breakdown of how
cleanly it was landed (pop, landing stability, roll-away, stomp, body
compactness, catch). Follow skaters and teams, and see the week's best on
Discover.

> **Status: step 4 done — the social app; step 5 (Terraform + GitHub Actions)
> written, not yet applied.** Steps 1–3 are done and verified (local dev
> foundation, Cognito auth/users/profiles, a clip's full path from draft
> through a stubbed analysis to published). Steps 4a (following users + the
> home feed), 4b (likes + comments), 4c (teams), and 4d (Discover) are all
> done and verified end-to-end. See [Clips](#clips),
> [Feed & follows](#feed--follows), [Likes & comments](#likes--comments),
> [Teams](#teams), and [Discover](#discover) to try it locally, and
> [Deployment](#deployment) for what running this in real AWS looks like
> (infra code is done; the first live apply is a manual bootstrap step,
> not yet run). [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) has the full
> design.

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
| Infra | Terraform, GitHub Actions, ECR *(step 5 — written, not yet applied)* |
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

# 5. Once status is "analyzed", tag it, optionally tag a team, and publish
curl -X POST "localhost:8000/clips/$clip_id/tricks" \
  -H "Authorization: Bearer $ID_TOKEN" -H "Content-Type: application/json" \
  -d '{"tricks": ["kickflip"]}'

# optional — only works while status is "analyzed", and only if you're a
# member of the team; team_id: null clears it
curl -X PATCH "localhost:8000/clips/$clip_id/team" \
  -H "Authorization: Bearer $ID_TOKEN" -H "Content-Type: application/json" \
  -d "{\"team_id\": \"$team_id\"}"

curl -X POST "localhost:8000/clips/$clip_id/publish" -H "Authorization: Bearer $ID_TOKEN"

# score_included defaults to true; flip it any time, even after publishing,
# if the analysis doesn't feel like a fair read of the clip — it still
# publishes and plays either way, it just won't count toward an average (4d)
curl -X PATCH "localhost:8000/clips/$clip_id/score-inclusion" \
  -H "Authorization: Bearer $ID_TOKEN" -H "Content-Type: application/json" \
  -d '{"included": false}'
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
`followed_by_me` (when called with a token), and `average_score` (4d — see
[Discover](#discover)). Following a team (see [Teams](#teams)) surfaces its
members' clips in your home feed the same way —
`POST/DELETE /teams/{slug}/follow`. If you follow both a clip's author and the
team it's tagged to, it still only shows up once.

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

# a view (4d) — the clip's own owner viewing it doesn't count, everyone
# else's does, and a rewatch counts again (it's not deduped like a like)
curl -X POST "localhost:8000/clips/$clip_id/view" -H "Authorization: Bearer $ID_TOKEN"
```

`GET /clips/{id}` (and every other clip payload) now also reports
`like_count`, `comment_count`, `view_count`, and `liked_by_me`. Like,
comment, and view all require the clip to be `published` — a 404 if you
can't see it at all (someone else's draft), a 409 if you can (your own
draft).

## Teams

The Postman collection's **Teams** folder covers this end-to-end — run
*New User* once, then *Teams → 0. Third Member Setup* once (founding needs
2 invitees beyond the owner, and the collection only has one spare user
otherwise), then *Teams* 1 through 11 in order, interleaving *Clips* 1–4 and
6 where its steps say to. By curl, continuing from an `$ID_TOKEN` and two
more registered usernames to found a team with:

```bash
# Founding a team isn't instant: it stays invisible to everyone but the
# owner and the two invitees below until BOTH accept (a minimum of 2
# founding invitees is required — this is the floor, not a cap).
resp=$(curl -s -X POST localhost:8000/teams \
  -H "Authorization: Bearer $ID_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "name": "Midnight Skaters", "slug": "midnight_skaters",
    "level": "intermediate", "join_policy": "open",
    "invitee_usernames": ["otheruser", "thirduser"]
  }')
slug=$(echo "$resp" | python3 -c 'import json,sys;print(json.load(sys.stdin)["slug"])')

# as otheruser / thirduser — the team goes live once both have accepted;
# rejecting instead cancels the whole attempt (the owner can redo it with
# the same name/slug)
curl -X POST "localhost:8000/teams/$slug/invites/mine/accept" -H "Authorization: Bearer $OTHER_TOKEN"
curl -X POST "localhost:8000/teams/$slug/invites/mine/accept" -H "Authorization: Bearer $THIRD_TOKEN"

curl "localhost:8000/teams/$slug" -H "Authorization: Bearer $ID_TOKEN"
```

Once founded (capped at 20 members, `level`/`join_policy`/description
editable later via `PATCH /teams/{slug}`, owner-only):

```bash
# how someone else ends up on the roster depends on join_policy:
#   open        -> POST /teams/{slug}/join makes them a member immediately
#   request     -> POST /teams/{slug}/join creates a pending request; an
#                  owner/admin resolves it via
#                  POST /teams/{slug}/join-requests/{username}/accept|reject
#   invite_only -> only an owner/admin can add someone, via
#                  POST /teams/{slug}/invites {"username": "..."} — the
#                  invited user then accepts/rejects it themselves, same as
#                  a founding invite (GET /teams/invites/mine lists all of
#                  a user's pending invites, founding or not)
curl -X POST "localhost:8000/teams/$slug/join" -H "Authorization: Bearer $ID_TOKEN"

# owner-only: promote/demote (admins can accept join requests and kick a
# plain member, but not another admin or the owner), or remove someone
# (a member can also remove themselves this way, to leave)
curl -X PATCH "localhost:8000/teams/$slug/members/otheruser" \
  -H "Authorization: Bearer $ID_TOKEN" -H "Content-Type: application/json" -d '{"role": "admin"}'
curl -X DELETE "localhost:8000/teams/$slug/members/otheruser" -H "Authorization: Bearer $ID_TOKEN"

# following a team works exactly like following a user (see Feed & follows)
curl -X POST "localhost:8000/teams/$slug/follow" -H "Authorization: Bearer $ID_TOKEN"
```

Tagging a clip to a team (`PATCH /clips/{id}/team`) and deciding whether its
score counts toward an average (`PATCH /clips/{id}/score-inclusion`) are
covered in [Clips](#clips) — see [Discover](#discover) for where that
average actually shows up.

## Discover

The Postman collection's **Discover** folder covers this, reusing `clip_id`
from the Clips folder. Rankings aren't computed live; rebuild them between
the folder's view requests and its three GET requests (see
[Commands](#commands)):

```bash
make rankings
```

```bash
# this week's top clips by steeze_score (score_included=false clips are
# left out — if you told the app a score wasn't fair, it doesn't get to
# rank on it either) — plain offset pagination, not keyset
curl "localhost:8000/discover/clips?sort=score&limit=20" -H "Authorization: Bearer $ID_TOKEN"

# same clips, ranked instead by a blended engagement score
# (view_count*1 + like_count*5 + comment_count*10) — a completely separate
# signal from the steeze score, for skaters who'd rather browse what looks
# good than what scored well; score_included has no effect here
curl "localhost:8000/discover/clips?sort=engagement&limit=20" -H "Authorization: Bearer $ID_TOKEN"

# teams ranked by score increase over the last ~7 days — a team needs at
# least a week of history to show up here at all
curl "localhost:8000/discover/teams?limit=20" -H "Authorization: Bearer $ID_TOKEN"
```

`GET /users/{username}` and `GET /teams/{slug}` both gained `average_score`
(null if there's nothing eligible yet) — a user's is an uncapped average
across every published, score-included clip; a team's is the average of its
top 10 (see `docs/ARCHITECTURE.md` §6 for why top 10, not all of them).
These are computed live, same cost class as `follower_count`; only the two
`/discover/*` rankings above depend on `make rankings` having been run.

## Deployment

Step 5's infra code (`infra/*.tf`, `.github/workflows/`) is written and
`terraform plan`-validated against a real AWS account — see
[docs/ARCHITECTURE.md §10](docs/ARCHITECTURE.md) for the design decisions
(the 3-Lambdas-from-1-image structure, why the CI deploy role is broad by
design, why `DATABASE_URL` lives in SSM instead of a plain Lambda env var,
the no-canary rollback approach, and the migrate-before-deploy ordering
rule). **Nothing has been applied yet** — there is no live TrickLens
deployment in AWS until the one-time bootstrap below is run by hand.

### `infra/` layout

One Terraform root module (no `modules/` split — see ARCHITECTURE.md's
Decisions for why): `versions.tf`/`providers.tf`/`backend.tf` (plumbing),
`variables.tf`/`outputs.tf`, then one file per AWS service —
`ecr.tf`, `iam.tf`, `lambda.tf`, `api_gateway.tf`, `sqs.tf`, `s3.tf`,
`cloudfront.tf`, `cognito.tf`, `eventbridge.tf`, `secrets.tf`, `budget.tf`,
`cloudwatch.tf`. `make tf-init` / `tf-plan` / `tf-apply` wrap the equivalent
`terraform -chdir=infra ...` commands (see the Commands table below).

### First-ever deploy — one-time, by hand

Every step below runs once, ever, on whichever machine does the first
deploy. After that, every push to `main` handles itself via
`.github/workflows/deploy.yml`.

1. **Create the prod Neon database** (same idiom as the Cognito dev pool —
   a real external account, not something Terraform manages). Save both
   connection strings — the asyncpg-flavored one and the psycopg-flavored
   one — as GitHub repo secrets `DATABASE_URL` and `ALEMBIC_DATABASE_URL`.
2. **Bootstrap the Terraform state backend:**
   ```bash
   ./scripts/terraform-bootstrap.sh
   ```
   Creates the S3 state bucket + DynamoDB lock table once (idempotent, same
   `aws configure` credentials Cognito's bootstrap script already needs).
3. **Create the GitHub OIDC provider + the two deploy roles** (`tricklens-gha-deploy`,
   `tricklens-gha-plan`) by hand, using your own `aws configure` credentials
   — this is the one place Terraform can't bootstrap itself, since the very
   first `terraform apply` needs to run *as* a role that doesn't exist yet.
   `infra/iam.tf` defines these resources; create them once via the AWS
   CLI/console matching that file, then `terraform import` them into state
   so future policy changes go through Terraform like everything else. Save
   both role ARNs as GitHub secrets `AWS_DEPLOY_ROLE_ARN` /
   `AWS_PLAN_ROLE_ARN`, and set `BUDGET_EMAIL` (the AWS Budget alarm's
   recipient) too. The trust policies match GitHub's OIDC `sub` claim
   against `var.github_oidc_sub_prefix` (`infra/variables.tf`). This repo
   uses GitHub's *immutable* subject format
   (`repo:NickPalceski@128099643/TrickLens@1306046704:...`), not the plain
   `repo:owner/repo:...` most guides show. If the role can't be assumed
   ("Not authorized to perform sts:AssumeRoleWithWebIdentity"), compare the
   variable with `sub_claim_prefix` from
   `curl -s https://api.github.com/repos/NickPalceski/TrickLens/actions/oidc/customization/sub`.
4. **Bootstrap the ECR repo, then a first image** (a genuine
   Terraform chicken-and-egg: a Lambda container function needs its image to
   already exist in ECR, and Terraform can't build/push one itself):
   ```bash
   make tf-init
   terraform -chdir=infra apply -target=aws_ecr_repository.main
   docker build backend/ -t <ecr_repo_url>:bootstrap
   docker push <ecr_repo_url>:bootstrap
   ```
5. **First full apply:**
   ```bash
   TF_VAR_database_url="$DATABASE_URL" TF_VAR_budget_email="you@example.com" \
     terraform -chdir=infra apply -var="image_tag=bootstrap"
   ```
   Creates everything else — Cognito prod pool, S3+CloudFront, SQS+DLQ, API
   Gateway, all 3 Lambda functions, EventBridge schedule, SSM parameter,
   budget alarm.
6. **Run the first migration by hand:**
   ```bash
   cd backend && ALEMBIC_DATABASE_URL="$ALEMBIC_DATABASE_URL" python -m alembic upgrade head
   ```
   `ALEMBIC_DATABASE_URL` is the only variable this needs. Alembic reads the
   DB-only `get_migration_settings()`, not the full app `Settings`.
7. **Verify:** `curl $(terraform -chdir=infra output -raw api_invoke_url)/health/deep`
   — all four checks green, against real Neon/S3/SQS/Cognito this time, not
   LocalStack.
8. From here on, every push to `main` runs the automated pipeline — test →
   build/push a real image → migrate → `terraform apply` → smoke test. None
   of the above repeats.

### Ongoing deploys

Nothing to do — push to `main`. `.github/workflows/deploy.yml` builds and
pushes a new image tagged with the commit SHA, runs `alembic upgrade head`
against Neon *before* the new image goes live (see the migration-ordering
rule in ARCHITECTURE.md — this is a hard requirement for any migration
shipped this way, not just a detail), then `terraform apply`s the new
`image_tag` to all 3 Lambda functions in one pass, then smoke-tests
`/health/deep`. Rollback is `terraform apply -var image_tag=<previous_sha>`
— no aliases/canary machinery, see ARCHITECTURE.md for why that's the right
call at this scale.

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
| `make rankings` | Rebuild Discover rankings + team score snapshots | `docker compose run --rm api python -m app.rankings` |
| `make tf-init` | Init Terraform against the account-specific state backend | see the flags in `scripts/terraform-bootstrap.sh`'s header |
| `make tf-plan` | `terraform plan` against prod | `terraform -chdir=infra plan` |
| `make tf-apply` | `terraform apply` against prod — real AWS resources, real cost | `terraform -chdir=infra apply` |

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
    config.py          Settings — the only place env vars are read (one
                       narrow exception in prod, see services/secrets.py)
    db.py              Async engine + session dependency
    main.py            FastAPI assembly
    lambda_handler.py  Production entrypoint (Mangum)
    worker.py          SQS consumer + stubbed analyzer (dev: poll loop,
                       prod: app.worker.lambda_handler per message)
    rankings.py        Discover rebuild — clip_rankings + team_score_history
                       (dev: `make rankings` on demand, prod: EventBridge ->
                       app.rankings.lambda_handler on a schedule)
    scoring.py         Shared average-score math — one definition used by
                       both live API responses and the rankings rebuild
    models/            SQLAlchemy models
    schemas/           Pydantic request/response models
    api/routes/        Endpoints
    api/serializers.py ORM model -> response schema conversion, defined once
    services/          storage.py (S3), queue.py (SQS), auth.py (Cognito),
                       secrets.py (SSM, step 5) — the only AWS-aware code
  alembic/             Migrations
infra/                 Terraform (step 5) — one resource file per AWS
                       service; see Deployment above
.github/workflows/     _test.yml (reusable), ci.yml (PR checks), deploy.yml
                       (push-to-main pipeline) — step 5
docs/ARCHITECTURE.md   System design and decisions
scripts/               LocalStack + Cognito + Terraform-state bootstrap
postman/               Postman collection for manual API testing
```

## Notes

- **One image, three prod entrypoints.** `backend/Dockerfile` builds on the
  AWS Lambda base image. Locally, Compose overrides the entrypoint to run
  uvicorn with hot-reload; in production (step 5) the same image backs 3
  separate Lambda functions — API, worker, rankings — distinguished only by
  an `image_config.command` override in Terraform, never a rebuild. Same
  image, same digest, everywhere.
- **`DATABASE_URL` is SSM in prod, everything else is a plain Lambda env
  var.** The one secret worth the extra ceremony — see
  `app/services/secrets.py` and [Deployment](#deployment).
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
| Terraform reports `AWS_REGION` as a reserved Lambda environment variable | Lambda injects `AWS_REGION` automatically; do not add it to the Terraform-managed Lambda environment. |
| Lambda rejects the ECR image manifest | Build with `docker buildx build --platform linux/amd64 --provenance=false`; Lambda does not accept the OCI image index Docker may push by default. |
| Lambda rejects reserved concurrency below the account minimum | The default Lambda quota is often 10 and AWS requires 10 unreserved executions; remove the worker reservation or request a higher account concurrency quota. |
| The API URL returns `Internal Server Error` while direct Lambda invocation works | Recreate `aws_lambda_permission.api_gateway`; replacing a Lambda removes its invoke policy, and Terraform must recreate that permission with it. |
| Edits do not hot-reload | Repo is on the Windows filesystem. Move it into WSL. |
| `/health/deep` returns 503 | Read the failing check's `error` field — it names the specific dependency. |
| `postgres` check fails with "schema at revision X, code expects Y" | The DB isn't migrated to this code's Alembic head. Locally: `docker compose run --rm migrate`. In prod: check the deploy's `migrate` job log for real `Running upgrade` lines. |
| `cognito` check fails in `/health/deep`, or every request 401s | `COGNITO_USER_POOL_ID`/`COGNITO_CLIENT_ID` are empty or wrong. Run `./scripts/cognito-bootstrap.sh` (see [Auth setup](#auth-setup)) and restart. |
| A clip never leaves `queued` | Check `docker compose logs -f worker` — it should log `polling <queue url>` on startup and one line per message it processes. |
| Uploading to the presigned URL fails to connect / DNS error | `AWS_PUBLIC_ENDPOINT_URL` is missing from `.env` (needs `http://localhost:4566`) or the API wasn't restarted after adding it. Presigned URLs are signed against the Docker-network `localstack` hostname, which nothing outside `docker compose` can resolve — see CLAUDE.md's gotchas. |

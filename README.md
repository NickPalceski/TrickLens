# TrickLens

Skate clip sharing with automated execution scoring.

Upload a clip, tag the trick, and get a **steeze score** — a breakdown of how
cleanly it was landed (pop, landing stability, roll-away, stomp, body
compactness, catch). Follow skaters and teams, and see the week's best on
Discover.

> **Status: step 1 of 6 complete — local development foundation.**
> Postgres, LocalStack (S3 + SQS), and the FastAPI service run under Docker
> Compose, with Alembic migrations applying on startup. No auth, no uploads,
> no analysis yet. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the
> full design.

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js + Tailwind + shadcn/ui *(step 4)* |
| API | Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic |
| ML worker | Python, ffmpeg, YOLOv8, MediaPipe *(step 6)* |
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
    { "name": "sqs",      "ok": true, "ms": 6.9, "detail": { "waiting": 0, "in_flight": 0 } }
  ]
}
```

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

## Services

| Service | Port | Purpose |
|---|---|---|
| `api` | 8000 | FastAPI |
| `postgres` | 5432 | Local database |
| `localstack` | 4566 | Emulated S3 + SQS |
| `migrate` | — | One-shot; runs `alembic upgrade head` and exits |

`docker compose up` is self-provisioning: `scripts/localstack-init.sh` creates
the bucket (with CORS and a lifecycle rule) and both queues automatically, and
`migrate` runs before the API starts. A fresh clone needs no manual setup.

## Layout

```
backend/
  app/
    config.py          Settings — the only place env vars are read
    db.py              Async engine + session dependency
    main.py            FastAPI assembly
    lambda_handler.py  Production entrypoint (Mangum)
    models/            SQLAlchemy models
    schemas/           Pydantic request/response models
    api/routes/        Endpoints
    services/          storage.py (S3) + queue.py (SQS) — the only AWS-aware code
  alembic/             Migrations
docs/ARCHITECTURE.md   System design and decisions
scripts/               LocalStack bootstrap
```

## Notes

- **One image, two entrypoints.** `backend/Dockerfile` builds on the AWS
  Lambda base image. Locally, Compose overrides the entrypoint to run uvicorn
  with hot-reload; in production the Lambda runtime invokes
  `app.lambda_handler.handler`. Same image, same digest, both places.
- **Two database URLs.** The app uses `asyncpg`, Alembic uses `psycopg`. Same
  database, two drivers. Expected, not a bug.
- **`AWS_ENDPOINT_URL` is the whole local↔cloud seam.** Set, boto3 talks to
  LocalStack. Empty, it talks to real AWS. No code branches on environment.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `localstack` never becomes healthy | `scripts/localstack-init.sh` is not executable. `make up` chmods it; if the repo is on `/mnt/c` this cannot work — move it into WSL. |
| `api` exits immediately | `migrate` failed. Check `docker compose logs migrate`. |
| Edits do not hot-reload | Repo is on the Windows filesystem. Move it into WSL. |
| `/health/deep` returns 503 | Read the failing check's `error` field — it names the specific dependency. |

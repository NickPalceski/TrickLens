.DEFAULT_GOAL := help

# The `web` container runs as the host user, so files it writes into
# frontend/ (node_modules, the lockfile) aren't root-owned (docker-compose.yml).
export HOST_UID := $(shell id -u)
export HOST_GID := $(shell id -g)
WEB := docker compose run --rm --no-deps web pnpm
OPENAPI_DUMP := import json; from app.main import app; print(json.dumps(app.openapi(), indent=2, sort_keys=True))

# Worker-image-only test files (need ffmpeg / the CV stack). Under `make test`
# (API image) they all skip.
WORKER_TESTS := tests/test_media.py tests/test_analyzer_detect.py \
	tests/test_analyzer_localize.py tests/test_analyzer_stage_b.py \
	tests/test_analyzer_landed.py tests/test_analyzer_measure.py \
	tests/test_analyzer_real_clips.py

.PHONY: help init up down clean logs ps health migrate revision shell psql fmt test test-worker \
	licenses analyze-clip calibrate rescore rankings sweep \
	tf-init tf-plan tf-apply \
	web web-install web-test web-check web-fmt web-types

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

init: ## First-time setup (creates .env)
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")
	@chmod +x scripts/localstack-init.sh
	@echo "ready — now run: make up"

up: ## Build and start everything
	@chmod +x scripts/localstack-init.sh
	docker compose up -d --build
	@echo ""
	@echo "  Web app:   http://localhost:3000"
	@echo "  API docs:  http://localhost:8000/docs"
	@echo "  Health:    make health"

down: ## Stop everything (keeps data)
	docker compose down

clean: ## Stop everything and delete volumes (full reset)
	docker compose down -v

logs: ## Tail API logs
	docker compose logs -f api

ps: ## Show service status
	docker compose ps

health: ## Check that all dependencies are reachable
	@curl -s localhost:8000/health/deep | python3 -m json.tool

migrate: ## Apply pending migrations
	docker compose run --rm migrate python -m alembic upgrade head

revision: ## Create a migration:  make revision m="add clips table"
	docker compose run --rm migrate python -m alembic revision -m "$(m)"

shell: ## Shell into the API container
	docker compose exec api /bin/bash

psql: ## Open a psql session
	docker compose exec postgres psql -U tricklens -d tricklens

fmt: ## Format and lint
	docker compose run --rm api python -m ruff format app
	docker compose run --rm api python -m ruff check --fix app

test: ## Run the test suite
	docker compose run --rm api python -m pytest

test-worker: ## Run the worker-image tests (media pipeline + analyzer; real-clip tests skip without clips)
	docker compose run --rm worker python -m pytest $(WORKER_TESTS)

analyze-clip: ## Run Stage A on a local clip + write a debug video:  make analyze-clip FILE=tests/fixtures/clips/x.mov
	@test -n "$(FILE)" || (echo 'usage: make analyze-clip FILE=tests/fixtures/clips/<clip> (path relative to backend/)' && exit 1)
	docker compose run --rm --no-deps --user "$$(id -u):$$(id -g)" worker python -m app.analyzer.cli $(FILE)

licenses: ## Fail if any worker-image Python dependency is AGPL (TrickLens goes closed-source)
	docker compose run --rm --no-deps worker sh -c \
	  "pip install -q pip-licenses && pip-licenses --partial-match --fail-on 'AGPL;Affero'"

rankings: ## Rebuild Discover rankings + team score snapshots (on demand; scheduled automatically in prod, step 5)
	docker compose run --rm api python -m app.rankings

calibrate: ## Tune calibration.py against your hand-judged clips (tests/fixtures/clips/judgments.toml); prints a report, changes nothing
	docker compose run --rm --no-deps --user "$$(id -u):$$(id -g)" worker python -m app.analyzer.calibrate

rescore: ## Dry run: list stored scores that the current calibration.py would change (add ARGS=--apply to write)
	docker compose run --rm api python -m app.rescore $(ARGS)

sweep: ## Fail clips stuck queued/analyzing for over 2h (on demand; runs with every rankings tick in prod, 6c-3)
	docker compose run --rm api python -m app.sweep

tf-init: ## Init Terraform against the account-specific state backend (run scripts/terraform-bootstrap.sh first)
	@ACCOUNT_ID=$$(aws sts get-caller-identity --query Account --output text); \
	terraform -chdir=infra init \
	  -backend-config="bucket=tricklens-terraform-state-$$ACCOUNT_ID" \
	  -backend-config="dynamodb_table=tricklens-terraform-locks" \
	  -backend-config="region=us-east-1" \
	  -backend-config="key=prod/terraform.tfstate"

tf-plan: ## terraform plan against prod (needs TF_VAR_database_url and TF_VAR_budget_email set)
	terraform -chdir=infra plan

tf-apply: ## terraform apply against prod — real AWS resources, real cost
	terraform -chdir=infra apply

web: ## Start just the web app on http://localhost:3000 (mock API by default)
	docker compose up -d web
	@echo "  Web app:   http://localhost:3000   (logs: docker compose logs -f web)"

web-install: ## Install or refresh frontend dependencies (writes frontend/pnpm-lock.yaml)
	$(WEB) install

web-test: ## Run the frontend unit tests
	$(WEB) install --frozen-lockfile
	$(WEB) test

web-check: ## Everything CI checks on the frontend: lint, API-type drift, typecheck, tests, build
	$(WEB) install --frozen-lockfile
	$(WEB) check

web-fmt: ## Format and lint-fix the frontend (Biome)
	$(WEB) fmt

web-types: ## Regenerate the frontend's API types from the backend's OpenAPI spec
	docker compose run --rm --no-deps -T api python -c "$(OPENAPI_DUMP)" > frontend/packages/api/openapi.json
	$(WEB) install --frozen-lockfile
	$(WEB) types

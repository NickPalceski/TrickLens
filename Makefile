.DEFAULT_GOAL := help

# Worker-image-only test files (need ffmpeg / the CV stack). Under `make test`
# (API image) they all skip.
WORKER_TESTS := tests/test_media.py tests/test_analyzer_detect.py \
	tests/test_analyzer_localize.py tests/test_analyzer_real_clips.py

.PHONY: help init up down clean logs ps health migrate revision shell psql fmt test test-worker \
	licenses analyze-clip rankings \
	tf-init tf-plan tf-apply

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

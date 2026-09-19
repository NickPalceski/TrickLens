.DEFAULT_GOAL := help
.PHONY: help init up down clean logs ps health migrate revision shell psql fmt test rankings

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

rankings: ## Rebuild Discover rankings + team score snapshots (on demand; scheduled automatically in prod, step 5)
	docker compose run --rm api python -m app.rankings

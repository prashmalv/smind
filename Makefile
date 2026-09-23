# ShopperMind AI — common tasks.
.PHONY: help dev api web install seed test lint build deploy clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install API and web dependencies
	cd apps/api && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
	cd apps/web && npm install

dev: ## Run the whole platform locally (Postgres, Redis, API, web)
	docker compose up --build

api: ## Run just the API against a local SQLite file
	cd apps/api && DATABASE_URL=sqlite:///../../data/shoppermind.db \
		.venv/bin/uvicorn app.main:app --reload --port 8000

web: ## Run just the web front end
	cd apps/web && npm run dev

test: ## Run the API test suite
	cd apps/api && .venv/bin/pytest -q

lint: ## Lint and type-check both apps
	cd apps/api && .venv/bin/ruff check app
	cd apps/web && npm run typecheck

build: ## Production build of the web app
	cd apps/web && npm run build

edge: ## Run the camera agent against a local API (needs CAMERA_AGENT_KEY)
	cd edge/camera-agent && python3 agent.py --simulate \
		--cameras KOR-ENT:entrance,KOR-QUE:queue,KOR-DSP:display \
		--api http://localhost:8000 --window 60

deploy: ## Deploy to Azure (POSTGRES_ADMIN_PASSWORD must be set)
	./scripts/deploy-azure.sh $(ENV) $(LOCATION)

clean: ## Remove local build artefacts and the dev database
	rm -rf apps/web/.next apps/api/.pytest_cache data/*.db
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

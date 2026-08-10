.RECIPEPREFIX := >

ENV_FILE ?= .env
API_DEV_PORT ?= 8000
API_RUNNER ?= uv run
API_DEV_RELOAD ?= --reload

.PHONY: setup env-merge lint typecheck test test-e2e check-compose check-env \
	check-host-api dev \
	compose-up compose-down docker-build-run docker-run docker-stop docker-logs \
	capture-docker-ports ensure-traefik-network api-dev web-dev

setup:
>cd api && uv sync --dev
>cd web && corepack pnpm install

env-merge:
>bash scripts/merge_env_example.sh

lint:
>cd api && uv run ruff format --check . && uv run ruff check .
>cd web && corepack pnpm lint

typecheck:
>cd api && uv run mypy app
>cd web && corepack pnpm typecheck

test:
>cd api && uv run pytest
>cd web && corepack pnpm test -- --run

test-e2e:
>cd web && corepack pnpm exec playwright test

check-compose:
>bash scripts/check_traefik_compose.sh

check-env:
>bash scripts/check_env_contexts.sh

check-host-api:
>bash scripts/check_host_api.sh

api-dev:
>set -a; . "$(abspath $(ENV_FILE))"; set +a; cd api && $(API_RUNNER) uvicorn app.main:app $(API_DEV_RELOAD) --port $(API_DEV_PORT)

web-dev:
>set -a; . "$(abspath $(ENV_FILE))"; set +a; cd web && corepack pnpm dev

dev: docker-build-run

docker-build-run: ensure-traefik-network
>docker compose up -d --build --wait --wait-timeout 180
>$(MAKE) capture-docker-ports

docker-run: ensure-traefik-network
>docker compose up -d --wait --wait-timeout 180
>$(MAKE) capture-docker-ports

ensure-traefik-network:
>docker network inspect traefik-proxy >/dev/null 2>&1 || docker network create traefik-proxy

docker-stop:
>docker compose down

docker-logs:
>docker compose logs -f

capture-docker-ports:
>bash scripts/capture_docker_ports.sh

compose-up: docker-run

compose-down: docker-stop

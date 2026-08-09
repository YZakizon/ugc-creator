.RECIPEPREFIX := >

.PHONY: setup env-merge lint typecheck test test-e2e check-compose dev \
	compose-up compose-down docker-build-run docker-run docker-stop docker-logs \
	capture-docker-ports ensure-traefik-network

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

dev: docker-build-run

docker-build-run: ensure-traefik-network
>docker compose up -d --build
>$(MAKE) capture-docker-ports

docker-run: ensure-traefik-network
>docker compose up -d
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

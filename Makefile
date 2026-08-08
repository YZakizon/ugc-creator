.RECIPEPREFIX := >

.PHONY: setup lint typecheck test test-e2e dev compose-up compose-down \
	docker-build-run docker-run docker-stop docker-logs capture-docker-ports

setup:
>cd api && uv sync --dev
>cd web && corepack pnpm install

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

dev: docker-build-run

docker-build-run:
>docker compose up -d --build
>$(MAKE) capture-docker-ports

docker-run:
>docker compose up -d
>$(MAKE) capture-docker-ports

docker-stop:
>docker compose down

docker-logs:
>docker compose logs -f

capture-docker-ports:
>bash scripts/capture_docker_ports.sh

compose-up: docker-run

compose-down: docker-stop

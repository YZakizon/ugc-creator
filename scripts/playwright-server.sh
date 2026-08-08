#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project_name="ugc-creator-playwright"

cleanup() {
  kill "${web_pid:-}" 2>/dev/null || true
  docker compose -p "$project_name" -f "$repo_root/compose.test.yaml" down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 143' INT TERM

docker compose -p "$project_name" -f "$repo_root/compose.test.yaml" down -v >/dev/null 2>&1 || true
docker compose -p "$project_name" -f "$repo_root/compose.test.yaml" up -d --build --wait postgres-test redis-test api-test worker-test

(cd "$repo_root/web" && API_BASE_URL="http://127.0.0.1:18011" corepack pnpm exec next dev --hostname 127.0.0.1 --port 13011) &
web_pid=$!

until curl -fsS http://127.0.0.1:18011/health >/dev/null && curl -fsS http://127.0.0.1:13011 >/dev/null; do
  if ! kill -0 "$web_pid" 2>/dev/null; then
    exit 1
  fi
  sleep 1
done

wait "$web_pid"

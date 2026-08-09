#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
example_file="$repo_root/.env.example"
target_file="$(mktemp)"
trap 'rm -f "$target_file"' EXIT

printf 'OPENAI_API_KEY=keep-existing-value\n' > "$target_file"
bash "$repo_root/scripts/merge_env_example.sh" "$example_file" "$target_file" >/dev/null
bash "$repo_root/scripts/merge_env_example.sh" "$example_file" "$target_file" >/dev/null

grep -qx 'OPENAI_API_KEY=keep-existing-value' "$target_file"
grep -qx 'DATABASE_URL=postgresql+psycopg://ugc:ugc@localhost:5432/ugc_creator' "$target_file"
grep -qx 'REDIS_URL=redis://localhost:6379/0' "$target_file"
grep -qx 'OBJECT_STORAGE_ENDPOINT=http://localhost:9000' "$target_file"
grep -qx 'API_BASE_URL=http://localhost:8000' "$target_file"

awk -F= '
  /^[A-Za-z_][A-Za-z0-9_]*=/ {
    count[$1]++
    if (count[$1] > 1) duplicate = 1
  }
  END { exit duplicate }
' "$target_file"

docker compose --project-directory "$repo_root" --file "$repo_root/compose.yaml" config --format json | jq -e '
  .services.api.environment.DATABASE_URL == "postgresql+psycopg://ugc:ugc@postgres:5432/ugc_creator" and
  .services.api.environment.REDIS_URL == "redis://redis:6379/0" and
  .services.api.environment.OBJECT_STORAGE_ENDPOINT == "http://minio:9000" and
  .services.web.environment.API_BASE_URL == "http://api:8000"
' >/dev/null

printf 'Host and Docker environment contexts are valid.\n'

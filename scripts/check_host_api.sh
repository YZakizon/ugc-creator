#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$(mktemp)"
log_file="$(mktemp)"
api_port="${HOST_API_TEST_PORT:-18012}"
api_pid=""

cleanup() {
  if [[ -n "$api_pid" ]] && kill -0 "$api_pid" 2>/dev/null; then
    kill -- "-$api_pid"
    wait "$api_pid" 2>/dev/null || true
  fi
  rm -f "$env_file" "$log_file"
}
trap cleanup EXIT

{
  printf 'DATABASE_URL=\n'
  printf 'REDIS_URL=redis://localhost:6379/0\n'
  printf 'OBJECT_STORAGE_ENDPOINT=http://localhost:9000\n'
  printf 'UGC_FAKE_PROVIDERS=1\n'
  printf 'COMFYUI_BASE_URL=http://localhost:8188\n'
} > "$env_file"

setsid make -C "$repo_root" api-dev \
  ENV_FILE="$env_file" \
  API_DEV_PORT="$api_port" \
  API_DEV_RELOAD= \
  >"$log_file" 2>&1 &
api_pid=$!

for _attempt in $(seq 1 30); do
  if curl --fail --silent --show-error \
    --max-time 2 "http://127.0.0.1:$api_port/health" >/dev/null; then
    printf 'Host API development workflow is healthy.\n'
    exit 0
  fi
  if ! kill -0 "$api_pid" 2>/dev/null; then
    cat "$log_file" >&2
    exit 1
  fi
  sleep 1
done

cat "$log_file" >&2
printf 'Host API development workflow did not become healthy.\n' >&2
exit 1

#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
example_file="${1:-$repo_root/.env.example}"
target_file="${2:-$repo_root/.env}"

if [[ ! -f "$example_file" ]]; then
  printf 'Environment example not found: %s\n' "$example_file" >&2
  exit 1
fi

touch "$target_file"

declare -A existing_keys=()
while IFS= read -r line || [[ -n "$line" ]]; do
  if [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)= ]]; then
    existing_keys["${BASH_REMATCH[1]}"]=1
  fi
done < "$target_file"

missing_lines=()
while IFS= read -r line || [[ -n "$line" ]]; do
  if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)= ]]; then
    key="${BASH_REMATCH[1]}"
    if [[ -z "${existing_keys[$key]:-}" ]]; then
      missing_lines+=("$line")
      existing_keys["$key"]=1
    fi
  fi
done < "$example_file"

if (( ${#missing_lines[@]} == 0 )); then
  printf 'No missing environment variables in %s.\n' "$target_file"
  exit 0
fi

if [[ -s "$target_file" ]]; then
  printf '\n' >> "$target_file"
fi
printf '# Added from .env.example\n' >> "$target_file"
printf '%s\n' "${missing_lines[@]}" >> "$target_file"
printf 'Added %d missing environment variables to %s.\n' "${#missing_lines[@]}" "$target_file"

#!/usr/bin/env bash
set -euo pipefail

docker compose config --format json | jq -e '
  .services.web.labels["traefik.enable"] == "true" and
  .services.web.labels["traefik.environment"] == "dev" and
  .services.web.labels["traefik.docker.network"] == "traefik-proxy" and
  .services.web.labels["traefik.http.routers.ugc-creator.rule"] == "Host(`ugc.localhost`)" and
  .services.web.labels["traefik.http.routers.ugc-creator.entrypoints"] == "web" and
  .services.web.labels["traefik.http.services.ugc-creator.loadbalancer.server.port"] == "3010" and
  (.services.web.networks | has("default")) and
  (.services.web.networks | has("traefik-proxy")) and
  .networks["traefik-proxy"].external == true and
  .networks["traefik-proxy"].name == "traefik-proxy"
' >/dev/null

printf 'Traefik Compose routing is valid.\n'

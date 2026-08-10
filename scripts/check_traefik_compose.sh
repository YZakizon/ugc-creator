#!/usr/bin/env bash
set -euo pipefail

docker compose config --format json | jq -e '
  .services.web.labels["traefik.enable"] == "true" and
  .services.web.labels["traefik.environment"] == "dev" and
  .services.web.labels["traefik.docker.network"] == "traefik-proxy" and
  .services.web.labels["traefik.http.routers.ugc-creator.rule"] == "Host(`web.ugc.localhost`) || Host(`ugc.localhost`)" and
  .services.web.labels["traefik.http.routers.ugc-creator.entrypoints"] == "web" and
  .services.web.labels["traefik.http.services.ugc-creator.loadbalancer.server.port"] == "3010" and
  (.services.web.networks | has("default")) and
  (.services.web.networks | has("traefik-proxy")) and
  .networks["traefik-proxy"].external == true and
  .networks["traefik-proxy"].name == "traefik-proxy" and
  ([.services[] | .restart] | all(. == "unless-stopped")) and
  .services.worker.depends_on.postgres.condition == "service_healthy" and
  .services.worker.depends_on.redis.condition == "service_healthy" and
  .services.worker.healthcheck.test[0] == "CMD-SHELL" and
  (.services.worker.healthcheck.test[1] | contains("inspect ping")) and
  (.services.worker.healthcheck.test[1] | contains("celery@$$HOSTNAME"))
' >/dev/null

printf 'Compose routing and worker recovery settings are valid.\n'

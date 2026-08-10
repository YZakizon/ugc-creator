# UGC Creator

UGC Creator generates provider-neutral UGC-style short-form videos. The first
rendering path is ComfyUI with an LTX 2.3 workflow, while the application
architecture also supports WAN through ComfyUI and external renderers such as
Kling.

## Repository layout

- `web/` — Next.js App Router frontend.
- `api/` — FastAPI application and Celery worker package.
- `compose.yaml` — local PostgreSQL, Redis, MinIO, API, worker, and web services.
- `AGENTS.md` — repository engineering rules.
- `PLANS.md` — implementation source of truth.

## Prerequisites

- Docker and Docker Compose
- Node.js 20+ and pnpm
- Python 3.12+ and uv

## Local setup

1. Create or update the local environment file without replacing existing values:

   ```bash
   make env-merge
   ```

   The command appends variables missing from `.env`; it never overwrites existing
   provider keys or local settings. Add your `OPENAI_API_KEY` and
   `ELEVENLABS_API_KEY` values after merging. The example uses host-reachable
   `localhost` URLs. Docker Compose overrides them with the `postgres`, `redis`,
   `minio`, and `api` service names for container-to-container traffic.

   Keep `UGC_FAKE_PROVIDERS=0` for real OpenAI and ElevenLabs requests. Set it
   to `1` only for deterministic automated tests or demos that must not call
   paid providers. The OpenAI content prompt is edited under **Settings** in the
   application and is stored in PostgreSQL, not in `.env`.

2. Install project dependencies:

   ```bash
   make setup
   ```

3. Start the full Docker development stack:

   ```bash
   make docker-build-run
   ```

   Docker assigns random host ports for PostgreSQL, Redis, MinIO, and the API.
   The assigned values are captured in `.docker/ports.env`:

   ```bash
   source .docker/ports.env
   curl "$UGC_API_BASE_URL/health"
   ```

   The web shell remains available at <http://localhost:3010>.
   Startup waits for required health checks, including a responsive Celery
   worker. Services restart automatically after Docker or the host restarts;
   `make docker-stop` still removes them explicitly.
   When the development Traefik stack is running, it is also available at
   <http://ugc.localhost>. The web container joins the shared `traefik-proxy`
   network; the API remains private and is reached through the web app's
   same-origin proxy.

   Traefik routing can be adjusted in `.env`:

   ```dotenv
   TRAEFIK_ENABLE=true
   TRAEFIK_ENVIRONMENT=dev
   TRAEFIK_HOST=ugc.localhost
   TRAEFIK_ENTRYPOINT=web
   ```

4. For non-Docker application development, start the API and web development
   servers in separate terminals. These targets load the root `.env` before
   changing into each application directory:

   ```bash
   make api-dev
   make web-dev
   ```

   The API health endpoint is available at <http://localhost:8000/health>.

   Use `make docker-run` to run an already-built Docker stack, `make docker-logs`
   to follow logs, and `make docker-stop` to bring it down.

## Quality checks

```bash
make lint
make typecheck
make test
```

The CI workflow runs these checks plus a production web build. Paid provider
credentials are not required for the foundation tests.

Playwright browser integration tests use a dedicated PostgreSQL Compose project
(`ugc-creator-playwright`) and the deterministic fake LLM provider. Install the
Playwright browser once, then run:

```bash
cd web && pnpm exec playwright install chromium
cd .. && make test-e2e
```

The test database is removed with its named volume when the run finishes.

## Local service endpoints

- Web: <http://localhost:3010>
- API: <http://localhost:8000>
- API docs: <http://localhost:8000/docs>
- PostgreSQL, Redis, MinIO, and API: random host ports recorded in
  `.docker/ports.env` after `make docker-run` or `make docker-build-run`.

No provider credentials or generated media should be committed. See
`AGENTS.md` and `PLANS.md` before expanding the application beyond Milestone 0.
# ugc-creator

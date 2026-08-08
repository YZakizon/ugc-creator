# AGENTS.md — UGC Creator

## Purpose

Repository-wide instructions for Codex and other coding agents working on **UGC Creator**.

UGC Creator is a provider-neutral app for generating UGC-style short-form influencer videos. A user supplies one topic or a batch of topics; the system generates a speech script and Instagram/TikTok metadata, creates TTS audio, prepares a selected render profile, submits video generation, tracks the job, and stores the finished media.

The first path is **ComfyUI + LTX 2.3**. The architecture MUST also support **WAN through ComfyUI** and external APIs such as **Kling** without redesigning the core application.

Read `PLANS.md` before work that changes architecture, persistence, provider interfaces, job flow, or milestone scope.

---

## Non-negotiable architecture rules

1. **Provider-neutral core**
   - Core services/models must not depend on LTX-, WAN-, or Kling-specific fields.
   - Provider/model-specific behavior belongs in adapters, workflow bindings, capabilities, and render-profile configuration.

2. **ComfyUI workflows are templates**
   - Never mutate the stored workflow during normal execution.
   - Deep-copy it for every render, apply job values to the copy, then submit the copy.
   - Never hardcode ComfyUI node IDs in generic services.

3. **Render Profile is the user-facing generation configuration**
   - It combines character, renderer/provider, workflow when applicable, voice profile, prompt template, defaults, capabilities, and parameter schema/bindings.
   - Examples: `Elena — Shelf — LTX`, `Elena — Shelf — WAN`, `Elena — Shelf — Kling`.

4. **Long-running work is asynchronous**
   - API calls must not block for TTS/video generation.
   - Persist state, enqueue work, return quickly, expose progress separately.

5. **External operations are retry-safe**
   - Persist provider task IDs immediately.
   - A worker retry must not duplicate a paid TTS call or render submission when the existing result/submission is recoverable.

6. **Media stays outside PostgreSQL**
   - DB stores metadata and asset references.
   - Images/audio/video/thumbnails/workflow files use the storage abstraction.

7. **Secrets stay server-side**
   - Never expose or commit OpenAI, ElevenLabs, Kling, storage, DB, Redis, or ComfyUI credentials.

8. **Keep V1 infrastructure simple**
   - No Kubernetes, Kafka, Temporal, service mesh, GraphQL, or microservices without an explicit architecture decision.

---

## Approved stack

### Web
- Next.js App Router
- React + TypeScript (`strict`)
- Tailwind CSS + shadcn/ui
- TanStack Query
- React Hook Form + Zod for non-trivial forms
- Zustand only for genuine client-only shared state
- Vitest + React Testing Library
- Playwright for critical E2E
- package manager: `pnpm`

### API/workers
- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2.x + Alembic
- PostgreSQL
- Celery + Redis
- HTTPX
- ffmpeg + ffprobe
- pytest
- Ruff
- mypy
- package/environment manager: `uv`

### Storage/rendering
- `StorageProvider` abstraction
- local filesystem and/or S3-compatible implementation
- MinIO for local S3-compatible development when needed
- `ComfyUIRenderer` for LTX/WAN workflows
- external renderer adapters such as `KlingRenderer`
- Docker Compose for application services
- ComfyUI may run independently on GPU machines

Do not create separate LTX/WAN renderer classes unless transport/runtime behavior truly differs from generic ComfyUI execution.

---

## Target repository shape

```text
ugc-creator/
├── AGENTS.md
├── PLANS.md
├── README.md
├── .env.example
├── compose.yaml
├── Makefile
├── web/
│   ├── app/
│   ├── components/
│   ├── features/
│   ├── lib/
│   ├── types/
│   └── tests/
├── api/
│   ├── pyproject.toml
│   ├── migrations/
│   └── app/
│       ├── main.py
│       ├── api/
│       ├── core/
│       ├── db/
│       ├── models/
│       ├── schemas/
│       ├── services/
│       ├── providers/
│       │   ├── llm/
│       │   ├── tts/
│       │   ├── render/
│       │   └── storage/
│       ├── workers/
│       └── tests/
└── docs/
    ├── architecture/
    └── decisions/
```

Prefer domain/feature grouping over generic catch-all `utils`.

If a subtree develops special conventions, add a nested `AGENTS.md` there instead of continuously enlarging this file.

---

## Domain vocabulary

Use these terms consistently.

### Character
Influencer/persona plus reference assets and optional defaults. A Character is not a renderer.

### VoiceProfile
Reusable TTS configuration: provider, voice ID, display name, model if applicable, speed, stability, similarity, style exaggeration, and bounded provider-specific settings. Secrets are not stored here.

### WorkflowTemplate
Imported ComfyUI **API workflow JSON** plus metadata/version/checksum. Treat as immutable during rendering.

### WorkflowParameterBinding
Maps a semantic parameter to a ComfyUI node input.

Example:

```json
{
  "key": "seed",
  "node_id": "27",
  "input_name": "seed",
  "value_type": "integer"
}
```

Typical semantic keys:
`source_image`, `audio`, `script`, `video_prompt`, `seed`, `fps`, `duration`, `frame_count`, `width`, `height`.

### RenderProvider
Transport/runtime implementation such as `comfyui` or `kling`.

### RenderProfile
Reusable configuration connecting Character + VoiceProfile + renderer/provider + optional WorkflowTemplate + prompts + defaults + parameter schema/capabilities/bindings.

### Batch
Collection of topic jobs created together.

### TopicJob
One topic's content/TTS/render lifecycle.

### RenderAttempt
One concrete render submission/rerender attempt. Preserve historical attempts rather than overwriting them.

### MediaAsset
Metadata/reference for image/audio/video/thumbnail/workflow files stored outside the DB.

---

## Job lifecycle

Use explicit persisted state; do not infer it from nullable fields.

Preferred states:

```text
draft
generating_content
content_ready
generating_tts
tts_ready
fitting_duration
ready_to_render
queued
submitting_render
rendering
downloading_output
completed
failed
cancelled
```

Rules:
- Centralize and test state transitions.
- Status is authoritative; progress is advisory.
- Store error category/message separately.
- Preserve meaningful timestamps.
- Retrying should restart from the failed stage where safe.
- Cancellation is best-effort when the upstream provider cannot cancel.
- Rerender creates a new RenderAttempt.

---

## End-to-end pipeline

```text
topic
  -> structured LLM content
  -> TTS
  -> ffprobe duration
  -> bounded duration-fit loop if needed
  -> resolve render profile
  -> copy/build render payload
  -> submit renderer
  -> track progress/status
  -> ingest output to storage
  -> completed library item
```

Do not put the whole pipeline into one giant function/task.

Use boundaries such as:
- `ContentService`
- `TTSService`
- `DurationFitService`
- `RenderService`
- `MediaService`
- `StorageService`

Celery tasks orchestrate services; provider logic lives in providers.

---

## LLM contract

LLM results must use structured output validated by Pydantic. Do not parse informal prose with string splitting.

Conceptual output:

```json
{
  "speech_script": "...",
  "hook": "...",
  "instagram": {
    "title": "...",
    "description": "...",
    "hashtags": ["#example"]
  },
  "tiktok": {
    "title": "...",
    "description": "...",
    "hashtags": ["#example"]
  }
}
```

Rules:
- Target conversational UGC speech and requested duration.
- Word count is not final duration.
- Persist useful provider/model/prompt-version metadata.
- OpenAI-specific DTOs stay inside the OpenAI adapter.
- Core code depends on an LLM interface, not SDK response objects.

---

## TTS and duration fitting

ElevenLabs is the first TTS provider.

Use a provider-neutral contract:

```python
class TTSProvider(Protocol):
    async def synthesize(self, request: TTSRequest) -> TTSResult: ...
```

Persist effective voice ID/settings, script version, provider request ID when available, audio asset, and actual measured duration.

Never call ElevenLabs from browser code with a secret key.

Use `ffprobe` to determine output duration.

For a target such as 30 seconds:
1. Generate script.
2. Generate TTS.
3. Measure audio.
4. If inside tolerance, continue.
5. Otherwise request a controlled shorten/expand revision.
6. Re-synthesize and measure.
7. Stop at configured max attempts.

Defaults may begin around target 30s, tolerance ±1s, max 2–3 fit attempts, but keep them configurable.

Never create an unbounded regeneration loop.

---

## Renderer contract

Core orchestration depends on a small capability-aware interface:

```python
class VideoRenderer(Protocol):
    async def submit(self, request: RenderRequest) -> RenderSubmission: ...
    async def get_status(self, external_job_id: str) -> RenderStatus: ...
    async def cancel(self, external_job_id: str) -> None: ...
    async def fetch_outputs(self, external_job_id: str) -> list[RenderOutput]: ...
```

Renderers expose capabilities, for example:

```json
{
  "supports_image": true,
  "supports_audio": true,
  "supports_native_lipsync": true,
  "supports_seed": true,
  "supports_fps": true,
  "supports_duration": true,
  "supports_negative_prompt": true,
  "supports_camera_control": false
}
```

Capabilities drive backend validation and frontend visibility.

Do not scatter `if provider == "kling"` checks across unrelated modules. Provider-specific branching belongs in adapters/configuration.

---

## ComfyUI rules

`ComfyUIRenderer` handles generic API-format ComfyUI workflows.

### Import/configure
- Accept/validate API workflow JSON.
- Store the original/versioned template.
- Allow semantic bindings to node IDs/input names.
- Validate bindings before saving.
- Clearly report mappings whose nodes/inputs disappeared.

### Render
- Load template.
- Deep-copy it.
- Resolve effective job/profile values.
- Apply semantic bindings to the copy.
- Resolve/upload input media.
- Submit workflow.
- Persist `prompt_id` immediately.
- Track status/progress (WebSocket when useful; status/history fallback).
- Discover outputs.
- Copy/download final assets into UGC Creator storage.

### Never
- mutate the stored template during render execution;
- hardcode universal node IDs;
- assume LTX and WAN share node layouts;
- use an absolute ComfyUI filesystem path as the only durable asset reference;
- allow arbitrary workflow/user data to write outside configured media paths.

Prompt templates may use controlled placeholders such as `{{SCRIPT}}`. Unknown placeholders should fail validation rather than silently vanish.

---

## External renderer rules

For Kling/future providers:
- verify current official API docs at implementation time;
- keep provider request/response schemas inside the adapter;
- normalize provider status/errors;
- persist task ID before polling/waiting;
- respect rate limits;
- use bounded backoff + jitter for transient failures;
- distinguish auth, quota, rate-limit, rejection, network, timeout, malformed response;
- redact secrets from logs.

Adding an external renderer must not require a separate content/TTS/job pipeline.

---

## Storage rules

Define `StorageProvider` with operations such as `put`, `get`, `delete`, `exists`, `signed_url`.

Use asset IDs/object keys in APIs, not arbitrary absolute paths.

Recommended object-key pattern:

```text
characters/{character_id}/...
batches/{batch_id}/jobs/{job_id}/audio/...
batches/{batch_id}/jobs/{job_id}/video/...
batches/{batch_id}/jobs/{job_id}/thumbnails/...
workflows/{workflow_id}/...
```

Never store video/audio blobs in PostgreSQL.

---

## API conventions

- Prefix app endpoints with `/api/v1`.
- Prefer resource nouns.
- Use UUIDs for exposed IDs unless an existing project standard says otherwise.
- Use Pydantic request/response models; never return SQLAlchemy models directly.
- Stable machine-readable error codes.
- Ownership/access checks at service boundaries.
- Pagination for growing lists.
- UTC timestamps serialized ISO 8601.
- Backend is authoritative for capability/parameter validation.
- Upload endpoints enforce type/size limits.

Likely resources:
`characters`, `voice-profiles`, `workflow-templates`, `render-profiles`, `render-nodes`, `batches`, `jobs`, `assets`, `library`.

Actions such as cancel/retry/rerender/regenerate may use action subresources.

---

## Realtime/progress

Backend may expose normalized job events through WebSocket with polling fallback.

Example:

```json
{
  "type": "job.updated",
  "job_id": "...",
  "status": "rendering",
  "progress": 43,
  "updated_at": "..."
}
```

Persisted state remains authoritative. Do not expose raw Celery/Redis messages directly.

---

## Celery rules

- Tasks must be retry-safe.
- Business/provider logic stays in services/providers.
- Pass durable IDs/object keys, not large binary payloads.
- Never put raw video/audio bytes in Redis task messages.
- Configure time limits/retry policy by task type.
- Provider submit must guard against duplicate submission.
- Worker crash/restart must be recoverable from persisted state.
- Avoid holding a worker slot during long sleeps; reschedule a status-check task where appropriate.

Useful task categories:
content generation, TTS, media analysis, render submission, render monitoring, output ingestion/finalization.

---

## Database rules

- Every schema change gets an Alembic migration.
- Do not rewrite already-shared migrations; add a new one.
- Use explicit FKs/indexes.
- Use constrained status values/enums.
- JSONB is for provider-specific/settings flexibility, not a substitute for modeling core relationships.
- Persist enough render-attempt history to diagnose failures and explain prior outputs.
- Snapshot effective render values needed for reproducibility; do not rely only on mutable current profile values.

---

## Frontend rules

### Architecture
- TanStack Query for server state.
- Keep API/domain types centralized/generated if OpenAPI generation is adopted.
- Server components for static/server layout; client components only where interaction requires.
- No privileged provider calls or secrets in client code.
- Client validation improves UX; backend validation is authoritative.

### Core screens
- Dashboard
- Characters
- Voice Profiles
- Workflow Templates
- Render Profiles
- Create Batch
- Batch/Job Queue
- Output Library
- Settings / Render Nodes

### Batch UX
- one topic or multiline topics;
- default render profile;
- per-topic override;
- target duration and auto-fit;
- clear status/progress/errors;
- retry from failed stage where safe.

### Render profile UX
Dynamically show controls from capability + parameter schema. Do not build unrelated hardcoded LTX/WAN/Kling forms.

### General
- responsive;
- accessible labels/keyboard behavior;
- useful loading/empty/error states;
- avoid unnecessary modal-heavy flows.

---

## Python style

- Python 3.12+.
- Type public service/provider APIs.
- Prefer Pydantic/dataclasses over untyped dicts at boundaries.
- Use async for network I/O where practical.
- Keep provider DTOs separate from domain DTOs.
- Raise explicit domain/provider exceptions.
- Structured logging; no secret leakage.
- Ruff formatting/linting + mypy.

Avoid:
- blanket `# type: ignore`;
- giant service classes;
- provider SDK objects escaping adapters;
- swallowing broad exceptions;
- mutable module-global runtime state.

---

## TypeScript style

- strict mode.
- Avoid `any`; prefer `unknown` + validation.
- Use Zod at untrusted boundaries where useful.
- Keep substantial business logic out of JSX.
- Prefer focused composable components.
- Accessible semantic HTML.
- Do not add global state for data already owned by TanStack Query.

---

## Error model

Use stable categories similar to:

```text
validation_error
not_found
conflict
provider_auth_error
provider_rate_limited
provider_quota_exceeded
provider_rejected
provider_unavailable
provider_timeout
media_processing_error
workflow_binding_error
workflow_submission_error
storage_error
internal_error
```

Retain safe user message + internal diagnostic context + provider + upstream task/request ID + retriable flag where known.

Never return raw headers, credentials, stack traces, or secrets.

---

## Logging/security

Trace jobs with identifiers such as:
`request_id`, `batch_id`, `job_id`, `render_attempt_id`, `provider`, `external_job_id`.

Never log authorization headers, API keys, binary payloads, or sensitive signed URLs.

Security requirements:
- `.env` is gitignored; `.env.example` has names/safe examples only.
- Validate uploads/workflow files and size.
- Sanitize filenames/object keys.
- Enforce ownership for user resources.
- Validate ComfyUI bindings server-side.
- Guard configurable URLs against SSRF.
- Protect expensive generation endpoints.
- Encrypt user-supplied provider keys at rest if supported later.
- Invoke ffmpeg with argument arrays, not user-built shell strings.

---

## Testing requirements

New behavior needs relevant tests.

### API
Test services, state transitions, duration fit, workflow binding/copying, capability validation, provider normalization, errors, idempotency.

### Providers
Use fakes/mocks and fixtures. Default CI must not require paid OpenAI/ElevenLabs/Kling calls.

For ComfyUI specifically:
- workflow copy/mutation fixture tests;
- missing node/input validation;
- status/progress parsing fixtures;
- opt-in real-node integration test.

### Web
Test critical forms, capability-driven controls, batch topic parsing, status/error states, workflow binding editor.

### E2E
Use fake providers for deterministic critical flow:
character -> voice -> workflow binding -> render profile -> batch -> content/TTS -> fake renderer progress -> completed output.

---

## Standard commands

Prefer repository scripts/Make targets when present. Otherwise converge on:

### API

```bash
cd api
uv sync --dev
uv run ruff format --check .
uv run ruff check .
uv run mypy app
uv run pytest
uv run alembic upgrade head
```

Development formatting:

```bash
uv run ruff format .
uv run ruff check --fix .
```

### Web

```bash
cd web
pnpm install
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm exec playwright test
```

### Root

```bash
docker compose up -d postgres redis minio
make lint
make typecheck
make test
make test-e2e
```

Do not claim checks passed unless actually run successfully. If a required external service is unavailable, run the largest valid subset and report what was not run.

---

## Dependencies

- Prefer mainstream maintained packages.
- Do not add production dependencies when the existing stack solves the problem simply.
- Major new infrastructure requires justification/ADR.
- Lock with `uv.lock` and `pnpm-lock.yaml`; never manually edit lockfiles.
- Avoid preview/beta core infrastructure without a clear reason.

---

## Change discipline

Before editing:
1. Read applicable `AGENTS.md`.
2. Read `PLANS.md`.
3. Inspect existing code/tests before assuming structure.
4. Keep scope tight.

While editing:
- preserve provider neutrality;
- add migrations for schema changes;
- update tests with behavior;
- update docs for public/architectural changes;
- do not revert unrelated user changes.

Before finishing:
1. Review `git diff`.
2. Run relevant format/lint/type/test commands.
3. Verify no secrets/generated media were accidentally added.
4. Check for accidental workflow-template mutation or hardcoded node IDs.
5. Update `PLANS.md` if tracked scope/decisions changed.
6. Report behavior, tests run, and limitations.

---

## Architecture decision rule

Record an ADR under `docs/decisions/` when a task would materially change an invariant, e.g.:
- replacing Celery/Redis or PostgreSQL;
- introducing microservices/GraphQL;
- changing persistent job-state semantics;
- changing the storage/renderer contract;
- allowing client-side provider API calls;
- putting model-specific fields in the core job model;
- abandoning immutable workflow-template execution.

ADR includes: context, decision, alternatives, consequences, migration implications.

---

## PLANS.md maintenance

`PLANS.md` is the implementation source of truth.

For a milestone:
- set status to `IN PROGRESS`;
- mark only actually completed items;
- add meaningful decisions to Decision Log;
- record blockers/risks;
- mark `DONE` only after acceptance criteria pass.

If implementation reality conflicts with the plan, update the plan in the same change.

---

## Definition of done

A feature is done when:
- requested behavior works;
- provider/domain boundaries remain intact;
- API/schema validation is correct;
- migrations exist if needed;
- relevant tests/lint/types pass;
- UI includes required loading/error/empty behavior;
- retry/failure behavior is considered;
- secrets are not exposed;
- docs/plan are updated when required.

For render/provider work also verify:
- stored workflow is unchanged;
- external job ID is persisted;
- statuses normalize correctly;
- duplicate submission is guarded;
- provider diagnostics are retained safely;
- final media lands through StorageProvider.

---

## V1 boundary

V1 proves the complete loop with:
- Character
- ElevenLabs VoiceProfile
- ComfyUI workflow import
- semantic workflow bindings
- LTX 2.3 RenderProfile
- one or many topics
- structured LLM content
- TTS + actual duration
- bounded duration fitting
- asynchronous jobs
- ComfyUI submission/progress/output ingestion
- Instagram/TikTok metadata
- output library
- retry/error handling
- Docker Compose development

WAN must reuse `ComfyUIRenderer` with a different workflow/profile.

Kling must be a new renderer adapter without changing the central content/TTS/job pipeline.

If adding WAN or Kling requires rewriting the central flow, fix the abstraction before proceeding.

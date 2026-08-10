# PLANS.md — UGC Creator Implementation Plan

## Document purpose

This is the living implementation plan for **UGC Creator**.

Codex and human contributors should use it to:
- understand the intended architecture and product scope;
- choose the next implementation task;
- record progress and discovered constraints;
- prevent LTX-specific implementation from becoming the product architecture;
- define acceptance criteria for each milestone.

The repository-wide engineering rules are in `AGENTS.md`.

---

# 1. Product vision

UGC Creator generates UGC-style short-form influencer videos for Instagram and TikTok.

A user can enter one topic or many topics. For each topic, the application:
1. Generates a short conversational speech script with an LLM.
2. Generates Instagram/TikTok hook/title/description/hashtags.
3. Generates TTS audio using the render profile's selected voice profile.
4. Measures the real TTS duration.
5. Optionally revises/re-synthesizes the speech to fit the target duration.
6. Selects or uses the topic's render profile.
7. Injects semantic inputs such as script, audio, image, seed, FPS, duration, prompt, width, and height into the selected rendering configuration.
8. Submits a video generation job.
9. Tracks queue/render progress.
10. Ingests the finished output into UGC Creator storage.
11. Presents the video, speech, and platform metadata together.

The application starts with:
- OpenAI as the LLM provider;
- ElevenLabs as the TTS provider;
- ComfyUI as the local rendering transport;
- LTX 2.3 as the first ComfyUI video workflow.

The architecture must then support:
- WAN through the same generic ComfyUI renderer;
- Kling through an external renderer adapter;
- additional LLM/TTS/video providers later.

---

# 2. Architecture summary

```text
                         ┌──────────────────────────────┐
                         │          Next.js UI          │
                         │                              │
                         │ Characters / Voices          │
                         │ Workflows / Render Profiles  │
                         │ Topics / Content / Library   │
                         └──────────────┬───────────────┘
                                        │
                                 REST + WebSocket
                                        │
                         ┌──────────────▼───────────────┐
                         │        FastAPI API           │
                         │                              │
                         │ Domain + orchestration       │
                         │ Provider-independent models  │
                         └──────┬────────┬────────┬─────┘
                                │        │        │
                         PostgreSQL    Redis    Storage
                                │        │        │
                                │        ▼        │
                                │   Celery Workers│
                                │        │        │
                                │        ├────────┼──────────────┐
                                │        │        │              │
                                │        ▼        ▼              ▼
                                │     OpenAI  ElevenLabs     RenderService
                                │                              │
                                │                   ┌──────────┴──────────┐
                                │                   │                     │
                                │                   ▼                     ▼
                                │            ComfyUIRenderer        KlingRenderer
                                │                   │
                                │              ┌────┴────┐
                                │              ▼         ▼
                                │           LTX 2.3     WAN
                                │
                                └──────────── job/assets/history
```

---

# 3. Architectural invariants

These are not optional implementation suggestions.

1. Core job orchestration is video-model neutral.
2. ComfyUI is one render provider/transport, not the entire application.
3. LTX and WAN are primarily workflow/profile choices under ComfyUI.
4. Kling is an adapter behind the same renderer contract.
5. Stored ComfyUI workflow templates are not mutated during render execution.
6. Semantic parameter bindings map application fields to workflow nodes.
7. Long jobs are queued and persisted.
8. Browser clients never receive server provider secrets.
9. Database stores metadata, not large media blobs.
10. The UI is driven by render capabilities/parameter schemas rather than hardcoded model-specific screens.
11. Retry does not mean duplicate paid/provider submission.
12. The source of truth for job status is persistent application state.

---

# 4. Intended repository structure

```text
ugc-creator/
├── AGENTS.md
├── PLANS.md
├── README.md
├── .env.example
├── compose.yaml
├── Makefile
├── web/
└── api/
```

Expanded shape is defined in `AGENTS.md`.

---

# 5. Environment and local services

## Application containers

Initial Docker Compose services:

```text
web
api
worker
postgres
redis
minio          # when S3-compatible local storage is enabled
```

The web service may join the shared `traefik-proxy` network and expose the
application through Traefik. The API remains internal behind the Next.js
same-origin proxy; direct random host ports remain available for diagnostics.

ComfyUI should not be tightly coupled to the Compose project. It can run:
- on localhost;
- on another LAN GPU machine;
- on multiple GPU machines later.

Example configuration names only:

```dotenv
DATABASE_URL=
REDIS_URL=
OBJECT_STORAGE_ENDPOINT=
OBJECT_STORAGE_BUCKET=
OBJECT_STORAGE_ACCESS_KEY=
OBJECT_STORAGE_SECRET_KEY=

OPENAI_API_KEY=
OPENAI_MODEL=

ELEVENLABS_API_KEY=
ELEVENLABS_DEFAULT_MODEL=

APP_BASE_URL=
API_BASE_URL=
```

Provider/render-node credentials and URLs may ultimately be stored in server-side configuration/database with appropriate encryption, but never in browser-visible code.

---

# 6. Domain entities

## 6.1 User / ownership

V1 can start single-user if desired, but schema/service boundaries should not make multi-user support impossible.

If authentication is deferred:
- keep `user_id`/ownership strategy documented;
- do not expose unauthenticated production endpoints publicly;
- do not scatter assumptions that all records belong to one permanent user.

## 6.2 Character

Fields:
- `id`
- `name`
- `slug`
- `description`
- `default_voice_profile_id` nullable
- `default_reference_asset_id` nullable
- `default_prompt`
- `is_active`
- timestamps

Relationships:
- assets
- voice profiles/render profiles

## 6.3 VoiceProfile

Fields:
- `id`
- `name`
- `provider`
- `provider_voice_id`
- `provider_model` nullable
- normalized voice settings:
  - speed
  - stability
  - similarity
  - style_exaggeration
- `extra_settings` JSONB
- timestamps

Secrets are not part of VoiceProfile.

## 6.4 WorkflowTemplate

Fields:
- `id`
- `name`
- `description`
- `renderer_provider` = `comfyui`
- source workflow JSON/asset reference
- optional parsed metadata
- version
- checksum
- timestamps

Prefer versioning when edited after being used for renders.

## 6.5 WorkflowParameterBinding

Fields:
- `id`
- `workflow_template_id`
- `semantic_key`
- `node_id`
- `input_name`
- `value_type`
- optional transform/config JSON
- required flag

Example semantic keys:
- `source_image`
- `audio`
- `script`
- `video_prompt`
- `seed`
- `fps`
- `duration`
- `frame_count`
- `width`
- `height`

## 6.6 RenderNode

Represents a configured remote/local runtime such as ComfyUI.

Fields:
- `id`
- `name`
- `provider`
- `base_url`
- server-side credential reference if needed
- enabled
- optional capacity metadata
- optional tags
- last health status/time

Future:
- GPU model
- VRAM
- active job count
- scheduling weight

## 6.7 RenderProfile

Fields:
- `id`
- `name`
- `character_id`
- `voice_profile_id`
- `renderer_provider`
- `render_node_id` nullable/strategy
- `workflow_template_id` nullable
- `prompt_template`
- `negative_prompt_template` nullable
- `default_parameters` JSONB
- `parameter_schema` JSONB
- `capabilities` JSONB or provider-derived capability reference
- `is_active`
- timestamps

A ComfyUI LTX profile points to an LTX workflow.
A ComfyUI WAN profile points to a WAN workflow.
A Kling profile has no ComfyUI workflow.

## 6.8 Batch

Fields:
- `id`
- `name`
- `status`
- default render profile
- job counts/derived summary if useful
- timestamps

## 6.9 TopicJob

Fields:
- `id`
- `batch_id`
- `topic`
- `render_profile_id`
- `status`
- target duration
- tolerance
- speech script
- hook
- Instagram metadata
- TikTok metadata
- LLM provider/model/prompt version metadata
- TTS audio asset
- measured TTS duration
- content/TTS revision counter
- latest render attempt ID
- error fields
- timestamps

## 6.10 RenderAttempt

Fields:
- `id`
- `job_id`
- attempt number
- provider
- render profile snapshot or effective parameter snapshot
- external job/task ID
- effective seed
- status
- progress
- provider request metadata (safe/redacted)
- output asset IDs
- error fields
- submitted/started/completed timestamps

Rerender should create another RenderAttempt.

## 6.11 MediaAsset

Fields:
- `id`
- `kind`: image/audio/video/thumbnail/workflow/other
- storage provider
- object key
- mime type
- size bytes
- checksum
- media duration nullable
- width/height nullable
- metadata JSONB
- timestamps

---

# 7. Normalized provider interfaces

## 7.1 LLM

```python
class LLMProvider(Protocol):
    async def generate_ugc_content(
        self,
        request: UGCContentRequest,
    ) -> UGCContentResult: ...

    async def revise_script_duration(
        self,
        request: ScriptRevisionRequest,
    ) -> ScriptRevisionResult: ...
```

`UGCContentResult`:
- speech_script
- hook
- Instagram title/description/hashtags
- TikTok title/description/hashtags

Use structured output and Pydantic validation.

## 7.2 TTS

```python
class TTSProvider(Protocol):
    async def synthesize(self, request: TTSRequest) -> TTSResult: ...
```

Result:
- bytes/temporary stream handled via service
- provider request ID if available
- format/mime
- provider metadata

Media service stores the audio and measures duration.

## 7.3 Video renderer

```python
class VideoRenderer(Protocol):
    async def capabilities(self, context: RendererContext) -> RendererCapabilities: ...
    async def submit(self, request: RenderRequest) -> RenderSubmission: ...
    async def get_status(self, external_job_id: str) -> RenderStatus: ...
    async def cancel(self, external_job_id: str) -> None: ...
    async def fetch_outputs(self, external_job_id: str) -> list[RenderOutput]: ...
```

Normalized statuses should include:
- queued
- running
- succeeded
- failed
- cancelled
- unknown

## 7.4 Storage

```python
class StorageProvider(Protocol):
    async def put(...): ...
    async def get(...): ...
    async def delete(...): ...
    async def exists(...): ...
    async def signed_url(...): ...
```

---

# 8. Job state machine

Preferred state progression:

```text
draft
  |
  v
generating_content
  |
  v
content_ready
  |
  v
generating_tts
  |
  v
tts_ready
  |
  +-------- actual duration outside tolerance -------+
  |                                                  |
  v                                                  |
fitting_duration -> generating_tts -> tts_ready -----+
  |
  v
ready_to_render
  |
  v
queued
  |
  v
submitting_render
  |
  v
rendering
  |
  v
downloading_output
  |
  v
completed
```

Terminal/alternate states:
- failed
- cancelled

Retry logic should restart from the failed stage where possible rather than recomputing everything.

---

# 9. Duration-fit algorithm

## Inputs
- target duration, default initially 30 seconds
- tolerance, e.g. ±1 second
- max fit attempts, e.g. 2
- active voice profile

## Algorithm

```text
generate script
generate TTS
measure duration

if duration within target ± tolerance:
    continue to render

else:
    determine direction and approximate change:
      too long  -> shorten
      too short -> expand

    ask LLM for a controlled revision preserving:
      topic
      hook/meaning
      UGC tone
      call-to-action constraints
      desired relative length change

    synthesize again
    measure again

stop after max attempts
```

Persist each speech/TTS version or at least enough history to diagnose why fitting failed.

Do not use word count as the final duration measure.

---

# 10. ComfyUI workflow architecture

## 10.1 Import

Workflow import screen:
1. Upload/paste API workflow JSON.
2. Parse node graph.
3. Store source workflow.
4. Present searchable node/input list.
5. User binds semantic fields.
6. Validate mappings.
7. Save WorkflowTemplate + bindings.

Potential enhancement:
- detect likely seed/text/image/audio nodes and suggest mappings;
- suggestions must be reviewable and not silently assumed.

## 10.2 Prompt/script handling

A video prompt may contain static scene/camera direction plus a speech placeholder.

Example:

```text
A woman stands naturally in front of a shelf.
Subtle natural body movement and direct eye contact.
Natural UGC delivery.

Spoken dialogue:
{{SCRIPT}}
```

Render preparation replaces `{{SCRIPT}}` for the job copy only.

Potential supported placeholders:

```text
{{SCRIPT}}
{{TOPIC}}
{{HOOK}}
{{VIDEO_PROMPT}}
{{DURATION}}
{{CHARACTER_NAME}}
```

Use a controlled template renderer. Unknown placeholders should produce a validation error, not disappear silently.

## 10.3 Render-time mutation

```text
load stored template
  -> deep copy
  -> resolve effective values
  -> apply binding transforms
  -> inject input media references
  -> submit copied workflow
```

Binding examples:

```json
{
  "seed": {
    "node_id": "27",
    "input_name": "seed",
    "value_type": "integer"
  },
  "script": {
    "node_id": "41",
    "input_name": "text",
    "value_type": "template"
  }
}
```

The application must not contain assumptions that these node IDs are universal.

## 10.4 ComfyUI transport

Implement adapter features:
- health check
- workflow submission
- prompt/task ID capture
- WebSocket progress when available
- status/history fallback
- output discovery
- upload/reference of source image/audio
- cancellation if supported
- error normalization

## 10.5 Multiple GPU nodes

Not required for first end-to-end MVP, but design RenderNode for it.

Future scheduler can select:
- explicitly chosen node;
- least busy node;
- node matching required model/profile tag;
- preferred node with fallback.

Do not build a complex scheduler before one-node operation is reliable.

---

# 11. External renderer architecture: Kling

Kling integration is a later milestone.

Rules:
- verify current official API at implementation time;
- do not copy ComfyUI assumptions into the external renderer;
- expose only provider-supported capabilities;
- map normalized RenderRequest to current API request;
- capture task ID immediately;
- track provider status;
- ingest result into the same MediaAsset pipeline;
- preserve provider diagnostics and cost/quota failures safely.

Adding Kling should not require changing:
- Batch model
- TopicJob model except generic metadata
- LLM generation
- ElevenLabs generation
- storage service
- output library core UI
- central renderer interface

If it does, fix abstraction leaks.

---

# 12. UI information architecture

## Primary navigation

```text
Dashboard
Create
  - New Topic
Characters
Voice Profiles
Render Profiles
Workflows
Content
Library
Settings
  - Providers
  - Render Nodes
```

Potential simplification for V1: surface Workflows under Render Profiles.

## Dashboard
Show:
- content queued/rendering/failed/completed
- recent topics
- recent outputs
- configured render node health
- quick Create Topic action

## Characters
Actions:
- list/create/edit
- upload reference image
- select default voice
- configure basic prompt/persona settings

## Voice Profiles
Actions:
- select TTS provider
- enter voice ID/name
- configure supported voice settings
- optional test phrase generation
- keep API key in server settings, not profile form

## Workflows
Actions:
- import API workflow JSON
- inspect nodes
- bind semantic parameters
- validate
- version/update
- test configuration

## Render Profiles
Actions:
- select character
- select voice
- select renderer/provider
- select ComfyUI workflow when provider is ComfyUI
- choose render node
- edit prompt template
- edit defaults
- capability/schema-driven advanced parameters

## Create Topic

Topic input supports one topic. A Topic is the durable history container for
multiple numbered Content versions.

Controls:
- default render profile
- target duration
- auto-fit duration

Possible workflow:
- create Topic and Content 1
- review content
- generate more numbered Content versions
- generate multiple speech/video outputs until satisfied
- delete one Content version or its complete Topic history

V1 may allow one-click generation while still supporting inspection.

## Content detail
Show:
- topic
- current state/progress
- script
- TTS player + measured duration
- render profile/effective seed
- render attempts/history
- errors/retry
- final video
- Instagram metadata
- TikTok metadata

Actions:
- edit/regenerate script
- regenerate audio
- rerender video
- retry failed stage
- cancel when possible
- copy platform content

## Output Library
Card/list:
- video thumbnail/player
- character
- topic
- render profile/provider
- completion time

Detail:
- video
- speech
- hook
- IG title/description/hashtags
- TikTok title/description/hashtags
- download/copy actions
- rerender

---

# 13. API sketch

This is a planning contract, not immutable API documentation.

```text
GET    /api/v1/characters
POST   /api/v1/characters
GET    /api/v1/characters/{id}
PATCH  /api/v1/characters/{id}

GET    /api/v1/voice-profiles
POST   /api/v1/voice-profiles
GET    /api/v1/voice-profiles/{id}
PATCH  /api/v1/voice-profiles/{id}

GET    /api/v1/workflow-templates
POST   /api/v1/workflow-templates
GET    /api/v1/workflow-templates/{id}
PATCH  /api/v1/workflow-templates/{id}
POST   /api/v1/workflow-templates/{id}/validate

GET    /api/v1/render-nodes
POST   /api/v1/render-nodes
PATCH  /api/v1/render-nodes/{id}
POST   /api/v1/render-nodes/{id}/health-check

GET    /api/v1/render-profiles
POST   /api/v1/render-profiles
GET    /api/v1/render-profiles/{id}
PATCH  /api/v1/render-profiles/{id}

GET    /api/v1/topics
POST   /api/v1/topics
GET    /api/v1/topics/{id}
POST   /api/v1/topics/{id}/contents
DELETE /api/v1/topics/{id}
DELETE /api/v1/contents/{id}

GET    /api/v1/jobs
GET    /api/v1/jobs/{id}
POST   /api/v1/jobs/{id}/cancel
POST   /api/v1/jobs/{id}/retry
POST   /api/v1/jobs/{id}/regenerate-content
POST   /api/v1/jobs/{id}/regenerate-tts
POST   /api/v1/jobs/{id}/rerender

GET    /api/v1/assets/{id}
GET    /api/v1/library

WS     /api/v1/ws/jobs
```

Batch creation request concept:

```json
{
  "name": "Daily Elena Batch",
  "default_render_profile_id": "...",
  "target_duration_seconds": 30,
  "auto_fit_duration": true,
  "topics": [
    {
      "topic": "Things that look like laziness but aren't: burnout"
    },
    {
      "topic": "A reminder for overthinkers",
      "render_profile_id": "..."
    }
  ]
}
```

---

# 14. Queue/task design

Do not use one giant twenty-minute task.

Suggested Celery tasks:

```text
generate_job_content(job_id)
generate_job_tts(job_id)
fit_job_duration(job_id)
queue_render(job_id)
submit_render_attempt(render_attempt_id)
check_render_attempt(render_attempt_id)
ingest_render_output(render_attempt_id)
finalize_job(job_id)
```

Implementation can combine adjacent steps early if retry/idempotency remain clean.

## Idempotency
Examples:
- `generate_job_content` should not regenerate already accepted content unless forced/version mismatch.
- `generate_job_tts` should detect an existing successful TTS version for the exact script/settings.
- `submit_render_attempt` must not submit again if `external_job_id` is already recorded.
- `ingest_render_output` should not create duplicate MediaAssets for the same provider output/checksum.

---

# 15. Failure/retry policy

## Retriable examples
- network connection reset
- provider 5xx
- transient object storage failure
- provider throttling after delay
- temporary ComfyUI unavailability

## Usually not automatically retriable
- malformed workflow mapping
- invalid API key
- quota exhausted
- unsupported provider parameter
- content rejected by upstream provider
- invalid source image/audio

Use exponential backoff + jitter for transient retries.

Never create an infinite monitor/retry loop.

The UI should display whether retry is likely to help.

---

# 16. Security and cost controls

Before any public/multi-user release:
- authentication
- ownership/authorization
- generation rate limits
- quotas/budgets
- server-side API keys
- upload size/type limits
- SSRF protections around configurable URLs
- encrypted user-supplied provider credentials
- audit log for expensive generation actions
- signed/controlled asset access

V1 local/internal deployment can simplify auth, but code should not expose secrets in the client.

---

# 17. Development quality gates

API:
```bash
cd api
uv run ruff format --check .
uv run ruff check .
uv run mypy app
uv run pytest
```

Web:
```bash
cd web
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

E2E:
```bash
cd web
pnpm exec playwright test
```

Root Make targets should eventually wrap the standard checks.

---

# 18. Milestone status legend

- `NOT STARTED`
- `IN PROGRESS`
- `BLOCKED`
- `DONE`

Mark individual tasks with:
- `[ ]` pending
- `[x]` complete

Do not mark a milestone DONE until acceptance criteria pass.

---

# 19. Milestone 0 — Repository foundation

**Status: IN PROGRESS**

## Goal
Create a reproducible monorepo development environment.

## Tasks
- [ ] Initialize Git repository if needed. *(Deferred: the workspace exposes an empty read-only `.git` directory.)*
- [x] Add root `AGENTS.md` and `PLANS.md`.
- [x] Create `web/` Next.js TypeScript app.
- [x] Configure Tailwind and shadcn/ui.
- [x] Add TanStack Query.
- [x] Create `api/` Python project using `uv`.
- [x] Add FastAPI, Pydantic, SQLAlchemy, Alembic.
- [x] Add Celery + Redis integration.
- [x] Add Ruff + mypy + pytest.
- [x] Add PostgreSQL service to Compose.
- [x] Add Redis service to Compose.
- [x] Add optional MinIO service to Compose.
- [x] Add `.env.example`.
- [x] Add root Makefile with setup/lint/typecheck/test/dev targets.
- [x] Add API `/health` endpoint.
- [x] Add basic web shell that can reach API health.
- [x] Add CI workflow for lint/type/test/build.

## Acceptance criteria
- Fresh checkout can be bootstrapped from README.
- API starts.
- Web starts.
- PostgreSQL, Redis, and MinIO connectivity verified on alternate host ports; defaults remain configurable.
- `make lint`, `make typecheck`, and `make test` exist and pass.
- No secrets are committed.

Implementation note: the foundation checks pass. Milestone 0 remains `IN PROGRESS`
only because Git initialization cannot be performed against the read-only `.git`
placeholder supplied by this workspace.

---

# 20. Milestone 1 — Persistence and core domain

**Status: IN PROGRESS**

## Goal
Establish the database schema and CRUD foundations without provider logic.

## Tasks
- [x] SQLAlchemy base/session setup.
- [x] Alembic initial migration.
- [x] Character model/schema/service/routes.
- [x] VoiceProfile model/schema/service/routes.
- [ ] WorkflowTemplate model.
- [ ] WorkflowParameterBinding model.
- [x] RenderNode model.
- [x] RenderProfile model.
- [x] Batch model.
- [x] TopicJob model.
- [x] RenderAttempt model.
- [x] MediaAsset model.
- [x] Define enums/state constants centrally.
- [ ] Add pagination pattern.
- [ ] Add consistent API error format.
- [x] Add timestamps/UUID conventions.
- [x] Add database indexes for common status/batch/profile queries.
- [x] Add tests for CRUD and constraints.

## Acceptance criteria
- Migrations create a clean DB.
- Core entities can be created/read/updated.
- Invalid foreign keys/statuses are rejected.
- Provider-specific settings can be stored without core schema becoming LTX-specific.

---

# 21. Milestone 2 — Storage and media utilities

**Status: IN PROGRESS**

## Goal
Create a durable media layer before adding paid/provider integrations.

## Tasks
- [x] Define `StorageProvider`.
- [x] Implement local filesystem storage for tests/dev or S3 first.
- [ ] Implement S3-compatible provider.
- [ ] Configure MinIO locally if used.
- [ ] Create MediaAsset service.
- [ ] Add upload validation.
- [x] Add safe object-key generation.
- [ ] Add `ffprobe` wrapper.
- [ ] Read audio/video duration.
- [ ] Read video width/height/FPS when needed.
- [ ] Add thumbnail utility with ffmpeg.
- [ ] Add checksum/dedup helpers.
- [ ] Unit tests for media parsing using small fixtures.
- [ ] Storage fake for tests.

## Acceptance criteria
- API/worker can store and retrieve an image/audio/video fixture.
- Audio duration is measured reliably.
- No binary payload is stored in PostgreSQL.
- Media tests do not depend on external services.

---

# 22. Milestone 3 — LLM content provider

**Status: IN PROGRESS**

## Goal
Generate structured UGC content for one topic or multiple jobs.

## Tasks
- [x] Define `LLMProvider`.
- [x] Define Pydantic content result.
- [x] Implement OpenAI provider adapter.
- [x] Use structured output rather than text parsing.
- [x] Add configurable prompt template/version.
- [x] Generate:
  - [x] speech script
  - [x] hook
  - [x] Instagram title
  - [x] Instagram description
  - [x] Instagram hashtags
  - [x] TikTok title
  - [x] TikTok description
  - [x] TikTok hashtags
- [x] Persist model/provider/prompt-version metadata.
- [ ] Implement script length revision operation.
- [x] Build fake LLM provider.
- [x] Unit tests for validation and service behavior.
- [x] Add Celery content-generation task.
- [x] Retry only provider failures classified as transient, with bounded backoff.

## Acceptance criteria
- A fake provider can deterministically produce valid content in CI.
- With a configured OpenAI key, one topic can generate persisted structured content.
- Bad provider output produces a typed error, not partially parsed garbage.
- Core `ContentService` does not expose OpenAI SDK types.

---

# 23. Milestone 4 — ElevenLabs TTS and duration fitting

**Status: IN PROGRESS**

## Goal
Create voice profiles, synthesize speech, measure real duration, and fit target duration.

## Tasks
- [x] Define `TTSProvider`.
- [x] Implement ElevenLabs adapter.
- [x] Map voice ID.
- [x] Map speed.
- [x] Map stability.
- [x] Map similarity.
- [x] Map style exaggeration.
- [x] Support provider-model configuration.
- [x] Store generated audio via StorageProvider.
- [x] Persist per-generation ElevenLabs character cost and post-generation account allowance snapshots.
- [x] Keep generated speech previews in user-managed history until explicit deletion.
- [ ] Measure duration with ffprobe.
- [ ] Store effective TTS settings.
- [x] Add fake TTS provider with deterministic audio fixture.
- [ ] Implement bounded DurationFitService.
- [ ] Add duration target/tolerance/max attempts.
- [ ] Add LLM shorten/expand request.
- [ ] Preserve script/TTS revision history or version metadata.
- [x] Add Celery tasks.
- [x] Retry transient TTS failures and recover stale queued/generating voice previews.
- [x] Generate job speech from the RenderProfile VoiceProfile, persist the audio asset, and inject it into ComfyUI renders.
- [ ] Tests for too-short, acceptable, too-long, and max-attempt cases.

## Acceptance criteria
- A job produces playable TTS audio.
- Actual duration is persisted.
- A 30-second target uses measured audio duration rather than word count.
- Fit loop terminates deterministically.
- Worker retry does not repeatedly create paid TTS for the same accepted script/settings without reason.

---

# 24. Milestone 5 — ComfyUI workflow import and semantic binding

**Status: IN PROGRESS**

## Goal
Import arbitrary ComfyUI API workflows and bind UGC Creator parameters without hardcoded node IDs.

## Tasks
- [x] Workflow JSON upload/paste API.
- [x] Validate API workflow shape.
- [x] Persist source workflow/template version/checksum.
- [x] Parse nodes and inputs for UI inspection.
- [x] Build workflow detail UI.
- [x] Build semantic parameter binding editor.
- [x] Support `script`.
- [x] Support `source_image`.
- [x] Support `audio`.
- [x] Support `seed`.
- [x] Support `fps`.
- [x] Support `duration` and/or `frame_count`.
- [x] Support width/height.
- [x] Support `video_prompt`.
- [x] Support validated provider-defined semantic keys without a fixed core allowlist.
- [x] Validate node/input existence at save time.
- [x] Define binding value types/transforms.
- [x] Add prompt placeholder validation.
- [x] Implement workflow deep-copy + parameter application service.
- [ ] Add fixture LTX workflow for tests.
- [x] Test original workflow remains byte/structurally unchanged after render preparation.
- [x] Test missing/broken mappings.
- [x] Test placeholder replacement.
- [x] Update configured workflows in place while RenderAttempt snapshots preserve historical execution inputs.
- [x] Snapshot workflow JSON and bindings when an attempt is queued so later edits affect only future attempts.
- [x] Block deletion while a render profile references the workflow.
- [x] Persist workflow media outside PostgreSQL and store semantic media placeholders.

## Acceptance criteria
- Imported LTX API workflow can be configured from the UI.
- Node IDs are configuration data, not hardcoded in generic services.
- Preparing two different jobs from one template yields independent workflow copies.
- Invalid mappings fail before expensive rendering.

---

# 25. Milestone 6 — Generic ComfyUI renderer + LTX end-to-end

**Status: IN PROGRESS**

## Goal
Complete the first real end-to-end video render using LTX 2.3 through generic ComfyUI infrastructure.

## Tasks
- [x] Define normalized VideoRenderer contract.
- [x] Define RendererCapabilities.
- [ ] Implement renderer registry/factory.
- [x] Implement `ComfyUIRenderer`.
- [x] RenderNode CRUD + health check.
- [x] ComfyUI asset upload/reference support.
- [x] Submit workflow.
- [x] Persist `prompt_id` immediately.
- [x] Track queue/execution progress.
- [ ] WebSocket integration when available.
- [x] History/status fallback.
- [x] Output discovery.
- [x] Output download/copy into StorageProvider.
- [x] Cancellation if supported.
- [x] Normalize errors/status.
- [x] Guard duplicate submit after worker retry.
- [x] Atomically claim render submission before external calls and recover expired claims.
- [x] Reconcile uncertain ComfyUI submissions by persisted client ID and never auto-resubmit an unknown outcome.
- [x] Redeliver unacknowledged tasks after worker loss so claimed submissions always reach reconciliation.
- [x] Bound render monitoring with a configurable timeout.
- [x] Keep history-only progress explicitly indeterminate until WebSocket progress is implemented.
- [x] Make render finalization terminal/idempotent and ingest only video/GIF outputs.
- [x] Create RenderAttempt records.
- [x] Implement render submission/monitor/finalize Celery tasks.
- [ ] Configure an LTX 2.3 RenderProfile.
- [x] End-to-end integration test against fake ComfyUI.
- [ ] Optional real ComfyUI integration test.
- [x] Add final video to MediaAsset.

## Acceptance criteria
Given:
- character image,
- configured ElevenLabs voice,
- topic,
- LTX ComfyUI workflow/profile,

the application can:
1. generate structured content;
2. generate/fit TTS;
3. inject script/audio/image/settings;
4. submit LTX workflow;
5. display progress;
6. ingest final video;
7. show platform metadata.

Most importantly: the core pipeline contains no LTX-specific node IDs.

---

# 26. Milestone 7 — Topic creation and content history UI

**Status: IN PROGRESS**

## Goal
Turn the single-content pipeline into a Topic with repeatable numbered Content.

## Tasks
- [x] Create Topic page.
- [x] One durable Topic with stable Content numbering.
- [x] Default render profile.
- [x] Per-content render-profile override.
- [x] Default target duration.
- [x] Auto-fit toggle.
- [x] Create initial Content transactionally.
- [x] Generate and queue more Content.
- [x] Collapsible Topic history and Content details.
- [x] Aggregate Content counts.
- [ ] Job status/progress events.
- [ ] WebSocket subscription.
- [x] Polling fallback.
- [x] Retry failed content stage.
- [ ] Cancel queued/rendering job.
- [x] Preserve speech and render attempt history.
- [ ] Add filters by status.
- [x] E2E with fake providers.

## Acceptance criteria
- User can create a Topic and generate multiple stable Content versions.
- Every Content version can use or override the Topic's profile.
- UI updates while content moves through stages.
- One failed Content version does not destroy prior successful versions.
- Retry does not rerun successful earlier stages unnecessarily.

---

# 27. Milestone 8 — Output library and social content UX

**Status: IN PROGRESS**

## Goal
Make finished videos and metadata easy to review and use.

## Tasks
- [ ] Library page.
- [ ] Video thumbnails.
- [x] Video player.
- [ ] Search/filter by character/profile/provider/date/status.
- [ ] Job/output detail page.
- [x] Show final script.
- [x] Audio player.
- [ ] Measured duration.
- [x] Instagram title.
- [ ] Instagram hook.
- [ ] Instagram description.
- [ ] Instagram hashtags.
- [x] TikTok title.
- [ ] TikTok hook if separately generated.
- [ ] TikTok description.
- [ ] TikTok hashtags.
- [ ] Copy-to-clipboard buttons.
- [x] Video download route/signed URL.
- [x] Generate another Content version.
- [x] Regenerate TTS while preserving prior audio.
- [x] Rerender while preserving prior video.
- [x] Show render attempt history.
- [x] Delete Content with all related media.
- [x] Delete Topic with all Content and related media.
- [ ] Responsive design.

## Acceptance criteria
- A completed job is usable without accessing ComfyUI directly.
- Platform content can be copied independently.
- Rerendering creates a new attempt and preserves prior output.

---

# 28. Milestone 9 — Character/render-profile management polish

**Status: NOT STARTED**

## Goal
Make reusable influencer setup practical.

## Tasks
- [ ] Character reference image management.
- [ ] Character default voice.
- [ ] Voice test generation.
- [ ] Render profile duplication.
- [ ] Render profile preview summary.
- [ ] Prompt template editor.
- [ ] Capability-driven parameter editor.
- [ ] Seed modes:
  - [ ] fixed
  - [ ] random per job
  - [ ] manual override
- [ ] FPS/duration validation.
- [ ] Parameter schema validation.
- [ ] Profile activation/deactivation.
- [ ] Workflow version warning when profile references old version.
- [ ] Character/profile usage references before deletion.

## Acceptance criteria
- User can create several Elena scenes/profiles without duplicating voice configuration.
- UI exposes only parameters relevant to the selected renderer/profile.
- Profile duplication supports fast A/B setup.

---

# 29. Milestone 10 — WAN support through ComfyUI

**Status: NOT STARTED**

## Goal
Prove that the ComfyUI abstraction is genuinely model-neutral.

## Tasks
- [ ] Import a WAN API workflow as WorkflowTemplate.
- [ ] Bind semantic inputs.
- [ ] Define WAN-specific optional parameters only in profile schema/bindings.
- [ ] Create WAN RenderProfile.
- [ ] Render one existing topic/script/audio using WAN.
- [ ] Verify no changes required to ContentService.
- [ ] Verify no changes required to TTSService.
- [ ] Verify no LTX-specific logic added to core RenderService.
- [ ] Add WAN workflow fixture tests if distributable/appropriate.
- [ ] Document workflow-specific requirements.

## Acceptance criteria
- User can choose either LTX or WAN render profiles for the same topic.
- Both use `ComfyUIRenderer`.
- No separate WAN orchestration pipeline exists.
- Successful WAN output lands in the same output library.

This milestone is an architecture test. If it requires large core changes, correct the abstractions before calling it complete.

---

# 30. Milestone 11 — Multi-render comparison

**Status: NOT STARTED**

## Goal
Generate multiple video versions for the same content without regenerating content/TTS unnecessarily.

Example:

```text
Topic: A reminder for overthinkers

Render with:
[x] Elena — Shelf — LTX
[x] Elena — Shelf — WAN
[ ] Elena — Shelf — Kling
```

## Tasks
- [ ] Separate generated content/TTS version from render attempt cleanly.
- [ ] Allow multiple render profiles for one content job or create a parent content item + child renders.
- [ ] Reuse compatible audio asset.
- [ ] Create separate RenderAttempts.
- [ ] Comparison UI.
- [ ] Show provider/profile/seed/duration side by side.
- [ ] Preserve costs/provider metadata if available.

## Acceptance criteria
- One script/TTS can produce LTX and WAN outputs.
- Rendering an extra version does not automatically call the LLM/TTS again.
- Each output has independent attempt status/history.

Note: data-model refinement may be needed here. Record any change as a Decision Log entry/ADR.

---

# 31. Milestone 12 — Kling renderer

**Status: NOT STARTED**

## Goal
Add the first external video API without redesigning the core pipeline.

## Tasks
- [ ] Review current official Kling API/docs before coding.
- [ ] Define credentials/configuration.
- [ ] Implement `KlingRenderer`.
- [ ] Define capabilities.
- [ ] Define provider parameter schema.
- [ ] Map normalized RenderRequest to provider request.
- [ ] Submit.
- [ ] Persist task ID immediately.
- [ ] Poll or consume supported status mechanism.
- [ ] Normalize states/errors.
- [ ] Respect rate limits/backoff.
- [ ] Cancel if supported.
- [ ] Fetch output.
- [ ] Ingest to MediaAsset.
- [ ] Create Kling RenderProfile UI.
- [ ] Fake Kling adapter tests.
- [ ] Optional sandbox/integration test if provider supports it.
- [ ] Add comparison with local render profiles.

## Acceptance criteria
- Existing topic/content/TTS flow can render with Kling by changing render profile.
- Central orchestration does not contain Kling conditionals except provider registry/configuration.
- Kling output appears identically in the Library.
- Provider failure/quota/rate-limit errors are shown clearly.

---

# 32. Milestone 13 — Multiple ComfyUI GPU nodes

**Status: NOT STARTED**

## Goal
Use multiple GPU machines safely.

Potential nodes:
```text
GPU-1 / RTX 3090 / ComfyUI
GPU-2 / RTX 3060 / ComfyUI
future GPU node
```

## Tasks
- [ ] RenderNode health polling.
- [ ] Node tags/capabilities.
- [ ] Profile required tags.
- [ ] Explicit node selection.
- [ ] Simple least-active scheduler.
- [ ] Node concurrency limits.
- [ ] Offline detection.
- [ ] Safe rescheduling only before external submit.
- [ ] UI health/status.
- [ ] Metrics: queued/running by node.

## Acceptance criteria
- Jobs are routed only to compatible/enabled nodes.
- Offline node does not lose already persisted job context.
- Worker retry cannot submit the same attempt to two nodes accidentally.

---

# 33. Milestone 14 — Production hardening

**Status: NOT STARTED**

## Goal
Prepare for real multi-user or internet-exposed deployment.

## Tasks
- [ ] Authentication.
- [ ] Resource ownership.
- [ ] Authorization tests.
- [ ] Expensive-operation rate limits.
- [ ] Per-user quota/budget model if needed.
- [ ] Provider key encryption if user-managed.
- [ ] Upload scanning/limits.
- [x] SSRF protections for render-node config.
- [ ] CSRF/session protections as applicable.
- [ ] Secure signed asset delivery.
- [ ] Structured request/job logging.
- [ ] Health/readiness endpoints.
- [ ] Backup plan for PostgreSQL.
- [ ] Object-storage lifecycle/backup plan.
- [ ] Worker graceful shutdown.
- [ ] Stuck-job reconciliation.
- [ ] Provider timeout policies.
- [ ] Metrics/dashboard.
- [ ] Error tracking.
- [ ] Terms/content/compliance review before public influencer-generation use.

## Acceptance criteria
- Threat model reviewed.
- No provider secret reaches browser bundle/network responses.
- A worker/API restart does not corrupt job state.
- Stuck jobs can be identified/reconciled.
- Backups/restores are documented and tested.

---

# 34. Optional future capabilities

Not part of V1 unless explicitly promoted into a milestone.

## Content
- recurring content calendar
- topic ideation
- brand voice presets
- reusable CTA templates
- multi-language scripts
- script approval workflow
- platform-specific alternate cuts

## Media
- automatic subtitles/captions
- B-roll
- background music
- logo/watermark overlays
- crop/reframe variants
- video concatenation
- intro/outro templates
- automated thumbnails
- FFmpeg final-normalization pipeline

## Publishing
- Instagram publishing API where appropriate
- TikTok publishing API where appropriate
- scheduled publishing
- content calendar
- approval queue

Publishing credentials must be separate from render credentials.

## Analytics
- associate post URL/platform ID
- views
- retention
- likes/comments/shares
- compare topics/hooks/profiles/renderers
- feed performance back into content generation

## Provider expansion
- additional TTS providers
- additional LLM providers
- additional external video providers
- cloud ComfyUI providers
- image generation providers

---

# 35. Testing matrix

| Layer | Fake | Integration | Real paid/provider |
|---|---|---|---|
| LLM | required | OpenAI adapter mocked/contract | opt-in |
| TTS | required | ElevenLabs adapter mocked/contract | opt-in |
| Storage | required | MinIO/S3 local | optional |
| ComfyUI | required | fake HTTP/WS server | opt-in real GPU |
| Kling | required when added | mocked contract | opt-in |
| Database | real test PostgreSQL preferred | required | n/a |
| Web | mocked API + test backend | E2E fake providers | optional staging |

CI must not require paid provider credentials.

---

# 36. Seed/reproducibility policy

Render profile should support:
- fixed seed
- random seed
- per-job manual override

Persist the effective seed on RenderAttempt.

"Same seed" does not guarantee identical output when:
- workflow/model version changes;
- provider changes;
- GPU/kernel behavior differs;
- other sampling/settings differ.

Record enough effective parameters to reproduce the configuration, not to promise bit-identical output.

---

# 37. Workflow update policy

When a workflow template already used by jobs is edited:
- update the configured workflow record in place;
- existing attempts retain their workflow snapshot/version/checksum;
- render profiles keep referencing the same workflow ID;
- old attempts remain inspectable without exposing workflow edit history.

A small V1 may store workflow snapshots on RenderAttempt instead, but historical reproducibility must remain possible.

---

# 38. Provider capability policy

Capabilities have two jobs:
1. validate backend requests;
2. drive UI parameter visibility.

Examples:
- image input
- audio input
- native lip sync
- seed
- FPS
- arbitrary duration
- negative prompt
- camera control
- source video
- reference character image

Do not assume every video provider supports the same semantics.

Parameter schema may describe:
- type
- min/max
- enum options
- default
- advanced/basic grouping
- provider-specific help text

Backend is authoritative even if UI already validates.

---

# 39. Data snapshots and reproducibility

At render submission, persist/snapshot the effective values needed to explain the output:
- character/reference asset
- voice/TTS settings
- script version
- audio asset
- render profile
- workflow version/checksum or provider model/version
- prompt after template resolution
- effective render parameters
- seed
- renderer/provider
- render node
- external job ID

Do not rely solely on mutable current RenderProfile values to explain an old render.

---

# 40. Decision log

Append decisions here as implementation clarifies unknowns.

## 40.1 Batch persistence slice

- Batch creation persists a `Batch` and one `TopicJob` per non-empty topic.
- The API uses PostgreSQL through SQLAlchemy when `DATABASE_URL` is configured and
  an in-memory repository for isolated tests or dependency-free local health checks.
- The web app calls the API through a same-origin Next.js proxy, keeping the
  Docker-internal API URL out of browser code.

## 40.2 Configuration profiles

- Render profiles reference a Character and VoiceProfile while keeping the
  renderer provider, workflow reference, capabilities, and parameter schema as
  provider-neutral configuration.
- `renderer_provider` remains an extensible string so adding ComfyUI, WAN, or
  external renderers does not change the core profile model.
- VoiceProfiles are created and tuned independently, including normalized TTS
  settings and provider-specific display metadata. RenderProfiles attach an
  existing VoiceProfile by ID instead of duplicating voice settings during setup.
- Existing RenderProfiles may explicitly disconnect their VoiceProfile while being
  reconfigured. Creation still requires a voice, and disconnected profiles are
  incomplete and cannot be selected for batch generation.

## 40.3 Structured content generation

- Content generation is expressed through a provider-neutral `LLMProvider` and
  Pydantic result contract; the OpenAI Responses request and response shapes
  remain inside the OpenAI adapter.
- Structured Outputs with a strict JSON schema is used instead of parsing
  informal model prose.
- Content is persisted on `TopicJob` before later TTS/render stages, and the
  Celery task receives only the durable job UUID.
- Prompt text is edited in Settings, persisted server-side, and loaded by the
  content worker. Its version is derived from the saved prompt checksum;
  provider calls never run in browser code.

## 40.4 ComfyUI workflow execution

- ComfyUI workflows are stored as API-format JSON with explicit semantic
  bindings; generic services never assume universal node IDs.
- A RenderAttempt is persisted before queueing, snapshots the prepared workflow
  and effective values, and stores the ComfyUI prompt ID before monitoring.
- Render retries reuse active attempts and never resubmit after a prompt ID has
  been persisted. Completed outputs are copied into application storage and
  exposed through MediaAsset download routes.
- Workflow preparation validates the complete binding set, deep-copies the
  template, applies typed values, and rejects unknown placeholders before any
  renderer call.
- The ComfyUI adapter owns `/prompt`, `/history`, `/system_stats`, upload, and
  interrupt transport details behind the normalized `VideoRenderer` contract.
- The ComfyUI base URL is server-side configuration and defaults to the host
  gateway for local Docker development; LTX and WAN remain workflow/profile
  choices rather than renderer classes.

## 40.5 Configuration and media safety

- Editing a workflow updates the same configured WorkflowTemplate record and ID.
  Existing RenderAttempts remain reproducible from their persisted workflow
  snapshot, version, checksum, and effective values.
- Workflow deletion is rejected when a render profile still references the
  template, with a database foreign key enforcing the same invariant.
- Development workflow media is stored through a local StorageProvider-backed
  durable volume and workflows reference `{{SOURCE_IMAGE}}`/`{{AUDIO}}`
  placeholders rather than ComfyUI-local filenames.
- Render profile creation uses one transactional setup endpoint so a failed
  setup cannot leave a voice profile or character orphaned.

## 40.6 Per-job generation selections

- A TopicJob may select a VoiceProfile and WorkflowTemplate independently of its
  RenderProfile. Null selections inherit the profile defaults; explicit selections
  drive the next TTS or render attempt.
- Render attempts continue to snapshot the selected workflow. Changing a voice or
  render profile archives the current speech asset and returns generated content to
  the speech stage so audio from one voice is never mislabeled as another.
- User-uploaded render audio is stored as a job MediaAsset and replaces the active
  audio input without mutating the workflow template.
- Deleting a completed video removes its MediaAsset and returns a job with no other
  video output to `ready_to_render`; the completed RenderAttempt remains as history.

## 40.7 Topic and repeatable Content lifecycle

- The existing `Batch` table remains a compatibility persistence container but is
  presented as Topic in the V1 API and UI. The existing `TopicJob` is presented as
  one immutable-in-history Content version rather than introducing a parallel model.
- A Topic starts with Content 1. Generate More Content creates a new row with the
  next unique `content_number` and queues content generation without overwriting
  earlier scripts, speech, or render attempts.
- Speech and video may be generated repeatedly for one Content. Stored filenames
  use `{short-topic}_content{content-number}_{output-number}-audio.mp3` and the
  corresponding `-video.mp4` form.
- Deleting Content or Topic is rejected during active external work and removes all
  referenced media through `StorageProvider` before deleting database history. A
  Topic's only Content is removed by deleting the Topic so no unusable empty Topic
  history remains.
- Legacy `/batches` and `/jobs` routes remain available while new user-facing flows
  use `/topics` and `/contents`.

Format:

```text
YYYY-MM-DD — Decision title
Status: accepted | superseded
Decision:
Reason:
Consequences:
```

Initial decisions:

### 2026-08-06 — Provider-neutral renderer abstraction
**Status: accepted**

**Decision:** UGC Creator core uses a normalized VideoRenderer interface. ComfyUI and Kling are render providers. LTX/WAN are not hardcoded into core orchestration.

**Reason:** The product must support multiple local and external video-generation engines.

**Consequences:** Render-specific settings live in profiles, capability schemas, bindings, and adapters.

### 2026-08-06 — Generic ComfyUI renderer
**Status: accepted**

**Decision:** LTX and WAN use one `ComfyUIRenderer` unless future transport behavior proves a split necessary.

**Reason:** Both execute through ComfyUI workflow submission/status/output mechanics.

**Consequences:** ComfyUI node IDs must stay in workflow binding configuration.

### 2026-08-06 — Workflow templates are immutable during execution
**Status: accepted**

**Decision:** Each render deep-copies a stored workflow template and mutates the copy.

**Reason:** Batch jobs must not leak values into each other.

**Consequences:** Render preparation tests must prove the source template remains unchanged.

### 2026-08-08 — Logical workflows own immutable revisions
**Status: superseded**

**Decision:** WorkflowTemplate revisions share a stable logical workflow ID. The
main workflow list returns only the latest revision; older revisions remain
available through version history. Saving an edit advances connected render
profiles to the new revision while existing RenderAttempts retain their stored
workflow revision and snapshot.

**Reason:** Immutable records are required for reproducibility, but exposing every
revision as a separate workflow makes a normal save behave like a misleading
Save As operation.

**Consequences:** Revision creation, profile reassignment, list grouping, history,
and logical-workflow deletion are transactional backend responsibilities.

### 2026-08-08 — Workflow edits update in place
**Status: accepted**

**Decision:** The Update workflow action modifies the same WorkflowTemplate record
and keeps its ID. The product does not expose workflow revision history.

**Reason:** Users expect Update to change the selected workflow, not create a copy
or a hidden Save As revision.

**Consequences:** RenderAttempt snapshots and checksums preserve historical render
inputs. Editing a configured workflow affects future renders using that profile.

### 2026-08-06 — Frontend/backend split
**Status: accepted**

**Decision:** Next.js/TypeScript web UI + FastAPI/Python backend.

**Reason:** TypeScript provides a strong UI ecosystem while Python fits ComfyUI/media/AI orchestration.

### 2026-08-06 — Queue architecture
**Status: accepted**

**Decision:** Celery + Redis for V1 background jobs.

**Reason:** Video/TTS work is long-running and requires retryable persisted orchestration without adding heavier workflow infrastructure.

### 2026-08-08 — Provider retries are typed and bounded
**Status: accepted**

**Decision:** Provider adapters classify failures as retriable or permanent. Celery
tasks retry only transient failures with bounded exponential backoff. Voice preview
requests safely requeue stale work only when no provider call started; stale
generating work becomes an explicit unknown outcome.

**Reason:** HTTP adapters normalize network failures into domain exceptions, so task
retry policy must use those typed exceptions. Persisted in-progress records also need
a recovery path after worker crashes.

**Consequences:** Permanent and exhausted failures are persisted as failed; transient
TTS attempts return to queued while waiting for retry. Identical active previews remain
deduplicated until the stale timeout expires.

### 2026-08-08 — External provider calls require durable claims
**Status: accepted**

**Decision:** Workers atomically claim voice-preview synthesis and ComfyUI
submission in PostgreSQL before making an external call. Render claims use a
bounded lease, and attempts snapshot workflow JSON and bindings when queued.

**Reason:** A read-then-call check permits concurrent workers to duplicate paid
TTS or render submissions, while editing a workflow after queueing can otherwise
change the payload of an already accepted attempt.

**Consequences:** Only the claim winner calls the provider. Expired submissions
are reconciled or fail safely without automatic resubmission, and workflow edits
apply only to attempts queued after the edit.

### 2026-08-08 — Unknown provider outcomes require reconciliation
**Status: accepted**

**Decision:** A ComfyUI submission persists a stable client ID and submission
intent before `/prompt`. Recovery searches ComfyUI queue/history for that client
ID and never automatically resubmits when the outcome remains unknown.
ElevenLabs preview claims use ownership tokens; a stale generating preview is
marked failed with an explicit unknown-outcome message and requires a new user
request before retrying.

**Reason:** A worker can die after a provider accepts a request but before the
provider ID is persisted. A timeout alone cannot prove that retrying is safe.

**Consequences:** Unknown operations may require an explicit retry, favoring
duplicate-charge prevention over automatic recovery. Late workers cannot update
records after losing ownership. Render completion uses terminal compare-and-set
plus one video asset per attempt so repeated monitors cannot regress or duplicate
the completed result. Celery acknowledges tasks only after execution and rejects
worker-lost deliveries back to the broker; prefetch is one to limit reserved
long-running work. A transport failure or malformed success response from
ComfyUI `/prompt` keeps the attempt in `submitting_render` and schedules
client-ID reconciliation instead of marking the attempt failed. Redelivered TTS
tasks schedule a check at claim expiry; expired claims become an explicit
unknown-outcome failure without automatically repeating the paid call.
ElevenLabs connect failures and definite retriable HTTP responses may retry, but
read/write/ambiguous network failures become non-retriable unknown outcomes.
Render preparation that outlives its submission claim schedules an immediate
reconciliation delivery rather than acknowledging into a stuck state.

### 2026-08-08 — Render-node URLs are deny-by-default
**Status: accepted**

**Decision:** Render-node URLs are restricted to HTTP(S), reject credentials and
private/reserved destinations after DNS resolution, and permit intentional local
development hosts only through `COMFYUI_ALLOWED_HOSTS`.

**Reason:** Server-side render health and submission requests must not provide an
SSRF path to loopback, metadata, or internal network services.

**Consequences:** Operators must explicitly allow each trusted private ComfyUI
hostname. The adapter revalidates immediately before real outbound requests.

### 2026-08-06 — PostgreSQL
**Status: accepted**

**Decision:** PostgreSQL is the primary relational database, with JSONB for provider-specific settings.

**Reason:** Most domain relationships are relational while render/provider configuration needs bounded flexibility.

### 2026-08-06 — Media storage abstraction
**Status: accepted**

**Decision:** Binary media is stored via StorageProvider; PostgreSQL stores metadata/references.

**Reason:** Videos/audio/images are not appropriate DB blobs and must move between local/S3-compatible storage.

### 2026-08-06 — Actual TTS duration drives fitting
**Status: accepted**

**Decision:** Use ffprobe-measured audio duration and a bounded regenerate/revise loop.

**Reason:** Word count and requested script duration do not reliably match synthesized speech duration.

---

# 41. Open questions

Resolve only when the related milestone needs the answer.

- [ ] Authentication approach for first non-local deployment.
- [ ] Local filesystem vs MinIO as default developer storage.
- [ ] Whether content review is mandatory before TTS/render or optional.
- [ ] Exact OpenAI model default.
- [ ] Exact ElevenLabs TTS model default.
- [ ] Default duration tolerance and max fit attempts.
- [x] For V1, one TopicJob is one numbered Content version and owns multiple speech
  and RenderAttempt outputs. Revisit a ContentItem/RenderJob split only if future
  comparison requirements cannot be represented by existing attempt history.
- [ ] How imported ComfyUI workflow files/media references are normalized across remote GPU nodes.
- [ ] Whether ComfyUI WebSocket progress is proxied live or normalized by worker/event publication only.
- [ ] Authentication/encryption strategy for user-supplied provider keys.
- [ ] Current Kling API capabilities/limits when Milestone 12 starts.

Do not block early milestones on questions that are intentionally deferred.

---

# 42. Current recommended build order

For the first usable product, execute in this order:

```text
M0 Repository foundation
  ->
M1 Core persistence
  ->
M2 Storage/media
  ->
M3 LLM content
  ->
M4 ElevenLabs + duration fit
  ->
M5 Workflow import/binding
  ->
M6 ComfyUI + LTX end-to-end
  ->
M7 Batch UI/job queue
  ->
M8 Output library
  ->
M9 Profile polish
```

Then validate extensibility:

```text
M10 WAN through same ComfyUI renderer
  ->
M11 multi-render comparison
  ->
M12 Kling external renderer
```

Then scale/harden:

```text
M13 multiple GPU nodes
  ->
M14 production hardening
```

---

# 43. First Codex task recommendation

After these files are placed at repository root, the first Codex implementation task should be narrowly scoped to **Milestone 0**.

Suggested task:

```text
Read AGENTS.md and PLANS.md. Implement Milestone 0 only.

Create the UGC Creator monorepo foundation with:
- Next.js + TypeScript web app using pnpm;
- FastAPI Python API using uv;
- PostgreSQL + Redis in compose.yaml;
- Celery worker wiring;
- optional MinIO service/config scaffolding;
- Ruff, mypy, pytest;
- frontend lint/typecheck/test setup;
- root Makefile;
- .env.example;
- health endpoint and a minimal web health check;
- README setup instructions.

Do not implement provider integrations, domain CRUD, or rendering yet.
Run all applicable checks.
Update PLANS.md checkboxes/status based only on work actually completed.
```

This keeps Codex from trying to build the entire product in one uncontrolled patch.

---

# 44. V1 success definition

V1 is successful when a user can:

1. Create Elena or another Character.
2. Configure an ElevenLabs VoiceProfile.
3. Import a ComfyUI LTX API workflow.
4. Bind image/audio/script/seed/FPS/duration and other required fields.
5. Create an LTX RenderProfile.
6. Paste one or many topics.
7. Generate structured speech + IG/TikTok metadata.
8. Generate TTS using the selected voice settings.
9. Automatically measure and fit approximately 30 seconds.
10. Submit each video asynchronously to ComfyUI.
11. Watch job status/progress.
12. Receive a finished video in the UGC Creator Library.
13. Copy the Instagram/TikTok text.
14. Retry a failed stage without unnecessarily repeating successful paid work.
15. Rerender while preserving previous attempts.

The implementation is architecturally successful when the same system can then add WAN through a new workflow/profile and Kling through a renderer adapter without rewriting the core content/TTS/job pipeline.

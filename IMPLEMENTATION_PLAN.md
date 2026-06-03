# Podcast Knowledge Engine — Implementation Plan

> Read alongside `ARCHITECTURE.md`. This document tells you **what to build, in what order, and why**.
> Each phase produces something runnable. Never more than one phase "in flight" at a time.

## Before You Start

This is the implementation plan for the **Podcast Knowledge Engine** — a local-first RAG application that ingests podcast feeds, transcribes and diarizes episodes, and exposes a freeform chat interface for querying podcast content. The full system design, schema, API reference, and configuration are in `ARCHITECTURE.md`. Read that document first and keep it open alongside this one.

**Tech stack:** Python 3.12 + uv, FastAPI, SQLAlchemy (async), PostgreSQL + pgvector, React + Vite + TypeScript, OpenTelemetry + Phoenix. All LLM and embedding calls use an OpenAI-compatible client pointed at a configurable endpoint — local (Ollama, llama.cpp) or cloud.

**Key design constraints to carry through every phase:**
- `speaker_id` is the stable link between segments/chunks and speaker metadata. In v1 (no diarization), all segments are written with `speaker_id = 'UNKNOWN'`. If `SpeakerResolver` infers exactly one speaker, that row is promoted to `speaker_id = 'SPEAKER_00'`. Display names live only in `episode_speakers.display_name` and are resolved via join at read time. Never store display names in `transcript_segments` or `chunks`.
- Speaker diarization is deferred to Future Scope 1.5. CPU/local Pyannote is impractical on non-CUDA hardware. The `UNKNOWN` sentinel is intentional — it distinguishes un-diarized episodes from single-speaker episodes where `SpeakerResolver` found a name.
- The DB is the source of truth for pipeline status. SSE streams read from the DB — they are not a direct pipe from the background worker.
- CPU-bound work (Whisper) must run in a `ProcessPoolExecutor`. Calling it directly blocks the asyncio event loop and freezes the API.
- All injectable dependencies (DB session, LLM client, embedding client, IngestionQueue) are wired through `src/api/dependencies.py` and injected via FastAPI's `Depends()`. Do not instantiate them inline in route handlers.

---

## Guiding Principles

- **Vertical slices over horizontal layers** — get one thing working end-to-end before generalizing
- **Test as you go** — each phase has explicit test targets; don't skip them
- **No premature abstraction** — build the concrete thing first, extract the interface when you have two implementations
- **Commit at phase boundaries** — each phase = one meaningful git tag
- **Agent-friendly tasks are marked** — sections where Claude Code / a coding agent can do the heavy lifting are noted with 🤖

---

## Phase Overview

| Phase | What You Build | Runnable At End |
|-------|---------------|-----------------|
| 0 | Project scaffold, tooling, DB | `GET /health` returns 200 |
| 1 | RSS feed ingestion + IngestionQueue | Feed + episodes in DB; queue abstraction in place |
| 2 | Audio download + transcription pipeline | Episode transcript in DB via SSE-tracked job |
| 3 | Speaker inference + naming API | LLM infers host name with confidence; pipeline runs straight to chunking |
| 4 | Chunking + embedding | Chunks with vectors in pgvector; speaker_id linked |
| 5 | Basic RAG query | Single-turn Q&A over transcript content |
| 6 | Tool-calling query engine | Multi-turn chat with conditional retrieval |
| 7 | Frontend — feeds + episodes + speaker naming | Full ingestion flow in UI with SSE progress |
| 8 | Frontend — chat interface | Full product usable end-to-end |
| 9 | Observability | Phoenix traces on all LLM + retrieval + inference calls |
| 10 | Polish, docs, demo prep | Shippable |

---

## Phase 0 — Scaffold and Infrastructure

**Goal:** Runnable project skeleton. A developer can clone, configure, and hit a health endpoint.

### Tasks

#### 0.1 Repository structure
Create the directory layout from `ARCHITECTURE.md` section 6.

```bash
mkdir -p backend/src/{api/{routers,middleware},llm,ingestion,transcription,storage,query,models,telemetry}
mkdir -p backend/tests/{unit,integration,fixtures}
mkdir -p frontend/src/{components,pages,hooks,api}
mkdir -p transcription-service
touch backend/src/{api,llm,ingestion,transcription,storage,query,models,telemetry}/__init__.py
```

#### 0.2 Backend tooling
```bash
cd backend
uv init
uv add fastapi uvicorn[standard] sqlalchemy[asyncio] asyncpg alembic \
       pydantic-settings python-dotenv httpx feedparser \
       pgvector openai tiktoken sse-starlette \
       pytest pytest-asyncio pytest-cov
```

`pyproject.toml` should define:
- `[tool.pytest.ini_options]` with `asyncio_mode = "auto"`
- Scripts: `dev`, `test`, `migrate`

#### 0.3 LLM and Embedding Protocols (`src/llm/base.py` + `src/llm/openai.py`) 🤖
Define `LLMClient` and `EmbeddingClient` Protocols before anything else references them. The OpenAI SDK is used only in `openai.py` — all business logic receives the Protocol.

```python
# src/llm/base.py
@dataclass
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict

@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    finish_reason: str
    usage: TokenUsage

class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_format: dict | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse: ...

class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

`OpenAILLMClient` and `OpenAIEmbeddingClient` in `openai.py` are thin wrappers over `AsyncOpenAI`. `MockLLMClient` and `MockEmbeddingClient` live in `tests/` for use in unit and integration tests.

#### 0.4 Configuration (`src/config.py`) 🤖
Pydantic-settings `Settings` class covering every `.env` variable from `ARCHITECTURE.md` section 4.

```python
class Settings(BaseSettings):
    database_url: str
    llm_base_url: str
    llm_model_name: str
    llm_api_key: str = "none"
    embedding_base_url: str = ""
    embedding_model_name: str = "nomic-embed-text"
    embedding_dimensions: int = 768
    transcription_backend: str = "local"
    transcription_service_url: str = "http://localhost:8001"
    huggingface_token: str = ""
    whisper_model_size: str = "medium"
    speaker_inference_window_ms: int = 900_000
    phoenix_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    audio_storage_path: str = "./data/audio"
    max_concurrent_ingestions: int = 2
    chunk_size_tokens: int = 256
    chunk_overlap_tokens: int = 32
    topic_similarity_threshold: float = 0.75
    auto_chunk_after_naming: bool = True
    demo_auth_enabled: bool = False
    demo_username: str = "demo"
    demo_password: str = "changeme"
    log_level: str = "INFO"
    model_config = SettingsConfigDict(env_file=".env")
```

#### 0.5 Database models (`src/models/db.py`) 🤖
SQLAlchemy async models for all tables from `ARCHITECTURE.md` section 3.9.

Key points:
- UUID primary keys throughout
- `transcript_segments` and `chunks` have `speaker_id` (TEXT), NOT `display_name`
- `episode_speakers` is the sole location of `display_name`, `name_inferred`, `name_confirmed`
- `episodes` has `pipeline_status`, `pipeline_stage`, `pipeline_progress`, `ingestion_job_id`
- All cascade deletes defined on foreign keys

#### 0.6 Alembic setup
```bash
uv run alembic init alembic
# Configure alembic/env.py for async engine
uv run alembic revision --autogenerate -m "initial schema"
uv run alembic upgrade head
```

#### 0.7 Dependency injection (`src/api/dependencies.py`)
This file is the wiring layer for the entire app. Every shared resource is defined here and injected via `Depends()` in route handlers. Build this in Phase 0 so every subsequent phase uses it consistently.

```python
# Provides an async DB session per request
async def get_db() -> AsyncGenerator[AsyncSession, None]: ...

# Provides the LLMClient (OpenAILLMClient pointed at LLM_BASE_URL)
# In tests: inject MockLLMClient — callers never reference the OpenAI SDK directly
def get_llm_client() -> LLMClient: ...

# Provides the EmbeddingClient (OpenAIEmbeddingClient pointed at EMBEDDING_BASE_URL)
def get_embedding_client() -> EmbeddingClient: ...

# Provides the IngestionQueue singleton (created in app lifespan)
def get_ingestion_queue(request: Request) -> IngestionQueue: ...

# Provides the TranscriptionService (local or remote, based on TRANSCRIPTION_BACKEND)
def get_transcription_service() -> TranscriptionService: ...

# Provides the VectorStore (PgvectorStore v1; swap to Qdrant/Pinecone here)
def get_vector_store() -> VectorStore: ...

# Provides the SessionStore singleton (InMemorySessionStore v1)
def get_session_store(request: Request) -> SessionStore: ...

# Provides PipelineStatusService (single place for all pipeline status writes)
def get_pipeline_status_service(db: AsyncSession = Depends(get_db)) -> PipelineStatusService: ...
```

Usage in route handlers:
```python
@router.post("/episodes/{episode_id}/ingest")
async def ingest(
    episode_id: UUID,
    db: AsyncSession = Depends(get_db),
    queue: IngestionQueue = Depends(get_ingestion_queue),
    transcription_svc: TranscriptionService = Depends(get_transcription_service),
): ...
```

Swapping any implementation requires changing one function in `dependencies.py`. No route handlers or business logic change.

#### 0.8 FastAPI app (`src/api/main.py`)
- Lifespan: DB engine, telemetry init, `IngestionQueue` singleton stored on `app.state`
- CORS middleware (localhost:3000)
- Mount routers (stubs for now)
- Register `BasicAuthMiddleware` (bypassed when `DEMO_AUTH_ENABLED=false`)

#### 0.9 Health endpoints
```
GET /api/v1/health       → { status: "ok", version: "0.1.0" }
GET /api/v1/health/deep  → { db: "ok", llm: "ok|error", embedding: "ok|error" }
```
Deep health: real DB query + minimal LLM ping. Use throughout development to verify config.

#### 0.10 Docker Compose (dev)
`docker-compose.dev.yml`: DB service only.
```bash
docker compose -f docker-compose.dev.yml up -d
uv run alembic upgrade head
uv run uvicorn src.api.main:app --reload
curl http://localhost:8000/api/v1/health
```

#### 0.11 `.env.example`
All keys with placeholder values and inline comments. Commit this. Never commit `.env`.

#### 0.12 Create `tests/fixtures/sample_transcript.json` now
This fixture is used by Phases 2, 3, and 4. Create it in Phase 0 so it's ready when needed.

```json
{
  "segments": [
    {"speaker_id": "SPEAKER_00", "text": "Welcome to the show. I'm Lex Fridman and today I have a very special guest.", "start_ms": 0, "end_ms": 5200},
    {"speaker_id": "SPEAKER_01", "text": "Thanks for having me, Lex. I'm Jensen Huang, CEO of NVIDIA.", "start_ms": 5400, "end_ms": 9800},
    {"speaker_id": "SPEAKER_00", "text": "Jensen, let's talk about the future of AI and what NVIDIA is building.", "start_ms": 10200, "end_ms": 14500}
  ],
  "language": "en",
  "source": "whisper_local"
}
```
Make the real version realistic: 2 speakers, 20+ segments, intro that mentions names clearly, varied timestamps throughout, mix of short and long turns.

Also create `tests/fixtures/sample_feed.xml` — valid RSS with 3 episodes, one with a `<podcast:transcript>` tag, varied duration formats (`HH:MM:SS`, `MM:SS`, raw seconds).

### Phase 0 Done When
- `GET /health` → 200
- `GET /health/deep` → DB connected, LLM reachable (if configured)
- `LLMClient` and `EmbeddingClient` Protocols defined in `src/llm/base.py`
- `dependencies.py` wires all providers: DB, LLM, embedding, queue, transcription, vector store, session store, status service
- Both fixture files exist in `tests/fixtures/`
- Git tag: `v0.1.0-scaffold`

---

## Phase 1 — RSS Feed Ingestion + Ingestion Queue

**Goal:** Add a podcast feed by URL. See episodes listed. Queue abstraction in place before any long-running work begins.

### Tasks

#### 1.1 Pydantic schemas (`src/models/schemas.py`) 🤖
Request/response schemas for feeds and episodes. Separate from DB models.

```python
class AddFeedRequest(BaseModel):
    rss_url: HttpUrl

class FeedResponse(BaseModel):
    id: UUID
    rss_url: str
    title: str | None
    description: str | None
    episode_count: int
    created_at: datetime

class EpisodeResponse(BaseModel):
    id: UUID
    feed_id: UUID
    title: str | None
    published_at: datetime | None
    duration_seconds: int | None
    pipeline_status: str
    pipeline_stage: str | None
    pipeline_progress: float | None
    audio_url: str | None

class PipelineStatusUpdate(BaseModel):
    status: str
    stage: str | None = None
    progress: float | None = None
    position: int | None = None     # queue position when QUEUED
    error: str | None = None
```

#### 1.2 RSS parser (`src/ingestion/rss_parser.py`)
Use `feedparser`. Extract per episode:
- `guid`, `title`, `description`, `published_at`
- `audio_url` (enclosure URL)
- `duration_seconds` — handle `HH:MM:SS`, `MM:SS`, raw seconds
- `transcript_url` — from `<podcast:transcript>` tag if present

#### 1.3 Feed service (`src/ingestion/feed_service.py`)
```python
async def add_feed(rss_url: str, db: AsyncSession) -> Feed
async def refresh_feed(feed_id: UUID, db: AsyncSession) -> list[Episode]   # new guids only
async def list_feeds(db: AsyncSession) -> list[Feed]
async def get_feed(feed_id: UUID, db: AsyncSession) -> Feed
async def delete_feed(feed_id: UUID, db: AsyncSession) -> None
```

`add_feed`: parse → upsert feed → upsert episodes (ON CONFLICT guid DO NOTHING).

#### 1.4 IngestionQueue (`src/ingestion/queue.py`) 🤖

**Protocol:**
```python
class IngestionQueue(Protocol):
    async def enqueue(self, episode_id: UUID, job_args: dict) -> str: ...
    async def get_status(self, job_id: str) -> JobStatus: ...
    async def get_position(self, job_id: str) -> int: ...
    async def cancel(self, job_id: str) -> bool: ...
```

**v1 implementation — `BackgroundTaskQueue`:**
```python
class BackgroundTaskQueue:
    def __init__(self, max_concurrent: int):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._jobs: dict[str, JobRecord] = {}
        self._queue: list[str] = []          # ordered list of job_ids

    async def enqueue(self, episode_id: UUID, job_args: dict) -> str:
        job_id = str(uuid4())
        self._jobs[job_id] = JobRecord(status=JobStatus.QUEUED, episode_id=episode_id)
        self._queue.append(job_id)
        asyncio.create_task(self._run(job_id, episode_id, job_args))
        return job_id

    async def _run(self, job_id: str, episode_id: UUID, job_args: dict):
        async with self._semaphore:           # blocks here if at capacity
            self._jobs[job_id].status = JobStatus.RUNNING
            self._queue.remove(job_id)
            await ingest_episode(episode_id, **job_args)

    async def get_position(self, job_id: str) -> int:
        try:
            return self._queue.index(job_id) + 1
        except ValueError:
            return 0
```

Queue singleton created in FastAPI lifespan, injected via dependency.

#### 1.5 Routers
```
POST   /api/v1/feeds
GET    /api/v1/feeds
GET    /api/v1/feeds/{feed_id}
DELETE /api/v1/feeds/{feed_id}
POST   /api/v1/feeds/{feed_id}/refresh
GET    /api/v1/feeds/{feed_id}/episodes
GET    /api/v1/episodes/{episode_id}
GET    /api/v1/episodes/{episode_id}/status         (polling — always available)
```

#### 1.6 Tests
```python
# tests/unit/test_rss_parser.py  (fixture: sample_feed.xml)
def test_parse_feed_extracts_title()
def test_parse_episodes_extracts_guid()
def test_parse_duration_hhmmss()
def test_parse_duration_raw_seconds()
def test_parse_transcript_url_tag()

# tests/unit/test_queue.py
async def test_enqueue_returns_job_id()
async def test_queue_position_reported()
async def test_semaphore_limits_concurrency()
async def test_queue_satisfies_protocol()

# tests/integration/test_feeds.py
async def test_add_feed_creates_episodes()
async def test_refresh_adds_only_new_episodes()
async def test_delete_feed_cascades()
```

**Create fixture now:** `tests/fixtures/sample_feed.xml` — valid RSS with 3 episodes, one with `podcast:transcript` tag, various duration formats.

### Phase 1 Done When
- `POST /api/v1/feeds` creates feed + episodes with `pipeline_status: PENDING`
- `GET /api/v1/feeds/{id}/episodes` returns episode list
- Queue protocol + BackgroundTaskQueue implemented and tested
- Git tag: `v0.1.1-feeds`

---

## Phase 2 — Audio Download + Transcription

**Goal:** Trigger ingestion. Status streams via SSE. Transcript lands in DB.

> **Implementation note:** Diarization is deferred to Future Scope 1.5.
> CPU/local diarization via Pyannote is impractical on non-CUDA hardware.
> In v1, all transcript segments are written with `speaker_id = 'UNKNOWN'`.
> `SpeakerResolver` (Phase 3) may promote this to `SPEAKER_00` if it infers
> a single host name. The `UNKNOWN` sentinel is intentional — it distinguishes
> un-diarized episodes from confirmed single-speaker episodes.

### Tasks

#### 2.1 SSE status stream (`src/api/routers/episodes.py`)
The `IngestionQueue` is built in Phase 1 (`src/ingestion/queue.py`) and injected via `Depends(get_ingestion_queue)` from `dependencies.py`. The SSE endpoint reads pipeline status from the DB independently of the running background job — it does not receive updates directly from the worker.
```python
from sse_starlette.sse import EventSourceResponse

@router.get("/{episode_id}/status/stream")
async def stream_status(episode_id: UUID, db: AsyncSession, queue: IngestionQueue):
    async def generator():
        while True:
            episode = await get_episode(episode_id, db)
            update = PipelineStatusUpdate(
                status=episode.pipeline_status,
                stage=episode.pipeline_stage,
                progress=episode.pipeline_progress,
                position=await queue.get_position(episode.ingestion_job_id) if episode.ingestion_job_id else None
            )
            yield {"data": update.model_dump_json()}
            if episode.pipeline_status in ("READY", "ERROR"):
                break
            await asyncio.sleep(2)
    return EventSourceResponse(generator())
```

#### 2.2 Transcription interface (`src/transcription/base.py`)
```python
@dataclass
class TranscriptSegment:
    speaker_id: str         # "SPEAKER_00"
    text: str
    start_ms: int
    end_ms: int

@dataclass
class TranscriptResult:
    segments: list[TranscriptSegment]
    language: str
    source: str             # "whisper_local" | "remote" | "rss_provided"

class TranscriptionService(Protocol):
    async def transcribe(
        self,
        audio_path: str,
        speaker_count_hint: int | None = None,
        language: str = "en"
    ) -> TranscriptResult: ...
```

#### 2.3 Audio downloader (`src/ingestion/audio_downloader.py`)
- `httpx.AsyncClient` streaming download
- Store to `AUDIO_STORAGE_PATH/{episode_id}.{ext}`
- Update `pipeline_status=DOWNLOADING`, `pipeline_progress` during download

#### 2.4 Local transcription service (`src/transcription/local.py`) 🤖
```bash
uv add faster-whisper
# mlx-whisper is optional for Apple Silicon: uv add mlx-whisper
```

Steps:
1. Whisper → transcript segments
2. Assign `speaker_id = 'UNKNOWN'` to all segments — diarization is deferred
3. Return `TranscriptSegment` list

Pyannote diarization is not invoked in v1. Run Whisper in `asyncio.get_running_loop().run_in_executor(None, ...)` — CPU-bound, must not block event loop.

#### 2.5 Remote transcription service (`src/transcription/remote.py`)
HTTP client POSTing audio to `TRANSCRIPTION_SERVICE_URL`. The remote service
owns both transcription and diarization — `DIARIZATION_MODEL` is ignored when
`TRANSCRIPTION_BACKEND=remote`.

**Deferred to align with remote diarization work (see FUTURE_SCOPE.md 1.5).**
Current implementation is a stub that satisfies the Protocol but is untested
against a real endpoint. Concrete remote backends to implement:

- Generic sidecar (Docker, same contract as local pipeline)
- OpenAI Whisper API (optional speaker diarization via response format)
- Cloud GPU providers (RunPod, Modal) running Whisper + Pyannote

When implementing a specific remote backend, normalise its response format
into `TranscriptResult` inside `RemoteTranscriptionService` — the pipeline
and Protocol are unchanged.

#### 2.6 RSS transcript shortcut
If `episode.transcript_url` is set:
- Download VTT/SRT file
- Parse into `TranscriptSegment` list with `speaker_id = 'UNKNOWN'`
- Proceed without audio download or Whisper
- User can override via reingest endpoint

#### 2.7 Transcript storage (`src/ingestion/transcript_store.py`)
Save segments to `transcript_segments` table — `speaker_id = 'UNKNOWN'` for all segments (no diarization in v1), no `display_name`.
Upsert one row into `episode_speakers` via `SpeakerStore` (`src/ingestion/speaker_store.py`) — `speaker_id='UNKNOWN'`, `display_name=NULL`, both flags false.
Keep these as separate services: `TranscriptStore` owns segment rows, `SpeakerStore` owns `episode_speakers` rows.

#### 2.8 Ingestion orchestrator (`src/ingestion/pipeline.py`)
`pipeline.py` is a thin orchestrator — it sequences stages and manages status transitions via `PipelineStatusService`. No business logic lives here.

```python
async def ingest_episode(
    episode_id: UUID,
    job_args: dict,
    services: PipelineServices,
) -> None:
    try:
        await services.status.set(episode_id, "DOWNLOADING")
        audio_path = await services.downloader.download(episode)

        await services.status.set(episode_id, "TRANSCRIBING")
        transcript = await services.transcription.transcribe(
            audio_path, speaker_count_hint=job_args.get("speaker_count_hint")
        )
        await services.transcript_store.save(episode_id, transcript)
        await services.speaker_store.initialize_from_transcript(episode_id, transcript)
        # All segments written with speaker_id = 'UNKNOWN'

        await services.status.set(episode_id, "INFERRING_SPEAKERS")
        result = await services.speaker_resolver.infer(transcript.segments)
        await services.speaker_store.save_inferred(episode_id, result)
        # If one name found: UNKNOWN → SPEAKER_00, display_name set, pipeline continues
        # If none found: UNKNOWN stays, pipeline continues — not an error

        await services.status.set(episode_id, "CHUNKING")
        segments = await services.transcript_store.get_segments(episode_id)
        chunks = await services.chunker.chunk(segments)

        await services.status.set(episode_id, "EMBEDDING")
        embedded = await services.embedder.embed(chunks)
        await services.vector_store.upsert(embedded)

        await services.status.set(episode_id, "READY")
    except Exception as e:
        await services.status.set(episode_id, "ERROR", error=str(e))
        raise
```

`PipelineServices` is a dataclass of all injected services — see `ARCHITECTURE.md` section 3.4. Note that chunking and embedding are now part of the same job, not a separate enqueued job.

#### 2.9 Ingest endpoint
```
POST /api/v1/episodes/{episode_id}/ingest
Body: { "speaker_count_hint": 2 }
→ { "status": "accepted", "job_id": "...", "queue_position": 1 }
```

#### 2.10 Tests
```python
# tests/unit/test_pipeline.py  (fixture: sample_transcript.json)
async def test_ingest_stores_segments_with_unknown_speaker_id()
async def test_ingest_creates_single_unknown_episode_speakers_row()
async def test_display_name_not_stored_in_segments()
async def test_status_transitions_correctly()
async def test_error_stored_on_failure()

# tests/unit/test_transcription_interface.py
def test_local_satisfies_protocol()
def test_remote_satisfies_protocol()
```

**Note on fixture:** `tests/fixtures/sample_transcript.json` was created in Phase 0. Use it here to test the pipeline without running real Whisper or Pyannote.

### Phase 2 Done When
- `POST /ingest` → queued, SSE streams stage transitions through to READY
- Transcript segments in DB with `speaker_id = 'UNKNOWN'` (no display_name)
- `episode_speakers` row created with `speaker_id='UNKNOWN'`, null display_name
- All tests pass using fixture (no real Whisper required)
- Git tag: `v0.1.2-transcription`

---

## Phase 3 — Speaker Inference

**Goal:** LLM infers host name from intro text with a confidence score. Result pre-populates `episode_speakers`. Pipeline runs straight to chunking — no pause for user input. Speaker names can be updated anytime via API.

**Context:** Diarization is deferred (Future Scope 1.5). All transcript segments arrive from Phase 2 with `speaker_id = 'UNKNOWN'`. This phase attempts to identify a single host name from the intro window. Multi-speaker episodes remain `UNKNOWN` until diarization is available — this is expected and correct, not an error state.

### Tasks

#### 3.1 `InferredSpeaker` dataclass (`src/ingestion/speaker_resolver.py`)

Before writing `SpeakerResolver`, define what it returns:

```python
@dataclass
class InferredSpeaker:
    name: str
    confidence: str   # "high" | "medium" | "low"
```

This is the return type of `SpeakerResolver.infer()`. Returning a typed dataclass (rather than a raw dict) makes the downstream logic in `SpeakerStore` explicit and testable.

#### 3.2 `SpeakerResolver` (`src/ingestion/speaker_resolver.py`) 🤖

`SpeakerResolver` takes a `LLMClient` — not `AsyncOpenAI` directly.

```python
class SpeakerResolver:
    def __init__(self, llm_client: LLMClient, window_ms: int = 900_000):
        self._llm = llm_client
        self._window_ms = window_ms

    async def infer(
        self,
        segments: list[TranscriptSegment],
    ) -> InferredSpeaker | None:
        intro = [s for s in segments if s.start_ms < self._window_ms]
        if not intro:
            return None

        formatted = "\n".join(f'"{s.text}"' for s in intro)
        prompt = f"""Who is the speaker in this podcast transcript and what is your confidence on this answer from low, medium, or high? Use the structured format: {{"name": "[person name]", "confidence": "[low|medium|high]"}}

Transcript:
{formatted}"""

        response = await self._llm.complete(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        try:
            data = json.loads(response.content)
            if data.get("name") and data.get("confidence") in ("low", "medium", "high"):
                return InferredSpeaker(name=data["name"], confidence=data["confidence"])
        except (json.JSONDecodeError, KeyError):
            pass
        return None
```

A few design points worth understanding:

- `temperature=0.0` — this is a factual lookup, not creative generation. We want the most deterministic output the model can give.
- `response_format={"type": "json_object"}` — forces structured output on models that support it (OpenAI, most local models). Avoids the model wrapping the JSON in prose.
- Returning `None` on parse failure rather than raising — the pipeline treats `None` as "couldn't determine, skip" and continues. A bad LLM response shouldn't abort ingestion.
- No diarization means there is only ever one "speaker" to infer. The prompt reflects this — we're asking "who is the speaker" not "who are the speakers".

#### 3.3 Update `SpeakerStore.save_inferred()` (`src/ingestion/speaker_store.py`)

The existing `save_inferred()` was written expecting a `dict[str, str | None]` (one entry per diarized speaker). Update it to accept `InferredSpeaker | None`:

```python
async def save_inferred(
    self,
    episode_id: UUID,
    result: InferredSpeaker | None,
    db: AsyncSession,
) -> None:
    if result is None:
        # Nothing to do — UNKNOWN row already exists from initialize_from_transcript
        return

    # Promote UNKNOWN → SPEAKER_00, set display_name and confidence
    await db.execute(
        update(EpisodeSpeaker)
        .where(
            EpisodeSpeaker.episode_id == episode_id,
            EpisodeSpeaker.speaker_id == "UNKNOWN",
        )
        .values(
            speaker_id="SPEAKER_00",
            display_name=result.name,
            name_inferred=True,
            confidence=result.confidence,
        )
    )
    # Also update transcript_segments and chunks to SPEAKER_00
    await db.execute(
        update(TranscriptSegment)
        .where(TranscriptSegment.episode_id == episode_id)
        .values(speaker_id="SPEAKER_00")
    )
    await db.commit()
```

Why update `transcript_segments` too: the `speaker_id` in segments should match `episode_speakers` so joins work correctly. Since there's only one speaker in v1, this is a bulk update of the entire episode.

Note: chunks don't exist yet at this point in the pipeline — they're created in the next step. The chunker will read the updated `speaker_id` from segments.

#### 3.4 Update `episode_speakers` schema

Add `confidence` column to the Alembic migration:

```python
# New column in EpisodeSpeaker model (src/models/db.py)
confidence: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Generate migration:
```bash
uv run alembic revision --autogenerate -m "add confidence to episode_speakers"
uv run alembic upgrade head
```

#### 3.5 Speaker endpoints (`src/api/routers/speakers.py`)

```
GET  /api/v1/episodes/{episode_id}/speakers
→ [{
    speaker_id: "SPEAKER_00",
    display_name: "Lex Fridman",
    name_inferred: true,
    name_confirmed: false,
    confidence: "high"
  }]

GET  /api/v1/episodes/{episode_id}/speakers/preview
→ [{
    speaker_id: "SPEAKER_00",
    sample_quote: "Welcome to the show...",
    sample_timestamp_ms: 0
  }]
# Returns first segment > 20 words for the speaker

PUT  /api/v1/episodes/{episode_id}/speakers
Body: [{ "speaker_id": "SPEAKER_00", "display_name": "Lex Fridman" }]
→ 200 OK
```

`PUT /speakers` logic:
- If `display_name` matches the current `display_name` (user confirmed without editing): set `name_confirmed=true`, leave `name_inferred` unchanged
- If `display_name` differs: set `name_confirmed=true`, `name_inferred=false`
- No pipeline trigger needed — chunking is no longer gated on speaker confirmation

Remove the `AUTO_CHUNK_AFTER_NAMING` config and the `queue.enqueue()` call that was in the original Phase 3.3. The pipeline now runs straight through.

#### 3.6 Update pipeline orchestrator (`src/ingestion/pipeline.py`)

Merge the two-function design (`ingest_episode` + `chunk_episode`) into one continuous function. See the updated pseudocode in ARCHITECTURE.md section 3.4. Key change: no `PENDING_NAMES` status, no pause, no second enqueue.

#### 3.7 Tests

```python
# tests/unit/test_speaker_resolver.py
async def test_infers_name_and_confidence_from_intro()
async def test_returns_none_when_no_name_found()
async def test_returns_none_on_malformed_json()
async def test_filters_to_intro_window_only()
async def test_temperature_zero_used()
async def test_empty_segments_returns_none()

# tests/integration/test_speakers.py
async def test_save_inferred_promotes_unknown_to_speaker_00()
async def test_save_inferred_updates_transcript_segments()
async def test_save_inferred_none_leaves_unknown_intact()
async def test_confirmed_name_sets_name_confirmed_true()
async def test_edited_name_sets_name_inferred_false()
async def test_speaker_lookup_joins_correctly()
async def test_confidence_stored_on_episode_speakers()
```

### Phase 3 Done When
- `SpeakerResolver.infer()` returns `InferredSpeaker | None`
- `SpeakerStore.save_inferred()` promotes `UNKNOWN` → `SPEAKER_00` when name found
- `GET /speakers` returns inferred name with confidence level
- `PUT /speakers` confirms or corrects names; `name_inferred` flag updated correctly
- Pipeline runs straight to chunking — no `PENDING_NAMES` pause
- All tests pass using `MockLLMClient` — no real LLM required
- Git tag: `v0.1.3-speakers`

---

## Phase 4 — Chunking + Embedding

**Goal:** Convert confirmed transcripts into retrievable vector chunks. Speaker identity linked via `speaker_id`.

### Tasks

#### 4.1 Chunker (`src/ingestion/chunker.py`) 🤖

**Step A — Speaker-boundary splits:**
```python
def split_by_speaker(segments: list[TranscriptSegment]) -> list[SpeakerBlock]:
    # Group consecutive segments with same speaker_id
    # Each contiguous run = one SpeakerBlock
    # Preserve: speaker_id, combined text, min(start_ms), max(end_ms)
```

**Step B — Topic segmentation via embedding similarity:**
```python
async def segment_by_topic(blocks: list[SpeakerBlock], embedder) -> list[TopicSegment]:
    embeddings = await embedder.embed([b.text for b in blocks])
    boundaries = []
    for i in range(1, len(embeddings)):
        similarity = cosine_similarity(embeddings[i-1], embeddings[i])
        if similarity < settings.topic_similarity_threshold:
            boundaries.append(i)
    # Group blocks into topic segments; merge segments below min token threshold
```

**Step C — Hierarchical chunk construction:**
```python
def build_chunks(segments: list[TopicSegment], episode_id: UUID) -> list[Chunk]:
    chunks = []
    for segment in segments:
        parent = Chunk(
            episode_id=episode_id,
            chunk_level="parent",
            speaker_id=segment.dominant_speaker_id,
            text=segment.full_text,
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
        )
        chunks.append(parent)
        # Sliding window leaf chunks
        for window in sliding_window(segment.text, settings.chunk_size_tokens, settings.chunk_overlap_tokens):
            leaf = Chunk(
                parent_id=parent.id,
                chunk_level="leaf",
                speaker_id=segment.dominant_speaker_id,   # speaker_id, NOT display_name
                ...
            )
            chunks.append(leaf)
    return chunks
```

Token counting: `tiktoken` (cl100k_base) for consistency across models.

#### 4.2 Embedder (`src/ingestion/embedder.py`)
Uses `EmbeddingClient` Protocol — not `AsyncOpenAI` directly. Embed leaf chunks only. Batch size 100, retry with exponential backoff.

```python
class Embedder:
    def __init__(self, embedding_client: EmbeddingClient): ...

    async def embed(self, chunks: list[Chunk]) -> list[Chunk]:
        # Batch embed, attach vectors, return
```

#### 4.3 VectorStore (`src/storage/vector_store.py`) 🤖
Define the `VectorStore` Protocol now — `PgvectorStore` is the v1 implementation.

```python
class PgvectorStore:
    async def search(
        self, embedding, filters: SearchFilters, top_k: int
    ) -> list[RawChunkResult]: ...

    async def upsert(self, chunks: list[ChunkRecord]) -> None: ...
```

`RawChunkResult` contains `speaker_id`, not `display_name`. Hydration happens in `ResultHydrator` (Phase 5).

#### 4.4 Chunk storage
Write to `chunks` table. Note: `speaker_id` stored, `display_name` resolved at read time via join on `episode_speakers`. Update episode `pipeline_status` → `READY`.

#### 4.5 Tests 🤖
Write these first (TDD for the chunker — it's pure logic, fast to test):

```python
# tests/unit/test_chunker.py
def test_speaker_boundaries_split_on_speaker_change()
def test_same_speaker_consecutive_segments_grouped()
def test_topic_threshold_creates_boundary()
def test_leaf_chunks_within_token_limit()
def test_leaf_chunks_reference_parent_id()
def test_chunks_store_speaker_id_not_display_name()
def test_timestamps_min_max_preserved()
def test_short_segments_merged_not_orphaned()
def test_single_speaker_episode_produces_chunks()
```

### Phase 4 Done When
- Ingesting with fixture transcript produces chunks in pgvector
- `chunks.speaker_id` contains "SPEAKER_00", never a display name
- All chunker tests pass
- Git tag: `v0.1.4-chunking`

---

## Phase 5 — Basic RAG Query

**Goal:** Ask a question, get a grounded answer with citations. No tool-calling yet.

**Dependency note:** The LLM client and embedding client are injected via `Depends(get_llm_client)` and `Depends(get_embedding_client)` from `dependencies.py` — the same pattern established in Phase 0. Do not instantiate `AsyncOpenAI` directly in query handlers.

### Tasks

#### 5.1 ResultHydrator (`src/query/result_hydrator.py`)

`VectorStore.search()` returns `RawChunkResult` with `speaker_id`. `ResultHydrator` resolves speaker names and formats output. Separating these means swapping the vector backend never touches hydration logic.

```python
class ResultHydrator:
    async def hydrate(
        self,
        raw: list[RawChunkResult],
        db: AsyncSession
    ) -> list[ChunkResult]:
        # JOIN episode_speakers ON speaker_id → get display_name
        # Fetch episode title
        # Format timestamp_display ("1:03:42")
        # Return ChunkResult list
```

#### 5.2 Retriever (`src/query/retriever.py`)

The retriever composes `EmbeddingClient`, `VectorStore`, and `ResultHydrator`:

```python
class Retriever:
    def __init__(
        self,
        embedding_client: EmbeddingClient,
        vector_store: VectorStore,
        hydrator: ResultHydrator,
    ): ...

    async def search(
        self,
        query: str,
        filters: SearchFilters,
        top_k: int = 5,
        db: AsyncSession,
    ) -> list[ChunkResult]:
        embedding = await self.embedding_client.embed([query])
        raw = await self.vector_store.search(embedding[0], filters, top_k)
        return await self.hydrator.hydrate(raw, db)
```

#### 5.3 Simple query endpoint
```
POST /api/v1/query/simple
Body: { "question": "...", "feed_id": "uuid", "top_k": 5 }
→ { "answer": "...", "citations": [...] }
```

Always retrieves, always passes context to LLM. Intentionally naive — Phase 6 replaces with tool-calling.

System prompt: "Answer based only on provided context. Always cite specific speakers and timestamps."

#### 5.4 Tests
```python
# tests/unit/test_result_hydrator.py
async def test_hydrator_resolves_speaker_id_to_display_name()
async def test_hydrator_formats_timestamp_correctly()
async def test_hydrator_handles_missing_display_name_gracefully()

# tests/integration/test_retriever.py
async def test_retrieval_returns_relevant_chunks()
async def test_speaker_filter_resolves_from_display_name()
async def test_episode_filter_applied()
async def test_results_ordered_by_similarity()
async def test_parent_context_fetched_alongside_leaf()
async def test_display_name_in_results_not_speaker_id()
```

### Phase 5 Done When
- `POST /api/v1/query/simple` returns answer + citations with resolved speaker names
- Manually verify 3-4 queries against real ingested episode
- Git tag: `v0.1.5-basic-rag`

---

## Phase 6 — Tool-Calling Query Engine

**Goal:** Multi-turn freeform chat. LLM decides when to retrieve.

**Dependency note:** The `ChatSession` store is a dict on `app.state`, accessed via a dependency `get_session_store(request: Request)`. The LLM client continues to use `Depends(get_llm_client)`. Session objects are ephemeral — stored in-process memory, cleared on restart.

### Tasks

#### 6.1 Tool definitions (`src/query/tools.py`) 🤖
Three tools in OpenAI function-calling format:

```python
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Search podcast transcript content. Use when asked about topics, opinions, or facts discussed in episodes.",
            "parameters": {
                "properties": {
                    "query": {"type": "string"},
                    "speaker_name": {"type": "string", "description": "Filter to specific speaker. Optional."},
                    "episode_id": {"type": "string", "description": "Filter to specific episode UUID. Optional."},
                    "top_k": {"type": "integer", "default": 5}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_episode_context",
            "description": "Get full transcript excerpt around a specific timestamp.",
            "parameters": {
                "properties": {
                    "episode_id": {"type": "string"},
                    "timestamp_ms": {"type": "integer"},
                    "padding_ms": {"type": "integer", "default": 30000}
                },
                "required": ["episode_id", "timestamp_ms"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_speaker_profile",
            "description": "Get information about a speaker: episodes, speaking time, topics.",
            "parameters": {
                "properties": {
                    "speaker_name": {"type": "string"}
                },
                "required": ["speaker_name"]
            }
        }
    }
]
```

#### 6.2 Tool executors
```python
async def execute_tool(name: str, args: dict, session: ChatSession, db: AsyncSession) -> str:
    if name == "search_knowledge_base":
        results = await retriever.search(**args, db=db)
        return json.dumps([r.to_dict() for r in results])
    elif name == "get_episode_context":
        ...
    elif name == "get_speaker_profile":
        ...
```

All tool results serialize display names (resolved), never speaker_ids.

#### 6.3 SessionStore (`src/query/session_store.py`)
Define the Protocol and `InMemorySessionStore` implementation.

```python
class InMemorySessionStore:
    def __init__(self):
        self._sessions: dict[str, ChatSession] = {}

    async def get(self, session_id: str) -> ChatSession | None: ...
    async def save(self, session: ChatSession) -> None: ...
    async def delete(self, session_id: str) -> None: ...
```

Singleton stored on `app.state`, injected via `get_session_store()`.

#### 6.4 Query engine (`src/query/engine.py`) 🤖

`QueryEngine` is a thin orchestrator that delegates to injected components. Uses `LLMClient` — not `AsyncOpenAI` directly.

```python
class QueryEngine:
    def __init__(
        self,
        llm_client: LLMClient,
        session_store: SessionStore,
        prompt_builder: PromptBuilder,
        tool_dispatcher: ToolDispatcher,
    ): ...

    async def chat(self, session_id: str, user_message: str) -> ChatResponse:
        session = await self.session_store.get(session_id)
        session.messages.append({"role": "user", "content": user_message})

        for _ in range(3):
            messages = self.prompt_builder.build_messages(session)
            response = await self.llm_client.complete(messages, tools=TOOLS)
            if not response.tool_calls:
                break
            for tc in response.tool_calls:
                result = await self.tool_dispatcher.dispatch(tc, session)
                session.messages.append(tool_result_message(tc, result))

        session.messages.append({"role": "assistant", "content": response.content})
        await self.session_store.save(session)
        return ChatResponse(message=response.content, citations=session.citations)
```

#### 6.5 Chat endpoints
```
POST   /api/v1/chat/sessions
POST   /api/v1/chat/{session_id}/message
GET    /api/v1/chat/{session_id}/history
DELETE /api/v1/chat/{session_id}
```

#### 6.6 Tests
```python
# tests/unit/test_prompt_builder.py
def test_builds_correct_system_prompt_with_scope()
def test_includes_full_message_history()

# tests/integration/test_chat.py  (inject MockLLMClient, MockVectorStore)
async def test_no_tool_call_for_summarization_request()
async def test_tool_called_for_topic_query()
async def test_multi_turn_history_maintained()
async def test_session_scope_applied_to_retrieval()
async def test_citations_accumulated_across_turns()
async def test_tool_results_contain_display_names_not_speaker_ids()
async def test_session_store_persists_between_turns()

# tests/unit/test_tool_dispatcher.py
async def test_dispatches_search_with_correct_filters()
async def test_dispatches_context_with_timestamp()
async def test_dispatches_speaker_profile()
```

### Phase 6 Done When
- Multi-turn chat works via curl
- Verified: topic query → tool call; "summarize that" → no tool call
- Citations show resolved speaker display names
- Git tag: `v0.1.6-chat-engine`

---

## Phase 7 — Frontend: Ingestion Flow

**Goal:** Full ingestion flow in browser. SSE progress. Speaker confirmation UI.

### Tasks

#### 7.1 Scaffold
```bash
cd frontend
npm create vite@latest . -- --template react-ts
npm install @tanstack/react-query axios react-router-dom
npm install -D tailwindcss postcss autoprefixer
```
Vite proxy: `/api` → `http://localhost:8000`

#### 7.2 API client (`src/api/client.ts`) 🤖
Typed axios wrapper for every endpoint. Types mirror backend Pydantic schemas.

#### 7.3 SSE hook (`src/hooks/useEpisodeStatus.ts`)
```typescript
function useEpisodeStatus(episodeId: string) {
  const [status, setStatus] = useState<PipelineStatusUpdate | null>(null)

  useEffect(() => {
    const source = new EventSource(`/api/v1/episodes/${episodeId}/status/stream`)
    source.onmessage = (e) => setStatus(JSON.parse(e.data))
    source.onerror = () => source.close()
    return () => source.close()
  }, [episodeId])

  return status
}
```

#### 7.4 Feeds page
- RSS URL input + "Add Feed"
- Feed cards: title, episode count, last fetched
- Refresh / Delete actions

#### 7.5 Episodes page
- Episode list with status badges
- In-progress: SSE-driven progress bar + stage label
- QUEUED: show position ("Position 3 in queue")
- "Ingest" button with speaker count hint input (informational only in v1 — no diarization)
- READY episodes: show speaker name + confidence badge if inferred, or "Speaker unknown" prompt

#### 7.6 Speaker naming page
- Accessible from episode detail — not a pipeline gate
- Shows inferred name (if any) with confidence badge ("High confidence", "Medium confidence")
- Name input pre-filled from inference, editable
- "Save" → PUT speakers → updates display name, no pipeline effect
- Episodes with `UNKNOWN` speaker show a prompt to add a name optionally

### Phase 7 Done When
- Add feed → trigger ingestion → watch SSE progress to READY — all in browser
- Speaker name (if inferred) visible with confidence badge; editable post-ingestion
- No curl required for happy path
- Git tag: `v0.1.7-frontend-ingestion`

---

## Phase 8 — Frontend: Chat Interface

**Goal:** Freeform conversational query UI.

### Tasks

#### 8.1 Chat page layout
- Left: scope selector (feed picker, optional episode multi-select)
- Main: message thread
- Bottom: input + send

#### 8.2 Message components
- User: right-aligned, plain text
- Assistant: left-aligned, markdown rendered
- Citation cards: collapsible, speaker + timestamp + excerpt
- Tool call indicator: subtle label ("searched knowledge base")

#### 8.3 Session management
- New session on page load or scope change
- "New conversation" button
- History in React state (ephemeral)

### Phase 8 Done When
- Full product usable end-to-end in browser
- Citations show resolved speaker names and clickable timestamps
- Git tag: `v0.1.8-frontend-chat`

---

## Phase 9 — Observability

**Goal:** LLM, inference, and retrieval traces in Phoenix.

### Tasks

#### 9.1 OTel setup (`src/telemetry/setup.py`) 🤖
```python
def setup_telemetry(settings: Settings):
    if not settings.phoenix_enabled:
        return
    provider = TracerProvider()
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
    )
    trace.set_tracer_provider(provider)
    OpenAIInstrumentor().instrument()    # auto-traces all LLM calls
```

#### 9.2 Custom spans
Add spans to: audio download, transcription, speaker inference (log names found vs null), diarization, chunking, embedding, retrieval. Each span carries `episode_id` attribute.

```python
tracer = trace.get_tracer("podcast-engine")

async def infer_speaker_names(...):
    with tracer.start_as_current_span("speaker_inference") as span:
        result = await _run_inference(...)
        found = sum(1 for v in result.values() if v is not None)
        span.set_attribute("speakers.total", len(result))
        span.set_attribute("speakers.inferred", found)
        return result
```

#### 9.3 Phoenix in Docker Compose
Already in `docker-compose.yml` under `observability` profile.

#### 9.4 Verify
Run a chat turn. Open Phoenix at `:6006`. Confirm:
- LLM call traced with tokens
- Tool calls as child spans
- Speaker inference span with found/total attributes
- Retrieval span with query + score distribution

### Phase 9 Done When
- Phoenix shows full trace for chat turn including speaker inference
- Git tag: `v0.1.9-observability`

---

## Phase 10 — Polish and Demo Prep

### Tasks

#### 10.1 README.md
- 2-sentence description
- Architecture diagram reference
- 5-command quick start
- Config reference
- Screenshot or demo GIF

#### 10.2 Error handling audit
- All pipeline errors stored and surfaced via status endpoint and SSE
- Frontend shows meaningful error states

#### 10.3 Demo seed script
```bash
uv run python scripts/seed_demo.py --feed-url https://... --episodes 5
```
Pre-ingest demo episodes. Commit this so anyone can reproduce your demo.

#### 10.4 Final test pass
```bash
uv run pytest --cov=src --cov-report=term-missing
```
Target: >70% coverage. Ensure contract tests cover all Protocols:
- `OpenAILLMClient` satisfies `LLMClient`
- `OpenAIEmbeddingClient` satisfies `EmbeddingClient`
- `LocalTranscriptionService` + `RemoteTranscriptionService` satisfy `TranscriptionService`
- `BackgroundTaskQueue` satisfies `IngestionQueue`
- `PgvectorStore` satisfies `VectorStore`
- `InMemorySessionStore` satisfies `SessionStore`

### Phase 10 Done When
- README gives a stranger enough to run it
- Seed script produces a good demo state
- Auth in place (`DEMO_AUTH_ENABLED=true`) for hosted version
- Git tag: `v1.0.0`

---

## Agent-Assisted Development Guide

**DO give the agent:**
- `ARCHITECTURE.md` + this document as context
- One bounded task: "implement `src/ingestion/speaker_resolver.py` per Phase 3.1"
- Existing code it will interact with
- The test file to write against

**DON'T ask the agent to:**
- Design the architecture (done)
- Build multiple phases at once
- Make infrastructure decisions (decided)

**Effective prompts:**
```
"Implement src/ingestion/chunker.py per Phase 4.1 of IMPLEMENTATION_PLAN.md.
Input: list[TranscriptSegment] from src/transcription/base.py.
Key constraint: chunks store speaker_id (not display_name) — see ARCHITECTURE.md section 3.8.
Write tests/unit/test_chunker.py first (TDD), then implement.
Use tests/fixtures/sample_transcript.json fixture."
```

```
"Implement src/ingestion/speaker_resolver.py per Phase 3.1.
Takes a LLMClient (Protocol from src/llm/base.py) — do not use AsyncOpenAI directly.
Return dict[str, str | None] — null for unknown speakers, never guess.
Inject MockLLMClient in tests/unit/test_speaker_resolver.py."
```

```
"Implement src/query/result_hydrator.py per Phase 5.1 of IMPLEMENTATION_PLAN.md.
Input: list[RawChunkResult] from src/storage/vector_store.py.
Must resolve speaker_id to display_name via join on episode_speakers.
Write tests/unit/test_result_hydrator.py first."
```

```
"Implement the IngestionQueue protocol and BackgroundTaskQueue in src/ingestion/queue.py per Phase 1.4.
The queue must enforce MAX_CONCURRENT_INGESTIONS via asyncio.Semaphore.
Include get_position() for QUEUED jobs.
Test that BackgroundTaskQueue satisfies the IngestionQueue Protocol."
```

---

## Milestone Summary

| Tag | What Works |
|-----|-----------|
| `v0.1.0-scaffold` | Health endpoint, DB connected |
| `v0.1.1-feeds` | RSS ingestion, episode listing, queue abstraction |
| `v0.1.2-transcription` | Transcription pipeline, SSE status streaming |
| `v0.1.3-speakers` | LLM speaker inference with confidence; pipeline runs straight to READY |
| `v0.1.4-chunking` | Chunks + embeddings, speaker_id preserved |
| `v0.1.5-basic-rag` | Simple Q&A with resolved speaker names in citations |
| `v0.1.6-chat-engine` | Multi-turn chat, tool-calling, conditional retrieval |
| `v0.1.7-frontend-ingestion` | Browser-based ingestion with SSE progress |
| `v0.1.8-frontend-chat` | Full product in browser |
| `v0.1.9-observability` | Phoenix traces including speaker inference metrics |
| `v1.0.0` | Shippable, documented, demo-ready |

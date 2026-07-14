# Podcast Knowledge Engine — Architecture Document

> Version: 1.0
> Status: In implementation
> Author: Cameron Perry
> Last Updated: 2026-07-04

---

> **Public name:** This project is published as **Throughline**. Internal naming throughout this document uses the original working title (Podcast Knowledge Engine).

## 1. Project Overview

The Podcast Knowledge Engine is a local-first, single-user application that ingests podcast feeds, transcribes and diarizes episodes, builds a queryable knowledge base, and exposes a conversational interface for exploring podcast content.

The primary interface is a freeform chat that uses tool-calling to decide when retrieval is needed — enabling natural queries like "what would [host] say about X?" as well as conversational follow-ups, summarization, and counter-argument exploration without forcing irrelevant retrieval on every turn.

### Goals

- Demonstrate AI-native application architecture: ingestion pipelines, RAG, tool-calling, observability
- Local-first with Docker deployment; designed for deployment flexibility from day one
- Provider-agnostic inference: any OpenAI-compatible LLM endpoint (local or cloud)
- Open source dependencies only; no vendor lock-in
- Thoroughly documented; API-first so the frontend is optional for testing and automation

### Non-Goals (v1)

- Multi-user support
- YouTube or non-RSS podcast sources
- Graph RAG (deferred upgrade path)
- Persistent conversation history (ephemeral sessions only in v1)
- Automated feed polling (manual ingestion trigger)
- Speaker diarization (deferred — CPU/local diarization via Pyannote is impractical on non-CUDA hardware; see Future Scope section 1.5)
- Mid-conversation scope changes (scope set once at session creation; V2 work — see Future Scope)

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        Frontend                          │
│                    React.js (Vite)                       │
│  Feed Mgmt │ Episode Mgmt │ Speaker UI │ Chat Interface  │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP / REST + SSE
┌────────────────────────▼─────────────────────────────────┐
│                    Backend API                           │
│                  FastAPI + Python                        │
│                                                          │
│  /feeds   /episodes   /transcripts   /query   /health    │
│                                                          │
│  IngestionQueue (Protocol-abstracted; Redis-backed via   │
│  streaQ — enqueue only, no pipeline code runs here)      │
└──────┬───────────────────────────────────────┬───────────┘
       │                                       │
┌──────▼───────────┐                ┌──────────▼──────────┐
│ Ingestion Worker │                │   Query Engine       │
│ (separate process│                │                      │
│  — streaq run)   │                │  engine.py           │
│                  │                │  (thin orchestrator) │
│ pipeline.py      │                │  ↕                   │
│ (orchestrator)   │                │  PromptBuilder       │
│  ↕               │                │  ToolDispatcher      │
│ AudioDownloader  │                │  SessionStore        │
│ TranscriptionSvc │                │  ↕                   │
│ SpeakerResolver  │                │  VectorStore         │
│ Chunker          │                │  ResultHydrator      │
│ Embedder         │                │                      │
│ PipelineStatus   │                │                      │
│   Service        │                │                      │
└──────┬───────────┘                └─────────┬────────────┘
       │                                      │
┌──────▼──────────────────────────────────────▼──────────┐
│                     Data Layer                           │
│                                                          │
│   PostgreSQL + pgvector                                  │
│   (feeds, episodes, transcripts, chunks, embeddings)     │
│   Speaker identity linked, never embedded in text        │
└─────────────────────────────────────────────────────────┘
       │                                      │
┌──────▼──────────┐                ┌──────────▼──────────┐
│ LLM / Embedding  │                │  Observability       │
│ (abstracted)     │                │                      │
│                  │                │  OpenTelemetry       │
│ LLMClient        │                │  Phoenix / Arize     │
│ EmbeddingClient  │                │  (LLM traces,        │
│ (Protocols)      │                │   pipeline metrics,  │
│                  │                │   inference quality) │
│ TranscriptionSvc │                │                      │
│ (Protocol)       │                └─────────────────────┘
└──────────────────┘
```

---

## 3. Component Breakdown

### 3.1 Backend API — FastAPI

**Responsibilities:**
- Expose REST endpoints for all operations
- Coordinate ingestion pipeline via `IngestionQueue`
- Stream pipeline status updates via SSE
- Wire all dependencies via `dependencies.py`
- Emit OpenTelemetry traces throughout

**Key design decisions:**
- All configuration via `.env` / environment variables — no hardcoded values
- All shared resources injected via FastAPI `Depends()` — never instantiated in route handlers
- LLM and embedding access via `LLMClient` / `EmbeddingClient` Protocols — SDK never referenced directly in business logic
- Async throughout (httpx, asyncpg)

**Entry point:** `src/api/main.py`

---

### 3.2 Dependency Injection Map

All shared resources are defined in `src/api/dependencies.py` and injected via `Depends()`. This is the single wiring point for the application — route handlers and services never instantiate dependencies directly.

```python
# src/api/dependencies.py

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    # Yields an async DB session per request

def get_llm_client() -> LLMClient:
    # Returns OpenAICompatibleLLMClient pointed at LLM_BASE_URL
    # In tests: inject MockLLMClient

def get_embedding_client() -> EmbeddingClient:
    # Returns OpenAICompatibleEmbeddingClient pointed at EMBEDDING_BASE_URL
    # In tests: inject MockEmbeddingClient

def get_ingestion_queue(request: Request) -> IngestionQueue:
    # Returns StreaqQueue singleton from app.state when REDIS_URL is set,
    # else BackgroundTaskQueue (in-process fallback — see section 3.5)

def get_transcription_service() -> TranscriptionService:
    # Returns LocalTranscriptionService or RemoteTranscriptionService
    # Presence of TRANSCRIPTION_SERVICE_URL implies remote; absence implies local

def get_vector_store() -> VectorStore:
    # Returns PgvectorStore
    # Swap to QdrantStore or PineconeStore without touching callers

def get_session_store(request: Request) -> SessionStore:
    # Returns InMemorySessionStore singleton from app.state

def get_pipeline_status_service(db: AsyncSession = Depends(get_db)) -> PipelineStatusService:
    # Returns service for writing pipeline status transitions

def get_prompt_builder() -> PromptBuilder:
    # Returns stateless PromptBuilder instance

def get_tool_dispatcher(retriever: Retriever = Depends(get_retriever)) -> ToolDispatcher:
    # Returns ToolDispatcher with injected Retriever

def get_query_engine(
    llm: LLMClient = Depends(get_llm_client),
    session_store: SessionStore = Depends(get_session_store),
    prompt_builder: PromptBuilder = Depends(get_prompt_builder),
    tool_dispatcher: ToolDispatcher = Depends(get_tool_dispatcher),
) -> QueryEngine:
    # Returns fully wired QueryEngine
```

**Swapping an implementation** requires changing one function in `dependencies.py`. No route handlers, pipeline code, or business logic changes.

---

### 3.3 Service Abstractions (Protocols)

All swappable components are defined as Python `Protocol` classes. Concrete implementations satisfy the Protocol structurally — no inheritance required.

#### LLMClient (`src/llm/base.py`)

```python
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict

@dataclass
class LLMResponse:
    content: str | None = None        # None when model is making tool calls
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    # TokenUsage deferred to Phase 9 observability

class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_format: dict | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse: ...
```

**Current state (post-Phase 6):** `LLMResponse` includes `content: str | None`, `tool_calls: list[ToolCall]`,
and `finish_reason: str`. `LLMClient.complete()` accepts a `tools` parameter. `TokenUsage` is deferred to Phase 9.

`OpenAICompatibleLLMClient` in `src/llm/client.py` parses tool call arguments from JSON strings defensively —
malformed arguments produce an empty dict with a logged warning rather than raising. All business logic receives
`LLMClient`. The OpenAI SDK is referenced only in `src/llm/client.py`.

`MockLLMClient` lives in `tests/conftest.py` and supports a `responses: list[LLMResponse]` sequence parameter
for multi-round tool-calling tests. It is a plain class, not a pytest fixture — import it directly in test files.

#### EmbeddingClient (`src/llm/base.py`)

```python
class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Implementations: `OpenAICompatibleEmbeddingClient` (production, in `src/llm/client.py`), `MockEmbeddingClient` (tests).

#### TranscriptionService (`src/transcription/base.py`)

```python
class TranscriptionService(Protocol):
    async def transcribe(
        self,
        audio_path: str,
        speaker_count_hint: int | None = None,
        language: str = "en"
    ) -> TranscriptResult: ...
```

Implementations: `LocalTranscriptionService` (Whisper + Pyannote), `RemoteTranscriptionService` (HTTP sidecar).

#### IngestionQueue (`src/ingestion/queue.py`)

```python
class IngestionQueue(Protocol):
    async def enqueue(self, episode_id: UUID, job_args: dict) -> str: ...
    async def get_status(self, job_id: str) -> JobStatus: ...
    async def cancel(self, job_id: str) -> bool: ...
```

Implementations: `StreaqQueue` (default, Redis-backed via streaQ, separate worker process), `BackgroundTaskQueue`
(in-process fallback when `REDIS_URL` is unset).

The queue never generates or accepts a caller-supplied job id — `enqueue()` always returns an id the queue
itself assigns. **Postgres, not the queue, is the sole authority for ingestion dedup**: `ingest` and `reingest`
route handlers guard against duplicate/conflicting requests entirely via `episode.pipeline_status` checks. The queue layer offers no id-collision backstop by design — see section 3.5.

`JobStatus` (`src/ingestion/queue.py`) is a five-value enum — `QUEUED`, `RUNNING`, `DONE`, `FAILED`, `CANCELLED`
— that both implementations map their native states onto. `CANCELLED` is not a native state in either backend;
it is inferred from the stored result being a cancellation-related exception. Three typed exceptions accompany
the Protocol: `JobNotFoundError` (raised when no record of a job id exists — normal once a result's TTL has
elapsed), `DuplicateJobError`, and `QueueConnectionError` (Redis unreachable — `StreaqQueue` only).

**`get_status()` usage note:** callers should check `episode.pipeline_status` first — it durably answers
"is this job done" with no TTL. `get_status()`/`cancel()` exist for the narrower case of inspecting or
interrupting a job that Postgres still shows as in-flight.

**`cancel()`** is a real operation in `StreaqQueue` (not a stub) — it can interrupt a job at any `await` point,
which stops most pipeline stages immediately. The one exception: CPU-bound Whisper transcription runs inside a
`ProcessPoolExecutor`, and cancelling the asyncio-level task does not kill the underlying OS subprocess. A
cancelled job mid-transcription stops accepting the result, but the subprocess keeps running to completion in
the background. See Future Scope for the subprocess-kill follow-up.

#### VectorStore (`src/storage/vector_store.py`)

```python
@dataclass
class SearchFilters:
    feed_ids: list[UUID] | None = None    # supports multi-feed scope
    episode_ids: list[UUID] | None = None
    speaker_id: str | None = None

@dataclass
class RawChunkResult:
    chunk_id: UUID
    text: str
    parent_text: str | None   # fetched alongside leaf for LLM context
    speaker_id: str           # NOT display_name — hydration resolves this
    episode_id: UUID
    start_ms: int
    end_ms: int
    similarity_score: float

class VectorStore(Protocol):
    async def search(
        self,
        embedding: list[float],
        filters: SearchFilters,
        top_k: int = 5,
        db: AsyncSession = ...,
    ) -> list[RawChunkResult]: ...

    async def upsert(self, chunks: list[ChunkRecord], db: AsyncSession) -> None: ...
```

`feed_ids` uses `Episode.feed_id.in_(filters.feed_ids)` — supports querying across multiple feeds in one
session. Unset fields are not applied as WHERE clauses.

Implementations: `PgvectorStore` (v1), `QdrantStore` / `PineconeStore` (post-v1, ~1 day each).

#### SessionStore (`src/query/session_store.py`)

```python
@dataclass
class ChatSession:
    session_id: str
    scope_feed_ids: list[UUID] = field(default_factory=list)    # multi-feed support
    scope_episode_ids: list[UUID] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)

class SessionStore(Protocol):
    async def get(self, session_id: str) -> ChatSession | None: ...
    async def save(self, session: ChatSession) -> None: ...
    async def delete(self, session_id: str) -> None: ...
    async def list_sessions(self) -> list[str]: ...
```

Implementations: `InMemorySessionStore` (v1, ephemeral — singleton on `app.state`), `DBSessionStore` (post-v1, persistent conversations).

---

### 3.4 Ingestion Pipeline

`pipeline.py` is a thin orchestrator. It owns sequencing and status transitions, but delegates all business logic to discrete injected services. No stage has knowledge of other stages.

```python
# src/ingestion/pipeline.py
async def ingest_episode(
    episode_id: UUID,
    job_args: dict,
    services: PipelineServices,   # injected dataclass of all services
) -> None:
    try:
        await services.status.set(episode_id, "DOWNLOADING")
        audio_path = await services.downloader.download(episode)

        await services.status.set(episode_id, "TRANSCRIBING")
        transcript = await services.transcription.transcribe(
            audio_path,
            speaker_count_hint=job_args.get("speaker_count_hint")
        )
        await services.transcript_store.save(episode_id, transcript)
        # All segments written with speaker_id = 'UNKNOWN' (no diarization in v1)

        await services.status.set(episode_id, "INFERRING_SPEAKERS")
        result = await services.speaker_resolver.infer(transcript.segments)
        await services.speaker_store.save_inferred(episode_id, result)
        # If exactly one speaker inferred: speaker_id promoted to SPEAKER_00,
        # display_name pre-populated, name_inferred=true.
        # If zero or multiple speakers inferred: speaker_id stays UNKNOWN,
        # display_name=NULL. Pipeline does not pause — proceeds straight to chunking.

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

**Note:** `PENDING_NAMES` status is removed from v1. The pipeline no longer pauses for user input. Speaker display names can be updated at any time via `PUT /speakers` — this is a metadata-only operation that updates `episode_speakers.display_name` with no effect on chunks or embeddings. When diarization is introduced (Future Scope 1.5), `PENDING_NAMES` will be reinstated as a pipeline pause point for multi-speaker episodes.

**`PipelineServices` dataclass** (`src/ingestion/pipeline.py`):
```python
@dataclass
class PipelineServices:
    status: PipelineStatusService
    downloader: AudioDownloader
    transcription: TranscriptionService
    transcript_store: TranscriptStore
    speaker_resolver: SpeakerResolver
    speaker_store: SpeakerStore
    chunker: Chunker
    embedder: Embedder
    vector_store: VectorStore
```

Each service has a single responsibility and is independently testable by injecting mocks.

#### Discrete pipeline services

| Service                 | File                            | Responsibility                                    |
| ----------------------- | ------------------------------- | ------------------------------------------------- |
| `AudioDownloader`       | `ingestion/audio_downloader.py` | httpx streaming download, stores to disk          |
| `TranscriptionService`  | `transcription/base.py`         | Protocol; local or remote impl                    |
| `TranscriptStore`       | `ingestion/transcript_store.py` | Save/retrieve `transcript_segments` rows          |
| `SpeakerResolver`       | `ingestion/speaker_resolver.py` | LLM inference of speaker names from intro         |
| `SpeakerStore`          | `ingestion/speaker_store.py`    | Read/write `episode_speakers` rows                |
| `Chunker`               | `ingestion/chunker.py`          | Speaker-boundary + topic segmentation + hierarchy |
| `Embedder`              | `ingestion/embedder.py`         | Batch embedding via `EmbeddingClient`             |
| `PipelineStatusService` | `ingestion/status_service.py`   | Write status transitions to DB                    |

---

### 3.5 Ingestion Queue and Worker Model

Understanding the execution model is important for reasoning about frontend reconnects, page refreshes, and job durability.

#### Why a separate worker process

Ingestion involves CPU-bound transcription and can run for minutes. Running it in the same process as the API means a long ingestion job and API responsiveness compete for the same event loop's attention, and a crashed/restarted API process would silently kill any in-flight job with no record of how far it got. The queue is Redis-backed (via [streaQ](https://github.com/tastyware/streaq)) specifically to decouple these: the API process only ever enqueues; a dedicated worker process (`streaq run src.worker:worker`) is the only thing that executes pipeline code.

#### Execution model

```
POST /ingest (HTTP request)
  │
  └─► StreaqQueue.enqueue()
        │
        ├─ worker.enqueue_unsafe(INGEST_EPISODE_JOB, episode_id, job_args)
        │    → serializes args, pushes to Redis, returns immediately
        │    → API process never imports pipeline code — dispatch is by
        │      function name string only (see below)
        ├─ Writes pipeline_status=QUEUED to DB    ← DB is source of truth
        └─ Returns job_id (streaQ-generated) immediately

             [HTTP request ends — frontend can close, refresh, disconnect]

        Separate worker process (streaq run), own event loop:
          │
          ├─ Picks up the job (bounded by Worker(concurrency=N))
          ├─ pipeline_runner.py builds PipelineServices — LLM/embedding
          │    clients from Worker lifespan context (built once, reused
          │    across jobs); AudioDownloader built fresh per job (cheap,
          │    stateless, no persistent connection worth holding)
          ├─ Calls PipelineStatusService.set() at every stage transition
          ├─ Delegates CPU-bound work to ProcessPoolExecutor (Whisper)
          │    └─► worker's event loop stays free for other jobs
          └─ Writes pipeline_status=READY (or ERROR) to DB when done

GET /episodes/{id}/status/stream (SSE — separate connection)
  │
  └─► Reads pipeline_status from DB every 2 seconds
        └─ Completely independent of the worker process
           Frontend can connect, disconnect, reconnect at any time
           Status is always current because DB is the source of truth
```

**Key point:** the worker process and the SSE stream are fully decoupled from the API process. The pipeline writes to the DB via `PipelineStatusService`. SSE reads from the DB. A page refresh, an API restart, or a worker restart has no effect on a running job — streaQ's pessimistic execution model keeps a job in Redis until it succeeds or fails, so a worker crash mid-job means the job is picked up again on restart, not lost.

**Decoupled dispatch by name, not import:** `StreaqQueue` calls `worker.enqueue_unsafe(INGEST_EPISODE_JOB, ...)` — `INGEST_EPISODE_JOB` is a plain string constant (`src/ingestion/queue.py`), matched against the worker process's own `@worker.task`-decorated function of the same name (`src/worker.py`). The API process never imports pipeline code as a result.

The `@worker.task` decorator is used only on the worker side. It's what builds the worker's task registry — the lookup table the worker consults when a job envelope arrives from Redis, to find the real function to call. `enqueue_unsafe()` does not consult any registry: it packages `fn_name` plus arguments into a task envelope and writes it to Redis, with no check that a function by that name actually exists anywhere. This is the literal meaning of "unsafe" in the method name — it's about the absence of this check, not about safety in a broader sense.

Consequence: a mismatched name between `INGEST_EPISODE_JOB` and the worker's registered task name does not fail at enqueue time, or at import time — the job writes to Redis successfully and sits as `QUEUED` indefinitely. The mismatch only surfaces when a worker actually attempts to pick up the job and fails its registry lookup. Both sides must be kept in sync deliberately; there is no automated check that they are.

**Queue ordering:** FIFO per Redis stream ordering; `Worker(concurrency=N)` bounds how many jobs run at once within one worker process. Not a strict cross-process guarantee if multiple worker processes are ever run — acceptable for a single-user, single-worker deployment.

**Job dedup lives entirely in Postgres, not the queue:** streaQ always generates a fresh job id on enqueue — there is no supported way to request a specific id. `ingest_episode_handler` and `reingest_episode_handler` guard against duplicate/conflicting requests via `episode.pipeline_status` checks before ever calling `enqueue()`. The queue layer offers no id-collision backstop by design.

**Cancellation:** `cancel()` is a real operation for both queued and in-progress jobs, via streaQ's `Task.abort()` / `Worker.abort_by_id()`. Known limitation: aborting a job blocked on Whisper transcription stops the job, but the underlying `ProcessPoolExecutor` subprocess runs to completion unobserved — actually killing that subprocess would require tracking its OS PID directly. See Future Scope.

#### CPU-bound work must use ProcessPoolExecutor

Whisper is CPU-bound and will block the worker's event loop if called directly. The executor lives at module scope in `src/transcription/local.py` (not per-instance) — it is created once per worker process, independent of how many `LocalTranscriptionService` instances are constructed:

```python
# src/transcription/local.py
_executor = ProcessPoolExecutor(max_workers=settings.transcription_max_workers)

class LocalTranscriptionService:
    async def transcribe(self, audio_path, speaker_count_hint=None, language="en"):
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _executor,
            _run_transcription_sync,
            audio_path, speaker_count_hint, language
        )
        return result
```

`transcription_max_workers` and the worker's `concurrency` are deliberately independent settings: `concurrency` bounds how many jobs the worker process runs concurrently (I/O-bound stages — downloads, LLM calls — genuinely run in parallel up to this limit); `transcription_max_workers` bounds how many of those concurrently-running jobs can be doing actual Whisper CPU work at the same literal instant, regardless of `concurrency`. A job whose transcription call arrives while all executor slots are full queues inside the executor, not in Redis. Both default to `1` for local-first, single-machine deployment; either can be raised independently once transcription or the LLM/embedding endpoints move off-box.

#### What survives a frontend page refresh

| Thing                  | Survives refresh? | Reason                                                                |
| ---------------------- | ----------------- | --------------------------------------------------------------------- |
| Pipeline job execution | Yes               | Runs in a separate worker process, unaffected by HTTP or API restarts |
| Pipeline status        | Yes               | Written to DB at every stage transition                               |
| SSE stream             | No                | HTTP connection dropped on refresh                                    |
| SSE reconnect          | Yes               | Frontend re-opens stream; DB has current status                       |
| Jobs in queue          | Yes               | Persisted in Redis; survives API and worker process restarts          |
| Chat sessions          | No                | InMemorySessionStore cleared on process restart                       |

#### Frontend reconnect pattern

```typescript
const TERMINAL_STATUSES = ['PENDING', 'READY', 'ERROR']

episodes
  .filter(ep => !TERMINAL_STATUSES.includes(ep.pipeline_status))
  .forEach(ep => connectSSE(ep.id))
```

#### Configuration

```
MAX_CONCURRENT_INGESTIONS=1          # streaQ Worker(concurrency=...)
TRANSCRIPTION_MAX_WORKERS=1          # ProcessPoolExecutor size for local Whisper
REDIS_URL=redis://redis:6379         # presence implies StreaqQueue; empty/unset falls
# back to BackgroundTaskQueue (in-process, no Redis)
```

---

### 3.6 Transcription Service

Swappable behind the `TranscriptionService` Protocol. See section 3.3 for interface definition.

**Configuration:**
```
TRANSCRIPTION_BACKEND=local          # local | remote
TRANSCRIPTION_SERVICE_URL=http://localhost:8001
HUGGINGFACE_TOKEN=hf_...
WHISPER_MODEL=medium
```

**Diarization:** Deferred to Future Scope 1.5. CPU/local diarization via Pyannote is impractical on non-CUDA hardware (2–4x real-time on CPU for long episodes). In v1, all transcript segments are written with `speaker_id = 'UNKNOWN'`. Speaker identity is resolved post-transcription by `SpeakerResolver` (see section 3.7). When diarization is introduced, it will be configured via `DIARIZATION_BACKEND=local|remote`, mirroring the existing transcription backend pattern.

**Local implementation:** Whisper (faster-whisper or mlx-whisper). Must run in `ProcessPoolExecutor` — see section 3.5 for rationale. Pyannote is not invoked in v1.

**Remote implementation:** HTTP POST to `TRANSCRIPTION_SERVICE_URL`. When a remote service performs both transcription and diarization (e.g. OpenAI Whisper API with speaker labels, or a custom GPU sidecar), `RemoteTranscriptionService` normalises the response into `TranscriptResult` — the pipeline sees no difference. Deferred to Future Scope 1.5.

**RSS shortcut:** If `transcript_url` is present in the RSS feed, download and parse directly. Set `speaker_id = 'UNKNOWN'` for all segments — diarization has not run. `SpeakerResolver` still runs on the intro window. User can override via reingest.

---

### 3.7 Speaker Inference

LLM-assisted name detection runs automatically after transcription. Uses `LLMClient` Protocol — not the OpenAI SDK directly. This is the primary speaker identity mechanism in v1, operating without diarization.

**When it runs:** Immediately after transcription, as part of the single continuous pipeline job. No pipeline pause.

**Prompt:**
```
Who is the speaker in this podcast transcript and what is your confidence on this answer
from low, medium, or high? Use the structured format:
{"name": "[person name]", "confidence": "[low|medium|high]"}
```

**Return type:**
```python
@dataclass
class InferredSpeaker:
    name: str
    confidence: str   # "high" | "medium" | "low"

# src/ingestion/speaker_resolver.py
class SpeakerResolver:
    def __init__(self, llm_client: LLMClient, window_ms: int): ...

    async def infer(
        self,
        segments: list[TranscriptSegment],
    ) -> InferredSpeaker | None:
        # Filter to intro window (SPEAKER_INFERENCE_WINDOW_MS)
        # Build prompt, call llm_client.complete()
        # Return InferredSpeaker if confident, None if not found
        # Never guess — return None rather than a low-quality result
```

**Post-inference logic in `SpeakerStore.save_inferred()`:**

| Inference result                | Action                                                                                                                                       |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| One name found (any confidence) | Update `speaker_id` from `UNKNOWN` → `SPEAKER_00`; set `display_name=name`, `name_inferred=true`, `confidence=level`, `name_confirmed=false` |
| None found                      | Leave `speaker_id = 'UNKNOWN'`, `display_name=NULL`. Pipeline continues to chunking.                                                         |

**User confirmation via `PUT /speakers`:**
- If user saves without editing the name: `name_confirmed=true`, `name_inferred` unchanged
- If user edits the name: `name_confirmed=true`, `name_inferred=false`
- Speaker display name can be updated at any time — it is pure metadata, no re-chunking required

**Configuration:**
```
SPEAKER_INFERENCE_WINDOW_MS=900000
```

---

### 3.8 Speaker Identity Model

**Core principle:** `speaker_id` is a stable identifier linking segments and chunks to speaker metadata in `episode_speakers`. Display names are mutable metadata — a name change is a single row update with no effect on chunks or embeddings.

**v1 constraint — no diarization:** All segments are written with `speaker_id = 'UNKNOWN'`. If `SpeakerResolver` infers exactly one speaker from the intro, that row is promoted to `speaker_id = 'SPEAKER_00'` with an inferred `display_name`. Multi-speaker episodes remain `UNKNOWN` until diarization is available (Future Scope 1.5).

**Why `UNKNOWN` not `SPEAKER_00`:** Using `SPEAKER_00` when diarization has not run would be semantically incorrect — it implies diarization ran and found one speaker. `UNKNOWN` is honest: it signals that speaker identity has not been determined. This distinction matters when diarization arrives, so old un-diarized episodes can be identified and re-ingested.

**`SPEAKER_00` is episode-scoped, not global:** The same `SPEAKER_00` identifier in two different episodes refers to two different people. Speaker name resolution in `ToolDispatcher` is scoped to the session's feed IDs to prevent cross-feed collisions. Chunks ingested before multi-feed support was introduced may have ambiguous `speaker_id` values — re-ingestion resolves this.

**Speaker states:**

| speaker_id   | name_inferred | name_confirmed | confidence            | Meaning                                  |
| ------------ | ------------- | -------------- | --------------------- | ---------------------------------------- |
| `UNKNOWN`    | false         | false          | NULL                  | No diarization; inference found nothing  |
| `SPEAKER_00` | true          | false          | "high"/"medium"/"low" | LLM inferred one speaker, unconfirmed    |
| `SPEAKER_00` | true          | true           | "high"/"medium"/"low" | Inferred, user confirmed without editing |
| `SPEAKER_00` | false         | true           | NULL                  | User entered or edited name manually     |

**Resolution at read time:** All reads join `episode_speakers` on `speaker_id`. `VectorStore.search()` returns `RawChunkResult` with `speaker_id`. `ResultHydrator` resolves to `display_name` (or `NULL` / "Unknown Speaker" fallback) before returning to callers. Speaker filter queries against `UNKNOWN` speaker_id return no results — expected behavior until diarization runs.

---

### 3.9 SSE Status Streaming

```
GET /api/v1/episodes/{episode_id}/status/stream
→ text/event-stream

data: {"status": "QUEUED", "position": 3}
data: {"status": "DOWNLOADING", "progress": 0.2}
data: {"status": "TRANSCRIBING", "stage": "whisper", "progress": 0.4}
data: {"status": "INFERRING_SPEAKERS"}
data: {"status": "CHUNKING", "progress": 0.5}
data: {"status": "EMBEDDING", "progress": 0.8}
data: {"status": "READY"}
```

Stream closes on `READY` or `ERROR`. No `PENDING_NAMES` pause in v1 — the pipeline runs to completion without waiting for user input. Polling fallback: `GET /api/v1/episodes/{episode_id}/status`.

---

### 3.10 Query Engine

The query engine is a thin orchestrator that delegates to discrete components. Uses `LLMClient` Protocol throughout.

#### Components

**`PromptBuilder` (`src/query/prompt_builder.py`)**
```python
class PromptBuilder:
    def build_system_prompt(self, session: ChatSession) -> str: ...
    def build_messages(self, session: ChatSession) -> list[dict]: ...
```
Pure logic, no I/O. Fully unit testable. System prompt is rebuilt on every `build_messages()` call — no stale state. Includes scope instructions when `scope_feed_ids` or `scope_episode_ids` are set; these are belt-and-suspenders — real enforcement is in `ToolDispatcher` filters.

**`ToolDispatcher` (`src/query/tool_dispatcher.py`)**
```python
class ToolDispatcher:
    def __init__(self, retriever: Retriever): ...

    async def dispatch(self, tool_call: ToolCall, session: ChatSession, db: AsyncSession) -> str:
        # Routes to correct tool implementation
        # db passed per-call, consistent with ResultHydrator and Retriever patterns
        # Returns JSON string for LLM consumption
        # All results use display_name, never speaker_id
        # Outer try/except returns JSON error string rather than raising
```

Speaker name → `speaker_id` resolution in `_search_knowledge_base` is scoped to `session.scope_feed_ids`
to prevent cross-feed `SPEAKER_00` collisions. Uses `.first()` — returns a row with `.speaker_id` attribute.
If no match: proceeds with `speaker_id=None` (unfiltered) rather than returning an error.

Citations are appended to `session.citations` after every successful `_search_knowledge_base` call and
accumulate across all tool rounds in the session.

**`ResultHydrator` (`src/query/result_hydrator.py`)**
```python
class ResultHydrator:
    async def hydrate(
        self,
        raw: list[RawChunkResult],
        db: AsyncSession
    ) -> list[ChunkResult]:
        # Resolves speaker_id → display_name via episode_speakers join
        # Fetches episode title and audio_url
        # Formats timestamp_display
        # Batched: one query per table, never N+1
```

`ChunkResult` carries `text` (leaf, for citation display), `parent_text` (full topic segment, for LLM context),
and `audio_url` (for frontend audio playback). Episode data fetched in a single batched query as a dict:
`{"title": row.title, "audio_url": row.audio_url}` — do not store whole SQLAlchemy Row objects, as they
are only valid during iteration.

**`_build_context` in `src/api/routers/query.py`**

Uses `chunk.parent_text or chunk.text` for the LLM context block. The leaf `text` is what matched the query; the `parent_text` is the full topic segment the LLM needs to reason about. Both are available on `ChunkResult` for frontend use.

**`SessionStore` (`src/query/session_store.py`)**

See Protocol definition in section 3.3. v1 implementation is `InMemorySessionStore` — dict on `app.state`. Sessions are ephemeral — cleared on process restart. `DBSessionStore` (post-v1) satisfies the same Protocol.

#### Engine orchestration (`src/query/engine.py`)

```python
class QueryEngine:
    def __init__(
        self,
        llm_client: LLMClient,
        session_store: SessionStore,
        prompt_builder: PromptBuilder,
        tool_dispatcher: ToolDispatcher,
        max_tool_rounds: int = 3,
    ): ...

    async def chat(self, session_id: str, user_message: str, db: AsyncSession) -> ChatResponse:
        session = await self.session_store.get(session_id)
        if session is None:
            raise ValueError(f"Session not found: {session_id}")

        session.messages.append({"role": "user", "content": user_message})

        for round_num in range(self.max_tool_rounds):
            messages = self.prompt_builder.build_messages(session)
            response = await self.llm_client.complete(messages, tools=TOOLS)

            if not response.tool_calls:
                break   # LLM has a final answer

            # Assistant tool call message must precede tool result messages
            session.messages.append({
                "role": "assistant",
                "tool_calls": [...]   # serialized with json.dumps, not str()
            })

            for tc in response.tool_calls:
                result = await self.tool_dispatcher.dispatch(tc, session, db)
                session.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,   # must match assistant tool call id
                    "content": result,
                })
        else:
            # for/else: loop exhausted without break — max rounds hit
            # Make one final synthesis call with explicit instruction
            synthesis_messages = self.prompt_builder.build_messages(session)
            synthesis_messages.append({
                "role": "user",
                "content": "Based on the search results above, please provide your best answer now."
            })
            response = await self.llm_client.complete(synthesis_messages)

        final_content = response.content or ""
        session.messages.append({"role": "assistant", "content": final_content})
        await self.session_store.save(session)
        return ChatResponse(message=final_content, session_id=session_id, citations=session.citations)
```

**Critical message ordering:** The OpenAI API requires that a `tool` message with `tool_call_id: X` is
always preceded by an `assistant` message that requested `X`. Missing or mismatched IDs produce API errors.

**`arguments` serialization:** Tool call arguments must be serialized with `json.dumps()` when appended to
the assistant message. Using `str()` on a Python dict produces single-quoted syntax that LLM servers reject
as invalid JSON.

**`for/else` synthesis:** Python's `for/else` fires the `else` block when the loop completes without a
`break`. When max rounds are exhausted, a final LLM call without tools forces a text response using whatever
was retrieved across all rounds.

**Request timeout:** Each `llm_client.complete()` call (both tool-calling rounds and the final synthesis
call) is wrapped in `asyncio.wait_for(..., timeout=LLM_REQUEST_TIMEOUT_SECONDS)` (60s, module-level constant
in `engine.py`). A timeout raises `LLMTimeoutError`, caught in `src/api/routers/chat.py` and mapped to
`504 Gateway Timeout`. The session is never saved when a timeout fires — `SessionStore.save()` only runs
on the success path at the end of `chat()` — so a timed-out request leaves no partial state and is safe
to retry. The whole `chat()` body runs inside a custom `"chat"` tracing span (`session.id`,
`chat.tool_rounds_used`, `chat.citation_count` on success; `record_exception` + `set_status` on any
exception) — this is orchestration-level instrumentation, distinct from the automatic per-call spans
`OpenAIInstrumentor` already provides for each `llm_client.complete()` call.

**`ChatResponse`:**
```python
@dataclass
class ChatResponse:
    message: str
    session_id: str
    citations: list[dict]
```

#### Tool definitions (`src/query/tools.py`)

Three tools in OpenAI function-calling format. The model reads these descriptions to decide when and how to call each tool.

| Tool | When used | Key parameters |
|------|-----------|----------------|
| `search_knowledge_base` | Topic queries, opinion questions, factual lookups | `query` (required), `speaker_name`, `episode_id`, `top_k` |
| `get_episode_context` | Expanding a specific timestamp from a prior citation | `episode_id`, `timestamp_ms`, `padding_ms` |
| `get_speaker_profile` | Questions about a person rather than a topic | `speaker_name` |

Query strings should be descriptive phrases rather than questions — embedding models match text, not
question syntax. The tool description instructs the model accordingly.

---

### 3.11 Data Layer — PostgreSQL + pgvector

**Schema:**

```sql
feeds (
  id UUID PRIMARY KEY,
  rss_url TEXT UNIQUE NOT NULL,
  title TEXT, description TEXT, image_url TEXT,
  last_fetched_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
)

episodes (
  id UUID PRIMARY KEY,
  feed_id UUID REFERENCES feeds ON DELETE CASCADE,
  guid TEXT UNIQUE NOT NULL,
  title TEXT, description TEXT, published_at TIMESTAMPTZ,
  audio_url TEXT, audio_local_path TEXT, transcript_url TEXT,
  duration_seconds INT,
  pipeline_status TEXT NOT NULL DEFAULT 'PENDING',
  pipeline_stage TEXT,
  pipeline_progress FLOAT,
  pipeline_error TEXT,
  ingestion_job_id TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
)

episode_speakers (
  id UUID PRIMARY KEY,
  episode_id UUID REFERENCES episodes ON DELETE CASCADE,
  speaker_id TEXT NOT NULL,        -- 'UNKNOWN' (no diarization) or 'SPEAKER_00', 'SPEAKER_01', etc.
  display_name TEXT,               -- mutable; only location of display name
  name_inferred BOOLEAN DEFAULT false,
  name_confirmed BOOLEAN DEFAULT false,
  confidence TEXT,                 -- 'high' | 'medium' | 'low' | NULL (not inferred)
  UNIQUE(episode_id, speaker_id)
)

transcript_segments (
  id UUID PRIMARY KEY,
  episode_id UUID REFERENCES episodes ON DELETE CASCADE,
  speaker_id TEXT NOT NULL,        -- 'UNKNOWN' in v1 (no diarization); join to episode_speakers for display_name
  text TEXT NOT NULL,
  start_ms INT NOT NULL, end_ms INT NOT NULL, sequence_order INT NOT NULL
)
-- No display_name column

chunks (
  id UUID PRIMARY KEY,
  episode_id UUID REFERENCES episodes ON DELETE CASCADE,
  parent_id UUID REFERENCES chunks,
  chunk_level TEXT NOT NULL,       -- 'parent' | 'leaf'
  speaker_id TEXT NOT NULL,        -- 'UNKNOWN' in v1 (no diarization); join to episode_speakers for display_name
  text TEXT NOT NULL,
  start_ms INT NOT NULL, end_ms INT NOT NULL,
  token_count INT,
  embedding vector(768),
  created_at TIMESTAMPTZ DEFAULT now()
)
-- No display_name column

CREATE INDEX ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

**Design principles:**
- `display_name` exists only in `episode_speakers`
- `transcript_segments` and `chunks` store `speaker_id` only
- `VectorStore.search()` returns raw results with `speaker_id`; `ResultHydrator` resolves names
- All cascade deletes defined
- `FeedResponse.latest_episode_published_at` is not a stored column — derived via `MAX(episodes.published_at)` grouped by feed (`feed_service.list_feeds()`, `feed_service.get_feed_stats()`); always recomputed at read time
-


---

### 3.12 Observability — OpenTelemetry + Phoenix

**Transport:** OTLP/HTTP via `opentelemetry-exporter-otlp-proto-http`.
TLS is implicit from the endpoint URL scheme — `http://` is plaintext,
`https://` is TLS. No `insecure` flag exists on the HTTP exporter; this is
an HTTP convention, unlike gRPC which defaults to TLS and requires an explicit
opt-out.

**Processor:** `SimpleSpanProcessor` — exports synchronously on every span.
Appropriate for a single-user application. `BatchSpanProcessor` is designed
for high-throughput multi-user scenarios where buffering reduces collector load.

**Auto-instrumentation:** `OpenAIInstrumentor().instrument()` patches the
OpenAI SDK globally at startup. Every `LLMClient.complete()` call emits a
span automatically — prompt content, response, token counts, model name,
finish reason. No changes to `LLMClient` or `client.py` required.

**Project routing:** Phoenix routes spans to projects via the
`openinference.project.name` resource attribute set on `TracerProvider`.
Configured via `OTEL_PROJECT_NAME` — defaults to `"podcast-engine"`.

**Setup (`src/telemetry/setup.py`):**
```python
def setup_telemetry(settings: Settings) -> None:
    if not settings.tracing_enabled:
        return  # no-op — app runs normally without a collector configured

    # OTel imports deferred — missing packages don't error when tracing disabled
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from openinference.instrumentation.openai import OpenAIInstrumentor

    resource = Resource(attributes={
        "openinference.project.name": settings.otel_project_name,
    })

    headers = {}
    if settings.otel_api_key:
        headers["Authorization"] = f"Bearer {settings.otel_api_key}"

    exporter = OTLPSpanExporter(
        endpoint=settings.otel_endpoint,
        headers=headers,
    )

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    OpenAIInstrumentor().instrument()

    logger.info(f"Tracing enabled — exporting to {settings.otel_endpoint}")
```

**Shared tracer (`src/telemetry/tracer.py`):**
```python
from opentelemetry import trace
tracer = trace.get_tracer("podcast-engine")
```
Safe to import before `setup_telemetry()` runs — returns a no-op tracer until
a provider is registered. Import in any file that needs custom spans:
```python
from src.telemetry.tracer import tracer
```

**Custom spans:**

| File                      | Span name                     | Key attributes                                                                                                                                             |
| ------------------------- | ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pipeline.py`             | `ingest_episode`              | `episode.id`, `episode.title`, `episode.has_transcript_url`, chunk counts, `episode.inferred_speaker`                                                      |
| `audio_downloader.py`     | `audio_download`              | `audio.url`, `audio.size_bytes`, `audio.bytes_received`                                                                                                    |
| `transcription/local.py`  | `transcription`               | `transcription.backend`, `transcription.model`, `transcription.language`, `transcription.diarization_enabled`, `transcription.segment_count`               |
| `transcription/remote.py` | `transcription`               | `transcription.backend`, `transcription.service_url`, `transcription.language`, `transcription.segment_count`                                              |
| `speaker_resolver.py`     | `speaker_inference`           | `speaker.intro_segment_count`, `speaker.name_found`, `speaker.confidence`                                                                                  |
| `embedder.py`             | `embedding`                   | `embedding.leaf_count`, `embedding.batch_size`, `embedding.batch_count`                                                                                    |
| `retriever.py`            | `retrieval`                   | `retrieval.query`, `retrieval.top_k`, `retrieval.feed_ids`, `retrieval.result_count`, `retrieval.score_max`, `retrieval.score_min`, `retrieval.score_mean` |
| LLM calls                 | auto via `OpenAIInstrumentor` | tokens, model, prompt/response                                                                                                                             |

**Error recording pattern:**
```python
except Exception as e:
    span.record_exception(e)           # full stack trace as span event
    span.set_status(trace.StatusCode.ERROR, str(e))
    raise
```
Use for unrecoverable failures only. Handled exceptions (e.g. RSS transcript
fallback that recovers to audio download) should log only — do not mark the
span ERROR if the pipeline continues successfully.

**Why transcription spans wrap the executor await:**
OTel context does not cross `ProcessPoolExecutor` subprocess boundaries. Spans
started inside `_transcribe_sync` would appear as orphaned traces with no
parent. The `transcription` span wraps `run_in_executor()` in the async layer
instead — wall-clock duration covers the full subprocess call including model
loading, inference, and diarization. Sub-span timing for Whisper vs Pyannote
separately requires splitting `_transcribe_sync` into two executor calls —
see Future Scope 1.6.

**Backend switching:** Local Phoenix, hosted Arize, Langfuse, or any
OTLP/HTTP collector — change `OTEL_ENDPOINT` in `.env`. No code changes
required.

```bash
# Local Phoenix in Docker
OTEL_ENDPOINT=http://localhost:6006/v1/traces

# Arize hosted
OTEL_ENDPOINT=https://app.phoenix.arize.com/s/{username}/v1/traces
OTEL_API_KEY=your-key-here
```

Phoenix runs as optional Docker Compose profile:
```bash
docker compose --profile observability up
```

---

### ### 3.13 Frontend — React + Vite

**Tech stack (as built, Phase 8):**
- React 19 + TypeScript, Vite 8, Tailwind v4 via `@tailwindcss/vite` plugin
- shadcn/ui (Radix style, custom mist theme), remixicon + lucide-react icon libraries
- TanStack Query v5 for server state, React Router v7 for routing
- axios for HTTP, Yarn as package manager
- `react-markdown` for LLM response rendering in chat
- `react-resizable-panels` via shadcn `Resizable` for split-panel chat layout
- Path alias: `@/*` → `src/*` in both tsconfig and vite config

**TanStack Query defaults (`main.tsx`):**

```typescript
new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
    },
  },
})
```

`staleTime: 30_000` is global — any `useQuery` without its own `staleTime` override is considered fresh for 30 seconds after a successful fetch, even across component remounts. This matters when debugging "data isn't updating" symptoms: a remounted query that doesn't refetch is not necessarily a missing-invalidation bug — check whether the 30-second window is simply still open before assuming the cache key is wrong. Explicit `invalidateQueries()` calls bypass `staleTime` entirely and force a refetch regardless of this window; `useChatSession`'s `staleTime: Infinity` (below) is a per-hook override of this default, set for a different reason (session-orphaning prevention, not general staleness tolerance).

**Feed/episode cache invalidation pattern (`lib/queryInvalidation.ts`):**

Feed-level mutations (refresh, delete) affect data cached under multiple, separate query keys — `['feeds']` (list), `['feed', feedId]` (detail), and `['episodes', feedId]` (episode list for that feed). A mutation invalidating only the query key for the page it's triggered from leaves the others stale; this happened independently in four places before being consolidated. Two shared helpers encode the relationship once:

```typescript
invalidateFeedAndEpisodes(queryClient, feedId)       // feed refresh — all three keys still valid, just stale
invalidateAfterFeedDelete(queryClient, feedId)       // feed delete — detail/episode keys removed via removeQueries(); list key invalidated
invalidateEpisode(queryClient, episodeId, feedId)    // any single-episode mutation (reingest, transcript delete) — invalidates ['episode', episodeId] and ['episodes', feedId]; does not touch feed-level keys
```

Any new mutation that changes feed or episode data should use these helpers rather than inlining `invalidateQueries()` calls — the rule is about the data relationship, not about which page or component triggers the change. The `invalidateEpisode` helper was introduced in Phase 11 after the same missing-key bug (status not updating cross-page mid-ingestion) was found independently across four mutations.

**App shell layout:**
- `Layout.tsx` uses `h-screen flex flex-col` — nav takes natural height, `<main>` is `flex-1 overflow-auto p-6`
- Pages using resizable panels (`EpisodesPage`, `EpisodeDetailPage`) get `h-full` from the flex shell and manage their own scroll/padding
- `ChatPage` is lazy-loaded via `React.lazy()` + `Suspense` to keep initial bundle under Vite's 500kb warning threshold

**Chat contexts — three entry points:**

| Context | Route | Scope |
| ------- | ----- | ----- |
| All feeds | `/chat` | No scope — all ingested episodes |
| Single feed | `/feeds/:feedId/episodes` | `scopeFeedIds={[feedId]}` |
| Single episode | `/episodes/:episodeId` | `scopeEpisodeIds={[episodeId]}` |

**Key components:**

- `ChatInterface` — reusable chat UI; accepts optional `scopeFeedIds` and `scopeEpisodeIds` props; owns session via `useChatSession`; `flex flex-col h-full` layout; toolbar shown only when no scope set; `SearchFilterList` sheet rendered only when no scope set
- `CitationList` — collapsible citation block per assistant message; top 7 by similarity score; audio playback via `#t=` URI fragment (Media Fragments spec — browser seeks natively, no JS event listener needed); chunk ID copy button; similarity score badge
- `SearchFilterList` — Sheet-based knowledge base browser (`side="left"`); self-contained, fetches its own feeds data; accordion per feed (`type="multiple"`); lazy episode fetch per feed from TanStack cache; read-only in V1; navigate buttons close sheet and route to feeds/episodes pages
- `EpisodeRow` — episode card; owns its own SSE connection via `useEpisodeStatus`; derives `isActive` from live status not cached status
- `SpeakerRow` — speaker display with confidence badge; popover edit with cancel/save
- `Layout` — nav shell with `NavLink`

**Resizable panel pattern (`EpisodesPage`, `EpisodeDetailPage`):**

```tsx
<ResizablePanelGroup orientation="horizontal" className="h-full">
  <ResizablePanel defaultSize="100%" minSize="50%">
    {/* page content — overflow-y-auto h-full p-6 on inner div */}
  </ResizablePanel>
  <ResizableHandle withHandle />
  <ResizablePanel
    panelRef={chatPanelRef}   // usePanelRef() from react-resizable-panels
    defaultSize={0}
    minSize={320}             // pixels, not percentage — prevents overflow at narrow widths
    maxSize="50%"
    collapsible
    onResize={(size) => setChatOpen(size.asPercentage > 0)}
    className="flex flex-col h-full"
  >
    <div className="shrink-0 flex items-center p-2 border-b">
      {/* panel header with close button */}
    </div>
    <div className="flex-1 min-h-0 overflow-hidden">
      <ChatInterface scopeFeedIds/scopeEpisodeIds />
    </div>
  </ResizablePanel>
</ResizablePanelGroup>
```

**Critical layout notes:**
- `min-h-0` on the `ChatInterface` wrapper div is required — without it a flex child won't shrink below its content size and internal scroll breaks
- `overflow-hidden` on the same wrapper clips content during collapse animation, preventing horizontal scrollbar at zero panel width
- `onCollapse`/`onExpand` callbacks were removed in current `react-resizable-panels`; use `onResize={(size) => setChatOpen(size.asPercentage > 0)}` instead
- `panelRef` prop + `usePanelRef()` hook are the current imperative API; `ref` prop and `ImperativePanel` type are no longer exported

**`useChatSession` hook:**

Uses `useQuery` (not `useEffect`) for session creation. React 19 StrictMode double-mounts components in development — a raw `useEffect` triggered two `POST /chat/sessions` calls. TanStack Query's internal deduplication prevents duplicate in-flight requests for the same query key.

```typescript
useQuery({
  queryKey: ['chat-session', scopeFeedIds ?? [], scopeEpisodeIds ?? []],
  queryFn: () => createChatSession(scopeFeedIds ?? [], scopeEpisodeIds ?? []),
  staleTime: Infinity,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
})
```

`staleTime: Infinity` prevents refetch on window focus or reconnect from creating a new session and orphaning the conversation. `resetSession` invalidates the cache entry and refetches, used for 404 recovery.

**SSE / TanStack cache pattern:**

SSE delivers real-time pipeline updates; TanStack Query cache is what React renders from. The `useEpisodeStatus` hook bridges them: on terminal status (`READY` or `ERROR`), it invalidates `['episodes']` and `['episode', episodeId]` cache keys. Without this, `episode.pipeline_status` stays stale after ingestion and the SSE hook cannot reopen on reingest.

**Session state:**

Chat session state lives in `ChatInterface` component. `InMemorySessionStore` on the backend is ephemeral — sessions are lost on server restart. Frontend handles 404 on stale session: shows error message, calls `resetSession()` to create a fresh session automatically.

**Docker note:**

Frontend Docker build (`frontend/Dockerfile` and `frontend` service in `docker-compose.yml`) has not been validated against the Tailwind v4 Vite plugin build. Verify before demo deployment.

---

## 4. Configuration Reference (.env)

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/podcast_engine

# LLM — any OpenAI-compatible endpoint
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL_NAME=llama3.1:8b

# Embeddings
EMBEDDING_BASE_URL=http://localhost:11434/v1
EMBEDDING_API_KEY=ollama
EMBEDDING_MODEL_NAME=nomic-embed-text
EMBEDDING_DIMENSIONS=768

# Transcription
TRANSCRIPTION_BACKEND=local             # local | remote
TRANSCRIPTION_SERVICE_URL=http://localhost:8001
WHISPER_BACKEND=faster_whisper          # faster_whisper | mlx_whisper
WHISPER_MODEL=medium               # tiny | base | small | medium | large-v3
DIARIZATION_MODEL=                      # leave empty to skip; very slow on CPU and non-CUDA GPUs; Ignored when TRANSCRIPTION_BACKEND=remote (remote service owns diarization)

# Speaker inference
SPEAKER_INFERENCE_WINDOW_MS=900000

# Ingestion
MAX_CONCURRENT_INGESTIONS=2

# Observability
TRACING_ENABLED=false
OTEL_ENDPOINT=http://localhost:6006/v1/traces
OTEL_API_KEY=                        # required for hosted Phoenix/Arize
OTEL_PROJECT_NAME=podcast-engine


# App
LOG_LEVEL=INFO
AUDIO_STORAGE_PATH=./data/audio
CHUNK_SIZE_TOKENS=256
CHUNK_OVERLAP_TOKENS=32
CHUNK_MIN_TOKENS=20
TOPIC_SIMILARITY_THRESHOLD=0.75

HUGGINGFACE_TOKEN=


# Demo auth
DEMO_AUTH_ENABLED=false
DEMO_USERNAME=demo
DEMO_PASSWORD=changeme
```

---

## 5. API Reference

Full OpenAPI docs at `/docs` (Swagger) and `/redoc`.

### Feeds
```
GET    /api/v1/feeds                          Query: ?sort=created_at|latest_episode (default created_at, descending only)
POST   /api/v1/feeds                          Body: { rss_url }
GET    /api/v1/feeds/{feed_id}
DELETE /api/v1/feeds/{feed_id}
POST   /api/v1/feeds/{feed_id}/refresh
GET    /api/v1/feeds/{feed_id}/episodes
```

### Episodes
```
GET    /api/v1/episodes/{episode_id}
POST   /api/v1/episodes/{episode_id}/ingest   Body: { speaker_count_hint? }
POST   /api/v1/episodes/{episode_id}/reingest
GET    /api/v1/episodes/{episode_id}/transcript
DELETE /api/v1/episodes/{episode_id}/transcript
GET    /api/v1/episodes/{episode_id}/status         (polling)
GET    /api/v1/episodes/{episode_id}/status/stream  (SSE)
```

### Speakers
```
GET    /api/v1/episodes/{episode_id}/speakers
GET    /api/v1/episodes/{episode_id}/speakers/preview
PUT    /api/v1/episodes/{episode_id}/speakers       Body: [{speaker_id, display_name}]
```

### Chat
```
POST   /api/v1/chat/sessions                  Body: { scope_feed_ids?: UUID[], scope_episode_ids?: UUID[] }
POST   /api/v1/chat/{session_id}/message      Body: { message }
GET    /api/v1/chat/{session_id}/history
DELETE /api/v1/chat/{session_id}
```

### System
```
GET    /api/v1/health
GET    /api/v1/health/deep
GET    /api/v1/config/models
```

### Example: Full flow via curl

```bash
# Add feed
curl -X POST http://localhost:3001/api/v1/feeds \
  -H "Content-Type: application/json" \
  -d '{"rss_url": "https://feeds.example.com/podcast.rss"}'

# Ingest episode
curl -X POST http://localhost:3001/api/v1/episodes/ep-uuid/ingest \
  -H "Content-Type: application/json" \
  -d '{"speaker_count_hint": 2}'
# → { "status": "accepted", "job_id": "job-uuid", "queue_position": 1 }

# Stream status
curl -N http://localhost:3001/api/v1/episodes/ep-uuid/status/stream

# Check inferred speakers
curl http://localhost:3001/api/v1/episodes/ep-uuid/speakers

# Confirm names
curl -X PUT http://localhost:3001/api/v1/episodes/ep-uuid/speakers \
  -H "Content-Type: application/json" \
  -d '[{"speaker_id": "SPEAKER_00", "display_name": "Marcus Webb"}]'

# Start chat session scoped to one or more feeds
curl -X POST http://localhost:3001/api/v1/chat/sessions \
  -H "Content-Type: application/json" \
  -d '{"scope_feed_ids": ["feed-uuid-1", "feed-uuid-2"]}'

# Query
curl -X POST http://localhost:3001/api/v1/chat/sess-uuid/message \
  -H "Content-Type: application/json" \
  -d '{"message": "What does Marcus think about AGI timelines?"}'

# Get history with citations
curl http://localhost:3001/api/v1/chat/sess-uuid/history
```

---

## 6. Project Structure

```
podcast-knowledge-engine/
├── backend/
│   ├── src/
│   │   ├── api/
│   │   │   ├── main.py
│   │   │   ├── routers/
│   │   │   │   ├── feeds.py
│   │   │   │   ├── episodes.py
│   │   │   │   ├── speakers.py
│   │   │   │   ├── chat.py
│   │   │   │   └── health.py
│   │   │   ├── middleware/
│   │   │   │   └── auth.py
│   │   │   └── dependencies.py      # ALL dependency wiring lives here
│   │   ├── llm/
│   │   │   ├── base.py              # LLMClient + EmbeddingClient Protocols, ToolCall, LLMResponse
│   │   │   └── client.py            # OpenAICompatibleLLMClient + OpenAICompatibleEmbeddingClient
│   │   ├── ingestion/
│   │   │   ├── pipeline.py          # Thin orchestrator only
│   │   │   ├── pipeline_runner.py   # Worker-side: builds PipelineServices, runs ingest_episode
│   │   │   ├── queue.py             # IngestionQueue Protocol + StreaqQueue + BackgroundTaskQueue
│   │   │   ├── rss_parser.py
│   │   │   ├── audio_downloader.py
│   │   │   ├── transcript_store.py  # Save/retrieve transcript_segments
│   │   │   ├── speaker_resolver.py  # LLM inference via LLMClient
│   │   │   ├── speaker_store.py     # Read/write episode_speakers
│   │   │   ├── status_service.py    # PipelineStatusService
│   │   │   ├── chunker.py           # Speaker-boundary + topic segmentation + min_tokens merge
│   │   │   └── embedder.py          # Uses EmbeddingClient
│   │   ├── transcription/
│   │   │   ├── base.py              # TranscriptionService Protocol + data types
│   │   │   ├── local.py             # Whisper + Pyannote via ProcessPoolExecutor
│   │   │   └── remote.py            # HTTP client
│   │   ├── storage/
│   │   │   └── vector_store.py      # VectorStore Protocol + PgvectorStore; SearchFilters with feed_ids
│   │   ├── query/
│   │   │   ├── engine.py            # Thin orchestrator; tool-calling loop; for/else synthesis
│   │   │   ├── prompt_builder.py    # Pure logic, no I/O; scope-aware system prompt
│   │   │   ├── tool_dispatcher.py   # Routes tool calls; speaker resolution; citation collection
│   │   │   ├── tools.py             # Tool definitions (OpenAI function format)
│   │   │   ├── retriever.py         # Composes EmbeddingClient + VectorStore + ResultHydrator
│   │   │   ├── result_hydrator.py   # Resolves speaker_id → display_name + audio_url; defines ChunkResult
│   │   │   └── session_store.py     # SessionStore Protocol + InMemorySessionStore; ChatSession
│   │   ├── models/
│   │   │   ├── db.py                # SQLAlchemy models
│   │   │   └── schemas.py           # Pydantic request/response schemas
│   │   ├── telemetry/
│   │   │   ├── setup.py              # OTel provider, exporter, OpenAIInstrumentor
│   │   │   └── tracer.py             # shared tracer singleton
│   │   └── config.py
│   │   ├── worker.py                # streaQ Worker + WorkerContext lifespan; entry point for `streaq run`
│   ├── tests
│   │   ├── conftest.py
│   │   ├── fixtures
│   │   │   ├── sample_feed.xml
│   │   │   └── sample_transcript.json
│   │   ├── integration
│   │   │   ├── conftest.py
│   │   │   ├── test_feeds.py
│   │   │   ├── test_ingestion_pipeline.py
│   │   │   ├── test_queue.py
│   │   │   └── test_speakers.py
│   │   └── unit
│   │       ├── test_auth_middleware.py
│   │       ├── test_background_queue.py
│   │       ├── test_chunker.py
│   │       ├── test_engine.py
│   │       ├── test_itunes.py
│   │       ├── test_prompt_builder.py
│   │       ├── test_result_hydrator.py
│   │       ├── test_retriever.py
│   │       ├── test_rss_parser.py
│   │       ├── test_schemas.py
│   │       ├── test_speaker_resolver.py
│   │       └── test_tool_dispatcher.py
│   ├── pyproject.toml
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   └── client.ts            # Typed axios wrapper; all backend types and endpoint functions
│   │   ├── components/
│   │   │   ├── ui/                  # shadcn/ui components (button, badge, card, input, sheet,
│   │   │   │                        #   accordion, collapsible, resizable, separator, popover,
│   │   │   │                        #   dropdown-menu, alert-dialog, etc.)
│   │   │   ├── ChatInterface.tsx    # Reusable chat UI; scopeFeedIds/scopeEpisodeIds props
│   │   │   ├── CitationList.tsx     # Collapsible citations; audio playback via #t= fragment
│   │   │   ├── ErrorBoundary.tsx    # Class component wrapping all routes
│   │   │   ├── EpisodeKebab.tsx     # Episode reingest/delete-transcript menu; AlertDialog confirm; MutationLike exported
│   │   │   ├── EpisodeRow.tsx       # Episode card; owns SSE connection; EpisodeKebab when status !== PENDING
│   │   │   ├── ExpandableDescription.tsx # Plain text preview + markdown expanded view
│   │   │   ├── FeedKebab.tsx        # Reusable refresh/delete menu; AlertDialog confirm; narrow MutationLike prop type
│   │   │   ├── Layout.tsx           # Nav shell; h-screen flex flex-col; main is flex-1 overflow-auto
│   │   │   ├── SearchFilterList.tsx # Sheet-based knowledge base browser; self-contained data fetch
│   │   │   ├── SpeakerRow.tsx       # Speaker display + popover edit
│   │   │   └── TranscriptViewer.tsx # Expand/collapse; standalone and reusable
│   │   ├── hooks/
│   │   │   ├── useChatSession.ts    # TanStack useQuery session creation; StrictMode-safe
│   │   │   └── useEpisodeStatus.ts  # SSE hook; invalidates TanStack cache on terminal status
│   │   ├── lib/
│   │   │   ├── date.ts              # formatDate, formatDuration, formatRelativeDate (Intl.RelativeTimeFormat)
│   │   │   ├── episode.ts           # ACTIVE_STATUSES; episode-specific logic only — date helpers moved to date.ts
│   │   │   ├── queryInvalidation.ts # invalidateFeedAndEpisodes, invalidateAfterFeedDelete, invalidateEpisode — shared cache invalidation rules
│   │   │   ├── text.ts              # stripMarkdown()
│   │   │   └── utils.ts             # shadcn cn() helper
│   │   ├── pages/
│   │   │   ├── ChatPage.tsx         # Thin wrapper around ChatInterface; lazy-loaded
│   │   │   ├── EpisodeDetailPage.tsx # Full detail, ingest/EpisodeKebab (reingest + delete transcript), speakers, transcript; resizable chat panel
│   │   │   ├── EpisodesPage.tsx     # List with search, filter, pagination; resizable chat panel
│   │   │   └── FeedsPage.tsx        # Add/sort feeds; refresh/delete via FeedKebab
│   │   ├── App.tsx                  # Route definitions; ErrorBoundary wraps routes; ChatPage lazy-loaded
│   │   ├── index.css                # @import "tailwindcss"
│   │   └── main.tsx                 # QueryClientProvider + StrictMode + App mount
│   ├── components.json              # shadcn config; aliases use explicit src/ paths
│   ├── package.json
│   ├── tsconfig.app.json            # @/* alias → src/*
│   ├── vite.config.ts               # Tailwind v4 plugin, proxy, @/* alias
│   └── yarn.lock
├── transcription-service/
│   ├── main.py
│   ├── pyproject.toml
│   └── Dockerfile
├── docker-compose.yml
├── docker-compose.db.yml
├── .env.example
├── ARCHITECTURE.md
├── IMPLEMENTATION_PLAN.md
├── FUTURE_SCOPE.md
├── OPERATIONS.md
└── README.md
```

---

## 7. Docker Compose

```yaml
# docker-compose.yml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: ${DB_NAME}
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d ${DB_NAME}"]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    # No persistence by default -- queued/in-flight jobs are lost if this
    # container restarts. See FUTURE_SCOPE.md 2.1c for adding durability.
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    env_file: backend/${BACKEND_ENV_FILE:-.env}
    environment:
      DATABASE_URL: postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@db:5432/${DB_NAME}
      REDIS_URL: redis://redis:6379
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: ["./entrypoint.sh", "worker"]
    env_file: backend/${BACKEND_ENV_FILE:-.env}
    environment:
      DATABASE_URL: postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@db:5432/${DB_NAME}
      REDIS_URL: redis://redis:6379
    volumes:
      - model_cache:/root/.cache/huggingface
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
    env_file: frontend/.env
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - backend
    restart: unless-stopped

volumes:
  pgdata:
  model_cache:
```

---

## 8. Testing Strategy

**Unit tests** — pure logic, no I/O, inject mocks:
- `Chunker` — boundaries, hierarchy, token limits, short segment merging
- `RSSParser` — fixture XML, duration formats, transcript tag detection
- `SpeakerResolver` — prompt construction, JSON parsing, null handling; inject `MockLLMClient`
- `PromptBuilder` — message construction, scope application; no I/O
- `ResultHydrator` — display name resolution, timestamp formatting, audio_url batching; mock DB
- `ToolDispatcher` — correct tool routing, filter application, citation population, speaker resolution
- `QueryEngine` — tool-calling loop, round limits, message ordering, citation passthrough
- `SessionStore` — save/retrieve/delete, key correctness

**Mock helpers** (`tests/conftest.py`) — plain classes, direct import in test files:
- `MockLLMClient` — supports `response_content`, `tool_calls`, and `responses: list[LLMResponse]` sequence
- `MockVectorStore` — configurable results, records last call args
- `MockHydrator` — configurable hydrated results
- `MockEmbeddingClient` — configurable vector output

**Integration tests** — real DB, mock LLM/transcription/embedding:
- Full ingestion pipeline with `sample_transcript.json` fixture (skips audio/Whisper)
- Speaker inference → confirmation → chunk `speaker_id` resolution via join
- Chat session: tool called for knowledge queries, not for summarization
- SSE stream: status transitions delivered correctly
- `PipelineStatusService`: writes correct status at each stage

**Contract tests** — verify all Protocol implementations:
- `LocalTranscriptionService` and `RemoteTranscriptionService` satisfy `TranscriptionService`
- `StreaqQueue` and `BackgroundTaskQueue` both satisfy `IngestionQueue`
- `PgvectorStore` satisfies `VectorStore`
- `InMemorySessionStore` satisfies `SessionStore`
- `OpenAICompatibleLLMClient` satisfies `LLMClient`
- `OpenAICompatibleEmbeddingClient` satisfies `EmbeddingClient`

```bash
uv run pytest tests/unit             # fast, no services
uv run pytest tests/integration      # requires running DB
uv run pytest --cov=src --cov-report=term-missing
```

---

## 9. Upgrade Path (Post-v1)

| Feature                  | What it requires                                                                                                                                     |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Graph RAG                | Post-chunking NER → entity/relationship tables; `search_graph` tool; new `GraphStore` Protocol                                                       |
| Persistent conversations | Implement `DBSessionStore` satisfying `SessionStore` Protocol; swap in `dependencies.py`                                                             |
| Query rewriting          | Pre-retrieval step in `engine.py`; `LLMClient.complete()` call; log original vs rewritten in telemetry                                               |
| Subprocess-level cancel  | Kill the OS-level Whisper subprocess on `cancel()`, not just the asyncio task — requires tracking PID across the `ProcessPoolExecutor` boundary        |
| Queue overview UI        | `queued_at`/`finished_at` columns on `Episode`; grouped-by-status read endpoint — pure Postgres, no `IngestionQueue` involvement                        |
| Automatic feed polling   | APScheduler; calls existing `refresh_feed` + `queue.enqueue()`                                                                                       |
| Alternative vector DBs   | Implement `VectorStore` Protocol for Qdrant/Pinecone; swap in `dependencies.py`; ~1 day                                                              |
| Speaker diarization      | See Future Scope 1.5. Reinstates `PENDING_NAMES` pipeline status; `UNKNOWN` speaker_ids get real diarization labels; existing episodes re-ingestable |
| Non-OpenAI LLM SDK       | Implement `LLMClient` Protocol; swap in `dependencies.py`; no business logic changes                                                                 |
| Chat response streaming  | `LLMClient.stream()` async generator; chat endpoint returns `EventSourceResponse`; applies to final synthesis only — tool rounds still block         |
| V2 chat scope filtering  | `GET /chat/{session_id}` returns full session object; `PATCH /chat/{session_id}` updates scope mid-conversation; frontend scope selector calls resetSession on change |

---

## 10. Quick Start

```bash
git clone https://github.com/youruser/podcast-knowledge-engine
cp .env.example .env
# Edit .env — DATABASE_URL, LLM_BASE_URL, LLM_MODEL_NAME at minimum

cd backend && uv sync
uv run alembic upgrade head
uv run uvicorn src.api.main:app --reload --port 8000

cd ../frontend && yarn && yarn dev

# Or full stack (Docker — frontend not yet validated with Tailwind v4 build)
docker compose up
docker compose --profile transcription --profile observability up
```

API docs: http://localhost:3001/docs
Frontend: http://localhost:3000
Phoenix: http://localhost:6006 (observability profile)

---

*Update this document when architectural decisions change during implementation. Note deviations with rationale.*

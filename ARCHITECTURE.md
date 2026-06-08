# Podcast Knowledge Engine — Architecture Document

> Version: 0.6
> Status: In implementation
> Author: Cameron Perry
> Last Updated: 2026-06-08

---

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
- Persistent job queue (semaphore-backed in-memory queue sufficient for v1)
- Speaker diarization (deferred — CPU/local diarization via Pyannote is impractical on non-CUDA hardware; see Future Scope section 1.5)

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        Frontend                          │
│                    React.js (Vite)                       │
│  Feed Mgmt │ Episode Mgmt │ Speaker UI │ Chat Interface  │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP / REST + SSE
┌────────────────────────▼────────────────────────────────┐
│                    Backend API                           │
│                  FastAPI + Python                        │
│                                                          │
│  /feeds   /episodes   /transcripts   /query   /health   │
│                                                          │
│  IngestionQueue (semaphore-backed, Protocol-abstracted)  │
└──────┬──────────────────────────────────────┬───────────┘
       │                                      │
┌──────▼──────────┐                ┌──────────▼──────────┐
│ Ingestion        │                │   Query Engine       │
│ Pipeline         │                │                      │
│ (orchestrator)   │                │  engine.py           │
│                  │                │  (thin orchestrator) │
│ AudioDownloader  │                │  ↕                   │
│ TranscriptionSvc │                │  PromptBuilder       │
│ SpeakerResolver  │                │  ToolDispatcher      │
│ Chunker          │                │  SessionStore        │
│ Embedder         │                │  ↕                   │
│ PipelineStatus   │                │  VectorStore         │
│   Service        │                │  ResultHydrator      │
└──────┬──────────┘                └──────────┬──────────┘
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
    # Returns BackgroundTaskQueue singleton from app.state

def get_transcription_service() -> TranscriptionService:
    # Returns LocalTranscriptionService or RemoteTranscriptionService
    # based on TRANSCRIPTION_BACKEND setting

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
    async def get_position(self, job_id: str) -> int: ...
    async def cancel(self, job_id: str) -> bool: ...
```

Implementations: `BackgroundTaskQueue` (v1, in-process), `ARQQueue` (post-v1, Redis-backed).

**Note:** `cancel()` returns `False` unconditionally in v1. Stuck jobs require a DB status update or uvicorn
restart to clear. See tech debt note in section 3.5.

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

#### Execution model

```
POST /ingest (HTTP request)
  │
  └─► BackgroundTaskQueue.enqueue()
        │
        ├─ Adds coroutine to asyncio event loop   ← runs independently of HTTP request
        ├─ Writes pipeline_status=QUEUED to DB    ← DB is source of truth
        └─ Returns job_id immediately

             [HTTP request ends — frontend can close, refresh, disconnect]

        Background coroutine continues running in uvicorn process:
          │
          ├─ Acquires semaphore slot
          ├─ Calls PipelineStatusService.set() at every stage transition
          ├─ Delegates CPU-bound work to ProcessPoolExecutor (Whisper, Pyannote)
          │    └─► asyncio event loop stays free — API remains responsive
          └─ Writes pipeline_status=READY (or ERROR) to DB when done

GET /episodes/{id}/status/stream (SSE — separate connection)
  │
  └─► Reads pipeline_status from DB every 2 seconds
        └─ Completely independent of the background coroutine
           Frontend can connect, disconnect, reconnect at any time
           Status is always current because DB is the source of truth
```

**Key point:** The background coroutine and the SSE stream are fully decoupled. The pipeline writes to the DB via `PipelineStatusService`. SSE reads from the DB. A page refresh drops the SSE connection but has no effect on the running job.

**Queue ordering:** Generally FIFO in practice — `asyncio.create_task()` schedules coroutines in order and the semaphore releases them in arrival order. Not a strict guarantee; two rapidly enqueued jobs could start in either order depending on event loop scheduling. For a single-user application this is acceptable.

**Known tech debt — no job cancellation:** `cancel()` on `BackgroundTaskQueue` returns `False` unconditionally. A running coroutine cannot be interrupted. To clear a stuck job: update `pipeline_status` to `ERROR` in the DB directly, or restart uvicorn. Fix: store `asyncio.Task` handles and expose real cancellation. Post-v1 ARQ upgrade makes this moot.

#### CPU-bound work must use ProcessPoolExecutor

Whisper is CPU-bound and will block the asyncio event loop if called directly. Pyannote (diarization) has the same constraint but is not used in v1 — this pattern is documented here for when diarization is introduced:

```python
# src/transcription/local.py
class LocalTranscriptionService:
    def __init__(self):
        self._executor = ProcessPoolExecutor(max_workers=1)

    async def transcribe(self, audio_path, speaker_count_hint=None, language="en"):
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            self._executor,
            _run_transcription_sync,
            audio_path, speaker_count_hint, language
        )
        return result
```

#### What survives a frontend page refresh

| Thing                  | Survives refresh?      | Reason                                                      |
| ---------------------- | ---------------------- | ----------------------------------------------------------- |
| Pipeline job execution | ✅ Yes                  | Background coroutine in uvicorn process, unaffected by HTTP |
| Pipeline status        | ✅ Yes                  | Written to DB at every stage transition                     |
| SSE stream             | ❌ No                   | HTTP connection dropped on refresh                          |
| SSE reconnect          | ✅ Yes                  | Frontend re-opens stream; DB has current status             |
| Queue position         | ✅ Yes                  | Derivable from in-memory registry on reconnect              |
| Jobs in queue          | ⚠️ Process restart only | Lost if uvicorn restarts; survives browser refresh          |
| Chat sessions          | ❌ No                   | InMemorySessionStore cleared on process restart             |

#### Frontend reconnect pattern

```typescript
const TERMINAL_STATUSES = ['PENDING', 'READY', 'ERROR']

episodes
  .filter(ep => !TERMINAL_STATUSES.includes(ep.pipeline_status))
  .forEach(ep => connectSSE(ep.id))
```

Note: `PENDING_NAMES` is not a terminal status in v1 — it is removed from the pipeline entirely until diarization is introduced.

#### Post-v1 queue upgrade

The `IngestionQueue` Protocol means `BackgroundTaskQueue` can be replaced with `ARQQueue` (Redis-backed, separate worker process) by implementing the Protocol and updating `dependencies.py`. No pipeline or route handler changes required.

```
MAX_CONCURRENT_INGESTIONS=2
# Future:
# QUEUE_BACKEND=arq
# REDIS_URL=redis://localhost:6379
```

---

### 3.6 Transcription Service

Swappable behind the `TranscriptionService` Protocol. See section 3.3 for interface definition.

**Configuration:**
```
TRANSCRIPTION_BACKEND=local          # local | remote
TRANSCRIPTION_SERVICE_URL=http://localhost:8001
HUGGINGFACE_TOKEN=hf_...
WHISPER_MODEL_SIZE=medium
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
        # Fetches episode title
        # Formats timestamp_display
        # Batched: one query per table, never N+1
```

`ChunkResult` carries both `text` (leaf, for citation display) and `parent_text` (full topic segment, for LLM context). Separates swappable vector search from stable hydration logic.

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

**Known tech debt — no request timeout:** Long-running chat requests (multiple tool rounds on a slow local
model) hold the HTTP connection open indefinitely. Fix: wrap `llm.complete()` in `asyncio.wait_for(..., timeout=60.0)`.

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

---

### 3.12 Observability — OpenTelemetry + Phoenix

**What gets traced:**
- Every `LLMClient.complete()` call — auto-instrumented via `OpenAIInstrumentor`
- Every `VectorStore.search()` call — custom span with query + filter + score distribution
- `SpeakerResolver.infer()` — span attributes: `speaker.name_found` (bool), `speaker.confidence` (str)
- Pipeline stage transitions — spans with `episode_id`, duration, errors
- API request spans — endpoint, status, duration

```python
def setup_telemetry(settings: Settings):
    if not settings.phoenix_enabled:
        return
    provider = TracerProvider()
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    OpenAIInstrumentor().instrument()
```

Phoenix runs as optional Docker Compose profile. `OTEL_EXPORTER_OTLP_ENDPOINT` is the only change needed for hosted telemetry (Arize, Langfuse, etc.).

---

### 3.13 Frontend — React + Vite

| View          | Purpose                                                                                             |
| ------------- | --------------------------------------------------------------------------------------------------- |
| Feeds         | Add RSS URL, list feeds, refresh                                                                    |
| Episodes      | Pipeline status badges, trigger ingestion, SSE progress                                             |
| Speaker Names | View inferred name + confidence; confirm or correct. Available post-ingestion, not a pipeline gate. |
| Chat          | Freeform conversation, citation cards, multi-feed scope selectors                                   |

State management: React Query for server state; Zustand or Context for session/UI state.

Chat session state lives in component — designed so persisting to localStorage or backend requires only extracting the session object. Session creation sends `scope_feed_ids: list[UUID]` (not a single `scope_feed_id`).

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

# Transcription backend
TRANSCRIPTION_BACKEND=local # local | remote
TRANSCRIPTION_SERVICE_URL=http://localhost:8001

# Diarization — local backend only, leave empty to skip
# Ignored when TRANSCRIPTION_BACKEND=remote (remote service owns diarization)
# Recommended on CUDA hardware; CPU is very slow for long episodes
DIARIZATION_MODEL=

# Speaker inference
SPEAKER_INFERENCE_WINDOW_MS=900000

# Ingestion
MAX_CONCURRENT_INGESTIONS=2

# Observability
PHOENIX_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# App
LOG_LEVEL=INFO
AUDIO_STORAGE_PATH=./data/audio
CHUNK_SIZE_TOKENS=256
CHUNK_OVERLAP_TOKENS=32
CHUNK_MIN_TOKENS=20
TOPIC_SIMILARITY_THRESHOLD=0.75

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
GET    /api/v1/feeds
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

### Simple Query (superseded by chat, retained until Phase 10)
```
POST   /api/v1/query/simple                   Body: { question, feed_id?, episode_ids?, top_k? }
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
curl -X POST http://localhost:8000/api/v1/feeds \
  -H "Content-Type: application/json" \
  -d '{"rss_url": "https://feeds.example.com/podcast.rss"}'

# Ingest episode
curl -X POST http://localhost:8000/api/v1/episodes/ep-uuid/ingest \
  -H "Content-Type: application/json" \
  -d '{"speaker_count_hint": 2}'
# → { "status": "accepted", "job_id": "job-uuid", "queue_position": 1 }

# Stream status
curl -N http://localhost:8000/api/v1/episodes/ep-uuid/status/stream

# Check inferred speakers
curl http://localhost:8000/api/v1/episodes/ep-uuid/speakers

# Confirm names
curl -X PUT http://localhost:8000/api/v1/episodes/ep-uuid/speakers \
  -H "Content-Type: application/json" \
  -d '[{"speaker_id": "SPEAKER_00", "display_name": "Marcus Webb"}]'

# Start chat session scoped to one or more feeds
curl -X POST http://localhost:8000/api/v1/chat/sessions \
  -H "Content-Type: application/json" \
  -d '{"scope_feed_ids": ["feed-uuid-1", "feed-uuid-2"]}'

# Query
curl -X POST http://localhost:8000/api/v1/chat/sess-uuid/message \
  -H "Content-Type: application/json" \
  -d '{"message": "What does Marcus think about AGI timelines?"}'

# Get history with citations
curl http://localhost:8000/api/v1/chat/sess-uuid/history
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
│   │   │   │   ├── query.py          # POST /query/simple (Phase 5); superseded by chat in Phase 6
│   │   │   │   └── health.py
│   │   │   ├── middleware/
│   │   │   │   └── auth.py
│   │   │   └── dependencies.py      # ALL dependency wiring lives here
│   │   ├── llm/
│   │   │   ├── base.py              # LLMClient + EmbeddingClient Protocols, ToolCall, LLMResponse
│   │   │   └── client.py            # OpenAICompatibleLLMClient + OpenAICompatibleEmbeddingClient
│   │   ├── ingestion/
│   │   │   ├── pipeline.py          # Thin orchestrator only
│   │   │   ├── queue.py             # IngestionQueue Protocol + BackgroundTaskQueue
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
│   │   │   ├── result_hydrator.py   # Resolves speaker_id → display_name; defines ChunkResult
│   │   │   └── session_store.py     # SessionStore Protocol + InMemorySessionStore; ChatSession
│   │   ├── models/
│   │   │   ├── db.py                # SQLAlchemy models
│   │   │   └── schemas.py           # Pydantic request/response schemas
│   │   ├── telemetry/
│   │   │   └── setup.py
│   │   └── config.py
│   ├── tests/
│   │   ├── conftest.py              # MockLLMClient, MockVectorStore, MockHydrator, MockEmbeddingClient
│   │   ├── unit/
│   │   │   ├── test_chunker.py
│   │   │   ├── test_rss_parser.py
│   │   │   ├── test_speaker_resolver.py
│   │   │   ├── test_prompt_builder.py
│   │   │   ├── test_result_hydrator.py
│   │   │   ├── test_retriever.py
│   │   │   ├── test_session_store.py
│   │   │   ├── test_tool_dispatcher.py
│   │   │   └── test_engine.py
│   │   ├── integration/
│   │   │   ├── conftest.py          # DB engine, session, HTTP client fixtures
│   │   │   ├── test_ingestion_pipeline.py
│   │   │   └── test_chat_session.py
│   │   └── fixtures/
│   │       ├── sample_feed.xml
│   │       └── sample_transcript.json
│   ├── pyproject.toml
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   │   └── useEpisodeStatus.ts
│   │   └── api/
│   ├── package.json
│   └── vite.config.ts
├── transcription-service/
│   ├── main.py
│   ├── pyproject.toml
│   └── Dockerfile
├── docker-compose.yml
├── docker-compose.dev.yml
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
services:
  api:
    build: ./backend
    ports: ["8000:8000"]
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - audio_data:/app/data/audio
    restart: unless-stopped

  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    depends_on: [api]
    restart: unless-stopped

  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: podcast_engine
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d podcast_engine"]
      interval: 5s
      retries: 5
    restart: unless-stopped

  transcription:
    build: ./transcription-service
    ports: ["8001:8001"]
    env_file: .env
    volumes:
      - audio_data:/app/data/audio
      - model_cache:/root/.cache
    profiles: ["transcription"]
    restart: unless-stopped

  phoenix:
    image: arizephoenix/phoenix:latest
    ports: ["6006:6006", "4317:4317"]
    profiles: ["observability"]
    restart: unless-stopped

volumes:
  pgdata:
  audio_data:
  model_cache:
```

---

## 8. Testing Strategy

**Unit tests** — pure logic, no I/O, inject mocks:
- `Chunker` — boundaries, hierarchy, token limits, short segment merging
- `RSSParser` — fixture XML, duration formats, transcript tag detection
- `SpeakerResolver` — prompt construction, JSON parsing, null handling; inject `MockLLMClient`
- `PromptBuilder` — message construction, scope application; no I/O
- `ResultHydrator` — display name resolution, timestamp formatting; mock DB
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
- `BackgroundTaskQueue` satisfies `IngestionQueue`
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
| ARQ job queue            | Implement `IngestionQueue` Protocol for ARQ; add Redis to Docker Compose; swap in `dependencies.py`                                                  |
| Automatic feed polling   | APScheduler; calls existing `refresh_feed` + `queue.enqueue()`                                                                                       |
| Alternative vector DBs   | Implement `VectorStore` Protocol for Qdrant/Pinecone; swap in `dependencies.py`; ~1 day                                                              |
| Speaker diarization      | See Future Scope 1.5. Reinstates `PENDING_NAMES` pipeline status; `UNKNOWN` speaker_ids get real diarization labels; existing episodes re-ingestable |
| Non-OpenAI LLM SDK       | Implement `LLMClient` Protocol; swap in `dependencies.py`; no business logic changes                                                                 |
| Chat response streaming  | `LLMClient.stream()` async generator; chat endpoint returns `EventSourceResponse`; applies to final synthesis only — tool rounds still block         |
| LLM request timeout      | `asyncio.wait_for(llm.complete(...), timeout=60.0)` in engine loop; graceful timeout response                                                        |

---

## 10. Quick Start

```bash
git clone https://github.com/youruser/podcast-knowledge-engine
cp .env.example .env
# Edit .env — DATABASE_URL, LLM_BASE_URL, LLM_MODEL_NAME at minimum

cd backend && uv sync
uv run alembic upgrade head
uv run uvicorn src.api.main:app --reload --port 8000

cd ../frontend && npm install && npm run dev

# Or full stack
docker compose up
docker compose --profile transcription --profile observability up
```

API docs: http://localhost:8000/docs
Frontend: http://localhost:3000
Phoenix: http://localhost:6006 (observability profile)

---

*Update this document when architectural decisions change during implementation. Note deviations with rationale.*

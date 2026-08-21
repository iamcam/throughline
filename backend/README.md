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
- Automated ingestion (manual trigger only — feed *refresh* is automatic as of Phase 16, ingestion is not)
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
    # else BackgroundTaskQueue (in-process fallback — see section 3.4)

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

Full code, dataclasses, and design notes: `docs/reference/architecture/protocols.md`

| Protocol                                             | Key method(s)                                                                           | Implementations                                                     |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `LLMClient` (`src/llm/base.py`)                      | `complete(messages, tools=None, response_format=None, temperature=0.7) -> LLMResponse`  | `OpenAICompatibleLLMClient`, `MockLLMClient`                        |
| `EmbeddingClient` (`src/llm/base.py`)                | `embed(texts: list[str]) -> list[list[float]]`                                          | `OpenAICompatibleEmbeddingClient`, `MockEmbeddingClient`            |
| `TranscriptionService` (`src/transcription/base.py`) | `transcribe(audio_path, language="en") -> TranscriptResult`                             | `LocalTranscriptionService` (Whisper), `RemoteTranscriptionService` |
| `DiarizationService` (`src/diarization/base.py`)     | `diarize(audio_path) -> DiarizationResult`                                              | `LocalDiarizationService` (Senko)                                   |
| `IngestionQueue` (`src/ingestion/queue.py`)          | `enqueue(episode_id, job_args)`, `get_status(job_id)`, `cancel(job_id)`                 | `StreaqQueue` (default), `BackgroundTaskQueue` (fallback)           |
| `VectorStore` (`src/storage/vector_store.py`)        | `search(embedding, filters, top_k=5, db) -> list[RawChunkResult]`, `upsert(chunks, db)` | `PgvectorStore`                                                     |
| `SessionStore` (`src/query/session_store.py`)        | `get(session_id)`, `save(session)`, `delete(session_id)`, `list_sessions()`             | `InMemorySessionStore`                                              |

---

### 3.4 Ingestion Pipeline, Queue, and Worker Model

`pipeline.py` is a thin orchestrator (`ingest_episode`) that sequences discrete injected services — download, transcribe, diarize + align, infer speakers, chunk, embed — via a `PipelineServices` dataclass, with status written to Postgres at every stage transition. No stage has knowledge of other stages.

Ingestion runs in a **separate worker process** (`streaq run src.worker:worker`), decoupled from the API via a Redis-backed queue (streaQ). The API only ever enqueues; the worker is the only thing that executes pipeline code. This means a page refresh, API restart, or worker restart has no effect on a running job — Postgres is the source of truth for status, and SSE reads from it independently. CPU/GPU-bound work (Whisper, Senko) runs inside a `ProcessPoolExecutor` so it never blocks the worker's event loop; Senko's model is kept warm across jobs via the executor's `initializer`.

Transcription and diarization are fully separate pipeline stages — transcription writes every segment as `speaker_id='UNKNOWN'`; a dedicated **alignment** step (`src/diarization/alignment.py`) then relabels segments by matching them against diarization's speaker turns via millisecond overlap.

Full execution-model diagram, dispatch-by-name mechanics, cancellation/dedup rules, ProcessPoolExecutor details, configuration, and the discrete-services table: `docs/reference/architecture/ingestion-pipeline.md`

---

### 3.5 Speaker Inference and Identity Model

LLM-assisted name detection (`SpeakerResolver`, via `LLMClient`) runs automatically after diarization + alignment, once per diarized speaker, using a time-bounded context window around that speaker's first utterance. A speaker maps to `None` rather than a guessed name when inference isn't confident. `speaker_id` (e.g. `SPEAKER_00`) is a stable, **episode-scoped** identifier — the same label in two episodes refers to different people — while `display_name` is separate, mutable metadata in `episode_speakers` that can be edited any time with no effect on chunks or embeddings.

Full prompt structure, `SpeakerStore` post-inference logic, speaker-state table, and identity-resolution rules: `docs/reference/architecture/speaker-identity.md`

---

### 3.6 SSE Status Streaming and Query Engine

Pipeline status streams over SSE (`GET /episodes/{id}/status/stream`), closing on `READY` or `ERROR`, with a polling fallback.

The query engine (`src/query/engine.py`) is a thin orchestrator (`QueryEngine.chat()`) composing `QueryRewriter` (pre-retrieval conversational query rewriting), `PromptBuilder` (pure, no I/O), `ToolDispatcher` (routes tool calls, resolves speaker names, collects citations), and `ResultHydrator` (resolves `speaker_id` → `display_name`, batched, never N+1). It runs a bounded tool-calling loop (`max_tool_rounds`, default 3) against `LLMClient`, with a `for/else` forced-synthesis fallback if rounds are exhausted, and a per-call timeout (`LLM_REQUEST_TIMEOUT_SECONDS`) that fails safe without saving partial session state.

| Tool                    | When used                                            | Key parameters                                            |
| ----------------------- | ---------------------------------------------------- | --------------------------------------------------------- |
| `search_knowledge_base` | Topic queries, opinion questions, factual lookups    | `query` (required), `speaker_name`, `episode_id`, `top_k` |
| `get_episode_context`   | Expanding a specific timestamp from a prior citation | `episode_id`, `timestamp_ms`, `padding_ms`                |
| `get_speaker_profile`   | Questions about a person rather than a topic         | `speaker_name`                                            |

Full component code (`PromptBuilder`, `ToolDispatcher`, `ResultHydrator`, `QueryRewriter`), engine orchestration source, and message-ordering/serialization gotchas: `docs/reference/architecture/query-engine.md`

---

### 3.7 Data Layer — PostgreSQL + pgvector

`display_name` exists only in `episode_speakers`; `transcript_segments` and `chunks` store `speaker_id` only, resolved to a display name at read time by `ResultHydrator`. All cascade deletes are defined. `FeedResponse.latest_episode_published_at` is derived at read time (`MAX(episodes.published_at)`), never stored.

Full schema (`feeds`, `episodes`, `episode_speakers`, `transcript_segments`, `chunks`, pgvector index): `docs/reference/architecture/data-layer.md`

---

### 3.8 Observability — OpenTelemetry + Phoenix

OTLP/HTTP export via `SimpleSpanProcessor` (synchronous, appropriate for single-user scale). `OpenAIInstrumentor().instrument()` auto-instruments every `LLMClient.complete()` call. Custom spans cover each pipeline stage (`ingest_episode`, `audio_download`, `transcription`, `diarization`, `speaker_inference`, `embedding`, `retrieval`, `chat`) with stage-specific attributes. Backend is swappable (local Phoenix, hosted Arize, Langfuse, any OTLP/HTTP collector) via `OTEL_ENDPOINT` alone — no code changes.

Full setup code, span attribute reference table, and error-recording pattern: `docs/reference/architecture/observability.md`

---

### 3.9 Frontend — React + Vite

React 19 + TypeScript, Vite 8, Tailwind v4, shadcn/ui, TanStack Query v5, React Router v7. Chat has three scoped entry points (all feeds, single feed, single episode) sharing one `ChatInterface` component. Feed/episode cache invalidation is centralized in `lib/queryInvalidation.ts` to avoid the stale-cache bugs that showed up independently across four mutations before consolidation. SSE and TanStack cache are bridged by `useEpisodeStatus`, invalidating on terminal status.

Full component inventory, resizable-panel layout pattern, `useChatSession`/`useEpisodeStatus` hook details, and layout gotchas: `docs/reference/architecture/frontend.md`


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

# Diarization
PIPELINE_MAX_WORKERS=1                  # ProcessPoolExecutor size shared by local Whisper and local Senko

# Speaker inference
SPEAKER_INFERENCE_WINDOW_MS=900000
SPEAKER_INFERENCE_PADDING_MS=60000

# Ingestion
MAX_CONCURRENT_INGESTIONS=2
REDIS_URL=                              # empty = in-process BackgroundTaskQueue; set = StreaqQueue (Redis-backed worker)

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
POST   /api/v1/episodes/{episode_id}/ingest
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
│   │   │   ├── local.py             # Whisper via ProcessPoolExecutor
│   │   │   └── remote.py            # HTTP client
│   │   ├── diarization/
│   │   │   ├── base.py              # DiarizationService Protocol + data types
│   │   │   ├── local.py             # Senko via ProcessPoolExecutor with warm-model initializer
│   │   │   └── alignment.py         # Segment-to-turn overlap matching
│   │   ├── storage/
│   │   │   └── vector_store.py      # VectorStore Protocol + PgvectorStore; SearchFilters with feed_ids
│   │   ├── query/
│   │   │   ├── engine.py            # Thin orchestrator; tool-calling loop; for/else synthesis
│   │   │   ├── prompt_builder.py    # Pure logic, no I/O; scope-aware system prompt
│   │   │   ├── query_rewriter.py    # Pre-retrieval conversational query rewriting; passthrough by default
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
│   │       ├── test_alignment.py
│   │       ├── test_auth_middleware.py
│   │       ├── test_background_queue.py
│   │       ├── test_chunker.py
│   │       ├── test_engine.py
│   │       ├── test_itunes.py
│   │       ├── test_prompt_builder.py
│   │       ├── test_query_rewriter.py
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
├── docs/
│   ├── ARCHITECTURE.md
│   ├── IMPLEMENTATION_PLAN.md
│   ├── FUTURE_SCOPE.md
│   ├── OPERATIONS.md
│   └── reference/
│       ├── architecture/
│       └── phases/
└── README.md
```

---

## 7. Docker Compose

Full `docker-compose.yml` (db, redis, backend, worker, frontend services), config-change workflow, and self-hosting notes: `OPERATIONS.md`.

Summary: `db` (Postgres + pgvector) and `redis` (streaQ job queue backend) are the only stateful services; `backend` only ever enqueues ingestion jobs, `worker` is the sole process that runs pipeline code, `frontend` is Caddy-served static React. Redis has no persistence by default — queued/in-flight jobs are lost on container restart (see Future Scope 2.1c). Bring your own Postgres/Redis by pointing `DATABASE_URL`/`REDIS_URL` at an existing instance and removing the corresponding service.

---

## 8. Testing Strategy

**Unit tests** — pure logic, no I/O, inject mocks:
- `Chunker` — boundaries, hierarchy, token limits, short segment merging
- `RSSParser` — fixture XML, duration formats, transcript tag detection
- `SpeakerResolver` — prompt construction, JSON parsing, null handling, per-speaker windowing/padding; inject `MockLLMClient`
- `PromptBuilder` — message construction, scope application; no I/O
- `ResultHydrator` — display name resolution, timestamp formatting, audio_url batching; mock DB
- `ToolDispatcher` — correct tool routing, filter application, citation population, speaker resolution
- `QueryEngine` — tool-calling loop, round limits, message ordering, citation passthrough
- `SessionStore` — save/retrieve/delete, key correctness
- Alignment (`tests/unit/test_alignment.py`) — overlap matching, tie-breaking, no-overlap fallback, non-mutation

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
- `LocalDiarizationService` satisfies `DiarizationService`

```bash
uv run pytest tests/unit             # fast, no services
uv run pytest tests/integration      # requires running DB
uv run pytest --cov=src --cov-report=term-missing
```

---

## 9. Upgrade Path (Post-v1)

| Feature                  | What it requires                                                                                                                                                                                                                                                                                                                                  |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Graph RAG                | Post-chunking NER → entity/relationship tables; `search_graph` tool; new `GraphStore` Protocol                                                                                                                                                                                                                                                    |
| Persistent conversations | Implement `DBSessionStore` satisfying `SessionStore` Protocol; swap in `dependencies.py`                                                                                                                                                                                                                                                          |
| Subprocess-level cancel  | Kill the OS-level Whisper subprocess on `cancel()`, not just the asyncio task — requires tracking PID across the `ProcessPoolExecutor` boundary                                                                                                                                                                                                   |
| Queue overview UI        | `queued_at`/`finished_at` columns on `Episode`; grouped-by-status read endpoint — pure Postgres, no `IngestionQueue` involvement                                                                                                                                                                                                                  |
| Automatic feed polling   | Shipped in Phase 16 — `poll_all_feeds` (`src/ingestion/feed_poller.py`) calls existing `refresh_feed` per feed, no queue/ingestion involvement; invoked via `scripts/feed_polling.py`, chained before the dev server and inside `entrypoint.sh` on container start, and via host cron (`docker compose run --rm --no-deps`) on deployed instances |
| Alternative vector DBs   | Implement `VectorStore` Protocol for Qdrant/Pinecone; swap in `dependencies.py`; ~1 day                                                                                                                                                                                                                                                           |
| Non-OpenAI LLM SDK       | Implement `LLMClient` Protocol; swap in `dependencies.py`; no business logic changes                                                                                                                                                                                                                                                              |
| Chat response streaming  | `LLMClient.stream()` async generator; chat endpoint returns `EventSourceResponse`; applies to final synthesis only — tool rounds still block                                                                                                                                                                                                      |
| V2 chat scope filtering  | `GET /chat/{session_id}` returns full session object; `PATCH /chat/{session_id}` updates scope mid-conversation; frontend scope selector calls resetSession on change                                                                                                                                                                             |

---

## 10. Quick Start

```bash
git clone https://github.com/youruser/podcast-knowledge-engine
cp .env.example .env
# Edit .env — DATABASE_URL, LLM_BASE_URL, LLM_MODEL_NAME at minimum

cd backend && uv sync
uv run alembic upgrade head
uv run uvicorn src.api.main:app --reload --port 3001

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

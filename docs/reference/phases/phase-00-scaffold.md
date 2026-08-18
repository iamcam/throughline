# Phase 0 — Scaffold and Infrastructure

> Moved from IMPLEMENTATION_PLAN.md. Status: ✅ Complete. Git tag: `v0.1.0-scaffold`.
> See IMPLEMENTATION_PLAN.md's Phase Overview table for the one-line summary; see ARCHITECTURE.md for current system design.

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

#### 0.3 LLM and Embedding Protocols (`src/llm/base.py` + `src/llm/client.py`) 🤖
Define `LLMClient` and `EmbeddingClient` Protocols before anything else references them. The OpenAI SDK is used only in `client.py` — all business logic receives the Protocol.

> **As built (post-Phase 6):** `LLMResponse` has `content: str | None = None`, `tool_calls: list[ToolCall] = field(default_factory=list)`, and `finish_reason: str = "stop"`. `LLMClient.complete()` accepts a `tools` parameter. `TokenUsage` deferred to Phase 9. `MockLLMClient` lives in `tests/conftest.py` as a plain class — import directly, not as a pytest fixture.

```python
# src/llm/base.py
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict

@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"

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

`OpenAICompatibleLLMClient` and `OpenAICompatibleEmbeddingClient` in `client.py` are thin wrappers over `AsyncOpenAI`. Tool call arguments are parsed from JSON string defensively — malformed arguments log a warning and produce an empty dict rather than raising.

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
    chunk_min_tokens: int = 20
    topic_similarity_threshold: float = 0.75
    demo_auth_enabled: bool = False
    demo_username: str = "demo"
    demo_password: str = "changeme"
    log_level: str = "INFO"
    model_config = SettingsConfigDict(env_file=".env")
```

#### 0.5 Database models (`src/models/db.py`) 🤖
SQLAlchemy async models for all tables from `ARCHITECTURE.md` section 3.7.

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

# Provides the LLMClient (OpenAICompatibleLLMClient pointed at LLM_BASE_URL)
# In tests: inject MockLLMClient — callers never reference the OpenAI SDK directly
def get_llm_client() -> LLMClient: ...

# Provides the EmbeddingClient (OpenAICompatibleEmbeddingClient pointed at EMBEDDING_BASE_URL)
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

# Added in Phase 6:
def get_prompt_builder() -> PromptBuilder: ...
def get_tool_dispatcher(retriever: Retriever = Depends(get_retriever)) -> ToolDispatcher: ...
def get_query_engine(...) -> QueryEngine: ...
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
- Lifespan: DB engine, telemetry init, `IngestionQueue` singleton and `InMemorySessionStore` singleton stored on `app.state`
- CORS middleware (localhost:3000)
- Mount routers (stubs for now)
- Register `BasicAuthMiddleware` (bypassed when `DEMO_AUTH_ENABLED=false`)
- `logging.basicConfig(level=logging.INFO)` at module level — configure before any other imports

#### 0.9 Health endpoints
```
GET /api/v1/health       → { status: "ok", version: "0.1.0" }
GET /api/v1/health/deep  → { db: "ok", llm: "ok|error", embedding: "ok|error" }
```
Deep health: real DB query + minimal LLM ping. Use throughout development to verify config.

#### 0.10 Docker Compose (dev)
`docker-compose.db.yml`: DB service only.
```bash
docker compose -f docker-compose.db.yml up -d
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
    {"speaker_id": "SPEAKER_00", "text": "Welcome to the show. I'm Marcus Webb and today I have a very special guest.", "start_ms": 0, "end_ms": 5200},
    {"speaker_id": "SPEAKER_01", "text": "Thanks for having me, Marcus. I'm Elena Vasquez.", "start_ms": 5400, "end_ms": 9800},
    {"speaker_id": "SPEAKER_00", "text": "Elena, let's talk about the future of AI and what you're building.", "start_ms": 10200, "end_ms": 14500}
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

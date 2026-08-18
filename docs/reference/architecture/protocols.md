# Service Abstractions (Protocols)

> Moved from ARCHITECTURE.md §3.3. Referenced from ARCHITECTURE.md — see that doc for the high-level component map and Dependency Injection wiring.

All swappable components are defined as Python `Protocol` classes. Concrete implementations satisfy the Protocol structurally — no inheritance required.

## LLMClient (`src/llm/base.py`)

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

## EmbeddingClient (`src/llm/base.py`)

```python
class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Implementations: `OpenAICompatibleEmbeddingClient` (production, in `src/llm/client.py`), `MockEmbeddingClient` (tests).

## TranscriptionService (`src/transcription/base.py`)

```python
class TranscriptionService(Protocol):
    async def transcribe(
        self,
        audio_path: str,
        language: str = "en"
    ) -> TranscriptResult: ...
```

Implementations: `LocalTranscriptionService` (Whisper), `RemoteTranscriptionService` (HTTP sidecar).

## DiarizationService (`src/diarization/base.py`)

```python
@dataclass
class SpeakerTurn:
    speaker_id: str    # e.g. "SPEAKER_00" - raw diarization label, not display name
    start_ms: int
    end_ms: int

@dataclass
class DiarizationResult:
    turns: list[SpeakerTurn]
    speaker_count: int   # merged/deduplicated count

class DiarizationService(Protocol):
    async def diarize(self, audio_path: str) -> DiarizationResult: ...
```

Implementations: `LocalDiarizationService` (Senko, MLX/Metal/CUDA/CPU auto-detected). No remote implementation exists yet — see Future Scope.

No speaker-count hint on this Protocol: Senko does not accept one, and no diarization backend under consideration (self-hosted or otherwise) changes that calculus enough to justify carrying an unused parameter. `TranscriptionService.transcribe()` has no diarization-related parameters either, by the same reasoning applied consistently across both Protocols.


## IngestionQueue (`src/ingestion/queue.py`)

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
route handlers guard against duplicate/conflicting requests entirely via `episode.pipeline_status` checks. The queue layer offers no id-collision backstop by design — see `docs/reference/architecture/ingestion-pipeline.md`.

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

## VectorStore (`src/storage/vector_store.py`)

```python
@dataclass
class SearchFilters:
    feed_ids: list[UUID] | None = None    # supports multi-feed scope
    episode_ids: list[UUID] | None = None
    speaker_pairs: list[tuple[UUID, str]] | None = None   # (episode_id, speaker_id) pairs — speaker_id is episode-scoped, so a display name can resolve to several different speaker_ids, one per episode

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

## SessionStore (`src/query/session_store.py`)

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

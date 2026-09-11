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

@dataclass
class ToolCallDelta:
    index: int
    id: str | None
    name: str | None
    arguments_delta: str | None

@dataclass
class StreamChunk:
    content_delta: str | None
    tool_call_deltas: list[ToolCallDelta] = field(default_factory=list)
    finish_reason: str | None = None

class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_format: dict | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse: ...

    def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamChunk]: ...
```

**Current state (post-Phase 17):** `LLMResponse` includes `content: str | None`, `tool_calls: list[ToolCall]`,
and `finish_reason: str`. `LLMClient.complete()` accepts a `tools` parameter. `TokenUsage` is deferred to Phase 9.
`LLMClient.stream()` (Phase 17) is declared as a plain `def`, not `async def` — it describes a callable that
*returns* an async generator, and calling an `async def` generator function does not execute any of its body
until first iteration, matching this Protocol's usage in `StreamAccumulator.accumulate()`.

`OpenAICompatibleLLMClient` in `src/llm/client.py` parses tool call arguments from JSON strings defensively —
malformed arguments produce an empty dict with a logged warning rather than raising. All business logic receives
`LLMClient`. The OpenAI SDK is referenced only in `src/llm/client.py`. `stream()` only reads `delta.content` from
each chunk — it never reads `delta.reasoning_content` (the field some backends use for "thinking mode" reasoning
text on models like Qwen 3), so reasoning tokens never become part of a `StreamChunk` in the first place.

`MockLLMClient` lives in `tests/conftest.py` and supports a `responses: list[LLMResponse]` sequence parameter
for multi-round tool-calling tests, plus a `stream_chunks: list[list[StreamChunk]]` sequence parameter for the
streaming path (Phase 17) — one inner list of `StreamChunk` per round, replayed via `stream()`. It is a plain
class, not a pytest fixture — import it directly in test files.

## EmbeddingClient (`src/llm/base.py`)

```python
class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Implementations: `OpenAICompatibleEmbeddingClient` (`src/llm/client.py`), `LocalEmbeddingClient` (`src/llm/local.py`,
sentence-transformers, Phase 19), `MockEmbeddingClient` (tests).

**Selection:** `src/shared/llm.py`'s `get_embedding_client()` branches on `EMBEDDING_BASE_URL` — `"local"` builds
`LocalEmbeddingClient`; anything else (including empty, which falls back to `LLM_BASE_URL`) builds
`OpenAICompatibleEmbeddingClient`. Same presence/absence-of-a-value convention `TRANSCRIPTION_SERVICE_URL` already
uses, rather than a separate `EMBEDDING_BACKEND` enum.

**`LocalEmbeddingClient`:** loads a `SentenceTransformer` model once, eagerly, in `__init__` (device resolution:
cuda -> mps -> cpu). `embed()` offloads the blocking `model.encode()` call to a small `ThreadPoolExecutor`. Unlike
`LocalDiarizationService`, it does not use a `ProcessPoolExecutor` with a warm-subprocess initializer — that
pattern exists because Senko only ever runs inside the worker process, whereas `EmbeddingClient` is constructed in
*both* the API process (`dependencies.py`, for query-time embedding) and the worker process (`worker.py`'s
`lifespan()`, for ingestion), so the model just lives in-process in whichever one constructs it.

**Singleton caching:** `get_embedding_client()` (and `get_llm_client()`, for consistency) is decorated with
`@lru_cache`, matching `get_settings()`'s existing pattern in `config.py`. This is load-bearing, not cosmetic —
FastAPI's `Depends()` caches a dependency only within one request, not across requests, and constructing a fresh
`LocalEmbeddingClient` per request was measured during Phase 19 smoke testing to reload the model and re-verify its
Hugging Face cache on every single chat message (several seconds of redirect-chain HTTP calls per request).
`OpenAICompatibleEmbeddingClient` never surfaced this because building it has no meaningful cost; `LocalEmbeddingClient`
does, since `__init__` performs real model-loading work.

**Model chosen:** `Alibaba-NLP/gte-modernbert-base` (768-dim native, Apache 2.0, no `trust_remote_code`, ungated,
~149M params) — see `IMPLEMENTATION_PLAN.md` Phase 19 for the comparison against other 768-dim candidates.
Deliberately requires no query/document prefix, which keeps `embed()`'s flat `texts: list[str]` signature accurate;
see `FUTURE_SCOPE.md` 2.11 for the deferred design to support prefix-sensitive models later.

**`OpenAICompatibleEmbeddingClient` dimensions (Phase 19.1):** `__init__` takes a required `dimensions: int`, and
`embed()` always includes `dimensions=self._dimensions` in the `embeddings.create()` request — unconditionally, with
no per-endpoint opt-in flag. This was verified empirically before writing any code: both Ollama's OpenAI-compatible
embeddings endpoint (`nomic-embed-text`) and OpenAI's real API honored an explicit `dimensions` value correctly
(neither rejected nor silently ignored it), which ruled out the originally-planned opt-in flag as unnecessary. No
client-side length check is done on the returned vector — `PgvectorStore`'s column has a fixed dimension, so a
mismatched vector already fails at insert time at the DB layer.

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

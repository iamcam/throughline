# SSE Status Streaming and Query Engine

> Moved from ARCHITECTURE.md §3.9–§3.10. Referenced from ARCHITECTURE.md — see that doc for the high-level component map. `LLMClient` and `SessionStore` Protocols referenced below live in `docs/reference/architecture/protocols.md`.

## SSE Status Streaming

```
GET /api/v1/episodes/{episode_id}/status/stream → text/event-stream

data: {"status": "QUEUED", "position": 3}
data: {"status": "DOWNLOADING", "progress": 0.2}
data: {"status": "TRANSCRIBING", "stage": "whisper", "progress": 0.4}
data: {"status": "DIARIZING"}
data: {"status": "INFERRING_SPEAKERS"}
data: {"status": "CHUNKING", "progress": 0.5}
data: {"status": "EMBEDDING", "progress": 0.8}
data: {"status": "READY"}
```

Stream closes on `READY` or `ERROR`. No `PENDING_NAMES` pause in v1 — the pipeline runs to completion without waiting for user input. Polling fallback: `GET /api/v1/episodes/{episode_id}/status`.

---

## Query Engine

The query engine is a thin orchestrator that delegates to discrete components. Uses `LLMClient` Protocol throughout.

### Components

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

Speaker name → `(episode_id, speaker_id)` pair resolution in `_search_knowledge_base` is scoped to `session.scope_feed_ids` to prevent cross-feed `SPEAKER_00` collisions. Resolves via `.all()`, not `.first()` — a display name can legitimately match multiple `(episode_id, speaker_id)` pairs, since `speaker_id` is episode-scoped and the same diarized label means a different person in each episode. If no match: proceeds with `speaker_pairs=None` (unfiltered) rather than returning an error.

`_label_for_llm(chunk)` prefixes the LLM-facing `results` list's `text`/`parent_text` with `f'{display_name or "Unknown Speaker"}: "{text}"'` before those chunks become tool-result content — the same labeled-script format the transcript view and `SpeakerResolver`'s own prompts already use, giving the LLM an explicit textual signal for who said what. `session.citations` (what the UI shows) keeps the original unprefixed text — the label is LLM-context-only, never stored or displayed.

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

See Protocol definition in `docs/reference/architecture/protocols.md`. v1 implementation is `InMemorySessionStore` — dict on `app.state`. Sessions are ephemeral — cleared on process restart. `DBSessionStore` (post-v1) satisfies the same Protocol.

**`QueryRewriter` (`src/query/query_rewriter.py`)**
```python
class QueryRewriter:
    def __init__(self, llm_client: LLMClient, timeout_seconds: float = QUERY_REWRITE_TIMEOUT_SECONDS): ...

    async def rewrite(self, session: ChatSession, user_message: str) -> str: ...
```
Runs once per `chat()`/`chat_stream()` call, before the tool-calling loop starts and before `user_message` is appended to `session.messages` — so its own conversation-history prompt only ever sees prior turns, never the current one. Resolves conversation-dependent queries (pronouns, implicit topic references) into a self-contained phrase; the prompt instructs passthrough (return unchanged) when the message is already self-contained, so this runs unconditionally on every turn rather than reactively after a low-similarity search — deliberate, not a default: the failure mode being fixed is query *formulation*, not corpus coverage, and no similarity-score signal currently reaches `engine.py` to gate on. The rewritten text is substituted into the LLM-facing message list for round 0 only — a transient swap done by constructing a new dict, never a mutation of the dict stored in `session.messages` (which `PromptBuilder.build_messages()` returns by reference, not by copy). `session.messages` therefore always retains the user's literal original wording; the rewrite has no persisted effect and cannot compound across turns. Never raises — a dedicated, constructor-configurable timeout (`QUERY_REWRITE_TIMEOUT_SECONDS`, default 15s, independent of the main `LLM_REQUEST_TIMEOUT_SECONDS`) and defensive JSON parsing both fall back to the original message on any failure, so this optimization can never block a chat turn.

**`StreamAccumulator` (`src/query/stream_accumulator.py`, Phase 17)**
```python
class MixedStreamResponseError(Exception): ...

class StreamAccumulator:
    async def accumulate(
        self, chunks: AsyncIterator[StreamChunk]
    ) -> AsyncIterator[str | LLMResponse]: ...
```
Consumes one round's `StreamChunk` sequence from `LLMClient.stream()`. Yields content deltas live as plain `str` — forwarded to the frontend as they arrive — and reconstructs tool calls from `ToolCallDelta` fragments, joined by `index` (parallel tool calls interleave their argument fragments across chunks; `index` is what keeps them straight). Yields exactly one terminal `LLMResponse` per round, the same type `complete()` returns — the streaming and non-streaming paths converge on one representation of "a round finished."

A round is assumed to be either a content round or a tool-call round, never both — mirroring `LLMResponse.content`'s "None when model is making tool calls" contract. A chunk sequence that violates this (content deltas followed by tool-call deltas, or vice versa) raises `MixedStreamResponseError` — fails the turn defensively rather than retrying (retry would require buffering the whole round, defeating the point of live token forwarding) or silently merging the two. The session is not saved on this path, same precedent as `LLMTimeoutError` below.

**Whitespace-only content deltas do not count as "content happened."** Discovered against a real thinking-model backend (Qwen 3.5 via MLX, in "thinking mode"): the model streams its reasoning separately via a `reasoning_content` delta field (which `OpenAICompatibleLLMClient.stream()` never reads — reasoning text never becomes a `StreamChunk` at all), but then emits a `content` delta of exactly `"\n\n"` as a transition artifact immediately before its `tool_calls` deltas. A naive truthiness check (`if chunk.content_delta:`) treats that as real content and incorrectly trips `MixedStreamResponseError`. `accumulate()` instead gates on `chunk.content_delta.strip()` — a whitespace-only delta is neither yielded as a token nor counted toward "content happened," while genuine internal whitespace inside real content (e.g. a paragraph break within an actual answer) still passes through unchanged, since the *original* unstripped string is what gets yielded once the check passes.

**`with_heartbeat` (`src/query/async_utils.py`, Phase 17)**
```python
async def with_heartbeat(
    source: AsyncIterator[T], interval: float
) -> AsyncIterator[T | None]: ...
```
Races the source iterator's `__anext__()` against `asyncio.wait(timeout=interval)`. On timeout, yields `None` (a heartbeat tick) *without* abandoning the pending `__anext__()` call — the upstream LLM call keeps running in the background across ticks, and the next real item is yielded transparently as soon as it arrives, whenever that is. `interval` is a polling cadence, not a wait duration: a call that finishes in 3 seconds with `interval=1.0` produces two heartbeat ticks then the real item, not a forced 1-second wait. `finally: pending.cancel()` ensures the in-flight task is cleaned up if the consumer stops iterating early (e.g. `aclose()`).

### Engine orchestration (`src/query/engine.py`)

```python
class QueryEngine:
    def __init__(
        self,
        llm_client: LLMClient,
        session_store: SessionStore,
        prompt_builder: PromptBuilder,
        tool_dispatcher: ToolDispatcher,
        query_rewriter: QueryRewriter,
        max_tool_rounds: int = 3,
    ): ...

    async def chat_stream(
        self, session_id: str, user_message: str, db: AsyncSession
    ) -> AsyncIterator[StatusEvent | TokenEvent | DoneEvent]: ...

    async def chat(self, session_id: str, user_message: str, db: AsyncSession) -> ChatResponse:
        # Thin wrapper (Phase 17): drains chat_stream(), accumulates TokenEvent.delta
        # into the final message string, captures DoneEvent.citations, and returns
        # the same ChatResponse shape this method has always returned.
        # One code path serves both the blocking and streaming endpoints.
        ...
```

**`chat_stream()` is the real orchestrator (Phase 17).** It runs the same session lookup, `QueryRewriter` call, and bounded tool-calling loop `chat()` always has, but each round is consumed via `_stream_round()` — which wraps `with_heartbeat(self._stream_accumulator.accumulate(self._llm.stream(...)), STATUS_HEARTBEAT_SECONDS)` and tracks elapsed time against `LLM_REQUEST_TIMEOUT_SECONDS` itself (since there's no single blocking call left to wrap in `asyncio.wait_for()`). `_stream_round()` yields three kinds of things: `None` (heartbeat tick, from `with_heartbeat`) → `chat_stream()` turns this into a `StatusEvent`; `str` (a content token, from `StreamAccumulator`) → turned into a `TokenEvent(delta=...)`, but only during what turns out to be the final round (tool rounds never produce content tokens in the first place, since a genuine tool-call round has no content deltas to yield — see `StreamAccumulator` above); and the terminal `LLMResponse` for the round, which drives the same tool-call-or-break decision `chat()`'s loop always made. Once the loop ends (via `break` or the `for/else` forced-synthesis fallback), `chat_stream()` yields a final `DoneEvent(citations, session_id)`.

Message ordering, `arguments` serialization, the `for/else` synthesis fallback, and the timeout/session-save interaction below are unchanged from pre-Phase-17 behavior — only the shape of how a round's response is obtained changed 	(`stream()` + `StreamAccumulator` instead of a single `complete()` call).

**Critical message ordering:** The OpenAI API requires that a `tool` message with `tool_call_id: X` is
always preceded by an `assistant` message that requested `X`. Missing or mismatched IDs produce API errors.

**`arguments` serialization:** Tool call arguments must be serialized with `json.dumps()` when appended to
the assistant message. Using `str()` on a Python dict produces single-quoted syntax that LLM servers reject
as invalid JSON.

**`for/else` synthesis:** Python's `for/else` fires the `else` block when the loop completes without a
`break`. When max rounds are exhausted, a final LLM call without tools forces a text response using whatever
was retrieved across all rounds.

**Request timeout:** Each round (both tool-calling rounds and the final synthesis round) is bounded by
`LLM_REQUEST_TIMEOUT_SECONDS` (60s, module-level constant in `engine.py`). A timeout raises `LLMTimeoutError`,
caught in `src/api/routers/chat.py` and mapped to `504 Gateway Timeout` on the blocking endpoint, or an SSE
`error` event with `error_type: "timeout"` on the streaming endpoint. The session is never saved when a timeout
fires — `SessionStore.save()` only runs on the success path — so a timed-out request leaves no partial state
and is safe to retry. The whole `chat_stream()` body runs inside a custom `"chat"` tracing span (`session.id`,
`chat.tool_rounds_used`, `chat.citation_count` on success; `record_exception` + `set_status` on any
exception) — this is orchestration-level instrumentation, distinct from the automatic per-call spans
`OpenAIInstrumentor` already provides for each `llm_client.stream()`/`complete()` call.

**SSE event vocabulary (Phase 17):** `src/api/routers/chat.py`'s `_sse_event_stream()` translates `chat_stream()`'s
events into SSE: `status` (`{}` — heartbeat only, no payload; tool-round activity is deliberately not broken out
per-tool, to avoid coupling the frontend to the backend's tool set — the frontend's existing "Thinking" indicator
covers this, persisting until the first `token`), `token` (`{"delta": str}`), `done` (`{"citations": [...],
"session_id": str}`), `error` (`{"detail": str, "error_type": str}`). `error_type` is produced by `_error_type()`,
a small mapping from exception type to a stable string category (`session_not_found` | `timeout` |
`internal_error`) — deliberately not the raw Python exception class name, since that would make the frontend's
error handling an accidental contract on backend implementation details.

**`ChatResponse`:**
```python
@dataclass
class ChatResponse:
    message: str
    session_id: str
    citations: list[dict]
```

### Tool definitions (`src/query/tools.py`)

Three tools in OpenAI function-calling format. The model reads these descriptions to decide when and how to call each tool.

| Tool | When used | Key parameters |
|------|-----------|----------------|
| `search_knowledge_base` | Topic queries, opinion questions, factual lookups | `query` (required), `speaker_name`, `episode_id`, `top_k` |
| `get_episode_context` | Expanding a specific timestamp from a prior citation | `episode_id`, `timestamp_ms`, `padding_ms` |
| `get_speaker_profile` | Questions about a person rather than a topic | `speaker_name` |

Query strings should be descriptive phrases rather than questions — embedding models match text, not
question syntax. The tool description instructs the model accordingly.

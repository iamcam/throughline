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
Runs once per `chat()` call, before the tool-calling loop starts and before `user_message` is appended to `session.messages` — so its own conversation-history prompt only ever sees prior turns, never the current one. Resolves conversation-dependent queries (pronouns, implicit topic references) into a self-contained phrase; the prompt instructs passthrough (return unchanged) when the message is already self-contained, so this runs unconditionally on every turn rather than reactively after a low-similarity search — deliberate, not a default: the failure mode being fixed is query *formulation*, not corpus coverage, and no similarity-score signal currently reaches `engine.py` to gate on. The rewritten text is substituted into the LLM-facing message list for round 0 only — a transient swap done by constructing a new dict, never a mutation of the dict stored in `session.messages` (which `PromptBuilder.build_messages()` returns by reference, not by copy). `session.messages` therefore always retains the user's literal original wording; the rewrite has no persisted effect and cannot compound across turns. Never raises — a dedicated, constructor-configurable timeout (`QUERY_REWRITE_TIMEOUT_SECONDS`, default 15s, independent of the main `LLM_REQUEST_TIMEOUT_SECONDS`) and defensive JSON parsing both fall back to the original message on any failure, so this optimization can never block a chat turn.

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

    async def chat(self, session_id: str, user_message: str, db: AsyncSession) -> ChatResponse:
        session = await self.session_store.get(session_id)
        if session is None:
            raise ValueError(f"Session not found: {session_id}")

        # Rewrite before appending -- _format_history should only see turns prior to this one
        rewritten_query = await self.query_rewriter.rewrite(session, user_message)

        session.messages.append({"role": "user", "content": user_message})

        for round_num in range(self.max_tool_rounds):
            messages = self.prompt_builder.build_messages(session)
            if round_num == 0:
                # New dict, not a mutation -- messages[-1] is the same object as
                # session.messages[-1]
                messages[-1] = {**messages[-1], "content": rewritten_query}
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

### Tool definitions (`src/query/tools.py`)

Three tools in OpenAI function-calling format. The model reads these descriptions to decide when and how to call each tool.

| Tool | When used | Key parameters |
|------|-----------|----------------|
| `search_knowledge_base` | Topic queries, opinion questions, factual lookups | `query` (required), `speaker_name`, `episode_id`, `top_k` |
| `get_episode_context` | Expanding a specific timestamp from a prior citation | `episode_id`, `timestamp_ms`, `padding_ms` |
| `get_speaker_profile` | Questions about a person rather than a topic | `speaker_name` |

Query strings should be descriptive phrases rather than questions — embedding models match text, not
question syntax. The tool description instructs the model accordingly.

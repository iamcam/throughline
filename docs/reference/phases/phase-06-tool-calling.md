# Phase 6 — Tool-Calling Query Engine

> Moved from IMPLEMENTATION_PLAN.md. Status: ✅ Complete. Git tag: `v0.1.6-tool-calling`.
> See IMPLEMENTATION_PLAN.md's Phase Overview table for the one-line summary; see ARCHITECTURE.md for current system design.
> Note: this phase's tool-calling loop was later extended with query rewriting in Phase 15, and its speaker-labeling logic was extended in Phase 14 — see those phases' files.
> Editorial note: the source document had the "6.6 Tests" section and "Phase 6 Done When" block duplicated verbatim back-to-back. Kept once here as the content was identical.

**Goal:** Multi-turn freeform chat. LLM decides when to retrieve.

**Dependency note:** The `ChatSession` store is a dict on `app.state`, accessed via a dependency `get_session_store(request: Request)`. The LLM client continues to use `Depends(get_llm_client)`. Session objects are ephemeral — stored in-process memory, cleared on restart.

### Tasks

#### 6.1 Tool definitions (`src/query/tools.py`) 🤖
Three tools in OpenAI function-calling format. Tool descriptions are the primary mechanism controlling when the model calls each tool — write them carefully.

```python
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Search podcast transcript content for specific topics, opinions, or facts. "
                "Use this when the user asks what was said about something, what a speaker "
                "thinks about a topic, or wants to find a specific moment in an episode. "
                "Do not use for greetings, clarifications, or questions answerable from "
                "the conversation history alone. "
                "If previous search results already contain sufficient information to answer "
                "the question, do not search again — synthesize from what you have."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Write as a descriptive phrase, not a question — e.g. 'Marcus views on consciousness' not 'What does Marcus think about consciousness?' Embedding models match text, not question syntax.",
                    },
                    "speaker_name": {"type": "string", "description": "Filter to specific speaker display name. Optional."},
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
            "description": "Retrieve the transcript excerpt surrounding a specific timestamp. Use when the user wants to explore a specific moment in more depth, or when a prior search result surfaced a citation the user wants to expand on.",
            "parameters": {
                "type": "object",
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
            "description": "Get information about a speaker across the knowledge base: which episodes they appear in. Use when the user asks about a specific person rather than a specific topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "speaker_name": {"type": "string"}
                },
                "required": ["speaker_name"]
            }
        }
    }
]
```

#### 6.2 ToolDispatcher (`src/query/tool_dispatcher.py`)

Use a class, not a standalone `execute_tool()` function. `Retriever` is injected at construction;
`db` and `session` are passed per-call — consistent with `ResultHydrator` and `Retriever` patterns.

```python
class ToolDispatcher:
    def __init__(self, retriever: Retriever): ...

    async def dispatch(
        self, tool_call: ToolCall, session: ChatSession, db: AsyncSession
    ) -> str:
        # Routes to search_knowledge_base, get_episode_context, get_speaker_profile
        # Outer try/except returns JSON error string rather than raising
        # Returns JSON string for LLM consumption
        # All results serialize display_name, never speaker_id
        # Citations appended to session.citations after successful search
```

**Speaker name resolution:** `_search_knowledge_base` resolves `speaker_name` → `speaker_id` by querying `episode_speakers` scoped to `session.scope_feed_ids`. This prevents cross-feed `SPEAKER_00` collisions — the same identifier in two episodes refers to two different people.

> **Tool result message format — critical.** The OpenAI API requires tool results
> in this exact shape or the LLM will error:
> ```python
> {"role": "tool", "tool_call_id": tc.id, "content": result_json_string}
> ```
> The `tool_call_id` must match the `id` field from the original tool call in the LLM response.
> Get this wrong and you'll see cryptic API errors about mismatched tool calls.

#### 6.3 SessionStore (`src/query/session_store.py`)
Define the Protocol and `InMemorySessionStore` implementation.

```python
@dataclass
class ChatSession:
    session_id: str
    scope_feed_ids: list[UUID] = field(default_factory=list)    # multi-feed support
    scope_episode_ids: list[UUID] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)

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
        max_tool_rounds: int = 3,
    ): ...

    async def chat(self, session_id: str, user_message: str, db: AsyncSession) -> ChatResponse:
        session = await self.session_store.get(session_id)
        if session is None:
            raise ValueError(f"Session not found: {session_id}")

        session.messages.append({"role": "user", "content": user_message})

        for _ in range(max_tool_rounds):
            messages = self.prompt_builder.build_messages(session)
            response = await self.llm_client.complete(messages, tools=TOOLS)
            if not response.tool_calls:
                break

            # CRITICAL: assistant tool call message must be appended before tool results
            session.messages.append({
                "role": "assistant",
                "tool_calls": [...]   # arguments serialized with json.dumps(), NOT str()
            })

            for tc in response.tool_calls:
                result = await self.tool_dispatcher.dispatch(tc, session, db)
                session.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        else:
            # for/else: loop exhausted without break — make one final synthesis call
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

**`arguments` serialization:** `json.dumps(tc.arguments)` — never `str(tc.arguments)`. Python dict string representation uses single quotes which LLM servers reject as invalid JSON.

**`for/else`:** Python fires the `else` block when the loop completes without hitting `break`. The explicit synthesis instruction prevents empty responses when all tool rounds are exhausted.

#### 6.5 Chat endpoints
```
POST   /api/v1/chat/sessions              Body: { scope_feed_ids?: UUID[], scope_episode_ids?: UUID[] }
POST   /api/v1/chat/{session_id}/message  Body: { message }
                                          Response: { message, session_id, citations }
GET    /api/v1/chat/{session_id}/history
DELETE /api/v1/chat/{session_id}
```

#### 6.6 Tests
```python
# tests/unit/test_prompt_builder.py
def test_system_prompt_included_as_first_message()
def test_session_messages_appended_after_system()
def test_scope_feed_ids_mentioned_in_system_prompt()
def test_scope_episode_ids_mentioned_in_system_prompt()
def test_no_scope_produces_clean_prompt()
def test_empty_session_messages_returns_only_system()

# tests/unit/test_session_store.py
async def test_save_and_retrieve_session()
async def test_get_returns_none_for_missing_session()
async def test_delete_removes_session()
async def test_list_sessions_returns_all_ids()
async def test_save_uses_session_id_as_key()

# tests/unit/test_tool_dispatcher.py
async def test_dispatches_search_knowledge_base()
async def test_dispatches_get_speaker_profile()
async def test_unknown_tool_returns_error_json()
async def test_search_applies_session_feed_scope()
async def test_search_resolves_speaker_name_to_id()
async def test_search_proceeds_unfiltered_when_speaker_not_found()
async def test_tool_exception_returns_error_json()
async def test_search_returns_empty_message_when_no_results()
async def test_search_populates_session_citations()
async def test_multi_feed_scope_applied_to_search()

# tests/unit/test_engine.py
async def test_direct_response_requires_no_tool_calls()
async def test_tool_call_dispatched_and_result_appended()
async def test_multi_turn_history_maintained()
async def test_session_not_found_raises_value_error()
async def test_max_tool_rounds_respected()
async def test_assistant_tool_call_message_appended_before_result()
async def test_final_response_saved_to_session()
async def test_none_content_returns_empty_string()
async def test_citations_returned_in_response()
```

### Phase 6 Done When
- Multi-turn chat works via curl
- Verified: topic query → tool call; "summarize that" → no tool call
- Citations show resolved speaker display names and are returned on `ChatMessageResponse`
- Tool call arguments serialized with `json.dumps()` — no single-quoted Python dict syntax
- `for/else` synthesis call fires when max rounds exhausted — no empty responses
- `scope_feed_ids: list[UUID]` on `ChatSession` and `SearchFilters` — multi-feed scope works
- Speaker name resolution scoped to session feed IDs — cross-feed SPEAKER_00 collisions prevented
- Git tags: `v0.1.6-tool-calling`

> **Post-phase addition (second commit):** `scope_feed_id: UUID | None` refactored to
> `scope_feed_ids: list[UUID]` on `ChatSession`; `SearchFilters.feed_id`
> → `feed_ids: list[UUID] | None` with `.in_()` query; `POST /api/v1/chat/sessions`
> request/response updated to list; `PromptBuilder` and `ToolDispatcher` updated.
> Speaker name resolution scoped to session feed IDs to prevent cross-feed
> `SPEAKER_00` collisions. Completed as second commit in Phase 6 before Phase 7 handoff.

> **Known tech debt from this phase:**
> - No request timeout on LLM calls — long local model queries hold the connection indefinitely.
>   Fix: `asyncio.wait_for(llm.complete(...), timeout=60.0)` in engine loop. (Shipped in Phase 11.)
> - No job cancellation in `BackgroundTaskQueue` — see Phase 1 note.
> - `MockLLMClient` is a plain class in `tests/conftest.py` — import directly, never as pytest fixture.

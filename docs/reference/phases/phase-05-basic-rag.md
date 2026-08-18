# Phase 5 — Basic RAG Query

> Moved from IMPLEMENTATION_PLAN.md. Status: ✅ Complete. Git tag: `v0.1.5-basic-rag`.
> See IMPLEMENTATION_PLAN.md's Phase Overview table for the one-line summary; see ARCHITECTURE.md for current system design.
> Note: `POST /api/v1/query/simple`, the endpoint built here, was later removed in Phase 10 once Phase 6's chat endpoints superseded it.

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
        # Batched: one query per table, never N+1
        # Return ChunkResult list — includes both text (leaf) and parent_text (topic segment)
```

`ChunkResult` carries both `text` (leaf, for citation display) and `parent_text` (full topic segment, for LLM context). Both fields are available for frontend use.

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

**`_build_context`:** Uses `chunk.parent_text or chunk.text` for the LLM context block. The leaf `text` found the right moment; the `parent_text` gives the LLM the surrounding topic segment needed to reason about what was actually said. Citations returned to the caller still include `text` for display.

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
- `similarity_score` exposed on `CitationResponse` for retrieval quality inspection
- `ChunkResult` defined in `src/query/result_hydrator.py` (not `schemas.py`)
- `ResultHydrator` is stateless — no constructor args; owned internally by `Retriever`
- `_build_context` uses `parent_text or text` — LLM receives full topic segment, not leaf text
- `Retriever` wired via `get_retriever()` in `dependencies.py`
- Manually verified 3-4 queries against real ingested episode
- Git tag: `v0.1.5-basic-rag`

> **Observed limitations (addressed in Phase 6):**
> - Retrieval always fires regardless of question type — stretch citations visible at low similarity scores
> - No conversation history — follow-up questions lose context
> - Vague queries ("what does the host think about technology?") produce multi-round tool calling with
>   low-similarity results — query rewriting (Future Scope 1.3) is the correct fix
> - `text == parent_text` on short-turn conversational episodes — symptom of single-sentence topic
>   segments; `min_tokens` merge helps but doesn't eliminate it on highly fragmented content

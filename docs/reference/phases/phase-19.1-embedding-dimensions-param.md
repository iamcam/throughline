# Phase 19.1 — Remote Embedding `dimensions` Parameter

> Moved from IMPLEMENTATION_PLAN.md. Status: ✅ Complete. Git tag: `v1.7.2`.
> Unplanned follow-up to Phase 19.

**Goal:** remote embedding endpoints that support OpenAI's `dimensions` parameter can be asked for 768-dim output directly, so the pgvector schema doesn't depend on a provider's native dimensionality matching by coincidence.

### Tasks

#### 19.1.1 Always request the configured dimension
`OpenAICompatibleEmbeddingClient.__init__` takes a required `dimensions: int`; `embed()` includes `dimensions=self._dimensions` in every `embeddings.create()` call, unconditionally — no opt-in flag. `src/shared/llm.py` passes `dimensions=settings.embedding_dimensions` when constructing the client.

#### 19.1.2 Verified empirically before writing any code
Both Ollama's OpenAI-compatible embeddings endpoint (`nomic-embed-text`) and OpenAI's real API were tested directly with the `dimensions` field before deciding whether it needed to be conditional. Neither rejected nor silently ignored it — both truncated output to the requested size. That ruled out the originally-planned `embedding_supports_dimensions` opt-in flag as unnecessary complexity.

#### 19.1.3 No client-side dimension validation
Considered and rejected adding a length check on the returned vector in `OpenAICompatibleEmbeddingClient.embed()`. `PgvectorStore`'s column is declared with a fixed dimension (`vector(768)`), so a mismatched vector already fails at insert time at the DB layer — a redundant app-level check would just duplicate that guarantee.

#### 19.1.4 Test coverage deferred to Phase 20
No test currently constructs `OpenAICompatibleEmbeddingClient` directly (confirmed via grep before closing this phase), despite `backend-README.md` §8 already claiming a contract test for it. Rather than add an isolated test now, coverage for this class is deliberately bundled into Phase 20's new `tests/unit/test_llm_client.py`, since Phase 20 touches the same file (`src/llm/client.py`) and needs a home for `OpenAICompatibleLLMClient` test coverage too — writing one file once instead of two separate small ones.

### Phase 19.1 Done When
- An OpenAI `text-embedding-3-small` deployment (1536-dim native) produces 768-dim vectors end-to-end via `EMBEDDING_DIMENSIONS=768`
- No behavior change for endpoints already in use (Ollama/`nomic-embed-text`)
- Git tag: `v1.7.2`

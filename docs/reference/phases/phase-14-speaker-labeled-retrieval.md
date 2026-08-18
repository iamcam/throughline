# Phase 14 — Speaker-Labeled Retrieval + Chunker Fix

> Moved from IMPLEMENTATION_PLAN.md. Status: ✅ Complete. Git tag: `v1.3.0`.
> See IMPLEMENTATION_PLAN.md's Phase Overview table for the one-line summary; see `docs/reference/architecture/query-engine.md` for current detail.

**Goal:** Ship Future Scope 1.14 (speaker-labeled retrieval) and 2.9 (chunker speaker-misattribution), both found during Phase 13 review, plus two real-world fixes from manual testing.

### 14.1 Chunker fix (2.9)
- `src/ingestion/chunker.py` — `_merge_short_segments` now speaker-aware (see FUTURE_SCOPE.md 2.9); dead code removed (`_block_embedding_indices`, `_blocks_to_topic_segment`, duplicate `_average_embeddings`, unused `blocks` param, `_group_by_speaker`/`SpeakerBlock`)
- `tests/unit/test_chunker.py` — reworked for the above

### 14.2 Speaker-labeled retrieval (1.14)
- `src/query/tool_dispatcher.py` — `_label_for_llm()` inline speaker labeling; `speaker_pairs` episode-scoped filter fix (see FUTURE_SCOPE.md 1.14)
- `src/storage/vector_store.py` — `SearchFilters.speaker_pairs` replaces `speaker_id`; `PgvectorStore.search()` uses `tuple_(...).in_(...)`
- `tests/unit/test_tool_dispatcher.py` — reworked; new `_label_for_llm` and multi-episode-match tests
- `tests/integration/test_vector_store.py` — new, 11 tests; surfaced an untrained-ivfflat-index test issue, worked around with a `SET enable_indexscan/enable_bitmapscan = off` autouse fixture local to the file

### 14.3 Deleted-episode guard
- `src/ingestion/pipeline_runner.py` — `run_ingest()` logs and returns cleanly if its episode was deleted before the worker picked up the job, instead of raising

### 14.4 Logging config consistency
- `src/ingestion/chunker.py` — removed `logging.basicConfig()` (a library module isn't the right place for it)
- `src/worker.py` — added `logging.basicConfig()`, matching `main.py`'s entry-point pattern

### Known issues / tech debt noted
- `reingest_episode_handler` still has no `pipeline_status` guard against a mid-pipeline reingest (carried from Phase 13)
- No guard against deleting a feed/episode while a job is queued/running for it — 14.3 handles the job side, not the delete side

### Phase 14 Done When
- Full test suite green (`uv run pytest`)
- Git tag: `v1.3.0`

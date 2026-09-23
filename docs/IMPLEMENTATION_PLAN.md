# Podcast Knowledge Engine — Implementation Plan

> Read alongside `ARCHITECTURE.md`. This document tells you **what to build, in what order, and why**.
> Each phase produces something runnable. Never more than one phase "in flight" at a time.

> **Public name:** This project is published as **Throughline**. Internal naming throughout this document uses the original working title (Podcast Knowledge Engine).

## Current Status

Phases 0 through 18 (including the unplanned 10.1 follow-up) are **✅ Complete** as of git tag `v1.7.0`. This document now carries only the durable, always-relevant planning material — guiding principles, the phase overview, and agent-collaboration guidance. Full build-by-build detail for every completed phase (tasks, code, decisions made, known tech debt at the time, done-when criteria) has moved to `docs/reference/phases/` — one file per phase, named `phase-NN-slug.md`. Open a specific phase file when you need the history behind a decision; you don't need to read them to work on new features.

For what to build next, see `FUTURE_SCOPE.md` — in particular its "What to Build Next (Recommended Order)" section.

Phase 19 (Local Embedding Support) is 🚧 in progress — see the task breakdown below. Phase 19.1 (Remote Embedding `dimensions` Parameter) is ✅ Complete — see `docs/reference/phases/phase-19.1-embedding-dimensions-param.md`. Phase 20 (OpenAI Model Compatibility) is ✅ Complete as of `v1.7.3`. Phase 20.1 (Transcript Segmentation Hardening) is ✅ Complete as of `v1.7.4` — see `docs/reference/phases/phase-20.1-transcript-segmentation-hardening.md`.

## Before You Start

This is the implementation plan for the **Podcast Knowledge Engine** — a local-first RAG application that ingests podcast feeds, transcribes and diarizes episodes, and exposes a freeform chat interface for querying podcast content. The full system design, schema, API reference, and configuration are in `ARCHITECTURE.md`. Read that document first and keep it open alongside this one.

**Tech stack:** Python 3.12 + uv, FastAPI, SQLAlchemy (async), PostgreSQL + pgvector, React + Vite + TypeScript, OpenTelemetry + Phoenix. All LLM and embedding calls use an OpenAI-compatible client pointed at a configurable endpoint — local (Ollama, llama.cpp) or cloud.

**Key design constraints to carry through every phase:**
- `speaker_id` is the stable link between segments/chunks and speaker metadata. Display names live only in `episode_speakers.display_name` and are resolved via join at read time. Never store display names in `transcript_segments` or `chunks`.
- The DB is the source of truth for pipeline status. SSE streams read from the DB — they are not a direct pipe from the background worker.
- CPU/GPU-bound work (Whisper, Senko) must run in a `ProcessPoolExecutor`. Calling it directly blocks the asyncio event loop and freezes the API.
- All injectable dependencies (DB session, LLM client, embedding client, IngestionQueue) are wired through `src/api/dependencies.py` and injected via FastAPI's `Depends()`. Do not instantiate them inline in route handlers.

---

## Guiding Principles

- **Vertical slices over horizontal layers** — get one thing working end-to-end before generalizing
- **Test as you go** — each phase has explicit test targets; don't skip them
- **No premature abstraction** — build the concrete thing first, extract the interface when you have two implementations
- **Commit at phase boundaries** — each phase = one meaningful git tag
- **Agent-friendly tasks are marked** — sections where Claude Code / a coding agent can do the heavy lifting are noted with 🤖

---

## Phase Overview

| Phase | What You Build                                              | Runnable At End                                                                                  | Detail |
| ----- | ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ------ |
| 0     | Project scaffold, tooling, DB ✅ Complete                    | `GET /health` returns 200                                                                        | `docs/reference/phases/phase-00-scaffold.md` |
| 1     | RSS feed ingestion + IngestionQueue ✅ Complete              | Feed + episodes in DB; queue abstraction in place                                                | `docs/reference/phases/phase-01-rss-ingestion.md` |
| 2     | Audio download + transcription pipeline ✅ Complete          | Episode transcript in DB via SSE-tracked job                                                     | `docs/reference/phases/phase-02-transcription.md` |
| 3     | Speaker inference + naming API ✅ Complete                   | LLM infers host name with confidence; pipeline runs straight to chunking                         | `docs/reference/phases/phase-03-speaker-inference.md` |
| 4     | Chunking + embedding ✅ Complete                             | Chunks with vectors in pgvector; speaker_id linked                                               | `docs/reference/phases/phase-04-chunking-embedding.md` |
| 5     | Basic RAG query ✅ Complete                                  | Single-turn Q&A over transcript content                                                          | `docs/reference/phases/phase-05-basic-rag.md` |
| 6     | Tool-calling query engine ✅ Complete                        | Multi-turn chat with conditional retrieval; multi-feed scope                                     | `docs/reference/phases/phase-06-tool-calling.md` |
| 7     | Frontend — feeds + episodes + speaker naming ✅ Complete     | Full ingestion flow in UI with SSE progress                                                      | `docs/reference/phases/phase-07-frontend-ingestion.md` |
| 8     | Frontend — chat interface ✅ Complete                        | Full product usable end-to-end; chat in three contexts                                           | `docs/reference/phases/phase-08-frontend-chat.md` |
| 9     | Observability ✅ Complete                                    | OTel traces on all LLM, retrieval, and pipeline calls via Phoenix                                | `docs/reference/phases/phase-09-observability.md` |
| 10    | Polish, docs, demo prep ✅ Complete                          | Shippable                                                                                        | `docs/reference/phases/phase-10-polish-demo-prep.md` |
| 10.1  | Feed sort, cache invalidation, pagination fixes ✅ Complete  | Unplanned follow-up to Phase 10                                                                  | `docs/reference/phases/phase-10.1-feed-sort-cache-fixes.md` |
| 11    | Transcription timeout, episode deletion  ✅ Complete         | Transcription can timeout and abort. Delete episode transcription data                           | `docs/reference/phases/phase-11-timeout-transcript-delete.md` |
| 12    | Decoupled worker queue (streaQ + Redis) ✅ Complete          | Ingestion runs in a separate worker process; API remains responsive during ingestion             | `docs/reference/phases/phase-12-worker-queue.md` |
| 13    | Speaker diarization (Senko) + per-speaker naming ✅ Complete | Real per-speaker identity; labeled transcript view; speaker preview playback                     | `docs/reference/phases/phase-13-speaker-diarization.md` |
| 14    | Speaker-labeled retrieval + chunker fix ✅ Complete          | Retrieval context carries speaker identity; short-segment merge no longer misattributes speakers | `docs/reference/phases/phase-14-speaker-labeled-retrieval.md` |
| 15    | Query rewriting ✅ Complete                                  | Vague/pronoun-dependent follow-ups resolve to retrievable queries before search; measurable in Phoenix | `docs/reference/phases/phase-15-query-rewriting.md` |
| 16    | Automatic feed polling ✅ Complete                           | Feeds refresh automatically on server startup and via cron in deployed environments; ingestion stays manual | `docs/reference/phases/phase-16-feed-polling.md` |
| 17    | Chat response streaming ✅ Complete                          | Multi-round tool-calling queries show live status while tools run, then stream the final answer token-by-token | `docs/reference/phases/phase-17-chat-streaming.md` |
| 18    | Episode UI updates ✅ Complete                               | Per-episode artwork with feed-artwork fallback; transcript layout/formatting improvements | `docs/reference/phases/phase-18-episode-ui-updates.md` |
| 19    | Local embedding support 🚧 In Progress                       | Embeddings can be produced locally (sentence-transformers) or via external API, selected per-deployment via `.env` | See "Phase 19" section below |
| 19.1  | Remote embedding `dimensions` param ✅ Complete                | Remote embedding endpoints that support OpenAI's `dimensions` parameter can request 768-dim output directly, matching the pgvector schema without relying on the provider's default | `docs/reference/phases/phase-19.1-embedding-dimensions-param.md` |
| 20    | OpenAI model compatibility ✅ Complete                        | LLM calls adapt automatically for OpenAI's gpt-5+ family: non-default `temperature` is omitted, and `reasoning_effort` is set to `"none"` when tools are used, instead of erroring | See "Phase 20" section below |
| 20.1  | Transcript segmentation hardening ✅ Complete                 | Local transcription segments never exceed the embedding token limit even when Whisper drops sentence punctuation on a long run of speech | `docs/reference/phases/phase-20.1-transcript-segmentation-hardening.md` |

---

## Phase 19 — Local Embedding Support (In Progress)

**Why:** the external embedding API in use doesn't support the 768-dim output the existing pgvector schema and already-embedded chunks depend on. Local embedding removes that dependency entirely, using the same `device="auto"`-style pattern already used by `senko.Diarizer`.

**Design note:** unlike `TranscriptionService`/`DiarizationService`, `EmbeddingClient` is constructed in both the API process (`dependencies.py`, for query-time embedding) and the worker process (`worker.py`'s `lifespan()`, for ingestion) — so `LocalEmbeddingClient` must be safe to load in-process in either, and doesn't need Senko's `ProcessPoolExecutor`/warm-subprocess treatment. It offloads `model.encode()` via a plain `run_in_executor` call to keep the event loop free.

**Tasks:**
1. Add `sentence-transformers` dependency.
2. `src/config.py`: add `embedding_backend: str = ""` (`""` = existing API-based client, `"local"` = sentence-transformers). `embedding_model_name` is reused; for local mode it holds a Hugging Face repo id instead of an API model name.
3. `src/llm/local.py`: `LocalEmbeddingClient(EmbeddingClient)` — loads `SentenceTransformer(model_name, device=resolve_device())` once in `__init__` (device resolution: cuda → mps → cpu); `embed()` runs `model.encode()` in an executor.
4. `src/shared/llm.py`: branch `get_embedding_client()` on `settings.embedding_backend`.
5. `.env.example`: document `EMBEDDING_BACKEND`, and flag that `EMBEDDING_BACKEND`/`EMBEDDING_MODEL_NAME` must match exactly across every API and worker deployment sharing the same pgvector data — a mismatch produces no error, just silently degraded retrieval, since embeddings from different models occupy unrelated vector spaces even at matching dimensionality.
6. Same warning added to `ARCHITECTURE.md`'s config reference.
7. Pick the model from the candidates below and verify 768-dim output before wiring in a default. Fallback if none fit: a pgvector schema migration + re-embed, not the default plan.
8. Update `docs/reference/architecture/protocols.md`'s `EmbeddingClient` implementations row.

**Model chosen:** `Alibaba-NLP/gte-modernbert-base` — 768-dim native, Apache 2.0, no `trust_remote_code`, ungated, ~149M params, and (unlike most of the alternatives considered) needs no query/document prefix, so `EmbeddingClient.embed()`'s flat `texts: list[str]` signature stays accurate with no further plumbing. Other candidates considered and ruled out:
- `nomic-embed-text-v1.5` — needs a prefix; `trust_remote_code` requirement is conditionally avoidable on newer transformers/sentence-transformers but adds risk
- `nomic-ai/modernbert-embed-base` — same architecture family and size class as the chosen model, but needs a prefix
- `BAAI/bge-base-en-v1.5`, `sentence-transformers/all-mpnet-base-v2` — viable, but GTE-ModernBERT benchmarks ahead of both at the same size class
- `intfloat/e5-base-v2` — requires `"query: "`/`"passage: "` prefixes on essentially everything, not just optionally
- `google/embeddinggemma-300m` — 768-dim native, but its HF repo is gated (requires accepting Google's Gemma terms + an `HF_TOKEN`), which breaks unattended first-boot model download on the worker
- `Qwen/Qwen3-Embedding-0.6B` — 1024-dim native (768 reachable via Matryoshka truncation, but not one of its headline-documented truncation points); at 0.6B params it's 3-5x the size of the other candidates and doesn't comfortably fit the target deployment's memory budget

Query/document prefix support (needed if a future model swap picks one of the prefix-sensitive candidates above) is deliberately deferred — see `FUTURE_SCOPE.md` 2.11.

**Found during implementation:** `get_embedding_client()`/`get_llm_client()` needed `@lru_cache` (matching `get_settings()`'s existing pattern) — without it, FastAPI's per-request `Depends()` caching was constructing a fresh `LocalEmbeddingClient` on every chat message, reloading the model and re-verifying its Hugging Face cache each time. Invisible with the API-based client (cheap to construct); a real bug once construction does actual work. See `docs/reference/architecture/protocols.md`'s EmbeddingClient section for the detail.

**Done when:** `EMBEDDING_BASE_URL=local` produces 768-dim vectors end-to-end (ingestion + query) with no schema change, on CPU, MPS, and CUDA. CPU and MPS verified via local smoke test. **CUDA still open** — not yet verified on any CUDA device.

---

## Phase 20 — OpenAI Model Compatibility

**Why:** two separate incompatibilities surfaced while testing Phase 19.1 against OpenAI directly, both specific to OpenAI's gpt-5-and-later family:
1. These models reject any `temperature` value other than their default (1) — `400 invalid_request_error`, structured `param: "temperature"`, `code: "unsupported_value"`. `OpenAICompatibleLLMClient.complete()`/`.stream()` currently always send `temperature`, so any call routed to one of these models fails outright.
2. Separately, calling one of these models with function tools on `/v1/chat/completions` fails unless `reasoning_effort` is explicitly set to `"none"` — observed directly against `gpt-5.6-luna`: `400 invalid_request_error`, `"Function tools with reasoning_effort are not supported for gpt-5.6-luna in /v1/chat/completions. To use function tools, use /v1/responses or set reasoning_effort to 'none'."` We never send `reasoning_effort` today, so the model's own default reasoning mode conflicts with tool calling.

A single hardcoded default temperature (or no `reasoning_effort` handling at all) can't work across every provider this app is designed to support — both issues need the same kind of fix: detect "this is one of OpenAI's reasoning models" and adjust the request accordingly.

**Design note:** decided against runtime error-driven detection (attempt a call, catch the specific `BadRequestError`, retry with adjusted params, remember the result) in favor of a static, name-based check performed once at client construction, for both issues. Reasoning: the failure mode is deterministic and known ahead of time for entire model families, so there's no need to spend a failed request discovering it per deployment — a name pattern (updated when a new non-conforming family ships) is simpler and avoids adding retry/state-management complexity to `complete()`/`stream()`. Both checks share one underlying classification (`_is_gpt5_plus`) rather than two independently-maintained detections, so they can't drift apart from each other as new models ship. Scope is deliberately limited to OpenAI's gpt-<N>, N>=5 family for now — o-series (o1/o3/o4) behavior for either quirk hasn't been confirmed, so it isn't classified; each of the two capability checks has its own override sets (for temperature support and for the reasoning-effort requirement independently) so o-series or any other family can be added later, or an individual model excepted, without the two checks drifting apart from each other.

**Tasks:**
1. New file `src/llm/model_capabilities.py`:
   - `_is_gpt5_plus(model_name: str) -> bool` (private): matches OpenAI's `gpt-<N>` where `N >= 5` (regex-based on the leading version number, so `gpt-6` and later match with no code change, and `gpt-5.6-luna` already matches correctly; `gpt-4o`/`gpt-4.1`/`gpt-3.5-turbo` correctly don't match). o-series (o1/o3/o4) is out of scope for now — behavior for either quirk hasn't been confirmed against it.
   - `supports_temperature(model_name: str) -> bool` — checks its own override sets (`_FORCE_TEMPERATURE_FIXED`/`_FORCE_TEMPERATURE_ADJUSTABLE`), then falls back to `not _is_gpt5_plus(model_name)`.
   - `needs_reasoning_effort_none(model_name: str) -> bool` — checks its own override sets (`_FORCE_REASONING_EFFORT_NONE_REQUIRED`/`_FORCE_REASONING_EFFORT_NONE_NOT_REQUIRED`), then falls back to `_is_gpt5_plus(model_name)`.
2. `src/llm/client.py`: `OpenAICompatibleLLMClient.__init__` computes `self._supports_temperature` and `self._needs_reasoning_effort_none` once. `complete()` and `stream()`: only add `temperature` to kwargs when `self._supports_temperature`; add `reasoning_effort="none"` to kwargs whenever `tools` is truthy and `self._needs_reasoning_effort_none` is `True`.
3. `tests/unit/test_model_capabilities.py`: cover `gpt-3.5-turbo`, `gpt-4o`, `gpt-4.1`, `gpt-5`, `gpt-5-mini`, `gpt-5.1`, `gpt-5.6-luna`, and a non-OpenAI name (e.g. `llama3.1:8b`) against both `supports_temperature` and `needs_reasoning_effort_none`.
4. `backend/README.md`: note this behavior near the `LLMClient` section — which model families are affected, both quirks, and where to add an override if a new model contradicts the naming pattern (OpenAI's own docs and actual API behavior have already been observed to disagree at least once).
5. `tests/unit/test_llm_client.py` (new file — none exists yet for this module despite `backend-README.md` §8 claiming embedding-client contract coverage): cover both `OpenAICompatibleEmbeddingClient` (satisfies `EmbeddingClient`; `embed()` passes `dimensions` through to the request — deferred here from Phase 19.1) and `OpenAICompatibleLLMClient`'s temperature-omission and `reasoning_effort`-injection behavior from this phase.

**Done when:** a chat request with tools routed to an OpenAI `gpt-5`-family (or `o`-series) model succeeds with no `temperature` sent and `reasoning_effort="none"` sent, while requests to `gpt-4o`/Ollama-hosted models are unaffected (unchanged `temperature`, no `reasoning_effort` added).

---

## Agent-Assisted Development Guide

**DO give the agent:**
- `ARCHITECTURE.md` + this document as context
- One bounded task: "implement `src/ingestion/speaker_resolver.py` per Phase 3.1"
- Existing code it will interact with
- The test file to write against
- The relevant `docs/reference/phases/phase-NN-*.md` file when the task revisits or extends a specific completed phase

**DON'T ask the agent to:**
- Design the architecture (done)
- Build multiple phases at once
- Make infrastructure decisions (decided)

**Effective prompts:**
```
"Implement src/ingestion/chunker.py per Phase 4.1 (docs/reference/phases/phase-04-chunking-embedding.md).
Input: list[TranscriptSegment] from src/transcription/base.py.
Key constraint: chunks store speaker_id (not display_name) — see ARCHITECTURE.md section 3.5.
Write tests/unit/test_chunker.py first (TDD), then implement.
Use tests/fixtures/sample_transcript.json fixture."
```

```
"Implement src/ingestion/speaker_resolver.py per Phase 3.1 (docs/reference/phases/phase-03-speaker-inference.md).
Takes a LLMClient (Protocol from src/llm/base.py) — do not use AsyncOpenAI directly.
Return InferredSpeaker | None — never guess, return None on low-quality result.
Inject MockLLMClient in tests/unit/test_speaker_resolver.py."
```

```
"Implement src/query/result_hydrator.py per Phase 5.1 (docs/reference/phases/phase-05-basic-rag.md).
Input: list[RawChunkResult] from src/storage/vector_store.py.
Must resolve speaker_id to display_name via join on episode_speakers.
Write tests/unit/test_result_hydrator.py first."
```

```
"Implement the IngestionQueue protocol and BackgroundTaskQueue in src/ingestion/queue.py per Phase 1.4 (docs/reference/phases/phase-01-rss-ingestion.md).
The queue must enforce MAX_CONCURRENT_INGESTIONS via asyncio.Semaphore.
Include get_position() for QUEUED jobs.
Test that BackgroundTaskQueue satisfies the IngestionQueue Protocol."
```

---

## Milestone Summary

| Tag                                   | What Works                                                                                   |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `v0.1.0-scaffold`                     | Health endpoint, DB connected                                                                |
| `v0.1.1-feeds`                        | RSS ingestion, episode listing, queue abstraction                                            |
| `v0.1.2-transcription`                | Transcription pipeline, SSE status streaming                                                 |
| `v0.1.3-speakers`                     | LLM speaker inference with confidence; pipeline runs straight to READY                       |
| `v0.1.4-chunking`                     | Chunks + embeddings, speaker_id preserved, short segment merging                             |
| `v0.1.5-basic-rag`                    | Simple Q&A with resolved speaker names; parent_text used for LLM context                     |
| `v0.1.6-tool-calling`                 | Multi-turn chat, tool-calling, conditional retrieval, multi-feed scope                       |
| `v0.1.7-frontend-ingestion`           | Browser-based ingestion with SSE progress                                                    |
| `v0.1.8-frontend-chat`                | Full product in browser; chat in three contexts; resizable panels; citations with audio      |
| `v0.1.9-observability`                | OTel traces via Phoenix; LLM, retrieval, pipeline, speaker inference all traced              |
| `v0.2.1`                              | Transcript viewer, speaker name removal                                                      |
| `v0.2.1-app-polish`                   | Feed sort by latest episode, FeedKebab menu, cache invalidation fixes, pagination scroll fix |
| `v0.2.2-timeout-transcript-delete`    | Added llm timeout and transcript delete capability                                           |
| `v1.0.0`                              | Shippable, documented, demo-ready.                                                           |
| `v1.1.0`                              | Decoupled worker queue (streaQ + Redis); ingestion survives API restarts; single-compose-file deploy |
| `v1.2.0`                              | Local speaker diarization (Senko) + per-speaker name inference; labeled transcript view; speaker preview playback |
| `v1.3.0`                              | Speaker-labeled retrieval context (inline LLM labels + episode-scoped speaker_pairs filter); chunker speaker-misattribution fix; deleted-episode job guard |
| `v1.4.0`                              | Query rewriting: conversation-aware pre-retrieval rewrite (passthrough by default), transient substitution only, chat span telemetry for original vs. rewritten query |
| `v1.5.0`                              | Automatic feed polling: `poll_all_feeds` routine, `scripts/feed_polling.py` CLI wrapper shared by dev startup chain and host cron, no auto-ingest |
| `v1.6.0`                              | Chat response streaming: SSE `status`/`token`/`done`/`error` events, `QueryEngine.chat_stream()`, thinking-model-safe `StreamAccumulator`, incremental frontend rendering |
| `v1.7.0`                              | Episode UI updates: per-episode artwork (`episodes.image_url`, item-level `<itunes:image>` parsing) with feed-artwork fallback; transcript view groups consecutive same-speaker segments with a per-speaker start timestamp |
| `v1.7.1`                              | Test isolation: `Settings.testing` auto-detects via `"pytest" in sys.modules`, skipping real `WorkerContext`/OTel construction in the API lifespan under test; `client` fixture default-overrides `get_ingestion_queue` and `get_embedding_client`; fixed a `WorkerContext` construction bug (missing `diarization_service`) in the no-Redis lifespan path found along the way |
| `v1.7.2`                              | Phase 19.1 — remote embedding `dimensions` parameter: `OpenAICompatibleEmbeddingClient` always requests `EMBEDDING_DIMENSIONS` via the API's `dimensions` field, verified directly against Ollama and OpenAI; a mismatched vector now fails at `PgvectorStore` insert time instead of silently degrading retrieval |
| `v1.7.3`                              | Phase 20 — OpenAI gpt-5+ compatibility: `src/llm/model_capabilities.py` classifies the gpt-5+ family; `OpenAICompatibleLLMClient` omits `temperature` and sets `reasoning_effort="none"` for tool calls accordingly; verified live against gpt-5.5-luna |
| `v1.7.4`                              | Phase 20.1 — transcript segmentation hardening: three-tier segmentation (punctuation → pause-rescue → hard-cut) in `LocalTranscriptionService` fixes an embedding-token-limit crash caused by Whisper occasionally dropping sentence punctuation on long runs of speech; settings-driven via `Settings`, verified against faster_whisper and mlx_whisper |
| `v1.8.0`                              | Artwork proxy fallback: `CoverArt` component tries direct embed, falls back to new `/episodes/{id}/artwork` and `/feeds/{id}/artwork` same-origin proxy endpoints on failure, then a placeholder; fixes broken images on podcast hosts with hotlink/referrer protection. Also fixes a feed-level `image_url` variable-shadowing bug in `rss_parser.py` where the per-episode loop was clobbering the feed's own artwork URL |
| `v1.8.1`                              | Dockerfile fix: `ENV UV_NO_SYNC=1`, resolving CUDA lib installation issues caused by unnecessary reinstalls during build |
| `v1.8.2`                              | Added `run_label` to `IngestRequest`, ingest and reingest endpoints, propagated to OTEL span attributes for pipeline-run benchmarking (e.g. filtering by `attributes["run_label"]` in Phoenix); `build_worker()` factory in `src/worker.py` now builds a fresh Modal `Worker` per invocation instead of reusing the cached singleton, fixing the warm-container lifespan-reuse crash |

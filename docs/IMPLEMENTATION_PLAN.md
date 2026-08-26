# Podcast Knowledge Engine — Implementation Plan

> Read alongside `ARCHITECTURE.md`. This document tells you **what to build, in what order, and why**.
> Each phase produces something runnable. Never more than one phase "in flight" at a time.

> **Public name:** This project is published as **Throughline**. Internal naming throughout this document uses the original working title (Podcast Knowledge Engine).

## Current Status

Phases 0 through 17 (including the unplanned 10.1 follow-up) are **✅ Complete** as of git tag `v1.6.0`. This document now carries only the durable, always-relevant planning material — guiding principles, the phase overview, and agent-collaboration guidance. Full build-by-build detail for every completed phase (tasks, code, decisions made, known tech debt at the time, done-when criteria) has moved to `docs/reference/phases/` — one file per phase, named `phase-NN-slug.md`. Open a specific phase file when you need the history behind a decision; you don't need to read them to work on new features.

For what to build next, see `FUTURE_SCOPE.md` — in particular its "What to Build Next (Recommended Order)" section.

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

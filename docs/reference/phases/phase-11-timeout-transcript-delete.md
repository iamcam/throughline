# Phase 11 — LLM Timeout + Episode Transcript Delete

> Moved from IMPLEMENTATION_PLAN.md. Status: ✅ Complete. Git tag: `v0.2.2-timeout-transcript-delete`.
> See IMPLEMENTATION_PLAN.md's Phase Overview table for the one-line summary; see `docs/reference/architecture/query-engine.md` for current detail on the timeout mechanism.

### 11.1 LLM request timeout
- `src/query/engine.py` — `LLM_REQUEST_TIMEOUT_SECONDS = 60.0`; `LLMTimeoutError(Exception)`; both `llm_client.complete()` call sites wrapped in `asyncio.wait_for()`; `asyncio.TimeoutError` re-raised as `LLMTimeoutError`; entire `chat()` body wrapped in a custom `"chat"` tracing span (`session.id`, `chat.tool_rounds_used`, `chat.citation_count` on success; `record_exception` + `span.set_status(trace.StatusCode.ERROR)` on exception); requires both `from opentelemetry import trace` (for `StatusCode`) and `from src.telemetry.tracer import tracer` (for `.start_as_current_span()`)
- `src/api/routers/chat.py` — `LLMTimeoutError` caught in `send_message`, mapped to `504 Gateway Timeout`
- `ARCHITECTURE.md` — tech debt callout replaced with description of what shipped; row removed from Upgrade Path table

### 11.2 Episode transcript delete
- `src/ingestion/feed_service.py` — `delete_episode_transcription(episode_id, db) -> bool`; existence check via `get_episode()` first (child tables may have zero rows for a valid never-ingested episode); bulk-deletes `Chunk`, `TranscriptSegment`, `EpisodeSpeaker`; resets `pipeline_status="PENDING"`, clears `pipeline_stage`, `pipeline_progress`, `pipeline_error`, `ingestion_job_id`; episode row preserved
- `src/api/routers/episodes.py` — `DELETE /{episode_id}/transcript` → `204`/`404`
- `src/api/client.ts` — `deleteEpisodeTranscript(episodeId)`
- `src/lib/queryInvalidation.ts` — `invalidateEpisode(queryClient, episodeId, feedId)` invalidates `['episode', episodeId]` and `['episodes', feedId]`; replaces inconsistent ad-hoc inline invalidation across both pages; fixes cross-page status staleness mid-ingestion
- `src/components/EpisodeKebab.tsx` — new; Reingest + Delete transcript menu items; `disabled` prop for external pipeline-active state; `MutationLike` exported; `AlertDialog` confirmation before delete; correct `isPending` guard polarity (`if (isPending) return`, not `if (!isPending) return`)
- `src/components/FeedKebab.tsx` — fixed inverted `isPending` guard in `onDelete` (was preventing delete from ever firing under normal use)
- `src/components/EpisodeRow.tsx` — `onReingest` removed; `reingestMutation`/`deleteTranscriptMutation: MutationLike` added; `EpisodeKebab` rendered conditionally when `status !== 'PENDING'`, disabled when `isActive`
- `src/pages/EpisodesPage.tsx` — `deleteTranscriptMutation` added; `reingestMutation.onSuccess` updated to `invalidateEpisode`
- `src/pages/EpisodeDetailPage.tsx` — `EpisodeKebab` integrated; `ingestMutation`, `reingestMutation`, `deleteTranscriptMutation` all use `invalidateEpisode`

### Decisions made

- **streaQ, not ARQ.** ARQ entered maintenance-only mode upstream partway through design; streaQ is the community's stated successor, same async-native-plus-Redis shape.
- **No caller-supplied job id.** streaQ's `enqueue_unsafe`/`Task` always auto-generate an id — no supported way to request a specific one. Eliminated the id-collision dedup design entirely in favor of Postgres-only dedup.
- **Postgres is the sole dedup authority.** Both `ingest` and `reingest` rely entirely on `episode.pipeline_status` checks. No queue-level backstop, by design.
- **`get_position()` dropped from the Protocol entirely.** No native equivalent in either backend without reaching into unstable internals. The "where am I in the queue" need is better served by a future Postgres-only queue-overview feature (Future Scope 2.1b) than by the queue layer.
- **`enqueue_unsafe` over type stubs.** Both require some hand-synchronized contract across the process boundary (a string name vs. a full duplicated signature); the string is the smaller surface area and preserves "API process never imports pipeline code."
- **streaQ is built on `coredis`, not `redis-py`.** `StreaqQueue`'s error-wrapping decorator catches `coredis.exceptions.RedisError`.
- **`StreaqQueue` requires its async context manager entered before any operation works**, and must be entered/exited within a single continuous coroutine — not across a pytest fixture's `yield`, which trips anyio's `CancelScope` bookkeeping. Entered once via `AsyncExitStack` in `main.py`'s lifespan and held open for the process lifetime.
- **`WorkerContext` holds LLM/embedding clients and the transcription service, not `AudioDownloader`.** The first three wrap real connection pools or a persistent `ProcessPoolExecutor` worth keeping warm across jobs; `AudioDownloader` constructs a fresh `httpx.AsyncClient` per call regardless, so there's nothing to preserve.
- **`transcription_max_workers` and `max_concurrent_ingestions` are independent settings**, both defaulting to `1`. The former bounds CPU-bound Whisper parallelism inside one worker process; the latter bounds how many jobs that process runs concurrently overall. Raising one doesn't require raising the other.
- **`src/shared/` introduced** (`db.py`, `llm.py`, `jobs.py`) as neutral ground both the API and worker processes import from — avoids either process reaching into the other's package for `AsyncSessionLocal`, LLM/embedding client factories, or the `INGEST_EPISODE_JOB` dispatch string.
- **`LocalTranscriptionService` owns its `ProcessPoolExecutor` as an instance attribute**, not a module-level global — fixes a pre-existing bug where `transcription_max_workers` was silently ignored, and matches how the rest of the codebase handles dependencies (explicit construction, injectable for tests).
- **Downloaded audio is job-lifetime-only.** Deleted on pipeline success (not failure, to preserve the redownload-skip optimization for a redelivered job); swept on worker/API startup; never mounted as a persistent volume in any compose file.
- **One compose file, not two.** `docker-compose.prod.yml` deleted — Postgres/Redis are cheap to self-host regardless of deployment target; the actually expensive parts (LLM inference, transcription) were already externalizable via the default compose file. Self-hosters with existing Postgres/Redis edit `docker-compose.yml` directly rather than using a separate trimmed file.
- **One `entrypoint.sh`, branching on an argument**, not a second `worker-entrypoint.sh` — avoids drift between two near-identical migration-then-launch scripts.
- **PyTorch pinned to CPU-only unconditionally** via `[tool.uv.sources]` in `pyproject.toml`, rather than an extras-based CPU/CUDA split — resolves Docker/Linux builds silently pulling CUDA wheels from PyPI's default index. Acceptable given this is effectively a single-developer project today; tracked as Future Scope 2.1f if that changes.

> **Note:** the streaQ/Redis decisions above properly belong to Phase 12 (Decoupled Worker Queue) and were captured here at handoff time before that phase formally began. See `phase-12-worker-queue.md` for that phase's actual implementation.

### Known issues / tech debt noted
- `EpisodeDetailPage` button area needs a cleanup pass — debug elements remain (e.g. `<div>status: {status}</div>`)
- `ExpandableDescription` toggle renders unconditionally — carried from Phase 10.1
- No feed-level error/health signal — carried from Phase 10.1
- `FeedKebab` double-fire guard on `AlertDialogAction` — carried from Phase 10.1

### Next session starts here (at time of writing)
1. Decoupled worker queue (streaQ + Redis) — see `phase-12-worker-queue.md`

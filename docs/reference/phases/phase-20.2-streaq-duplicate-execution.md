# Phase 20.2 — streaQ Duplicate Execution Fix

> Status: ✅ Complete. Git tag: `v1.8.3`.
> Unplanned bugfix, following Phase 20.1.

**Bug:** With `MAX_CONCURRENT_INGESTIONS=2` and several episodes queued, the worker intermittently ran the same ingestion job twice, concurrently — two pipelines writing status, transcripts, and chunks for one episode. It looked like streaQ deciding a slow task had stalled and retrying it; earlier attempts (idempotency guards, error handling, timeouts, TTLs) didn't resolve it.

**Root cause:** streaQ's prefetch buffer, not slow tasks. Mechanics, confirmed against streaQ 7.2.0's source:
- Messages read from the Redis stream stay pending under the worker's consumer, each with an idle clock.
- `renew_idle_timeouts` resets that clock every `0.9 × idle_timeout` — but only for tasks currently running. Prefetched tasks waiting in the worker's in-memory buffer are never renewed.
- By default the worker holds `(prefetch or concurrency) + concurrency` tasks in total — 4 at concurrency 2 — so 2 wait unrenewed in the buffer while 2 run.
- Every fetch also runs `XAUTOCLAIM`, reclaiming any pending message idle longer than `idle_timeout` — including messages this same worker already holds. A buffered task waiting behind a multi-minute episode passes `idle_timeout`, gets reclaimed, and a second copy (same message id, same task id) enters the buffer.
- streaQ's pre-run check (`refresh_timeout`) only asks whether the message is still pending for this consumer. Both copies pass, so when the copy reaches a free slot while the original is still running, the task runs twice concurrently. streaQ logs this as `Task ... ran twice in the same worker!` and attributes it to a blocked event loop, which was misleading here.
- At concurrency 1 the duplicate always lands behind the original, runs after the original has acked, and is dropped harmlessly (`task ↩ ... reclaimed`) — which is why the bug only surfaced once concurrency was raised to 2.
- `prefetch=0` does not disable prefetching despite streaQ's docs: `prefetch or concurrency` treats `0` as unset.

Being slow does not make a *running* task stale: streaQ has no notion of progress, it only renews running tasks on a timer. A 40-minute job is renewed ~22 times at `idle_timeout=120` and is never reclaimed as long as the event loop stays responsive.

### Tasks

#### 20.2.1 Fetch only when a slot is free
`build_worker()` (`src/worker.py`) sets `worker.prefetch = worker.concurrency` after constructing the `Worker`. Naming trap: the constructor argument `prefetch` means *extra* tasks beyond concurrency, while the attribute `worker.prefetch` is the *total* held (running + buffered), read when `run()` creates the buffer. With total == concurrency, every held task is running and being renewed, so nothing ever waits unrenewed. Applies to every entry point that builds through `build_worker()`, including the CLI entry point `src/worker_cli.py` (`streaq run src.worker_cli:worker`, which exists so importing `build_worker()` elsewhere doesn't eagerly construct a worker as an import side effect).

#### 20.2.2 Event-loop hygiene
The remaining duplicate path: the event loop blocks for longer than `idle_timeout` (so renewal can't run), then a freed slot's fetch reclaims a still-running task. Synchronous work moved off the loop via `asyncio.to_thread`: `align_segments` and `Chunker.chunk` (confirmed thread-safe — `tiktoken` encoding is thread-safe and `chunk()` only reads instance config), plus `AudioDownloader`'s per-chunk file writes and final rename. Whisper and Senko already run in `ProcessPoolExecutor`. `AudioDownloader`'s progress callback is now throttled to ≥1% steps instead of firing once per 64 KB chunk.

#### 20.2.3 Configurable streaQ lifecycle settings
- `STREAQ_WORKER_IDLE_TIMEOUT` (default `120`) → `Worker(idle_timeout=...)`. How long a running task can go without a liveness renewal before it's reclaimable; also the delay before a crashed worker's task is picked up again.
- `STREAQ_TASK_TIMEOUT` (default `7200`) → `@worker.task(timeout=...)`. streaQ's `@worker.task` has no default timeout, so ingestion jobs previously had none. This is a hang backstop, not a speed limit — it must never kill a legitimately long episode. Stalled downloads are caught separately by httpx's read timeout in `AudioDownloader` (`timeout=300`, i.e. 300s without receiving bytes), which tolerates slow-but-progressing downloads.

#### 20.2.4 Timeout/cancellation leaves an ERROR status
`ingest_episode` catches `asyncio.CancelledError`, writes `ERROR` ("Ingestion cancelled or timed out") inside `anyio.CancelScope(shield=True)`, then re-raises. The shield is required: streaQ enforces task timeouts with an anyio cancel scope (`move_on_after(timeout, shield=True)` around the task), and anyio cancellation is level-triggered — any unshielded `await` inside the handler is itself cancelled immediately, so the status write would never land and the episode would stay frozen mid-stage. Verified by temporarily setting `STREAQ_TASK_TIMEOUT=60`.

#### 20.2.5 Worker diagnostics
`ingest_episode_job` logs a `🔰` start line with `task_id`, `context.tries`, `episode_id`, and a per-`build_worker()` instance id. Two `🔰` lines for one `task_id`, or `try` > 1 without a crash, indicates a reclaim.

#### 20.2.6 Concurrency guidance
Each local pipeline service (Whisper, Senko) owns its own `ProcessPoolExecutor` of `PIPELINE_MAX_WORKERS` slots. At 2:1, two jobs can transcribe and diarize at the same time but not both transcribe at once — the waiting job has already started from streaQ's point of view, so that wait counts toward `STREAQ_TASK_TIMEOUT`. Recommended: keep `MAX_CONCURRENT_INGESTIONS == PIPELINE_MAX_WORKERS` so jobs only ever wait in Redis. `.env.example` now ships 2:2; the cost is one model instance per slot on the shared GPU (see FUTURE_SCOPE 2.1h).

#### 20.2.7 Chunker log cleanup
The per-segment "Leaving short segment standalone" log line was replaced with a single per-episode count.

### Rejected: per-episode Redis lock in the task handler
A `SET ingest_episode:{episode_id} NX` lock at task start, skipping the job if already held, was tried and removed:
- A skipped duplicate returns normally, so streaQ acks and deletes the shared stream message and records success while the original is still running — and removes the message from the renewal set.
- It blocks legitimate crash retries: a retry carries the same task id while the old lock is still alive, gets skipped and marked successful, and leaves the episode frozen mid-status.
- It's redundant: API-level dedup already happens via `pipeline_status` checks before enqueue (see `docs/reference/architecture/ingestion-pipeline.md`).

**coredis gotcha found along the way:** `delete()` takes a *collection* of keys (`coredis` 6.9.0: `*[Key(key) for key in keys]`). `delete("ingest_episode:…")` iterates the string and sends one key per character, so the lock was never released and every re-enqueue was skipped until the TTL expired. Always pass lists — `delete([key])`, `srem(key, [member])` — matching streaQ's own usage. The type hints don't catch it and Redis doesn't error.

### Investigating further
If duplicate or reclaimed runs reappear, or streaQ is upgraded:
- **streaQ internals** (`streaq/worker.py` in the installed version): `Worker.__init__` (the `self.prefetch = (prefetch or concurrency) + concurrency` line), `renew_idle_timeouts` (what gets renewed), `producer` (when fetches — and therefore reclaims — happen), `run_task` (the pre-run ownership check and the timeout cancel scope). Lua functions in `streaq/lua/streaq.lua`: `read_streams` (`XAUTOCLAIM` then `XREADGROUP`) and `refresh_timeout`. On Redis versions with `XREADGROUP ... CLAIM` support, streaQ uses `_read_streams_max_count` instead of the Lua path — same idle semantics.
- **On upgrade, re-check the prefetch semantics.** If streaQ fixes `prefetch=0` or starts renewing buffered tasks, the `worker.prefetch` override may become unnecessary — or wrong, if the attribute's meaning changes.
- **Log markers:** streaQ's `task <fn> □ <id> → worker <wid>` (start), `task ↩ <id> reclaimed from worker` (duplicate dropped), `ran twice in the same worker!` (concurrent duplicate), `… timed out`; this app's `🔰` start line (with `try=`).
- **Redis state:** stream `streaq:default:queues:normal`, consumer group `workers`, worker health keys `streaq:default:health:<worker id>`. `XINFO CONSUMERS` and `XPENDING` on the stream show each consumer's pending messages and idle times; exactly one health key should exist per running worker.
- **Test recipe:** queue more episodes than `2 × concurrency` (including long ones), start the worker, then count `🔰` lines against episodes queued and grep for `↩` / `ran twice` / `try=` values other than 1.

### Known issues / follow-ups
- Worth reporting upstream to streaQ: buffered tasks are never renewed, and `prefetch=0` can't disable prefetching.
- Residual risk from an event loop blocked longer than `idle_timeout`; there's no loop-lag watchdog to detect it.
- Throughput/GPU utilization work → FUTURE_SCOPE 2.1h.
- Hard kills (OOM, SIGKILL) still leave a frozen status → FUTURE_SCOPE 2.1g.

### Phase 20.2 Done When
- 9 episodes queued at concurrency 2: exactly 9 `🔰` lines, all `try=1`, no `↩` or `ran twice` ✅
- Re-enqueueing completed episodes on a running worker processes them normally ✅
- A task timeout leaves the episode in `ERROR` with "Ingestion cancelled or timed out" ✅
- Git tag: `v1.8.3`

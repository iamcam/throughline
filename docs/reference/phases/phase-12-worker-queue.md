# Phase 12 — Decoupled Worker Queue (streaQ + Redis)

> Moved from IMPLEMENTATION_PLAN.md. Status: ✅ Complete. Git tag: `v1.1.0`.
> See IMPLEMENTATION_PLAN.md's Phase Overview table for the one-line summary; see `docs/reference/architecture/ingestion-pipeline.md` for current detail.

**Goal:** Ingestion runs in a separate worker process, fully decoupled from the API. The API remains responsive during ingestion; jobs survive API restarts.

### 12.1 IngestionQueue Protocol + StreaqQueue + BackgroundTaskQueue (`src/ingestion/queue.py`)

```python
class JobStatus(Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class JobNotFoundError(Exception): ...
class DuplicateJobError(Exception): ...
class QueueConnectionError(Exception): ...

class IngestionQueue(Protocol):
    async def enqueue(self, episode_id: UUID, job_args: dict) -> str: ...
    async def get_status(self, job_id: str) -> JobStatus: ...
    async def cancel(self, job_id: str) -> bool: ...
```

`enqueue()` takes no caller-supplied job id — the queue always generates and returns its own. There is no `get_position()`. Job dedup is Postgres's responsibility, not the queue's; see 12.6.

`INGEST_EPISODE_JOB`, the function-name string both `StreaqQueue` and `worker.py` use to agree on dispatch, lives in `src/shared/jobs.py` — shared, neutral ground between the API and worker processes, not queue-internal.

**`BackgroundTaskQueue`** — in-process fallback, active when `REDIS_URL` is unset. Takes a `job_runner: Callable[[UUID, dict], Awaitable[None]]` at construction time, not per-call — this is what actually runs a job, set once when the queue is built (`main.py`'s lifespan). `get_status()` raises `JobNotFoundError` for unknown ids, matching `StreaqQueue`.

**`StreaqQueue`** — default when `REDIS_URL` is set. Wraps a `streaq.worker.Worker`, plus an `AsyncExitStack` for connection lifecycle and an optional `queue_name` param (used by tests to isolate runs). `enqueue()` calls `worker.enqueue_unsafe(INGEST_EPISODE_JOB, episode_id, job_args)`, awaits the returned `Task`, returns `task.id` — dispatch by function name string only, so the API process never imports pipeline code. `get_status()` maps streaQ's `TaskStatus` (`QUEUED`/`SCHEDULED`→`QUEUED`, `RUNNING`, `NOT_FOUND`→raise, `DONE`→split via `result_by_id()` into `DONE`/`FAILED`/`CANCELLED`, the last inferred from a stored `StreaqCancelled` exception). `cancel()` uses `Worker.abort_by_id()`. All Redis-touching methods wrapped in a decorator translating `coredis.exceptions.RedisError` into `QueueConnectionError` — streaQ is built on `coredis`, not `redis-py`.

**`StreaqQueue` requires its async context manager to be entered before any operation works** — `enqueue()`/`get_status()`/`cancel()` all route through `Worker`'s internal Redis connection and Lua-script library, both of which are unset until `__aenter__` runs. `main.py`'s lifespan enters it once via `AsyncExitStack` and holds it open for the process lifetime; callers never see this.

Test target: `tests/integration/test_queue.py` (contract tests — Protocol conformance and basic `enqueue()`/`get_status()` behavior, parametrized over both implementations) and `tests/unit/test_background_queue.py` (`BackgroundTaskQueue`-specific lifecycle coverage: status transitions, cancel semantics, concurrency limits).

### 12.2 Config additions (`src/config.py`, `.env.example`)

```python
# Queue
redis_url: str = ""  # empty = in-process BackgroundTaskQueue; set = StreaqQueue (Redis-backed worker)
max_concurrent_ingestions: int = 1  # in-process semaphore size, or streaQ worker concurrency when REDIS_URL is set

# Transcription
transcription_max_workers: int = 1  # ProcessPoolExecutor size for local Whisper, independent of max_concurrent_ingestions
```

`transcription_max_workers` bounds CPU-bound Whisper parallelism inside one worker process. `max_concurrent_ingestions` bounds how many jobs that process runs concurrently overall (I/O-bound stages only). The two can be raised independently — e.g. moving transcription off-box only requires raising `max_concurrent_ingestions`.

`.env.example` documents both, plus a `BACKEND_ENV_FILE` variable (read by Compose only, not the app) that lets `docker-compose.yml` load `backend/.env.docker` instead of `backend/.env` when set — supports keeping native-dev and containerized settings separate without duplicating the whole file.

### 12.3 `pipeline_runner.py` (`src/ingestion/pipeline_runner.py`)

Worker-side pipeline assembly, separated from route-handler code the same way `dependencies.py` separates API-side wiring from route handlers. Holds:

- `build_pipeline_services(settings, worker_context) -> PipelineServices` — assembles per-job services. LLM client, embedding client, and transcription service come from `worker_context` (built once at worker startup, reused across jobs, since each wraps a real connection pool or persistent `ProcessPoolExecutor` worth keeping warm). `AudioDownloader`, `TranscriptStore`, `SpeakerStore`, `Chunker`, `PgvectorStore`, `PipelineStatusService` are built fresh per job — cheap and stateless, nothing worth persisting.
- `run_ingest(episode_id, job_args, services)` — opens its own DB session (two-phase: one to look up the episode, a second held for the pipeline run), calls `ingest_episode()`.
- `WorkerContext` (dataclass: `llm_client`, `embedding_client`, `transcription_service`) and `build_transcription_service(settings)` (Local/Remote branching) — both live here rather than in `worker.py`, since `BackgroundTaskQueue`'s in-process fallback path (12.7) needs the identical assembly logic to run ingestion without a separate worker process.
- `clear_audio_storage(settings)` — wipes `audio_storage_path` on startup. Nothing in that directory is trusted to survive a process restart; files live only as long as a single ingest job takes to run. Called from both `worker.py`'s and `main.py`'s lifespans.

`AsyncSessionLocal` (DB session factory), `get_llm_client()`/`get_embedding_client()`, and `INGEST_EPISODE_JOB` all live in `src/shared/` (`db.py`, `llm.py`, `jobs.py` respectively) — neutral ground both the API and worker processes import from, avoiding either process reaching into the other's package for shared plumbing.

### 12.4 `worker.py` (`src/worker.py`)

streaQ worker process entry point, run via `streaq run src.worker:worker`. Thin by design — constructs the `Worker`, defines its `lifespan()`, registers the one task:

```python
@asynccontextmanager
async def lifespan() -> AsyncGenerator[WorkerContext, None]:
    clear_audio_storage(settings)
    transcription_service = build_transcription_service(settings)
    yield WorkerContext(
        llm_client=get_llm_client(),
        embedding_client=get_embedding_client(),
        transcription_service=transcription_service,
    )
    if isinstance(transcription_service, LocalTranscriptionService):
        transcription_service.shutdown()

worker = Worker(redis_url=settings.redis_url, concurrency=settings.max_concurrent_ingestions, lifespan=lifespan)

@worker.task(name=INGEST_EPISODE_JOB)
async def ingest_episode_job(episode_id: UUID, job_args: dict) -> None:
    services = build_pipeline_services(settings, ingest_episode_job.worker.context)
    await run_ingest(episode_id, job_args, services)
```

`name=INGEST_EPISODE_JOB` is passed explicitly rather than relying on streaQ's default (the function's `__qualname__`) — makes the link between `StreaqQueue`'s dispatch string and this registration visible in the code, since there's no compile-time check tying them together. `ingest_episode_job.worker.context` (not the module-level `worker` reference) is used inside the task body, matching streaQ's documented pattern for tasks that might later be `include()`d into another worker.

`LocalTranscriptionService.shutdown()` — not `RemoteTranscriptionService`, which has no executor to clean up — is called conditionally in the teardown.

### 12.5 `local.py` fix (`src/transcription/local.py`)

`LocalTranscriptionService` owns its `ProcessPoolExecutor` as an instance attribute, built in `__init__`:

```python
class LocalTranscriptionService:
    def __init__(
        self,
        huggingface_token: str,
        whisper_backend: str,
        whisper_model: str,
        diarization_model: str | None,
        max_workers: int = 1,
        executor: ProcessPoolExecutor | None = None,
    ):
        ...
        self._executor = executor or ProcessPoolExecutor(max_workers=max_workers)

    def shutdown(self):
        self._executor.shutdown(wait=True)
```

Replaces a prior module-level global executor that ignored `settings.transcription_max_workers` entirely (hardcoded `max_workers=1`). Instance ownership was chosen over a lazy module-level singleton for consistency with how the rest of the codebase handles dependencies — explicit construction, not module globals — and because the `executor=` injection point makes the class straightforwardly testable (fake executor, or a deliberately shared one across instances) without reaching into module state.

### 12.6 `episodes.py` updates

`_build_pipeline_services`/`_run_ingest` removed — pipeline assembly moved to `pipeline_runner.py` (12.3). `episodes.py` is now a pure producer: look up the episode, call `queue.enqueue(episode_id, job_args)`, write the resulting status/`job_id` to Postgres. It imports nothing from `src.ingestion.pipeline`, `src.transcription`, `src.storage`, or any pipeline-stage module.

`ingest_episode_handler`'s existing `pipeline_status not in ("PENDING", "ERROR")` guard is unchanged and now carries full dedup responsibility — the queue offers no id-collision backstop.

All `queue.get_position(...)` calls removed (method no longer exists on the Protocol); `PipelineStatusUpdate.position` field removed from the schema; ingest/reingest response bodies drop `queue_position`.

**Known gap:** `reingest_episode_handler` has no `pipeline_status` guard at all beyond confirming the episode exists — a reingest can currently be triggered while a pipeline run is already in progress for that episode. Worth adding a guard (block while actively mid-pipeline, allow from any terminal state) before this ships broadly. (Still open as of Phase 14.)

### 12.7 `dependencies.py` + `main.py` wiring

`dependencies.py` unchanged — `get_ingestion_queue(request)` just reads `request.app.state.ingestion_queue`, agnostic to which concrete implementation is present.

`main.py`'s lifespan branches on `settings.redis_url`:

```python
transcription_service = None
async with AsyncExitStack() as stack:
    if settings.redis_url:
        queue = StreaqQueue(redis_url=settings.redis_url)
        await stack.enter_async_context(queue)
        app.state.ingestion_queue = queue
    else:
        transcription_service = build_transcription_service(settings)
        worker_context = WorkerContext(
            llm_client=get_llm_client(),
            embedding_client=get_embedding_client(),
            transcription_service=transcription_service,
        )
        app.state.ingestion_queue = BackgroundTaskQueue(
            max_concurrent=settings.max_concurrent_ingestions,
            job_runner=_make_job_runner(worker_context, settings),
        )

    yield

    if isinstance(transcription_service, LocalTranscriptionService):
        transcription_service.shutdown()
```

`StreaqQueue` is entered once via an `AsyncExitStack` owned by the lifespan itself and held open for the process lifetime — required, since `StreaqQueue.__aenter__`/`__aexit__` must run within a single continuous coroutine for anyio's `CancelScope` bookkeeping to work correctly. The `BackgroundTaskQueue` fallback path builds a `WorkerContext` once at startup (mirroring `worker.py`'s own lifespan) and closes over it in a `job_runner` closure — this is the one place the API process legitimately imports and runs pipeline code, since without a separate worker process it has to act as its own.

### 12.8 Docker Compose + entrypoint

Single root `docker-compose.yml` covers local full-stack development and demo/VPS deployment — no separate prod file. Services: `db`, `redis` (no volume — ephemeral, queued jobs lost on restart, tracked as Future Scope 2.1c), `backend`, `worker` (same image as `backend`, `command: ["./entrypoint.sh", "worker"]`), `frontend`. Self-hosters with existing Postgres/Redis point `DATABASE_URL`/`REDIS_URL` at them and remove the corresponding service.

`backend/entrypoint.sh` branches on an argument rather than maintaining two near-identical scripts:

```bash
#!/bin/bash
set -e
uv run alembic upgrade head
if [ "$1" = "worker" ]; then
    exec uv run streaq run src.worker:worker
else
    exec uv run uvicorn src.api.main:app --host 0.0.0.0 --port 3001
fi
```

`worker` mounts `model_cache` (persisted — re-downloading Whisper/pyannote models on every restart isn't a defensible default) but not `audio_data`, which was removed from every compose file entirely. Downloaded audio is job-lifetime-only: `AudioDownloader.delete()` is called on pipeline success (not failure, preserving the existing `dest.exists()` skip-redownload optimization for a redelivered job), and `pipeline_runner.clear_audio_storage()` sweeps the directory on both `worker.py`'s and `main.py`'s startup as a safety net for anything a crashed job left behind. A periodic sweep for long-running containers (beyond the startup case) is tracked as Future Scope 2.1d.

For native dev (bare-metal `uv run uvicorn`/`streaq run`, not containerized), `backend/docker-compose.db.yml` (renamed from `docker-compose.dev.yml`) and a new sibling `backend/docker-compose.redis.yml` provide standalone Postgres and Redis, startable together (`docker compose -f docker-compose.db.yml -f docker-compose.redis.yml up -d`) or independently.

`ARCHITECTURE.md` §7 and `OPERATIONS.md` now both reflect the real compose setup. (`ARCHITECTURE.md` §7 was later reduced to a summary pointing at `OPERATIONS.md` as the single source of truth for the compose file, during a documentation cleanup pass.)

### 12.9 Contract tests

`tests/integration/test_queue.py` — Protocol conformance and `enqueue()`/`get_status()` basics, parametrized over `BackgroundTaskQueue` and `StreaqQueue`. Requires a running Postgres and Redis.

```python
@pytest.fixture(params=["background", "streaq"])
def queue_cm(request):
    if request.param == "background":
        return _background_queue_cm()
    return StreaqQueue(redis_url=get_settings().redis_url, queue_name=f"test-{uuid4().hex[:8]}")

async def test_enqueue_returns_job_id(queue_cm):
    async with queue_cm as queue:
        job_id = await queue.enqueue(uuid4(), {})
        assert isinstance(job_id, str)
```

`queue_cm` is a plain (non-async) fixture returning an *unentered* context manager — each test does its own `async with queue_cm as queue:`, keeping `StreaqQueue.__aenter__`/`__aexit__` within one continuous test-function coroutine. Necessary, not stylistic: entering/exiting across a fixture's `yield` boundary causes a spurious anyio `CancelScope` "different task" error.

`tests/unit/test_background_queue.py` (renamed from the pre-Phase-12 `test_queue.py`) — full lifecycle coverage for `BackgroundTaskQueue` specifically: `enqueue()` return type, `get_status()` transitions through `RUNNING`/`DONE`/`FAILED`, `cancel()` on queued vs. running jobs, semaphore concurrency limits, Protocol conformance.

Full lifecycle contract tests for `StreaqQueue` (real `RUNNING`→`DONE`/`FAILED`/`CANCELLED` transitions against a live consuming worker) are out of scope for this phase — doing so safely requires a real subprocess worker matching production's actual process topology, tracked as Future Scope 2.1e.

### Known issues / tech debt noted
- Subprocess-level kill on `cancel()` during active transcription — not implemented; see Future Scope 2.1a.
- Queue overview UI (`queued_at`/`finished_at` columns, grouped-by-status view) — deferred; see Future Scope 2.1b.
- Redis has no persistence by default — queued/in-flight jobs are lost on container restart; see Future Scope 2.1c.
- Periodic stale-audio sweep for long-running worker containers, beyond the startup sweep — see Future Scope 2.1d.
- Full lifecycle contract tests for `StreaqQueue` (needs a real subprocess worker) — see Future Scope 2.1e.
- PyTorch is pinned to CPU-only unconditionally in `pyproject.toml`; no extras-based CPU/CUDA split — acceptable for a single-developer project today, see Future Scope 2.1f.
- `reingest_episode_handler` has no `pipeline_status` guard against triggering a reingest mid-pipeline (see 12.6).

### Phase 12 Done When
- `POST /episodes/{id}/ingest` returns `202` immediately; a separate `streaq run src.worker:worker` process performs the actual pipeline run
- Killing/restarting the API process mid-ingestion has no effect on the running job
- Killing/restarting the worker process mid-ingestion: job is re-run from the top on worker restart (streaQ's pessimistic execution — no partial-resume); manually verified against a live queued job
- `cancel()` interrupts a queued or in-progress job at any I/O-bound stage; known-gap behavior (Whisper subprocess) matches the documented limitation, not a crash
- `REDIS_URL` unset falls back cleanly to `BackgroundTaskQueue` with no behavior change from pre-Phase-12
- `docker compose up` from repo root brings up `db`, `redis`, `backend`, `worker`, `frontend` with no manual steps beyond `.env` setup
- Git tag: `v1.1.0`

# Ingestion Pipeline

> Moved from ARCHITECTURE.md §3.4–§3.6a. Referenced from ARCHITECTURE.md — see that doc for the high-level component map. Protocol definitions referenced below (`TranscriptionService`, `DiarizationService`, `IngestionQueue`) live in `docs/reference/architecture/protocols.md`.

## Ingestion Pipeline

`pipeline.py` is a thin orchestrator. It owns sequencing and status transitions, but delegates all business logic to discrete injected services. No stage has knowledge of other stages.

```python
# src/ingestion/pipeline.py
async def ingest_episode(
    episode_id: UUID,
    job_args: dict, # run_label (optional, str)
    services: PipelineServices,   # injected dataclass of all services
) -> None:
    try:
        await services.status.set(episode_id, "DOWNLOADING")
        audio_path = await services.downloader.download(episode)

        await services.status.set(episode_id, "TRANSCRIBING")
        transcript = await services.transcription.transcribe(
            audio_path,
        )
        await services.transcript_store.save(episode_id, transcript)
        # All segments written with speaker_id = 'UNKNOWN' (no diarization in v1)

        await services.status.set(episode_id, "INFERRING_SPEAKERS")
        result = await services.speaker_resolver.infer(transcript.segments)
        await services.speaker_store.save_inferred(episode_id, result)
        # If exactly one speaker inferred: speaker_id promoted to SPEAKER_00,
        # display_name pre-populated, name_inferred=true.
        # If zero or multiple speakers inferred: speaker_id stays UNKNOWN,
        # display_name=NULL. Pipeline does not pause — proceeds straight to chunking.

        await services.status.set(episode_id, "CHUNKING")
        segments = await services.transcript_store.get_segments(episode_id)
        chunks = await services.chunker.chunk(segments)

        await services.status.set(episode_id, "EMBEDDING")
        embedded = await services.embedder.embed(chunks)
        await services.vector_store.upsert(embedded)

        await services.status.set(episode_id, "READY")

    except Exception as e:
        await services.status.set(episode_id, "ERROR", error=str(e))
        raise
```

**Note:** `PENDING_NAMES` was considered when diarization was introduced but deliberately not built. The pipeline never pauses for user input — diarization and per-speaker name inference both run unattended as part of the same continuous job. Speaker display names can be updated at any time via `PUT /speakers`, a metadata-only operation with no effect on chunks or embeddings, regardless of how many speakers an episode has.

**`PipelineServices` dataclass** (`src/ingestion/pipeline.py`):
```python
@dataclass
class PipelineServices:
    status: PipelineStatusService
    downloader: AudioDownloader
    transcription: TranscriptionService
    transcript_store: TranscriptStore
    diarization: DiarizationService
    speaker_resolver: SpeakerResolver
    speaker_store: SpeakerStore
    chunker: Chunker
    embedder: Embedder
    vector_store: VectorStore
```

Each service has a single responsibility and is independently testable by injecting mocks.

### Discrete pipeline services

| Service                 | File                            | Responsibility                                    |
| ----------------------- | -------------------------------- | -------------------------------------------------- |
| `AudioDownloader`       | `ingestion/audio_downloader.py` | httpx streaming download, stores to disk          |
| `TranscriptionService`  | `transcription/base.py`         | Protocol; local or remote impl                    |
| `DiarizationService`    | `diarization/base.py`           | Protocol; local (Senko) impl only                 |
| `TranscriptStore`       | `ingestion/transcript_store.py` | Save/retrieve `transcript_segments` rows          |
| `SpeakerResolver`       | `ingestion/speaker_resolver.py` | LLM inference of one name per diarized speaker    |
| `SpeakerStore`          | `ingestion/speaker_store.py`    | Read/write `episode_speakers` rows                |
| `Chunker`               | `ingestion/chunker.py`          | Speaker-boundary + topic segmentation + hierarchy |
| `Embedder`              | `ingestion/embedder.py`         | Batch embedding via `EmbeddingClient`             |
| `PipelineStatusService` | `ingestion/status_service.py`   | Write status transitions to DB                    |

---

## Ingestion Queue and Worker Model

Understanding the execution model is important for reasoning about frontend reconnects, page refreshes, and job durability.

### Why a separate worker process

Ingestion involves CPU-bound transcription and can run for minutes. Running it in the same process as the API means a long ingestion job and API responsiveness compete for the same event loop's attention, and a crashed/restarted API process would silently kill any in-flight job with no record of how far it got. The queue is Redis-backed (via [streaQ](https://github.com/tastyware/streaq)) specifically to decouple these: the API process only ever enqueues; a dedicated worker process (`streaq run src.worker_cli:worker` — `src/worker_cli.py` just calls `build_worker()` from `src/worker.py`, so importing the factory elsewhere never constructs a worker as a side effect) is the only thing that executes pipeline code.

### Execution model

```
POST /ingest (HTTP request)
  │
  └─► StreaqQueue.enqueue()
        │
        ├─ worker.enqueue_unsafe(INGEST_EPISODE_JOB, episode_id, job_args)
        │    → serializes args, pushes to Redis, returns immediately
        │    → API process never imports pipeline code — dispatch is by
        │      function name string only (see below)
        ├─ Writes pipeline_status=QUEUED to DB    ← DB is source of truth
        └─ Returns job_id (streaQ-generated) immediately

             [HTTP request ends — frontend can close, refresh, disconnect]

        Separate worker process (streaq run), own event loop:
          │
          ├─ Picks up the job (bounded by Worker(concurrency=N))
          ├─ pipeline_runner.py builds PipelineServices — LLM/embedding
          │    clients from Worker lifespan context (built once, reused
          │    across jobs); AudioDownloader built fresh per job (cheap,
          │    stateless, no persistent connection worth holding)
          ├─ Calls PipelineStatusService.set() at every stage transition
          ├─ Delegates CPU-bound work to ProcessPoolExecutor (Whisper)
          │    └─► worker's event loop stays free for other jobs
          └─ Writes pipeline_status=READY (or ERROR) to DB when done

GET /episodes/{id}/status/stream (SSE — separate connection)
  │
  └─► Reads pipeline_status from DB every 2 seconds
        └─ Completely independent of the worker process
           Frontend can connect, disconnect, reconnect at any time
           Status is always current because DB is the source of truth
```

**Key point:** the worker process and the SSE stream are fully decoupled from the API process. The pipeline writes to the DB via `PipelineStatusService`. SSE reads from the DB. A page refresh, an API restart, or a worker restart has no effect on a running job — streaQ's pessimistic execution model keeps a job in Redis until it succeeds or fails, so a worker crash mid-job means the job is picked up again on restart, not lost.

**Decoupled dispatch by name, not import:** `StreaqQueue` calls `worker.enqueue_unsafe(INGEST_EPISODE_JOB, ...)` — `INGEST_EPISODE_JOB` is a plain string constant (`src/ingestion/queue.py`), matched against the worker process's own `@worker.task`-decorated function of the same name (`src/worker.py`). The API process never imports pipeline code as a result.

The `@worker.task` decorator is used only on the worker side. It's what builds the worker's task registry — the lookup table the worker consults when a job envelope arrives from Redis, to find the real function to call. `enqueue_unsafe()` does not consult any registry: it packages `fn_name` plus arguments into a task envelope and writes it to Redis, with no check that a function by that name actually exists anywhere. This is the literal meaning of "unsafe" in the method name — it's about the absence of this check, not about safety in a broader sense.

Consequence: a mismatched name between `INGEST_EPISODE_JOB` and the worker's registered task name does not fail at enqueue time, or at import time — the job writes to Redis successfully and sits as `QUEUED` indefinitely. The mismatch only surfaces when a worker actually attempts to pick up the job and fails its registry lookup. Both sides must be kept in sync deliberately; there is no automated check that they are.

**Queue ordering:** FIFO per Redis stream ordering; `Worker(concurrency=N)` bounds how many jobs run at once within one worker process. Not a strict cross-process guarantee if multiple worker processes are ever run — acceptable for a single-user, single-worker deployment.

**Job dedup lives entirely in Postgres, not the queue:** streaQ always generates a fresh job id on enqueue — there is no supported way to request a specific id. `ingest_episode_handler` and `reingest_episode_handler` guard against duplicate/conflicting requests via `episode.pipeline_status` checks before ever calling `enqueue()`. The queue layer offers no id-collision backstop by design.

**Cancellation:** `cancel()` is a real operation for both queued and in-progress jobs, via streaQ's `Task.abort()` / `Worker.abort_by_id()`. Known limitation: aborting a job blocked on Whisper transcription stops the job, but the underlying `ProcessPoolExecutor` subprocess runs to completion unobserved — actually killing that subprocess would require tracking its OS PID directly. See Future Scope.

**Task liveness, prefetch, and duplicate execution (Phase 20.2):** streaQ keeps a message pending in Redis until the task finishes, and tracks liveness with an idle clock per message. A background loop renews that clock every `0.9 × STREAQ_WORKER_IDLE_TIMEOUT` — but only for tasks that are *running*. Any message idle longer than `idle_timeout` is reclaimed (`XAUTOCLAIM`) on the worker's next fetch, even by the same worker that already holds it. Slow jobs are safe: streaQ doesn't measure progress, so a 40-minute job keeps being renewed. What wasn't safe was streaQ's default prefetch buffer — tasks fetched ahead of a free slot sit unrenewed behind long episodes, get reclaimed, and the duplicate copy can run concurrently with the original. `build_worker()` therefore sets `worker.prefetch = worker.concurrency` (the attribute is the *total* held, running + buffered), so the worker only fetches when a slot is free and everything it holds is running. The remaining duplicate path is an event loop blocked longer than `idle_timeout`, which is why synchronous CPU work (alignment, chunking) runs via `asyncio.to_thread` and Whisper/Senko run in `ProcessPoolExecutor`. A per-episode Redis lock in the task handler was tried and rejected — it acks the shared message on skip and blocks legitimate crash retries. Full root-cause analysis, streaQ internals to check on upgrade, and the coredis `delete()` list-argument gotcha: `docs/reference/phases/phase-20.2-streaq-duplicate-execution.md`.

**Timeouts:** `STREAQ_TASK_TIMEOUT` (default 2h) is a hang backstop, not a speed limit — it must never kill a legitimately long episode. Stalled downloads are caught earlier by httpx's read timeout in `AudioDownloader` (no bytes for 300s). On timeout or cancellation, `ingest_episode` writes `ERROR` inside `anyio.CancelScope(shield=True)` — required because streaQ enforces the timeout with an anyio cancel scope and anyio cancellation is level-triggered, so an unshielded status write would itself be cancelled.

### CPU/GPU-bound work must use ProcessPoolExecutor

Whisper and Senko are both CPU/GPU-bound and will block the worker's event loop if called directly. Each service builds its own `ProcessPoolExecutor` in `__init__` — constructed once, in `pipeline_runner.py`'s `build_transcription_service`/`build_diarization_service`, at worker startup, and held for the life of the worker process via `WorkerContext`:

```python
# src/transcription/local.py
class LocalTranscriptionService:
    def __init__(
        self, whisper_backend, whisper_model,
        min_segment_words, max_segment_tokens, pause_threshold_s,
        max_workers=1, executor=None,
    ):
        self._executor = executor or ProcessPoolExecutor(max_workers=max_workers)

    async def transcribe(self, audio_path, language="en"):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor, _transcribe_sync, audio_path, language,
            self._whisper_backend, self._model_size,
            self._min_segment_words, self._max_segment_tokens, self._pause_threshold_s,
        )
```

`LocalDiarizationService` follows the same shape but adds one thing Whisper's executor doesn't do: keeping the model warm across jobs. Senko's model load cost is non-trivial relative to its inference speed, so reloading it every call would erode most of the speed advantage. `ProcessPoolExecutor`'s `initializer` parameter runs once per subprocess, before any tasks arrive, loading the `Diarizer` into a module-level variable inside that subprocess — every subsequent `diarize()` call routed to that subprocess reuses it:

```python
# src/diarization/local.py
_diarizer = None

def _init_diarizer(device: str) -> None:
    global _diarizer
    import senko
    _diarizer = senko.Diarizer(device=device, warmup=True)

def _diarize_sync(audio_path: str) -> DiarizationResult:
    result = _diarizer.diarize(_make_wav(audio_path))   # reuses the warm model
    ...

class LocalDiarizationService:
    def __init__(self, device="auto", max_workers=1, executor=None):
        self._executor = executor or ProcessPoolExecutor(
            max_workers=max_workers, initializer=_init_diarizer, initargs=(device,),
        )
```

Whisper's executor has no equivalent initializer — `WhisperModel(...)` is constructed fresh inside `_transcribe_sync` on every call, even though the subprocess itself is reused across calls. This is an accepted asymmetry, not an oversight: Whisper's load cost is smaller relative to its own inference time than Senko's, and unifying the two patterns is tracked as a possible future improvement, not a current requirement.

`PIPELINE_MAX_WORKERS` and the worker's `concurrency` are deliberately independent settings: `concurrency` bounds how many jobs the worker process runs concurrently (I/O-bound stages — downloads, LLM calls — genuinely run in parallel up to this limit); `PIPELINE_MAX_WORKERS` bounds how many of those concurrently-running jobs can be doing actual Whisper/Senko compute at the same literal instant, regardless of `concurrency`. A job whose transcription or diarization call arrives while all executor slots are full queues inside that executor, not in Redis. Both default to `1` for local-first, single-machine deployment. Recommended since Phase 20.2: keep them equal. A job waiting for a busy executor slot has already started from streaQ's point of view, so that wait counts toward `STREAQ_TASK_TIMEOUT`; with matching values, jobs only ever wait in Redis. Note that each local service (Whisper, Senko) owns its own pool of this size — at 2:1, one job can transcribe while another diarizes, but two can't transcribe at once.

**GPU sharing caveat:** on a single-GPU machine (Metal or CUDA), raising `PIPELINE_MAX_WORKERS` above `1` does not give the same clean parallelism CPU-only concurrency would - GPU compute is generally serialized per-device, and multiple subprocesses competing for one GPU risk memory contention rather than a speedup. It's also each Senko subprocess's own warm model held in memory for the life of the worker, so raising this setting multiplies both compute contention and memory footprint. Treat `PIPELINE_MAX_WORKERS > 1` as something to measure on real hardware, not a default to raise speculatively.

### What survives a frontend page refresh

| Thing                  | Survives refresh? | Reason                                                                |
| ----------------------- | ------------------ | ----------------------------------------------------------------------- |
| Pipeline job execution | Yes               | Runs in a separate worker process, unaffected by HTTP or API restarts |
| Pipeline status        | Yes               | Written to DB at every stage transition                               |
| SSE stream             | No                | HTTP connection dropped on refresh                                    |
| SSE reconnect          | Yes               | Frontend re-opens stream; DB has current status                       |
| Jobs in queue          | Yes               | Persisted in Redis; survives API and worker process restarts          |
| Chat sessions          | No                | InMemorySessionStore cleared on process restart                       |

### Frontend reconnect pattern

```typescript
const TERMINAL_STATUSES = ['PENDING', 'READY', 'ERROR']

episodes
  .filter(ep => !TERMINAL_STATUSES.includes(ep.pipeline_status))
  .forEach(ep => connectSSE(ep.id))
```

### Configuration

```
MAX_CONCURRENT_INGESTIONS=1          # streaQ Worker(concurrency=...)
PIPELINE_MAX_WORKERS=1               # ProcessPoolExecutor size per local service (Whisper, Senko); keep equal to MAX_CONCURRENT_INGESTIONS
REDIS_URL=redis://redis:6379         # presence implies StreaqQueue; empty/unset falls back to BackgroundTaskQueue (in-process, no Redis)
STREAQ_WORKER_IDLE_TIMEOUT=120       # s without liveness renewal before a running task is reclaimable; also crash-recovery delay
STREAQ_TASK_TIMEOUT=7200             # hang backstop per job, not a speed limit
```

---

## Transcription Service

Swappable behind the `TranscriptionService` Protocol. See `docs/reference/architecture/protocols.md` for interface definition.

**Configuration:**
```
TRANSCRIPTION_BACKEND=local          # local | remote
TRANSCRIPTION_SERVICE_URL=http://localhost:8001
WHISPER_MODEL=medium
TRANSCRIPTION_MIN_SEGMENT_WORDS=5    # floor before a punctuation or pause cut is allowed to fire
TRANSCRIPTION_MAX_SEGMENT_TOKENS=200 # crossing this with no punctuation triggers the pause-rescue/hard-cut fallback below
TRANSCRIPTION_PAUSE_THRESHOLD_S=1.2  # word-timestamp gap treated as a natural speech pause during rescue
```

**Segmentation (punctuation → pause-rescue → hard-cut):** `_build_segments_from_words` in `src/transcription/local.py` normally cuts segments on terminal punctuation (`.`/`?`/`!`/`...`/`。`), same as before Phase 20.1. This alone isn't safe: Whisper has a known upstream bug where it occasionally drops sentence-ending punctuation entirely across a long run of speech, which let one segment grow unbounded and eventually exceed the embedding API's token limit. The fix adds two fallback tiers that only engage once an unpunctuated run crosses `TRANSCRIPTION_MAX_SEGMENT_TOKENS`: first, search backward (past `TRANSCRIPTION_MIN_SEGMENT_WORDS`) for a word-timestamp gap greater than `TRANSCRIPTION_PAUSE_THRESHOLD_S` and cut there; if no such pause exists, hard-cut at the token boundary and log a warning. Pause-based cutting is deliberately never used as a routine/opportunistic segmentation signal — natural speaking cadence includes pauses inside otherwise-normal sentences, so it only applies as a last resort once punctuation has already failed. Full design rationale and test coverage: `docs/reference/phases/phase-20.1-transcript-segmentation-hardening.md`.

**Diarization:** Fully separate from transcription — see "Diarization + Alignment" below. Transcription's only remaining job is speech-to-text; every segment it produces is written with `speaker_id = 'UNKNOWN'` and relabeled afterward by the diarization + alignment stage.

**Local implementation:** Whisper (faster-whisper or mlx-whisper). Must run in `ProcessPoolExecutor` — see "CPU/GPU-bound work must use ProcessPoolExecutor" above for rationale.

**Remote implementation:** HTTP POST to `TRANSCRIPTION_SERVICE_URL`. Current implementation (`src/transcription/remote.py`) targets a plain OpenAI-compatible `/audio/transcriptions` endpoint — no timestamps or speaker labels come back, so every segment gets placeholder `start_ms=0, end_ms=0`. **This makes `RemoteTranscriptionService` incompatible with diarization today** — alignment can't match real speech to a segment with no real timing. A future remote backend offering combined transcription+diarization (e.g. OpenAI's diarized transcription endpoint) would return pre-labeled segments directly and bypass `DiarizationService` entirely for that path — tracked in Future Scope, not yet built.

---

## Diarization + Alignment

Diarization runs as its own pipeline stage (`DIARIZING` status), between transcription and speaker inference. It answers "who was talking, and when" — completely independent of *what* was said. Its output (`DiarizationResult`) is a list of speaker turns with no text at all.

**Alignment** (`src/diarization/alignment.py`) reconciles diarization's turns against transcription's already-finalized sentence segments, since the two are independently timestamped and produced by unrelated models. For each transcript segment, alignment finds the diarization turn it overlaps with the most (by raw millisecond overlap) and relabels that segment's `speaker_id` accordingly. A segment with zero overlapping turns is left as `UNKNOWN` rather than guessed — same "don't fabricate confidence" principle used throughout speaker inference.

**Known precision limit:** alignment operates at segment granularity, not word granularity. Word-level timestamps are available from local Whisper transcription but are discarded after sentence-grouping; a word-level alignment pass was considered and rejected for Phase 13 — see Future Scope for the reasoning (bounded precision gain, given Senko itself reports only one dominant speaker per stretch and doesn't detect overlapping speech).

**Configuration:**

```
SPEAKER_INFERENCE_PADDING_MS=60000 # see docs/reference/architecture/speaker-identity.md — unrelated to alignment itself, listed here for proximity
```

No diarization-specific settings beyond `PIPELINE_MAX_WORKERS` (above) — device selection (`device="auto"`) is hardcoded in `LocalDiarizationService`, matching how transcription decides its own device internally rather than exposing it as a setting.

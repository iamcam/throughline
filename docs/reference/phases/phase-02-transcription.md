# Phase 2 — Audio Download + Transcription

> Moved from IMPLEMENTATION_PLAN.md. Status: ✅ Complete. Git tag: `v0.1.2-transcription`.
> See IMPLEMENTATION_PLAN.md's Phase Overview table for the one-line summary; see ARCHITECTURE.md for current system design.
> Note: this phase's original transcription design (Pyannote-based diarization, RSS transcript shortcut) was later superseded by Phase 13 (Senko diarization) — see that phase's file for what actually shipped.

**Goal:** Trigger ingestion. Status streams via SSE. Transcript lands in DB.

> **Implementation note:** Diarization is deferred to Future Scope 1.5.
> CPU/local diarization via Pyannote is impractical on non-CUDA hardware.
> In v1, all transcript segments are written with `speaker_id = 'UNKNOWN'`.
> `SpeakerResolver` (Phase 3) may promote this to `SPEAKER_00` if it infers
> a single host name. The `UNKNOWN` sentinel is intentional — it distinguishes
> un-diarized episodes from confirmed single-speaker episodes.

### Tasks

#### 2.1 SSE status stream (`src/api/routers/episodes.py`)
The `IngestionQueue` is built in Phase 1 (`src/ingestion/queue.py`) and injected via `Depends(get_ingestion_queue)` from `dependencies.py`. The SSE endpoint reads pipeline status from the DB independently of the running background job — it does not receive updates directly from the worker.
```python
from sse_starlette.sse import EventSourceResponse

@router.get("/{episode_id}/status/stream")
async def stream_status(episode_id: UUID, db: AsyncSession, queue: IngestionQueue):
    async def generator():
        while True:
            episode = await get_episode(episode_id, db)
            update = PipelineStatusUpdate(
                status=episode.pipeline_status,
                stage=episode.pipeline_stage,
                progress=episode.pipeline_progress,
                position=await queue.get_position(episode.ingestion_job_id) if episode.ingestion_job_id else None
            )
            yield {"data": update.model_dump_json()}
            if episode.pipeline_status in ("READY", "ERROR"):
                break
            await asyncio.sleep(2)
    return EventSourceResponse(generator())
```

#### 2.2 Transcription interface (`src/transcription/base.py`)
```python
@dataclass
class TranscriptSegment:
    speaker_id: str         # "SPEAKER_00"
    text: str
    start_ms: int
    end_ms: int

@dataclass
class TranscriptResult:
    segments: list[TranscriptSegment]
    language: str
    source: str             # "whisper_local" | "remote" | "rss_provided"

class TranscriptionService(Protocol):
    async def transcribe(
        self,
        audio_path: str,
        speaker_count_hint: int | None = None,
        language: str = "en"
    ) -> TranscriptResult: ...
```

#### 2.3 Audio downloader (`src/ingestion/audio_downloader.py`)
- `httpx.AsyncClient` streaming download
- Store to `AUDIO_STORAGE_PATH/{episode_id}.{ext}`
- Update `pipeline_status=DOWNLOADING`, `pipeline_progress` during download

#### 2.4 Local transcription service (`src/transcription/local.py`) 🤖
```bash
uv add faster-whisper
# mlx-whisper is optional for Apple Silicon: uv add mlx-whisper
```

Steps:
1. Whisper → transcript segments
2. Assign `speaker_id = 'UNKNOWN'` to all segments — diarization is deferred
3. Return `TranscriptSegment` list

Pyannote diarization is not invoked in v1. Run Whisper in `asyncio.get_running_loop().run_in_executor(None, ...)` — CPU-bound, must not block event loop.

#### 2.5 Remote transcription service (`src/transcription/remote.py`)
HTTP client POSTing audio to `TRANSCRIPTION_SERVICE_URL`. The remote service
owns both transcription and diarization — `DIARIZATION_MODEL` is ignored when
`TRANSCRIPTION_BACKEND=remote`.

**Deferred to align with remote diarization work (see FUTURE_SCOPE.md 1.5).**
Current implementation is a stub that satisfies the Protocol but is untested
against a real endpoint. Concrete remote backends to implement:

- Generic sidecar (Docker, same contract as local pipeline)
- OpenAI Whisper API (optional speaker diarization via response format)
- Cloud GPU providers (RunPod, Modal) running Whisper + Pyannote

When implementing a specific remote backend, normalise its response format
into `TranscriptResult` inside `RemoteTranscriptionService` — the pipeline
and Protocol are unchanged.

#### 2.6 RSS transcript shortcut
If `episode.transcript_url` is set:
- Download VTT/SRT file
- Parse into `TranscriptSegment` list with `speaker_id = 'UNKNOWN'`
- Proceed without audio download or Whisper
- User can override via reingest endpoint

#### 2.7 Transcript storage (`src/ingestion/transcript_store.py`)
Save segments to `transcript_segments` table — `speaker_id = 'UNKNOWN'` for all segments (no diarization in v1), no `display_name`.
Upsert one row into `episode_speakers` via `SpeakerStore` (`src/ingestion/speaker_store.py`) — `speaker_id='UNKNOWN'`, `display_name=NULL`, both flags false.
Keep these as separate services: `TranscriptStore` owns segment rows, `SpeakerStore` owns `episode_speakers` rows.

#### 2.8 Ingestion orchestrator (`src/ingestion/pipeline.py`)
`pipeline.py` is a thin orchestrator — it sequences stages and manages status transitions via `PipelineStatusService`. No business logic lives here.

```python
async def ingest_episode(
    episode_id: UUID,
    job_args: dict,
    services: PipelineServices,
) -> None:
    try:
        await services.status.set(episode_id, "DOWNLOADING")
        audio_path = await services.downloader.download(episode)

        await services.status.set(episode_id, "TRANSCRIBING")
        transcript = await services.transcription.transcribe(
            audio_path, speaker_count_hint=job_args.get("speaker_count_hint")
        )
        await services.transcript_store.save(episode_id, transcript)
        await services.speaker_store.initialize_from_transcript(episode_id, transcript)
        # All segments written with speaker_id = 'UNKNOWN'

        await services.status.set(episode_id, "INFERRING_SPEAKERS")
        result = await services.speaker_resolver.infer(transcript.segments)
        await services.speaker_store.save_inferred(episode_id, result)
        # If one name found: UNKNOWN → SPEAKER_00, display_name set, pipeline continues
        # If none found: UNKNOWN stays, pipeline continues — not an error

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

`PipelineServices` is a dataclass of all injected services — see `ARCHITECTURE.md` section 3.4. Note that chunking and embedding are now part of the same job, not a separate enqueued job.

#### 2.9 Ingest endpoint
```
POST /api/v1/episodes/{episode_id}/ingest
Body: { "speaker_count_hint": 2 }
→ { "status": "accepted", "job_id": "...", "queue_position": 1 }
```

#### 2.10 Tests
```python
# tests/unit/test_pipeline.py  (fixture: sample_transcript.json)
async def test_ingest_stores_segments_with_unknown_speaker_id()
async def test_ingest_creates_single_unknown_episode_speakers_row()
async def test_display_name_not_stored_in_segments()
async def test_status_transitions_correctly()
async def test_error_stored_on_failure()

# tests/unit/test_transcription_interface.py
def test_local_satisfies_protocol()
def test_remote_satisfies_protocol()
```

**Note on fixture:** `tests/fixtures/sample_transcript.json` was created in Phase 0. Use it here to test the pipeline without running real Whisper or Pyannote.

### Phase 2 Done When
- `POST /ingest` → queued, SSE streams stage transitions through to READY
- Transcript segments in DB with `speaker_id = 'UNKNOWN'` (no display_name)
- `episode_speakers` row created with `speaker_id='UNKNOWN'`, null display_name
- All tests pass using fixture (no real Whisper required)
- Git tag: `v0.1.2-transcription`

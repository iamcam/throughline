# Phase 13 — Speaker Diarization

> Moved from IMPLEMENTATION_PLAN.md. Status: ✅ Complete. Git tag: `v1.2.0`.
> See IMPLEMENTATION_PLAN.md's Phase Overview table for the one-line summary; see `docs/reference/architecture/ingestion-pipeline.md` and `docs/reference/architecture/speaker-identity.md` for current detail.

**Goal:** Real per-speaker identity instead of the v1 single-inferred-name sentinel. Local diarization via Senko, wired between transcription and speaker-name inference; segment-level alignment reconciles the two independently-timestamped outputs; `SpeakerResolver` now resolves one name per diarized speaker instead of one name for the whole episode.

### 13.1 DiarizationService Protocol (`src/diarization/base.py`)

```python
@dataclass
class SpeakerTurn:
    speaker_id: str
    start_ms: int
    end_ms: int

@dataclass
class DiarizationResult:
    turns: list[SpeakerTurn]
    speaker_count: int

class DiarizationService(Protocol):
    async def diarize(self, audio_path: str) -> DiarizationResult: ...
```

No `speaker_count_hint` — Senko doesn't accept one, and no diarization backend under real consideration changes that. Mirrors `TranscriptionService`'s local/remote split in shape, though no remote implementation was built this phase.

### 13.2 Pyannote removal from `local.py`

`LocalTranscriptionService` had a full, mostly-dormant pyannote diarization + word-alignment path (`diarization_model` param, `speaker_turns`/`find_speaker`, WAV conversion for diarization). Removed entirely rather than left alongside the new `DiarizationService` — two independent implementations of "assign speakers to text" would have silently diverged the moment `diarization_model` was ever set again. `huggingface_token` removed from `config.py` and the constructor along with it — no remaining consumer. Trimmed `local.py` now only produces `UNKNOWN`-labeled sentence segments; a real timestamp bug was found and fixed in the process (`current_start` was being set from the *previous* segment's last word end, not the new segment's first word start — silently erased natural gaps between sentences).

### 13.3 LocalDiarizationService (Senko) (`src/diarization/local.py`)

`ProcessPoolExecutor` with an `initializer` that loads `senko.Diarizer` once per subprocess (`warmup=True`) and keeps it warm across every job routed to that subprocess — deliberately different from `LocalTranscriptionService`'s pattern, where `WhisperModel` is rebuilt fresh on every call despite the subprocess itself being reused. Senko's own benchmark numbers (`experiments/diarization/bench_senko.py`) justified the asymmetry: model-load cost is non-trivial relative to Senko's inference speed. Requires 16-bit mono WAV input (`ffmpeg` conversion, same reasoning as the removed pyannote path — exact sample-boundary alignment). Filters `merged_segments` below 0.5s as diarization noise, per the same benchmark's findings.

### 13.4 Config wiring

`pipeline_runner.py`'s `build_diarization_service` + `WorkerContext.diarization_service`, mirroring `build_transcription_service`. `PIPELINE_MAX_WORKERS` replaces the transcription-only `TRANSCRIPTION_MAX_WORKERS` — one `ProcessPoolExecutor` size shared by both local Whisper and local Senko, justified by both running sequentially per-episode and converging on the same GPU-first resource profile (not because their profiles were assumed similar in general). `worker.py`'s lifespan builds and shuts down `diarization_service` the same way it already did for `transcription_service`.

### 13.5 Alignment (`src/diarization/alignment.py`)

Segment-level (not word-level) overlap matching: for each transcript segment, find the diarization turn with the greatest millisecond overlap, relabel `speaker_id` to that turn's. Zero-overlap segments stay `UNKNOWN` rather than falling back to nearest-turn-by-distance. Word-level re-segmentation (preserving Whisper's per-word timestamps through to alignment, breaking segments at diarization speaker-changes) was seriously evaluated and rejected — see FUTURE_SCOPE.md 2.8b for the full reasoning; short version: Senko itself only reports one dominant speaker per stretch and doesn't detect overlapping speech, which caps how much word-level precision could actually buy over segment-level.

### 13.6 SpeakerResolver rework (`src/ingestion/speaker_resolver.py`)

`infer()` returns `dict[str, InferredSpeaker | None]`, one entry per diarized speaker, looping `_infer_one` per speaker rather than a single episode-wide inference call. Each speaker's context window starts `padding_ms` before their first utterance (default 60s, new `speaker_inference_padding_ms` setting) through `window_ms` after it, and includes *all* speakers' segments in that range — not just the target speaker's own lines — rendered as a labeled script (`SPEAKER_00: "..."`). This is deliberate: the identifying utterance for a given speaker is very often spoken by someone *else* ("my guest today is Marcus"), so a self-lines-only window would miss it. Prompt asks specifically "who is `{speaker_id}`" rather than "who is *the* speaker."

### 13.7 Pipeline wiring + RSS-provided-transcript removal

`pipeline.py`: `PipelineServices` gains a `diarization` field; new `DIARIZING` status between `TRANSCRIBING` and `INFERRING_SPEAKERS`; `transcript.segments = align_segments(...)` runs before the transcript is persisted, so `transcript_store.save()` and `speaker_store.initialize_from_transcript()` both see real diarized labels. No `PENDING_NAMES` gate — deliberately not reinstated (see Decisions below); `INFERRING_SPEAKERS` naturally handles the 1-speaker case as a 1-iteration loop, no special-casing needed.

Removed in the same pass: the RSS-provided-transcript ingestion shortcut (`fetch_transcript`, `transcript_url` parsing in `rss_parser.py`/`feed_service.py`, `Episode.transcript_url` column + migration, `TranscriptResult.source`'s `"rss_provided"` literal). Judged low real-world value (few feeds actually provide speaker-labeled, well-formatted transcripts) and directly incompatible with diarization, since that path never downloaded audio at all.

### 13.8 Tests

`tests/unit/test_alignment.py` (new) — overlap matching, tie-breaking (earlier turn wins), no-overlap fallback, non-mutation of input segments. `tests/unit/test_speaker_resolver.py` — fully reworked for the dict return type, per-speaker windowing/padding, script-format prompt construction. `tests/integration/test_ingestion_pipeline.py` — `mock_services` fixture gained a `DiarizationService` mock (must set `.diarize.return_value` explicitly — an unconfigured `AsyncMock` silently behaves like an empty-turns result via `MagicMock`'s auto-iterables, which was caught the hard way); new multi-speaker end-to-end test (two turns, two distinct inferred names, verified against real `EpisodeSpeaker` rows). `tests/integration/test_speakers.py` — `save_inferred` call sites updated for the dict signature. `tests/unit/test_rss_parser.py` — `transcript_url` test removed.

### 13.9 Frontend — speaker verification UX

`TranscriptViewer.tsx`: speaker labels un-commented and made consecutive-speaker-aware (label suppressed when the same `speaker_id` as the previous segment — compared by `speaker_id`, not `display_name`, since two different unresolved speakers can share a `null` display name). `SpeakerRow.tsx`: play/pause button per speaker using `GET /speakers/preview`'s existing `sample_timestamp_ms` + `episode.audio_url` (both already existed in the API, no backend work needed). Controls the single shared `<audio>` element already on `EpisodeDetailPage` via a callback ref (`useState`, not `useRef`, so the element's *mounting* itself is what re-triggers the listener-attaching effect — a plain ref update doesn't cause a re-render, so an effect depending only on a ref never re-fires once the initial loading-state render finds nothing there). Native `pause`/`ended`/`seeked` event listeners drive the active-speaker state, with a ref-flag distinguishing the component's own programmatic seeks from genuine user interaction with the player. `queryInvalidation.ts` gained `invalidateSpeakersAndTranscript` — renaming a speaker now also refreshes the transcript view's labels, not just the speaker list.

### 13.10 speaker_count_hint removal

Traced end-to-end and confirmed unused by every real consumer (`LocalTranscriptionService`, `RemoteTranscriptionService`, and — the reason it existed at all — `DiarizationService`, which never had it). Removed from the `TranscriptionService` Protocol, both implementations, `IngestRequest` (now field-less), both `episodes.py` handlers, `client.ts`'s `ingestEpisode`/`reingestEpisode`, and `README.md`'s example. `job_args`'s own plumbing (queue → worker → pipeline) kept as a deliberate empty extension point rather than removed — inert with no field to misfire, unlike the pyannote/RSS removals which had real dormant behavior. `IngestRequest`'s now-optional body required a `= IngestRequest()` default on both route handlers so a bodyless POST doesn't 422.

### Decisions made

- **Senko only — no pyannote, anywhere, ever.** Not deferred, excluded. Reasoning: anywhere capable of running pyannote-on-GPU can run Senko-on-GPU; pyannote's gated-model/HF-token requirement and CPU slowness have no upside once that's true. A future compute-offload need is more likely to be served by a combined remote transcription+diarization provider (OpenAI-style) than by remote pyannote.
- **No `PENDING_NAMES` pipeline gate**, contrary to what FUTURE_SCOPE.md originally sketched for this phase. Naming confirmation (`PUT /speakers`) stays exactly as decoupled/metadata-only as it already was in v1 — the pipeline runs straight through regardless of speaker count, same as v1's single-speaker behavior. This resolved cleanly because `SpeakerResolver`'s per-speaker loop needs no special-casing for N=1 vs N>1.
- **Segment-level, not word-level, alignment.** See 13.5 / FUTURE_SCOPE.md 2.8b. A genuine, deliberated tradeoff, not a shortcut — Senko's own single-dominant-speaker-per-stretch behavior caps how much word-level precision could realistically buy.
- **`PIPELINE_MAX_WORKERS` shared between transcription and diarization**, replacing `TRANSCRIPTION_MAX_WORKERS`. One dial, since both stages are sequential per-episode and GPU-first.
- **`job_args` kept, not removed**, despite having zero live fields after 13.10 — judged a reasonable, inert extension point rather than dead code needing removal, unlike pyannote/RSS which had real (if dormant) behavior attached.

### Known issues / tech debt noted
- `RemoteTranscriptionService` incompatible with diarization (returns placeholder `start_ms=0, end_ms=0` for every segment) — see Future Scope 2.8a.
- Word-level alignment rejected for now, revisit only if segment-level misattribution proves to be a real, frequent problem — see Future Scope 2.8b.
- `SpeakerResolver`'s context window is time-bounded, not length-bounded — see Future Scope 2.8c.
- Whisper hallucination on trailing silence/outro audio, found via real-episode testing — see Future Scope 2.8d.
- Dynamic ad insertion (confirmed on Simplecast) can desync playback timestamps from transcript after an ad boundary — see Future Scope 2.8e.
- `reingest_episode_handler` still has no `pipeline_status` guard against a mid-pipeline reingest — carried over from Phase 12's handoff (was next-session priority #1; diarization work superseded it this phase). Still open.

### Phase 13 Done When
- A real multi-speaker episode, ingested end-to-end through the actual worker, produces distinct `SPEAKER_XX` labels and distinct inferred names in `episode_speakers`
- `align_segments` leaves genuinely unresolved segments as `UNKNOWN` rather than guessing — verified via unit tests and observed on real audio
- No pyannote import or `HF_TOKEN`/`diarization_model` setting remains anywhere in the codebase
- No RSS-provided-transcript code path remains — `Episode.transcript_url` column dropped via migration
- Full test suite green (`uv run pytest`)
- Frontend: transcript view shows speaker names (deduplicated on consecutive same-speaker segments); speaker list has working play/pause preview per speaker; renaming a speaker updates the transcript view without manual refresh
- Git tag: `v1.2.0`

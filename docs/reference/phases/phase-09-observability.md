# Phase 9 — Observability

> Moved from IMPLEMENTATION_PLAN.md. Status: ✅ Complete. Git tag: `v0.1.9-observability`.
> See IMPLEMENTATION_PLAN.md's Phase Overview table for the one-line summary; see `docs/reference/architecture/observability.md` for current detail.
> Note: the `transcription` span described here covered Whisper+Pyannote combined; Phase 13 later split diarization into its own fully separate span — see that phase's file.

**Goal:** LLM, retrieval, and pipeline traces in Phoenix via OpenTelemetry.

### As Built

**Packages:** `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`,
`openinference-instrumentation-openai`. gRPC exporter removed in favour of HTTP —
TLS is implicit from URL scheme, no `insecure` flag needed.

**`src/telemetry/setup.py`:**
- OTLP/HTTP exporter — `http://` = plaintext, `https://` = TLS, no flag needed
- `SimpleSpanProcessor` — appropriate for single-user app; synchronous export
  surfaces errors immediately; `BatchSpanProcessor` is for high-throughput
  multi-user scenarios
- `OpenAIInstrumentor().instrument()` — auto-instruments all OpenAI SDK calls
- Project name sent as `openinference.project.name` resource attribute on
  `TracerProvider` — Phoenix uses this to route spans to the correct project;
  defaults to `"podcast-engine"` so it never falls through to Phoenix's `"default"`
- Auth via `Authorization: Bearer {key}` header when `OTEL_API_KEY` is set
- No-op when `TRACING_ENABLED=false` — OTel imports deferred inside the `if`
  block so missing packages don't error when tracing is disabled

**`src/telemetry/tracer.py`:**
```python
from opentelemetry import trace
tracer = trace.get_tracer("podcast-engine")
```
Safe to import before `setup_telemetry()` runs — returns a no-op tracer until
a provider is registered. Any file needing a custom span imports this directly:
```python
from src.telemetry.tracer import tracer
```

**Custom spans (as of this phase):**

| File                      | Span name                     | Key attributes                                                                                                                                                                                                                                           |
| ------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pipeline.py`             | `ingest_episode`              | `episode.id`, `episode.title`, `episode.has_transcript_url`, chunk counts, `episode.inferred_speaker`; `record_exception` + `set_status(ERROR)` on unrecoverable failure; RSS transcript fallback logged only — not marked ERROR since pipeline recovers |
| `audio_downloader.py`     | `audio_download`              | `audio.url`, `audio.size_bytes` (when content-length present), `audio.bytes_received`; span starts after cache-hit early return — no span if file already exists                                                                                         |
| `transcription/local.py`  | `transcription`               | `transcription.backend`, `transcription.model`, `transcription.language`, `transcription.diarization_enabled`, `transcription.diarization_model`, `transcription.segment_count`                                                                          |
| `transcription/remote.py` | `transcription`               | `transcription.backend`, `transcription.service_url`, `transcription.language`, `transcription.segment_count`                                                                                                                                            |
| `speaker_resolver.py`     | `speaker_inference`           | `speaker.intro_segment_count`, `speaker.name_found` (always set), `speaker.confidence` (set on success only)                                                                                                                                             |
| `embedder.py`             | `embedding`                   | `embedding.leaf_count`, `embedding.batch_size`, `embedding.batch_count` via `math.ceil`                                                                                                                                                                  |
| `retriever.py`            | `retrieval`                   | `retrieval.query`, `retrieval.top_k`, `retrieval.feed_ids`, `retrieval.result_count`, `retrieval.score_max`, `retrieval.score_min`, `retrieval.score_mean` (all scores rounded to 4dp)                                                                   |
| LLM calls                 | auto via `OpenAIInstrumentor` | tokens, model, full prompt/response content, finish reason                                                                                                                                                                                               |

**Why transcription span wraps the executor await, not the subprocess:**
OTel context does not cross `ProcessPoolExecutor` subprocess boundaries — the
context is thread/coroutine-local and is not copied on fork. A span started
inside `_transcribe_sync` would have no parent and appear as an orphaned trace.
The span wraps `run_in_executor()` in the async layer instead — wall-clock
duration of the full executor call is the meaningful metric for model comparison.
Sub-span timing for Whisper vs Pyannote requires splitting `_transcribe_sync`
into two separate executor calls — deferred to transcription refactor (Future
Scope 1.6). (Superseded by Phase 13's fully separate `DiarizationService`.)

**Config keys added:**
- `tracing_enabled: bool = False` — master switch; `phoenix_enabled` was never used
- `otel_endpoint: str = "http://localhost:6006/v1/traces"` — OTLP/HTTP URL
- `otel_api_key: str | None = None` — Bearer token for hosted Phoenix/Arize
- `otel_project_name: str = "podcast-engine"` — Phoenix project routing

**Verified against Arize hosted Phoenix:**
- Endpoint: `https://app.phoenix.arize.com/s/{username}/v1/traces`
- LLM traces visible with token counts and prompt/response content
- `retrieval` span with score distribution attributes confirmed
- `speaker_inference` child span nested under `ingest_episode` confirmed

### Known tech debt
- `_transcribe_sync` not split — sub-span timing for Whisper vs Pyannote
  deferred to transcription refactor (Future Scope 1.6). Superseded by Phase 13.
- `WHISPER_MODEL_SIZE` → `WHISPER_MODEL` rename deferred to Phase 10

### Phase 9 Done When ✅
- Phoenix shows full trace for chat turn: LLM spans, `retrieval` child span
- `retrieval` span carries score distribution attributes
- Ingestion trace shows `ingest_episode` → `speaker_inference` → LLM child span
- Git tag: `v0.1.9-observability`

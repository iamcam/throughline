# Observability — OpenTelemetry + Phoenix

> Moved from ARCHITECTURE.md §3.12. Referenced from ARCHITECTURE.md — see that doc for the high-level component map.

**Transport:** OTLP/HTTP via `opentelemetry-exporter-otlp-proto-http`.
TLS is implicit from the endpoint URL scheme — `http://` is plaintext,
`https://` is TLS. No `insecure` flag exists on the HTTP exporter; this is
an HTTP convention, unlike gRPC which defaults to TLS and requires an explicit
opt-out.

**Processor:** `SimpleSpanProcessor` — exports synchronously on every span.
Appropriate for a single-user application. `BatchSpanProcessor` is designed
for high-throughput multi-user scenarios where buffering reduces collector load.

**Auto-instrumentation:** `OpenAIInstrumentor().instrument()` patches the
OpenAI SDK globally at startup. Every `LLMClient.complete()` call emits a
span automatically — prompt content, response, token counts, model name,
finish reason. No changes to `LLMClient` or `client.py` required.

**Project routing:** Phoenix routes spans to projects via the
`openinference.project.name` resource attribute set on `TracerProvider`.
Configured via `OTEL_PROJECT_NAME` — defaults to `"podcast-engine"`.

**Setup (`src/telemetry/setup.py`):**
```python
def setup_telemetry(settings: Settings) -> None:
    if not settings.tracing_enabled:
        return  # no-op — app runs normally without a collector configured

    # OTel imports deferred — missing packages don't error when tracing disabled
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from openinference.instrumentation.openai import OpenAIInstrumentor

    resource = Resource(attributes={
        "openinference.project.name": settings.otel_project_name,
    })

    headers = {}
    if settings.otel_api_key:
        headers["Authorization"] = f"Bearer {settings.otel_api_key}"

    exporter = OTLPSpanExporter(
        endpoint=settings.otel_endpoint,
        headers=headers,
    )

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    OpenAIInstrumentor().instrument()

    logger.info(f"Tracing enabled — exporting to {settings.otel_endpoint}")
```

**Shared tracer (`src/telemetry/tracer.py`):**
```python
from opentelemetry import trace
tracer = trace.get_tracer("podcast-engine")
```
Safe to import before `setup_telemetry()` runs — returns a no-op tracer until
a provider is registered. Import in any file that needs custom spans:
```python
from src.telemetry.tracer import tracer
```

**Custom spans:**

| File                      | Span name                     | Key attributes                                                                                                                                             |
| --------------------------- | -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pipeline.py`             | `ingest_episode`              | `episode.id`, `episode.title`, `episode.speaker_count`, chunk counts                                                                                       |
| `audio_downloader.py`     | `audio_download`              | `audio.url`, `audio.size_bytes`, `audio.bytes_received`                                                                                                    |
| `transcription/local.py`  | `transcription`               | `transcription.backend`, `transcription.model`, `transcription.language`, `transcription.segment_count`                                                    |
| `transcription/remote.py` | `transcription`               | `transcription.backend`, `transcription.service_url`, `transcription.language`, `transcription.segment_count`                                              |
| `diarization/local.py`    | `diarization`                 | `diarization.turn_count`, `diarization.speaker_count`                                                                                                      |
| `speaker_resolver.py`     | `speaker_inference`           | `speaker.target_id`, `speaker.window_segment_count`, `speaker.name_found`, `speaker.confidence` (one span per diarized speaker, not per episode)           |
| `embedder.py`             | `embedding`                   | `embedding.leaf_count`, `embedding.batch_size`, `embedding.batch_count`                                                                                    |
| `retriever.py`            | `retrieval`                   | `retrieval.query`, `retrieval.top_k`, `retrieval.feed_ids`, `retrieval.result_count`, `retrieval.score_max`, `retrieval.score_min`, `retrieval.score_mean` |
| LLM calls                 | auto via `OpenAIInstrumentor` | tokens, model, prompt/response                                                                                                                             |
| `engine.py`               | `chat`                         | `session.id`, `chat.tool_rounds_used`, `chat.citation_count`, `chat.original_query`, `chat.rewritten_query`                                                 |

**Error recording pattern:**
```python
except Exception as e:
    span.record_exception(e)           # full stack trace as span event
    span.set_status(trace.StatusCode.ERROR, str(e))
    raise
```
Use for unrecoverable failures only. Log-only for handled, non-fatal exceptions that the pipeline recovers from without failing the job — do not mark the span ERROR if the pipeline continues successfully.

**Why transcription and diarization spans each wrap their own executor await:**
OTel context does not cross `ProcessPoolExecutor` subprocess boundaries. Spans started inside `_transcribe_sync` or `_diarize_sync` would appear as orphaned traces with no parent. Each service's span wraps its own `run_in_executor()` call in the async layer instead — wall-clock duration covers the full subprocess call including any model loading and inference. Because transcription and diarization are now fully separate pipeline stages with their own spans, per-stage timing is already visible without needing to split anything further — unlike the old combined Whisper+Pyannote design this replaced.

**Backend switching:** Local Phoenix, hosted Arize, Langfuse, or any
OTLP/HTTP collector — change `OTEL_ENDPOINT` in `.env`. No code changes
required.

```bash
# Local Phoenix in Docker
OTEL_ENDPOINT=http://localhost:6006/v1/traces

# Arize hosted
OTEL_ENDPOINT=https://app.phoenix.arize.com/s/{username}/v1/traces
OTEL_API_KEY=your-key-here
```

Phoenix runs as optional Docker Compose profile:
```bash
docker compose --profile observability up
```

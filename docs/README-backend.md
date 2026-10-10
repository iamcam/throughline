# Throughline - Backend

This is the backend for the Throughline project. All commands below run from the `backend/` directory.

## Requirements

- Python 3.13+
- uv
- ffmpeg (required for diarization's audio conversion step)
- [Podman](https://podman-desktop.io) or Docker w/ compose

Examples use podman for container management, but docker will also work - just swap `podman` for `docker`.

## Setup

### 1. Environment

Copy `backend/.env.example` to `backend/.env` and fill in the relevant settings.

**Running via Docker/Podman?**

You can copy `backend/.env.example` straight to `backend/.env` and start the whole stack from the project root with `podman compose up -d` — no extra setup needed.

If you'd rather keep native-dev and containerized settings separate (e.g. different `DATABASE_URL`/`REDIS_URL` hostnames), copy your Docker-specific settings into `backend/.env.docker` instead, then set `BACKEND_ENV_FILE=.env.docker` in the project root `.env`. Compose falls back to `backend/.env` if `BACKEND_ENV_FILE` isn't set.

Either way, any service running on your host machine (Ollama, MLX, llama-server, etc.) needs to be reached via `host.docker.internal`, not `localhost`, from inside a container.

### 2. Virtual Environment

We use uv + venv for environment management. [Install uv](https://docs.astral.sh/uv/) if you haven't already.

```bash
uv venv
source .venv/bin/activate
```

### 3. Install Dependencies

**All architectures**
```bash
uv sync
```

**PyTorch (CUDA)**

By default `torch` and `torchaudio` are installed on `uv sync`, falling back to CPU if CUDA is not available. For NVIDIA GPU:

```bash
uv add torch torchaudio --index https://download.pytorch.org/whl/cu121
```

**Whisper**

`faster-whisper` is installed automatically. Apple Silicon users may prefer `mlx-whisper`:

```bash
# mlx-whisper — Apple Silicon only, faster than faster-whisper on Metal
uv add mlx-whisper
```

**Configure `.env`**

```bash
# Local Whisper
WHISPER_BACKEND=faster_whisper   # faster_whisper | mlx_whisper
WHISPER_MODEL=medium             # size: tiny | base | small | medium | large-v3
                                 # or HF repo: mlx-community/whisper-medium-mlx
```

**Remote transcription (optional)**

To use a remote OpenAI-compatible transcription service instead of local Whisper:

```bash
TRANSCRIPTION_SERVICE_URL=http://localhost:8001/v1   # any OpenAI-compatible endpoint
TRANSCRIPTION_API_KEY=your-key-here                  # required for OpenAI; leave empty for local services
```

When `TRANSCRIPTION_SERVICE_URL` is set, local Whisper config is ignored.

**Embeddings**

Any OpenAI-compatible embeddings endpoint works. Set `EMBEDDING_BASE_URL=local` to run sentence-transformers in-process instead. `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL_NAME`, and `EMBEDDING_DIMENSIONS` must match across the API and worker — changing the embedding model means re-ingesting existing episodes (see `docs/ARCHITECTURE.md` §3.3).

**Speaker Diarization**

Diarization always runs as part of ingestion — there's no opt-in setting. Local diarization uses [Senko](https://github.com/narcotic-sh/senko) (MIT license, no Hugging Face token required), with device selection (`device="auto"`) handled automatically — Metal on Apple Silicon, CUDA on Nvidia GPUs, CPU fallback elsewhere. No diarization-specific configuration exists beyond `PIPELINE_MAX_WORKERS`, which sizes the worker pool shared with local Whisper transcription.

No remote diarization backend exists yet — every episode is diarized locally, regardless of whether transcription itself is local or remote.


### 4. Bootstrapping

This project uses Postgres with pgvector for embeddings. If you don't already have a Postgres instance with pgvector, use the included `docker-compose.db.yml`:

```bash
podman compose -f docker-compose.db.yml up -d
```

**Run migrations**

```bash
uv run alembic upgrade head
```

Migrations handle pgvector installation — no separate step needed. Run this after every pull that adds a migration.

**(Local dev only) Create the test database**

Required only if you want to run the integration test suite:

```bash
PYTHONPATH=. uv run python scripts/create_test_db.py
```

Then enable pgvector on the test DB (note the container name may differ):

```bash
podman exec -it backend-db-1 psql -U <username> -d podcast_engine_test -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

The test database only needs to be created once.


**Queue (optional)**

By default, ingestion jobs run in-process (`BackgroundTaskQueue`) — no additional setup needed. To run them through a real queue instead (streaQ + Redis, closer to how the app runs in production), start Redis with the included `docker-compose.redis.yml`:

```bash
podman compose -f docker-compose.redis.yml up -d
```

Then set `REDIS_URL` in `.env`:

```bash
REDIS_URL=redis://localhost:6379
```

Leave it empty to keep using the in-process queue.

**Stuck-job thresholds (optional)**

The queue overview flags an in-progress episode as `possibly_stuck` once it has spent longer than its stage's threshold in that stage. This is a warning only — nothing is cancelled. Defaults (minutes) suit a single local GPU/Apple Silicon machine; raise them on slower hardware or for very long episodes. `STREAQ_TASK_TIMEOUT` (default 2h) is the hard stop for the whole job — it is killed and marked `ERROR` regardless of these thresholds:

```bash
STUCK_THRESHOLD_DOWNLOADING_MIN=60
STUCK_THRESHOLD_TRANSCRIBING_MIN=45
STUCK_THRESHOLD_DIARIZING_MIN=20
STUCK_THRESHOLD_INFERRING_SPEAKERS_MIN=15
STUCK_THRESHOLD_CHUNKING_MIN=10
STUCK_THRESHOLD_EMBEDDING_MIN=15
```


### 5. Run the Dev Server

```bash
uv run uvicorn src.api.main:app --reload --port 3001
```

> API available at http://localhost:3001
> API docs at http://localhost:3001/docs

**If `REDIS_URL` is set**, ingestion jobs are enqueued to Redis but won't run until a worker picks them up. In a separate terminal:

```bash
uv run streaq run src.worker_cli:worker
```

If `REDIS_URL` is empty, skip this — ingestion runs in-process instead.

## Observability

Tracing is powered by OpenTelemetry and compatible with any OTLP/HTTP collector — local Phoenix in Docker or hosted services like [Arize Phoenix](https://app.phoenix.arize.com).

**Local Phoenix (Docker)**

```bash
docker run -p 6006:6006 arizephoenix/phoenix:latest
```

```bash
# .env
TRACING_ENABLED=true
OTEL_ENDPOINT=http://localhost:6006/v1/traces
OTEL_PROJECT_NAME=podcast-engine
# OTEL_API_KEY not required for local Phoenix unless configured
```

**Arize hosted**

Sign up at https://app.phoenix.arize.com and grab your API key.

```bash
# .env
TRACING_ENABLED=true
OTEL_ENDPOINT=https://app.phoenix.arize.com/s/{username}/v1/traces
OTEL_API_KEY=your-key-here
OTEL_PROJECT_NAME=podcast-engine
```

Tracing is disabled by default (`TRACING_ENABLED=false`). The app runs normally without a collector configured.

**What gets traced**

- All LLM calls — prompt, response, token counts (auto-instrumented via OpenAIInstrumentor)
- Retrieval — query, result count, similarity score distribution
- Ingestion pipeline — episode, chunk counts, speaker count, optional `run_label` for benchmarking runs
- Audio download — file size, bytes received
- Transcription — backend, model, segment count, wall-clock duration
- Diarization — turn count, speaker count
- Speaker inference — one span per diarized speaker; name found, confidence level
- Chat orchestration — tool rounds used, citation count, original vs. rewritten query


## Usage

API docs are available at http://localhost:3001/docs

**Add a feed**

```bash
curl -X POST http://localhost:3001/api/v1/feeds \
  -H "Content-Type: application/json" \
  -d '{"rss_url": "https://feeds.example.com/podcast.rss"}'
```

**Ingest an episode**

Once a feed is added, get the episode ID from the episodes list then trigger ingestion:

```bash
curl -X POST http://localhost:3001/api/v1/episodes/{episode_id}/ingest \
  -H "Content-Type: application/json" \
  -d '{}'
```

Ingest returns `409` if the episode is already queued or running, and `503` if the queue is unreachable (the episode is marked `ERROR`).

Monitor progress via SSE stream or poll the status endpoint:

```bash
# SSE stream
curl -N http://localhost:3001/api/v1/episodes/{episode_id}/status/stream

# Poll
curl http://localhost:3001/api/v1/episodes/{episode_id}/status
```

Transcript and speaker endpoints return `409` until the episode reaches `READY`.

**Queue overview**

Everything queued, in progress, recently finished, and errored, grouped by status:

```bash
# Default window: finished/errored in the last 24h
curl http://localhost:3001/api/v1/queue

# Cap each group's items (totals stay complete)
curl "http://localhost:3001/api/v1/queue?limit=5"
```

**Retry or reset**

```bash
# Retry an errored (or re-run a ready) episode
curl -X POST http://localhost:3001/api/v1/episodes/{episode_id}/reingest \
  -H "Content-Type: application/json" \
  -d '{}'

# Reset one episode to PENDING (or cancel it, if queued/running) — discards its data
# 409 = the episode changed or is mid-write; try again in a moment
curl -X POST http://localhost:3001/api/v1/episodes/{episode_id}/reset

# Reset every errored episode
curl -X POST http://localhost:3001/api/v1/queue/errors/reset
```

## Useful Commands

### Migrations

```bash
# Generate a new migration after model changes
uv run alembic revision --autogenerate -m "description"

# Rollback one migration
uv run alembic downgrade -1
```

### Database

```bash
# Connect directly to the DB
podman compose -f docker-compose.db.yml exec db psql -U username -d podcast_engine

# Wipe the database volume and start fresh
podman compose -f docker-compose.db.yml down -v
```

### Testing

```bash
# Run all tests
uv run pytest

# Unit only (no services) / integration only (requires the test DB)
uv run pytest tests/unit
uv run pytest tests/integration

# With coverage
uv run pytest --cov=src --cov-report=term-missing
```

## Project Structure

```
src/
  api/           # FastAPI app, routers (feeds, episodes, speakers, queue, chat, health), middleware, dependencies
  models/        # SQLAlchemy models and Pydantic schemas
  ingestion/     # RSS parsing, audio download, pipeline orchestration, status + job ownership, queue overview
  query/         # RAG query engine, tool-calling, session management, query rewriting, chat streaming
  storage/       # Vector store abstraction
  llm/           # LLM and embedding client protocols + implementations
  telemetry/     # OpenTelemetry setup and tracer
  transcription/ # TranscriptionService protocol, local (Whisper) and remote implementations
  diarization/   # DiarizationService protocol, local (Senko) implementation, segment alignment
  worker.py      # streaQ worker factory (build_worker) + WorkerContext lifespan
  worker_cli.py  # `streaq run src.worker_cli:worker` entry point
```

For architecture and design decisions, see `docs/ARCHITECTURE.md`.

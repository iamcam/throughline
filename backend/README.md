# Pod Knowledge Engine - Backend

This is the backend for the Pod Knowledge Engine project.

## Requirements

- Python 3.13+
- uv
- [Podman](https://podman-desktop.io) or Docker w/ compose

Examples use podman for container management, but docker will also work - just swap `docker` for `podman`.

## Setup

### 1. Environment

copy the `.env.example` to `.env` and fill in the relevant settings.

### 2. Virtual Env

We use uv + venv for environment management. [Install uv](https://docs.astral.sh/uv/) if you haven't already

```
uv venv
source .venv/bin/activate
```

### 3. Install Dependencies

All devices are supported, falling back to cpu if CUDA is not availabe. If you are running CUDA, it's one extra uv command.

**All architectures**
```
uv sync
```

**Install Pytorch**

By default `torch` and `torchaudio` are both installed on `uv sync`, but if you have a CUDA-capable GPU, you can install the appropriate versions:

```
# Linux / Windows — NVIDIA GPU
uv add torch torchaudio --index https://download.pytorch.org/whl/cu121
```

**Whisper**

The `faster-whisper` package is automatically installed, but Mac / Apple Silicon users might want a faster option via `mlx-whisper`:

```
# mlx-whisper — Apple Silicon only, faster than faster-whisper on Metal
uv add mlx-whisper
```
Then update the .env to reflect your `mlx_whisper` choice

```
# Set in .env:
WHISPER_BACKEND=mlx_whisper
WHISPER_MODEL_SIZE=large-v3
```

**Configure `.env`**

```
# All platforms
WHISPER_MODEL_SIZE=medium # tiny | base | small | medium | large-v3

# Apple Silicon with mlx-whisper (if installed)
WHISPER_BACKEND=mlx_whisper

# Everyone else (default)
WHISPER_BACKEND=faster_whisper
```

Because speaker diarization is very computationally intensive and quite slow, it is off by default.

```
ENABLE_DIARIZATION=false
```

Pyannote requires a Hugging Face token and model access. Go to https://huggingface.co/pyannote/speaker-diarization-community-1 and accept the terms, then set `HUGGINGFACE_TOKEN` in your `.env`.


### 4. Bootstrapping

This project uses postgres with pgvector for embeddings and can be bootstrapped by running the following lines the postgres docker image (via podman)

**Start the container**

```
podman compose -f docker-compose.dev.yml up -d
```

Note the container name. It may be `backend-db-1`

**Enable PGVector**

```
podman exec -it <container-name> psql -U <username> -d podcast_engine -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

**Run Migrations and create the test db**

```
uv run alembic upgrade head
PYTHONPATH=. uv run python scripts/create_test_db.py
podman exec -it <container-name> psql -U <username> -d podcast_engine_test -c "CREATE EXTENSION IF NOT EXISTS vector;
```

this will create a test database at `<database_name>_test` used by the testing suite. You only need to run it once


### 5. Run the dev server

Run the dev server - default port is on 3001

```
uv run uvicorn src.api.main:app --reload --port 3001
```

> API Available at http://localhost:3001
> API docs at http://localhost:3001/docs

Alternatively you can run uvicorn directly on your chosen port (default is 8000)

```
uv run uvicorn src.api.main:app --reload --port 8080
```

## Useage

API docs are automatically generated and available at http://localhost:3001/docs



**Ingesting Feed**

To submit a feed for ingestion, pass the rss_url to the feeds endpoint:

```
curl -X POST http://localhost:3001/api/v1/feeds \
  -H "Content-Type: application/json" \
  -d '{"rss_url": "https://orvisffguide.libsyn.com/rss"}'
```

**Ingesting an Episode**

Once a feed is added, get the episode ID from the episodes list, then trigger ingestion:

- Optional `speaker_count_hint` tells the diarization model how many speakers to expect. Omit if unknown
- Monitor progress via SSE stream or poll the status endpoint
- Pipeline pauses at `PENDING_NAMES` because speaker confirmation required before chunking begins

## Useful Commands

### Migrations

**Generate a new migration after model changes**

```
uv run alembic revision --autogenerate -m "description"
```

**Rollback one migration**

```
uv run alembic downgrade -1
```

### Database

**Connect directly to the DB**

```
podman compose -f docker-compose.dev.yml exec db psql -U username -d podcast_engine
```

(replace `username` and `podcast_engine` with any values you may be using - local or hosted)

**Wipe the database volume and start fresh**

```
podman compose -f docker-compose.dev.yml down -v
```

### Testing

For general test runs:
```
uv run pytest
```

...or for coverage information:

```
uv run pytest --cov=src --cov-report=term-missing
```

## Project Structure

The backend project structure will contain the following components, to be completed in successive iterations.

```
src/
  api/          # FastAPI app, routers, middleware, dependencies
  models/       # SQLAlchemy models and Pydantic schemas
  ingestion/    # RSS parsing, audio download, transcription pipeline
  query/        # RAG query engine, tool-calling, session management
  storage/      # Vector store abstraction
  llm/          # LLM and embedding client protocols
  transcription/ # TranscriptionService protocol, local (Whisper + Pyannote) and remote implementations
```


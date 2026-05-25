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

```
uv sync
```

### 4. Database

This project uses postgres with pgvector for embeddings.

**Start the container**

```
podman compose -f docker-compose.dev.yml up -d
```

**Run Migrations**

```
uv run alembic upgrade head
```

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
  transcription/ # Transcription service protocol and implementations
```


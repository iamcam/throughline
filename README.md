# Pod Knowledge Engine

If you ever wondered about the knowledge and information discussed in a podcast, this is your tool.

This project contains backend and frontend components for a podcast knowledge engine.

This engine ingests select podcast episodes, transcribes + diarizes speakers, and uses conversational RAG to serve as a topic-specific knowledgebase.

Follow the bootstrapping instructions below to get started quickly. For further information, backend/frontend component details are available in the [`frontend/README.md`](frontend/README.md) and [`backend/README.md`](backend/README.md) directory README files.

## General Approach

Project development is directed through thoughtful discussion with Claude Sonnet about code, architecture, and user-facing concerns like usability, expectations, and utility. The intent is a hybrid development approach - managing the product and code guidelines as a human while allowing the language model to pair program. While possible to allow a coding agent full control over decisions with only guiding input from a human (me), I've decided to take a more hands-on approach as both a learning exercise into new topics while using experience to guide and let the models shine where they do best.

This project is not vibe-coded. It's intentionally allowing tools to do what they are best at without surrendering knowledge, wisdom, and discernment... a bicycle for the mind.

The following files were developed in collaboration with Claude Sonnet 4.6. Architectural decisions, tradeoffs, and product direction were my decisions; the model contributed structure, detail, and implementation guidance.

* `ARCHITECTURE.md` - system design, protocols, dependencies, schema, API reference - the primary guide
* `IMPLEMENTATION_PLAN.md` - includes the sequential development phases.
* `FUTURE_SCOPE.md` - my thoughts around areas for improvement after the initial development milestone, post v1
* `OPERATIONS.md` - information about deployment, demo auth, hosting guides, etc.

...and of course, all subject to change.

## Bootstrapping

There are two ways to run this project: locally on your machine (recommended for development) or via Docker/Podman (recommended for demos and hosting). Both require external services for LLM inference and embeddings.

### External Services

This project does not bundle LLM or embedding models. You need at least one OpenAI-compatible endpoint for LLM inference and one for embeddings — local or cloud, your choice.

| Service       | What it does             | Local options                        | Cloud options           |
| ------------- | ------------------------ | ------------------------------------ | ----------------------- |
| LLM           | Chat + speaker inference | Ollama, llama-server, MLX, LM Studio | OpenAI, Anthropic, etc. |
| Embeddings    | Semantic search          | Ollama, llama-server, MLX            | OpenAI, etc.            |
| Transcription | Audio → text             | Whisper (runs locally)               | OpenAI Whisper API      |

Any OpenAI-compatible endpoint works — set `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL_NAME` in `backend/.env` to point at whichever provider you prefer. The same applies to embeddings. Model quality will affect speaker inference and RAG results — a capable 7B+ model is recommended for best results.

---

### Option 1 — Local Dev

Best for development. Backend and frontend run directly on your machine; only the database runs in Docker.

**Requirements:** Python 3.13+, uv, Node 20+, Yarn, Docker or Podman

```bash
# 1. Configure backend
cp backend/.env.example backend/.env
# Edit backend/.env — set DATABASE_URL, LLM_BASE_URL, LLM_MODEL_NAME at minimum

# 2. Configure frontend
cp frontend/.env.example frontend/.env
# Defaults work for local dev — no changes needed

# 3. Start the database separately if you don't already have access to a postgres instance
cd backend
podman compose -f docker-compose.dev.yml up -d

# 4. Bootstrap (migrations + test DB)
./scripts/bootstrap.sh

# 5. Start the backend (from backend/)
uv run uvicorn src.api.main:app --reload --port 3001

# 6. Start the frontend (separate terminal, from frontend/)
yarn && yarn dev
```

> Backend: http://localhost:3001
> Frontend: http://localhost:3000
> API docs: http://localhost:3001/docs

**Service URLs in `backend/.env` for local dev:**
```dotenv
LLM_BASE_URL=http://localhost:11434/v1       # Ollama or other local provider on your machine
EMBEDDING_BASE_URL=http://localhost:11434/v1  # Ollama or other local provider on your machine
TRANSCRIPTION_SERVICE_URL=http://localhost:8001 # leave empty if using local (in-process)
```

---

### Option 2 — Docker / Podman

Best for demos and hosting. One command starts everything.

**Requirements:** Docker or Podman with Compose

```bash
# 1. Configure
cp .env.example .env                          # compose-level DB vars
cp backend/.env.example backend/.env          # backend config
cp frontend/.env.example frontend/.env        # frontend config

# Edit backend/.env — set LLM_BASE_URL, LLM_MODEL_NAME at minimum
# Edit .env — set DB_USER, DB_PASSWORD, DB_NAME

# 2. Start everything
podman compose up --build

# 3. Open the app
open http://localhost
```

> The app is available at http://localhost
> API docs are available in local dev only at http://localhost:3001/docs

**Important — service URLs inside Docker:**

Services running on your host machine are not reachable via `localhost` from inside a container. Use `host.docker.internal` instead:

```dotenv
# backend/.env when running via Docker with local Ollama or other local provider
LLM_BASE_URL=http://host.docker.internal:11434/v1
EMBEDDING_BASE_URL=http://host.docker.internal:11434/v1
TRANSCRIPTION_SERVICE_URL=http://host.docker.internal:8001
```

For cloud APIs (OpenAI, Anthropic, etc.) the URL works the same in both modes — no change needed.

---

### Transcription

Transcription runs locally via Whisper by default. For the Docker setup this means the Whisper model is downloaded on first use and cached in a Docker volume.

To use a separate transcription service instead:

```dotenv
TRANSCRIPTION_SERVICE_URL=http://host.docker.internal:8001  # Docker
# or
TRANSCRIPTION_SERVICE_URL=http://localhost:8001              # local dev
```

See `backend/README.md` for full transcription configuration options including diarization.
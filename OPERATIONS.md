# Podcast Knowledge Engine — Operations and Deployment

> Covers: local development, demo hosting, environment configurations, auth, and monitoring.

> **Public name:** This project is published as **Throughline**. Internal naming throughout this document uses the original working title (Podcast Knowledge Engine).

---



## Environments

| Environment  | Purpose | Infrastructure |
|--------------|---------|---------------|
| `local-dev`  | Daily development | Docker DB only, services run natively |
| `local-full` | Full stack test | All services in Docker Compose |
| `demo`       | Hosted demo for preview | Single VPS, all services in Docker Compose |

---

## Local Development

Fastest iteration loop: run the DB in Docker, everything else natively.

```bash
# Backend
cd backend

# Start Redis (optional -- only needed if REDIS_URL is set)
docker compose -f docker-compose.db.yml -f docker-compose.redis.yml ...

cp .env.example .env
# Edit .env — set DATABASE_URL, LLM_BASE_URL at minimum
uv run alembic upgrade head
uv run uvicorn src.api.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
yarn                  # install dependencies (yarn, not npm)
yarn dev              # http://localhost:3000

# Frontend build and lint
yarn build            # TypeScript check + Vite production build
yarn lint             # ESLint

# API docs
open http://localhost:3001/docs
```

**Frontend dev notes:**
- Package manager is Yarn — do not use `npm install` in the frontend directory
- Tailwind v4 via `@tailwindcss/vite` plugin — no `postcss.config.js` needed
- The Vite dev server proxies `/api/*` requests to `http://localhost:8000`. In production, Nginx handles the same routing (see `docker-compose.yml` and Nginx config below).
- Path alias `@/*` → `src/*` — use `@/components/Foo` not `../../components/Foo`
- shadcn components are in `src/components/ui/`; add new ones with `yarn dlx shadcn add <component>`

### Local LLM options

**Ollama (recommended for local dev):**
```bash
ollama serve
ollama pull llama3.1:8b
ollama pull nomic-embed-text

# .env
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL_NAME=llama3.1:8b
EMBEDDING_BASE_URL=http://localhost:11434/v1
EMBEDDING_MODEL_NAME=nomic-embed-text
EMBEDDING_DIMENSIONS=768
```

**llama.cpp server:**
```bash
./llama-server -m models/llama-3.1-8b.gguf --port 8080

# .env
LLM_BASE_URL=http://localhost:8080/v1
LLM_API_KEY=none
LLM_MODEL_NAME=llama-3.1-8b
```

**Cloud (Claude, OpenAI):**
```bash
# .env
LLM_BASE_URL=https://api.anthropic.com/v1   # or api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL_NAME=claude-sonnet-4-20250514     # or gpt-4o
```

### Transcription options

**Local (pyannote + Whisper):**
```bash
# .env
HUGGINGFACE_TOKEN=hf_...
WHISPER_MODEL=medium   # tiny/base/small/medium/large, or a Hugging Face repo for mlx_whisper
```

Accept that diarization is slow on CPU. For dev, use the `sample_transcript.json` fixture to skip transcription entirely.

**Transcription sidecar (Docker):**
```bash
docker compose --profile transcription up transcription

# .env
TRANSCRIPTION_SERVICE_URL=http://localhost:8001
TRANSCRIPTION_API_KEY=...   # if required by the remote service
```

Presence of `TRANSCRIPTION_SERVICE_URL` is what selects remote transcription — absence means local. Don't set it if you want local Whisper.

---

## Full Stack Docker

Runs everything in containers: Postgres, Redis, the API, a worker process, and the frontend.

```bash
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
# Edit backend/.env — set LLM_BASE_URL, LLM_MODEL_NAME at minimum

docker compose up --build     # first run, or after dependency/code changes
docker compose up -d          # detached
```

**Applying config changes:** editing `.env`/`backend/.env.docker` doesn't require a rebuild — just recreate the affected containers:

```bash
docker compose up -d --force-recreate backend worker
```

Rebuilds are only needed for dependency or code changes (neither service live-reloads inside the container):

```bash
docker compose up -d --build backend    # or: worker
```

**Logs**
```bash
docker compose logs -f backend
docker compose logs -f worker
```

**DB shell**
```bash
docker compose exec db psql -U $DB_USER -d $DB_NAME
```

**Migrations** — run automatically on container start (`backend/entrypoint.sh`); to run manually:
```bash
docker compose exec backend uv run alembic upgrade head
```

**Services**

| Service    | Purpose                                                                          |
| ---------- | -------------------------------------------------------------------------------- |
| `db`       | Postgres + pgvector                                                              |
| `redis`    | Job queue backend for `worker`                                                   |
| `backend`  | FastAPI app — enqueues ingestion jobs, never runs the pipeline directly          |
| `worker`   | Runs ingestion jobs (streaQ) — same image as `backend`, different entrypoint arg |
| `frontend` | Nginx-served React app                                                           |

Bring your own Postgres or Redis instead of the containerized ones by pointing `DATABASE_URL`/`REDIS_URL` at your existing instance and removing the corresponding service (and its `depends_on` entry on `backend`/`worker`) from `docker-compose.yml`.

### docker-compose.yml (full)

```yaml
# docker-compose.yml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: ${DB_NAME}
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d ${DB_NAME}"]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    # No persistence by default -- queued/in-flight jobs are lost if this
    # container restarts. See FUTURE_SCOPE.md 2.1c for adding durability.
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    env_file: backend/${BACKEND_ENV_FILE:-.env}
    environment:
      DATABASE_URL: postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@db:5432/${DB_NAME}
      REDIS_URL: redis://redis:6379
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: ["./entrypoint.sh", "worker"]
    env_file: backend/${BACKEND_ENV_FILE:-.env}
    environment:
      DATABASE_URL: postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@db:5432/${DB_NAME}
      REDIS_URL: redis://redis:6379
    volumes:
      - model_cache:/root/.cache/huggingface
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
    env_file: frontend/.env
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - backend
    restart: unless-stopped

volumes:
  pgdata:
  model_cache:
```

**Applying config changes:** editing `.env`/`backend/.env.docker` doesn't require a rebuild — just recreate the affected containers:

```bash
docker compose up -d --force-recreate backend worker
```

Rebuilds are only needed for dependency or code changes (neither service live-reloads inside the container):

```bash
docker compose up -d --build backend    # or: worker
```

---

## Demo Hosting

### VPS Sizing

| Workload | Recommended |
|----------|------------|
| API + frontend + DB only (remote transcription or pre-ingested) | 2 vCPU, 4GB RAM |
| API + DB + CPU transcription | 4 vCPU, 8GB RAM |
| API + DB + GPU transcription | GPU VPS |

---

### Deployment Steps (example)

```bash
# 1. Provision server (Ubuntu 24.04)
# 2. SSH in, install Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker $USER

# 3. Clone repo
git clone https://github.com/youruser/podcast-knowledge-engine /app
cd /app

# 4. Configure
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
nano backend/.env    # set all production values

# 5. Build and start
docker compose up -d --build

# 6. Seed demo data
docker compose exec backend uv run python scripts/seed_demo.py

# 7. Verify
curl http://your-server-ip/api/v1/health/deep
```

---

### Nginx Reverse Proxy (recommended)

Run Nginx on the VPS to terminate HTTPS and route traffic.

```nginx
# /etc/nginx/sites-available/podcast-engine

server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # Frontend
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # API
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
# SSL via Let's Encrypt
apt install certbot python3-certbot-nginx
certbot --nginx -d your-domain.com
```

---

## Demo Authentication

A simple HTTP Basic Auth layer protects the demo without requiring user accounts.

### Backend middleware (`src/api/middleware/auth.py`)

```python
import base64
import secrets
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from src.config import get_settings

class BasicAuthMiddleware(BaseHTTPMiddleware):
    """
    HTTP Basic Auth middleware.
    Bypassed when DEMO_AUTH_ENABLED=false.
    Unprotected routes: /api/v1/health, /docs, /redoc, /openapi.json
    """

    UNPROTECTED = {"/api/v1/health", "/docs", "/redoc", "/openapi.json"}

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()

        if not settings.demo_auth_enabled:
            return await call_next(request)

        if request.url.path in self.UNPROTECTED:
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Basic "):
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Podcast Knowledge Engine Demo"'},
                content="Authentication required"
            )

        try:
            credentials = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, password = credentials.split(":", 1)
        except Exception:
            return JSONResponse(status_code=401, content={"detail": "Invalid credentials"})

        valid_user = secrets.compare_digest(username, settings.demo_username)
        valid_pass = secrets.compare_digest(password, settings.demo_password)

        if not (valid_user and valid_pass):
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Podcast Knowledge Engine Demo"'},
                content="Invalid credentials"
            )

        return await call_next(request)
```

Register in `main.py`:
```python
app.add_middleware(BasicAuthMiddleware)
```

### `.env` for demo
```bash
DEMO_AUTH_ENABLED=true
DEMO_USERNAME=demo
DEMO_PASSWORD=your-secure-password-here
```

### Frontend handling
When the API returns 401, the browser's native Basic Auth prompt appears — no frontend code needed. For a cleaner UX, add a simple login form that stores credentials in memory and passes them via `Authorization` header on all requests.

---

## Database Management

### Backups
```bash
# Dump
docker compose exec db pg_dump -U $DB_USER podcast_engine > backup_$(date +%Y%m%d).sql

# Restore
docker compose exec -T db psql -U $DB_USER podcast_engine < backup_20260101.sql
```

### Moving data between environments
Pre-ingest locally, export, import to hosted DB:
```bash
# Export from local
pg_dump -h localhost -U $DB_USER podcast_engine \
  --exclude-table=alembic_version > demo_data.sql

# Import to hosted
psql $HOSTED_DATABASE_URL < demo_data.sql
```

### Managed Postgres options (if you don't want to self-host DB)
- **Neon** — serverless Postgres, generous free tier, supports pgvector
- **Supabase** — Postgres + pgvector, free tier
- **Railway** — simple deployment, $5/mo hobby plan

For the demo: Neon free tier is sufficient and removes the DB from your VPS footprint.

```bash
# .env with Neon
DATABASE_URL=postgresql+asyncpg://user:pass@ep-xxx.us-east-2.aws.neon.tech/podcast_engine?sslmode=require
```

---

## Monitoring the Demo

### Health check endpoint
```bash
# Quick check
curl https://your-domain.com/api/v1/health/deep

# Automated with cron or uptime monitor (UptimeRobot free tier)
# Monitor URL: https://your-domain.com/api/v1/health
```

### Container health
```bash
docker compose ps           # see status of all services
docker stats               # live resource usage
docker compose logs -f api  # tail logs
```

### Phoenix (if running)
Accessible at port 6006 — not exposed via Nginx on the demo server by default. Use SSH tunnel to view:
```bash
ssh -L 6006:localhost:6006 user@your-server
open http://localhost:6006
```



---

## Dockerfile Reference

### Backend

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ ./src/

CMD ["uv", "run", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Frontend

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile
COPY . .
RUN yarn build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
```

### Transcription sidecar

```dockerfile
FROM python:3.12-slim

# ffmpeg required for audio processing
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY main.py ./

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
```


---

## Version Control Notes

**`.gitignore` (frontend):** Ensure these are covered at the repo root or in `frontend/.gitignore`:
```
frontend/node_modules/
frontend/dist/
frontend/.env
```

The frontend was scaffolded with a `.gitignore` covering `node_modules`, `dist`, and editor files. The `frontend/.git` directory should not exist — the frontend is tracked by the root repo, not as a submodule.

---

## Known TODOs

### Frontend Bundle Size

`react-markdown` and its remark/rehype dependencies add significant weight to the frontend bundle. `ChatPage` is lazy-loaded via `React.lazy()` + `Suspense` in `App.tsx` to keep the initial bundle under Vite's 500kb warning threshold. If bundle size becomes a concern at build time:

```bash
yarn build --report   # check chunk sizes
```

The lazy load is already in place — no further action needed unless other large dependencies are added.

### Frontend Dependencies Added (Phase 8)

New packages added beyond the Phase 7 baseline:
- `react-markdown` — LLM response rendering in `ChatInterface`
- `react-resizable-panels` — resizable split-panel layout (via shadcn `Resizable` component)

New shadcn components added:
- `sheet` — knowledge base browser panel (`SearchFilterList`)
- `accordion` — feed list in knowledge base browser
- `collapsible` — citation expansion in `CitationList`
- `resizable` — split-panel chat layout in `EpisodesPage` and `EpisodeDetailPage`

# Podcast Knowledge Engine — Operations and Deployment

> Covers: local development, demo hosting, environment configurations, auth, and monitoring.

---

## Environments

| Environment | Purpose | Infrastructure |
|-------------|---------|---------------|
| `local-dev` | Daily development | Docker DB only, services run natively |
| `local-full` | Full stack test | All services in Docker Compose |
| `demo` | Hosted demo for interviews | Single VPS, all services in Docker Compose |

---

## Local Development

Fastest iteration loop: run the DB in Docker, everything else natively.

```bash
# Start DB only
docker compose -f docker-compose.dev.yml up -d

# Backend
cd backend
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
open http://localhost:8000/docs
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
TRANSCRIPTION_BACKEND=local
HUGGINGFACE_TOKEN=hf_...
WHISPER_MODEL_SIZE=medium   # tiny/base/small/medium/large
```

Accept that diarization is slow on CPU. For dev, use the `sample_transcript.json` fixture to skip transcription entirely.

**Transcription sidecar (Docker):**
```bash
docker compose --profile transcription up transcription

# .env
TRANSCRIPTION_BACKEND=remote
TRANSCRIPTION_SERVICE_URL=http://localhost:8001
```

---

## Full Stack Docker

```bash
cp .env.example .env
# Edit .env

docker compose up           # api + frontend + db
docker compose up -d        # detached

# With optional services
docker compose --profile transcription up          # + transcription sidecar
docker compose --profile observability up          # + Phoenix
docker compose --profile transcription \
               --profile observability up          # everything

# Logs
docker compose logs -f api
docker compose logs -f transcription

# DB shell
docker compose exec db psql -U $DB_USER -d podcast_engine

# Migrations
docker compose exec api uv run alembic upgrade head
```

### docker-compose.yml (full)

```yaml
version: "3.9"

services:
  api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@db:5432/podcast_engine
      TRANSCRIPTION_SERVICE_URL: http://transcription:8001
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - audio_data:/app/data/audio
    restart: unless-stopped

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    depends_on:
      - api
    restart: unless-stopped

  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: podcast_engine
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"    # expose for local DB tools; remove in production
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d podcast_engine"]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  transcription:
    build:
      context: ./transcription-service
      dockerfile: Dockerfile
    ports:
      - "8001:8001"
    env_file: .env
    volumes:
      - audio_data:/app/data/audio  # shared with api
      - model_cache:/root/.cache    # cache Whisper + Pyannote models
    profiles: ["transcription"]
    restart: unless-stopped

  phoenix:
    image: arizephoenix/phoenix:latest
    ports:
      - "6006:6006"   # Phoenix UI
      - "4317:4317"   # OTLP gRPC collector
    profiles: ["observability"]
    restart: unless-stopped

volumes:
  pgdata:
  audio_data:
  model_cache:
```

---

## Demo Hosting

### VPS Sizing

| Workload | Recommended |
|----------|------------|
| API + frontend + DB only (remote transcription or pre-ingested) | 2 vCPU, 4GB RAM — ~$10/mo |
| API + DB + CPU transcription | 4 vCPU, 8GB RAM — ~$20/mo |
| API + DB + GPU transcription | GPU VPS — Hetzner CCX, Lambda, RunPod |

For an interview demo, the pragmatic approach: pre-ingest your demo episodes locally, push the data to the hosted DB, and run only the API + frontend on the VPS. No transcription service needed on the server.

**Recommended providers:**
- Hetzner (EU/US) — best price/performance, CAX21 (4 vCPU ARM, 8GB) ~€6/mo
- DigitalOcean — easy setup, slightly pricier
- Fly.io — good for API + frontend as separate apps, free tier available

---

### Deployment Steps (Hetzner example)

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
nano .env    # set all production values

# 5. Build and start
docker compose up -d --build

# 6. Run migrations
docker compose exec api uv run alembic upgrade head

# 7. Seed demo data
docker compose exec api uv run python scripts/seed_demo.py

# 8. Verify
curl http://your-server-ip:8000/api/v1/health/deep
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

## Demo Runbook

Steps to run before an interview demo:

```bash
# 1. Verify server is up
curl https://your-domain.com/api/v1/health

# 2. Verify demo data is loaded
curl -u demo:password https://your-domain.com/api/v1/feeds

# 3. Run a test query
curl -u demo:password -X POST https://your-domain.com/api/v1/chat/sessions \
  -H "Content-Type: application/json" \
  -d '{"scope_feed_id": "your-feed-uuid"}'

# 4. Open browser to https://your-domain.com
# 5. Log in with demo credentials
# 6. Navigate to Chat, confirm session starts
```

Prepare 3 demo queries in advance that you know produce good results. Know the timestamps. Practice the flow twice before the interview.

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
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

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

## Cost Estimate (Demo Setup)

| Item | Option | Monthly Cost |
|------|--------|-------------|
| VPS (API + frontend) | Hetzner CX22 | ~€4 |
| Database | Neon free tier | $0 |
| LLM inference | Ollama on VPS or API key | $0–$5 |
| SSL cert | Let's Encrypt | $0 |
| Domain | Namecheap | ~$1 |
| Uptime monitoring | UptimeRobot free | $0 |
| **Total** | | **~$5–10/mo** |

For interview purposes, you could also run everything locally and share your screen — no hosting required. The hosted demo is a nice-to-have, not a requirement.

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

### Docker Integration Not Yet Validated (Phase 7 + 8)

The frontend Docker build (`frontend/Dockerfile` and the `frontend` service in `docker-compose.yml`) has not been verified against the actual frontend stack. The scaffold `Dockerfile` uses a standard Node + nginx pattern, but the following need confirmation before demo deployment:

- Tailwind v4 via `@tailwindcss/vite` plugin builds correctly in Docker (no postcss.config.js)
- `yarn build` succeeds inside the Docker build context
- The built `dist/` is served correctly by the nginx config inside the container
- The Nginx reverse proxy correctly routes `/api/*` to the backend container

**Recommended verification step:**
```bash
docker compose up --build frontend
curl http://localhost:3000
```

Until this is verified, use local dev (`yarn dev`) for frontend and Docker only for the backend + DB.

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

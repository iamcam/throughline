# Phase 1 — RSS Feed Ingestion + Ingestion Queue

> Moved from IMPLEMENTATION_PLAN.md. Status: ✅ Complete. Git tag: `v0.1.1-feeds`.
> See IMPLEMENTATION_PLAN.md's Phase Overview table for the one-line summary; see ARCHITECTURE.md for current system design.

**Goal:** Add a podcast feed by URL. See episodes listed. Queue abstraction in place before any long-running work begins.

### Tasks

#### 1.1 Pydantic schemas (`src/models/schemas.py`) 🤖
Request/response schemas for feeds and episodes. Separate from DB models.

```python
class AddFeedRequest(BaseModel):
    rss_url: HttpUrl

class FeedResponse(BaseModel):
    id: UUID
    rss_url: str
    title: str | None
    description: str | None
    episode_count: int
    created_at: datetime

class EpisodeResponse(BaseModel):
    id: UUID
    feed_id: UUID
    title: str | None
    published_at: datetime | None
    duration_seconds: int | None
    pipeline_status: str
    pipeline_stage: str | None
    pipeline_progress: float | None
    audio_url: str | None

class PipelineStatusUpdate(BaseModel):
    status: str
    stage: str | None = None
    progress: float | None = None
    position: int | None = None     # queue position when QUEUED
    error: str | None = None
```

#### 1.2 RSS parser (`src/ingestion/rss_parser.py`)
Use `feedparser`. Extract per episode:
- `guid`, `title`, `description`, `published_at`
- `audio_url` (enclosure URL)
- `duration_seconds` — handle `HH:MM:SS`, `MM:SS`, raw seconds
- `transcript_url` — from `<podcast:transcript>` tag if present

#### 1.3 Feed service (`src/ingestion/feed_service.py`)
```python
async def add_feed(rss_url: str, db: AsyncSession) -> Feed
async def refresh_feed(feed_id: UUID, db: AsyncSession) -> list[Episode]   # new guids only
async def list_feeds(db: AsyncSession) -> list[Feed]
async def get_feed(feed_id: UUID, db: AsyncSession) -> Feed
async def delete_feed(feed_id: UUID, db: AsyncSession) -> None
```

`add_feed`: parse → upsert feed → upsert episodes (ON CONFLICT guid DO NOTHING).

#### 1.4 IngestionQueue (`src/ingestion/queue.py`) 🤖

**Protocol:**
```python
class IngestionQueue(Protocol):
    async def enqueue(self, episode_id: UUID, job_args: dict) -> str: ...
    async def get_status(self, job_id: str) -> JobStatus: ...
    async def get_position(self, job_id: str) -> int: ...
    async def cancel(self, job_id: str) -> bool: ...
```

**v1 implementation — `BackgroundTaskQueue`:**
```python
class BackgroundTaskQueue:
    def __init__(self, max_concurrent: int):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._jobs: dict[str, JobRecord] = {}
        self._queue: list[str] = []          # ordered list of job_ids

    async def enqueue(self, episode_id: UUID, job_args: dict) -> str:
        job_id = str(uuid4())
        self._jobs[job_id] = JobRecord(status=JobStatus.QUEUED, episode_id=episode_id)
        self._queue.append(job_id)
        asyncio.create_task(self._run(job_id, episode_id, job_args))
        return job_id

    async def _run(self, job_id: str, episode_id: UUID, job_args: dict):
        async with self._semaphore:           # blocks here if at capacity
            self._jobs[job_id].status = JobStatus.RUNNING
            self._queue.remove(job_id)
            await ingest_episode(episode_id, **job_args)

    async def get_position(self, job_id: str) -> int:
        try:
            return self._queue.index(job_id) + 1
        except ValueError:
            return 0
```

Queue singleton created in FastAPI lifespan, injected via dependency.

**Note:** `cancel()` returns `False` unconditionally in v1. Stuck jobs require a DB status update (`UPDATE episodes SET pipeline_status='ERROR' WHERE id=...`) or uvicorn restart to clear.

#### 1.5 Routers
```
POST   /api/v1/feeds
GET    /api/v1/feeds
GET    /api/v1/feeds/{feed_id}
DELETE /api/v1/feeds/{feed_id}
POST   /api/v1/feeds/{feed_id}/refresh
GET    /api/v1/feeds/{feed_id}/episodes
GET    /api/v1/episodes/{episode_id}
GET    /api/v1/episodes/{episode_id}/status         (polling — always available)
```

#### 1.6 Tests
```python
# tests/unit/test_rss_parser.py  (fixture: sample_feed.xml)
def test_parse_feed_extracts_title()
def test_parse_episodes_extracts_guid()
def test_parse_duration_hhmmss()
def test_parse_duration_raw_seconds()
def test_parse_transcript_url_tag()

# tests/unit/test_queue.py
async def test_enqueue_returns_job_id()
async def test_queue_position_reported()
async def test_semaphore_limits_concurrency()
async def test_queue_satisfies_protocol()

# tests/integration/test_feeds.py
async def test_add_feed_creates_episodes()
async def test_refresh_adds_only_new_episodes()
async def test_delete_feed_cascades()
```

**Create fixture now:** `tests/fixtures/sample_feed.xml` — valid RSS with 3 episodes, one with `podcast:transcript` tag, various duration formats.

### Phase 1 Done When
- `POST /api/v1/feeds` creates feed + episodes with `pipeline_status: PENDING`
- `GET /api/v1/feeds/{id}/episodes` returns episode list
- Queue protocol + BackgroundTaskQueue implemented and tested
- Git tag: `v0.1.1-feeds`

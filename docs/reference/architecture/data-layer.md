# Data Layer — PostgreSQL + pgvector

> Moved from ARCHITECTURE.md §3.11. Referenced from ARCHITECTURE.md — see that doc for the high-level component map.

**Schema:**

```sql
feeds (
  id UUID PRIMARY KEY,
  rss_url TEXT UNIQUE NOT NULL,
  title TEXT, description TEXT, image_url TEXT,
  last_fetched_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
)

episodes (
  id UUID PRIMARY KEY,
  feed_id UUID REFERENCES feeds ON DELETE CASCADE,
  guid TEXT UNIQUE NOT NULL,
  title TEXT, description TEXT, published_at TIMESTAMPTZ,
  audio_url TEXT, audio_local_path TEXT,
  duration_seconds INT,
  image_url TEXT,
  pipeline_status TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING | QUEUED | DOWNLOADING … EMBEDDING | READY | ERROR
  pipeline_progress FLOAT,
  pipeline_error TEXT,
  ingestion_job_id TEXT,           -- owning queue job; claims, resets, and worker writes check it (Phase 21)
  queued_at TIMESTAMPTZ,           -- set when the episode is claimed for the queue (Phase 21)
  status_changed_at TIMESTAMPTZ,   -- bumped only when pipeline_status actually changes (Phase 21)
  started_at TIMESTAMPTZ,          -- set on the first DOWNLOADING of a run; cleared by queue claims and resets, kept on READY/ERROR (v1.9.1)
  created_at TIMESTAMPTZ DEFAULT now()
)

episode_speakers (
  id UUID PRIMARY KEY,
  episode_id UUID REFERENCES episodes ON DELETE CASCADE,
  speaker_id TEXT NOT NULL,        -- 'UNKNOWN' or a real diarized label: 'SPEAKER_00', 'SPEAKER_01', etc.
  display_name TEXT,               -- mutable; only location of display name
  name_inferred BOOLEAN DEFAULT false,
  name_confirmed BOOLEAN DEFAULT false,
  confidence TEXT,                 -- 'high' | 'medium' | 'low' | NULL (not inferred)
  UNIQUE(episode_id, speaker_id)
)

transcript_segments (
  id UUID PRIMARY KEY,
  episode_id UUID REFERENCES episodes ON DELETE CASCADE,
  speaker_id TEXT NOT NULL,        -- 'UNKNOWN' or a real diarized label; join to episode_speakers for display_name
  text TEXT NOT NULL,
  start_ms INT NOT NULL, end_ms INT NOT NULL, sequence_order INT NOT NULL
)
-- No display_name column

chunks (
  id UUID PRIMARY KEY,
  episode_id UUID REFERENCES episodes ON DELETE CASCADE,
  parent_id UUID REFERENCES chunks,
  chunk_level TEXT NOT NULL,       -- 'parent' | 'leaf'
  speaker_id TEXT NOT NULL,        -- 'UNKNOWN' or a real diarized label; join to episode_speakers for display_name
  text TEXT NOT NULL,
  start_ms INT NOT NULL, end_ms INT NOT NULL,
  token_count INT,
  embedding vector(768),
  created_at TIMESTAMPTZ DEFAULT now()
)
-- No display_name column

CREATE INDEX ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX ix_episodes_pipeline_status_status_changed_at ON episodes (pipeline_status, status_changed_at);  -- GET /queue grouping + since window
```

**Design principles:**
- `display_name` exists only in `episode_speakers`
- `transcript_segments` and `chunks` store `speaker_id` only
- `VectorStore.search()` returns raw results with `speaker_id`; `ResultHydrator` resolves names
- All cascade deletes defined
- `FeedResponse.latest_episode_published_at` is not a stored column — derived via `MAX(episodes.published_at)` grouped by feed (`feed_service.list_feeds()`, `feed_service.get_feed_stats()`); always recomputed at read time
- `pipeline_stage` was dropped in Phase 21 — `pipeline_status` alone carries the stage (`DOWNLOADING` through `EMBEDDING`).
- Episode status writes are compare-and-set: queue claims, resets, and job-bound worker writes put the expected `ingestion_job_id` (and, for claims/resets, the expected status) in the `WHERE` clause, so a superseded job's write matches no row instead of overwriting newer state. Data writes are guarded by `PipelineStatusService.still_owns`, which takes `SELECT … FOR SHARE` on the episode row until the write commits, so a reset or claim can't interleave with one. `status_changed_at` is bumped only on a real status change (`CASE … IS DISTINCT FROM`), so progress updates within a stage don't reset the `possibly_stuck` timer.
- Only `READY` counts as complete. Partial data left by an `ERROR` run stays in place until the next Retry or Reset wipes it; transcript and speaker routes refuse non-`READY` episodes with `409`, and retrieval (`PgvectorStore.search`) and the chat tools filter on `pipeline_status = 'READY'`.

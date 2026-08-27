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
  pipeline_status TEXT NOT NULL DEFAULT 'PENDING',
  pipeline_stage TEXT,
  pipeline_progress FLOAT,
  pipeline_error TEXT,
  ingestion_job_id TEXT,
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
```

**Design principles:**
- `display_name` exists only in `episode_speakers`
- `transcript_segments` and `chunks` store `speaker_id` only
- `VectorStore.search()` returns raw results with `speaker_id`; `ResultHydrator` resolves names
- All cascade deletes defined
- `FeedResponse.latest_episode_published_at` is not a stored column — derived via `MAX(episodes.published_at)` grouped by feed (`feed_service.list_feeds()`, `feed_service.get_feed_stats()`); always recomputed at read time

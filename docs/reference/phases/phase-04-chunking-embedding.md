# Phase 4 — Chunking + Embedding

> Moved from IMPLEMENTATION_PLAN.md. Status: ✅ Complete. Git tag: `v0.1.4-chunking`.
> See IMPLEMENTATION_PLAN.md's Phase Overview table for the one-line summary; see ARCHITECTURE.md for current system design.
> Note: the `_merge_short_segments` logic described here was later reworked to be speaker-aware in Phase 14 — see that phase's file.

**Goal:** Convert confirmed transcripts into retrievable vector chunks. Speaker identity linked via `speaker_id`.

### Tasks

#### 4.1 Chunker (`src/ingestion/chunker.py`) 🤖

**Step A — Speaker-boundary splits:**
```python
def split_by_speaker(segments: list[TranscriptSegment]) -> list[SpeakerBlock]:
    # Group consecutive segments with same speaker_id
    # Each contiguous run = one SpeakerBlock
    # Preserve: speaker_id, combined text, min(start_ms), max(end_ms)
```

**Step B — Topic segmentation via embedding similarity:**
```python
async def segment_by_topic(blocks: list[SpeakerBlock], embedder) -> list[TopicSegment]:
    embeddings = await embedder.embed([b.text for b in blocks])
    boundaries = []
    for i in range(1, len(embeddings)):
        similarity = cosine_similarity(embeddings[i-1], embeddings[i])
        if similarity < settings.topic_similarity_threshold:
            boundaries.append(i)
    # Group blocks into topic segments
```

**Step B.5 — Merge short segments:**
After topic segmentation, merge any `TopicSegment` below `min_tokens` into its predecessor. This prevents filler turns ("yes yes yes", short affirmations) from becoming standalone chunks with meaningless embeddings.

```python
def _merge_short_segments(self, segments: list[TopicSegment]) -> list[TopicSegment]:
    # Merge segments below self._min_tokens into predecessor
    # Edge case: first segment is short → merge forward into second
```

`chunk_min_tokens: int = 20` in `Settings`. Not an environment variable — configure in code if adjustment needed.

**Step C — Hierarchical chunk construction:**
```python
def build_chunks(segments: list[TopicSegment], episode_id: UUID) -> list[Chunk]:
    chunks = []
    for segment in segments:
        parent = Chunk(
            episode_id=episode_id,
            chunk_level="parent",
            speaker_id=segment.dominant_speaker_id,
            text=segment.full_text,
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
        )
        chunks.append(parent)
        # Sliding window leaf chunks
        for window in sliding_window(segment.text, settings.chunk_size_tokens, settings.chunk_overlap_tokens):
            leaf = Chunk(
                parent_id=parent.id,
                chunk_level="leaf",
                speaker_id=segment.dominant_speaker_id,   # speaker_id, NOT display_name
                ...
            )
            chunks.append(leaf)
    return chunks
```

Token counting: `tiktoken` (cl100k_base) for consistency across models.

**Chunker constructor:**
```python
class Chunker:
    def __init__(
        self,
        chunk_size_tokens: int,
        chunk_overlap_tokens: int,
        min_tokens: int = 20,
        topic_similarity_threshold: float = 0.75,
        tokenizer: Callable[[str], int] | None = None,
    ): ...
```

#### 4.2 Embedder (`src/ingestion/embedder.py`)
Uses `EmbeddingClient` Protocol — not `AsyncOpenAI` directly. Embed leaf chunks only. Batch size 100, retry with exponential backoff.

```python
class Embedder:
    def __init__(self, embedding_client: EmbeddingClient): ...

    async def embed(self, chunks: list[Chunk]) -> list[Chunk]:
        # Batch embed, attach vectors, return
```

#### 4.3 VectorStore (`src/storage/vector_store.py`) 🤖
Define the `VectorStore` Protocol now — `PgvectorStore` is the v1 implementation.

```python
@dataclass
class SearchFilters:
    feed_ids: list[UUID] | None = None    # multi-feed scope; uses .in_() query
    episode_ids: list[UUID] | None = None
    speaker_id: str | None = None

class PgvectorStore:
    async def search(
        self, embedding, filters: SearchFilters, top_k: int, db: AsyncSession
    ) -> list[RawChunkResult]: ...

    async def upsert(self, chunks: list[ChunkRecord], db: AsyncSession) -> None: ...
```

`RawChunkResult` contains `speaker_id`, not `display_name`. Hydration happens in `ResultHydrator` (Phase 5). `parent_text` is fetched alongside each leaf result in a single batched query.

#### 4.4 Chunk storage
Write to `chunks` table. Note: `speaker_id` stored, `display_name` resolved at read time via join on `episode_speakers`. Update episode `pipeline_status` → `READY`.

#### 4.5 Tests 🤖
Write these first (TDD for the chunker — it's pure logic, fast to test):

```python
# tests/unit/test_chunker.py
def test_speaker_boundaries_split_on_speaker_change()
def test_same_speaker_consecutive_segments_grouped()
def test_topic_threshold_creates_boundary()
def test_leaf_chunks_within_token_limit()
def test_leaf_chunks_reference_parent_id()
def test_chunks_store_speaker_id_not_display_name()
def test_timestamps_min_max_preserved()
def test_short_segments_merged_not_orphaned()
def test_short_segments_merged_into_predecessor()
def test_single_speaker_episode_produces_chunks()
```

### Phase 4 Done When
- Ingesting with fixture transcript produces chunks in pgvector
- `chunks.speaker_id` contains "SPEAKER_00", never a display name
- Short segments below `min_tokens` are merged — no standalone filler chunks
- All chunker tests pass
- Git tag: `v0.1.4-chunking`

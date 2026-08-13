# tests/integration/test_vector_store.py

import math
import uuid
import pytest

from sqlalchemy import text

from src.storage.vector_store import PgvectorStore, SearchFilters
from src.models.db import Feed, Episode, Chunk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EMBEDDING_DIM = 768


def make_embedding(similarity: float, dim: int = EMBEDDING_DIM) -> list[float]:
    """
    Builds a unit vector whose cosine similarity to QUERY_EMBEDDING (all mass
    on dimension 0) is exactly `similarity`, by splitting mass between
    dimension 0 and dimension 1. Both vectors are unit length, so cosine
    similarity reduces to the dot product -- this gives fully predictable
    similarity scores instead of relying on real embedding data.
    """
    v0 = similarity
    v1 = math.sqrt(max(0.0, 1 - similarity ** 2))
    vec = [0.0] * dim
    vec[0] = v0
    vec[1] = v1
    return vec


QUERY_EMBEDDING = make_embedding(1.0)

@pytest.fixture(autouse=True)
async def _disable_ann_index(db_session):
    """
    chunks_embedding_idx_leaf (ivfflat) is built by create_all() before any
    test data exists, so every test starts with an index trained on zero
    vectors -- its clusters are arbitrary, not a real partition of the
    vector space. Every search() query orders by cosine_distance, which
    Postgres' planner strongly prefers to satisfy via that index, so an
    untrained approximate index silently misses legitimate matches
    depending on which arbitrary cluster a given vector lands in. That's a
    real property of ivfflat at tiny/untrained scale, not a bug in
    PgvectorStore.search() -- production tables are well past this problem
    by the time lists=100 clustering means anything. Forcing sequential
    scan here makes these tests exercise the actual filter/order/limit
    logic against an exact search instead.

    SET, not SET LOCAL: these tests commit partway through (chunks are
    added, then committed, before search() runs), and SET LOCAL only lasts
    for the current transaction -- it would revert right after that first
    commit, before the search query even ran.
    """
    await db_session.execute(text("SET enable_indexscan = off"))
    await db_session.execute(text("SET enable_bitmapscan = off"))


async def make_feed(db_session, **overrides) -> Feed:
    feed = Feed(
        id=uuid.uuid4(),
        rss_url=overrides.get("rss_url", f"https://example.com/{uuid.uuid4()}.rss"),
        title=overrides.get("title", "Synthetic Minds"),
    )
    db_session.add(feed)
    await db_session.flush()
    return feed


async def make_episode(db_session, feed: Feed, **overrides) -> Episode:
    episode = Episode(
        id=uuid.uuid4(),
        feed_id=feed.id,
        guid=str(uuid.uuid4()),
        title=overrides.get("title", "Test Episode"),
        pipeline_status=overrides.get("pipeline_status", "READY"),
    )
    db_session.add(episode)
    await db_session.flush()
    return episode


def make_chunk(
    episode: Episode,
    chunk_level: str = "leaf",
    speaker_id: str = "SPEAKER_00",
    text: str = "Some leaf text.",
    embedding: list[float] | None = None,
    parent_id: uuid.UUID | None = None,
    start_ms: int = 0,
    end_ms: int = 1000,
) -> Chunk:
    return Chunk(
        id=uuid.uuid4(),
        episode_id=episode.id,
        parent_id=parent_id,
        chunk_level=chunk_level,
        speaker_id=speaker_id,
        text=text,
        start_ms=start_ms,
        end_ms=end_ms,
        token_count=len(text.split()),
        embedding=embedding,
    )


# ---------------------------------------------------------------------------
# chunk_level / embedding presence filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_excludes_parent_chunks(db_session):
    """Parent chunks must never surface, even if they'd win on similarity --
    proves the chunk_level filter is load-bearing, not just a side effect of
    parents lacking embeddings."""
    feed = await make_feed(db_session)
    episode = await make_episode(db_session, feed)

    parent = make_chunk(
        episode, chunk_level="parent", text="Full topic segment.",
        embedding=QUERY_EMBEDDING,
    )
    leaf = make_chunk(
        episode, chunk_level="leaf", parent_id=parent.id, text="Leaf window.",
        embedding=make_embedding(0.5),
    )
    db_session.add_all([parent, leaf])
    await db_session.commit()

    store = PgvectorStore()
    results = await store.search(QUERY_EMBEDDING, SearchFilters(), top_k=5, db=db_session)

    assert len(results) == 1
    assert results[0].chunk_id == leaf.id


@pytest.mark.asyncio
async def test_search_excludes_null_embedding_chunks(db_session):
    feed = await make_feed(db_session)
    episode = await make_episode(db_session, feed)

    unembedded = make_chunk(episode, embedding=None, text="Never embedded.")
    embedded = make_chunk(episode, embedding=make_embedding(0.8), text="Embedded leaf.")
    db_session.add_all([unembedded, embedded])
    await db_session.commit()

    store = PgvectorStore()
    results = await store.search(QUERY_EMBEDDING, SearchFilters(), top_k=5, db=db_session)

    assert len(results) == 1
    assert results[0].chunk_id == embedded.id


# ---------------------------------------------------------------------------
# top_k / ordering / score
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_respects_top_k(db_session):
    feed = await make_feed(db_session)
    episode = await make_episode(db_session, feed)

    chunks = [
        make_chunk(episode, embedding=make_embedding(s), text=f"Chunk {s}")
        for s in [0.9, 0.8, 0.7, 0.6, 0.5]
    ]
    db_session.add_all(chunks)
    await db_session.commit()

    store = PgvectorStore()
    results = await store.search(QUERY_EMBEDDING, SearchFilters(), top_k=2, db=db_session)

    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_orders_by_similarity_descending(db_session):
    feed = await make_feed(db_session)
    episode = await make_episode(db_session, feed)

    low = make_chunk(episode, embedding=make_embedding(0.3), text="Low similarity.")
    high = make_chunk(episode, embedding=make_embedding(0.95), text="High similarity.")
    mid = make_chunk(episode, embedding=make_embedding(0.6), text="Mid similarity.")
    db_session.add_all([low, high, mid])
    await db_session.commit()

    store = PgvectorStore()
    results = await store.search(QUERY_EMBEDDING, SearchFilters(), top_k=5, db=db_session)

    assert [r.chunk_id for r in results] == [high.id, mid.id, low.id]


@pytest.mark.asyncio
async def test_search_similarity_score_matches_cosine_similarity(db_session):
    feed = await make_feed(db_session)
    episode = await make_episode(db_session, feed)

    chunk = make_chunk(episode, embedding=make_embedding(0.75), text="Known similarity.")
    db_session.add(chunk)
    await db_session.commit()

    store = PgvectorStore()
    results = await store.search(QUERY_EMBEDDING, SearchFilters(), top_k=5, db=db_session)

    assert results[0].similarity_score == pytest.approx(0.75, abs=1e-4)


# ---------------------------------------------------------------------------
# episode_ids / feed_ids filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_filters_by_episode_ids(db_session):
    feed = await make_feed(db_session)
    episode_a = await make_episode(db_session, feed)
    episode_b = await make_episode(db_session, feed)

    chunk_a = make_chunk(episode_a, embedding=make_embedding(0.9), text="Episode A chunk.")
    chunk_b = make_chunk(episode_b, embedding=make_embedding(0.9), text="Episode B chunk.")
    db_session.add_all([chunk_a, chunk_b])
    await db_session.commit()

    store = PgvectorStore()
    results = await store.search(
        QUERY_EMBEDDING,
        SearchFilters(episode_ids=[episode_a.id]),
        top_k=5,
        db=db_session,
    )

    assert len(results) == 1
    assert results[0].chunk_id == chunk_a.id


@pytest.mark.asyncio
async def test_search_filters_by_feed_ids(db_session):
    feed_a = await make_feed(db_session)
    feed_b = await make_feed(db_session)
    episode_a = await make_episode(db_session, feed_a)
    episode_b = await make_episode(db_session, feed_b)

    chunk_a = make_chunk(episode_a, embedding=make_embedding(0.9), text="Feed A chunk.")
    chunk_b = make_chunk(episode_b, embedding=make_embedding(0.9), text="Feed B chunk.")
    db_session.add_all([chunk_a, chunk_b])
    await db_session.commit()

    store = PgvectorStore()
    results = await store.search(
        QUERY_EMBEDDING,
        SearchFilters(feed_ids=[feed_a.id]),
        top_k=5,
        db=db_session,
    )

    assert len(results) == 1
    assert results[0].chunk_id == chunk_a.id


# ---------------------------------------------------------------------------
# speaker_pairs -- the actual regression scenario
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_speaker_pairs_isolates_same_label_across_episodes(db_session):
    """Two different episodes both have a chunk labeled SPEAKER_00 -- these
    are two different people, since speaker_id is episode-scoped. Filtering
    by one specific (episode_id, speaker_id) pair must not leak the other
    episode's same-labeled chunk. This is the exact bug the speaker_pairs
    filter replaced the old single speaker_id filter to fix."""
    feed = await make_feed(db_session)
    episode_a = await make_episode(db_session, feed)
    episode_b = await make_episode(db_session, feed)

    chunk_a = make_chunk(
        episode_a, speaker_id="SPEAKER_00", embedding=make_embedding(0.9),
        text="Episode A's SPEAKER_00.",
    )
    chunk_b = make_chunk(
        episode_b, speaker_id="SPEAKER_00", embedding=make_embedding(0.9),
        text="Episode B's SPEAKER_00 -- a different person.",
    )
    db_session.add_all([chunk_a, chunk_b])
    await db_session.commit()

    store = PgvectorStore()
    results = await store.search(
        QUERY_EMBEDDING,
        SearchFilters(speaker_pairs=[(episode_a.id, "SPEAKER_00")]),
        top_k=5,
        db=db_session,
    )

    assert len(results) == 1
    assert results[0].chunk_id == chunk_a.id


@pytest.mark.asyncio
async def test_search_speaker_pairs_matches_multiple_pairs(db_session):
    """The same person can carry a different label in each episode -- Marcus
    is SPEAKER_00 in one episode and SPEAKER_01 in another. A name resolving
    to multiple pairs must match all of them, and only them."""
    feed = await make_feed(db_session)
    episode_a = await make_episode(db_session, feed)
    episode_b = await make_episode(db_session, feed)

    marcus_in_a = make_chunk(
        episode_a, speaker_id="SPEAKER_00", embedding=make_embedding(0.9),
        text="Marcus in episode A.",
    )
    marcus_in_b = make_chunk(
        episode_b, speaker_id="SPEAKER_01", embedding=make_embedding(0.9),
        text="Marcus in episode B.",
    )
    someone_else_in_b = make_chunk(
        episode_b, speaker_id="SPEAKER_00", embedding=make_embedding(0.9),
        text="A different person in episode B.",
    )
    db_session.add_all([marcus_in_a, marcus_in_b, someone_else_in_b])
    await db_session.commit()

    store = PgvectorStore()
    results = await store.search(
        QUERY_EMBEDDING,
        SearchFilters(speaker_pairs=[
            (episode_a.id, "SPEAKER_00"),
            (episode_b.id, "SPEAKER_01"),
        ]),
        top_k=5,
        db=db_session,
    )

    result_ids = {r.chunk_id for r in results}
    assert result_ids == {marcus_in_a.id, marcus_in_b.id}


# ---------------------------------------------------------------------------
# parent_text resolution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_returns_parent_text_from_parent_chunk(db_session):
    feed = await make_feed(db_session)
    episode = await make_episode(db_session, feed)

    parent = make_chunk(episode, chunk_level="parent", text="The full topic segment text.", embedding=None)
    db_session.add(parent)
    await db_session.flush()

    leaf = make_chunk(episode, chunk_level="leaf", parent_id=parent.id, text="A leaf window.", embedding=make_embedding(0.9))
    db_session.add(leaf)
    await db_session.commit()

    store = PgvectorStore()
    results = await store.search(QUERY_EMBEDDING, SearchFilters(), top_k=5, db=db_session)

    assert len(results) == 1
    assert results[0].parent_text == "The full topic segment text."


@pytest.mark.asyncio
async def test_search_parent_text_none_when_no_parent(db_session):
    feed = await make_feed(db_session)
    episode = await make_episode(db_session, feed)

    orphan_leaf = make_chunk(episode, chunk_level="leaf", parent_id=None, text="No parent.", embedding=make_embedding(0.9))
    db_session.add(orphan_leaf)
    await db_session.commit()

    store = PgvectorStore()
    results = await store.search(QUERY_EMBEDDING, SearchFilters(), top_k=5, db=db_session)

    assert len(results) == 1
    assert results[0].parent_text is None
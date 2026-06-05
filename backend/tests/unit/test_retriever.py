# tests/unit/test_retriever.py

import uuid
import pytest
from src.query.retriever import Retriever
from src.query.result_hydrator import ResultHydrator, ChunkResult
from src.storage.vector_store import SearchFilters, RawChunkResult


# ~~~~~~ Helpers ~~~~~~

EPISODE_ID = uuid.uuid4()
FEED_ID = uuid.uuid4()


def make_raw(episode_id=None, speaker_id="SPEAKER_00") -> RawChunkResult:
    return RawChunkResult(
        chunk_id=uuid.uuid4(),
        text="Interesting content about machine learning.",
        parent_text="Broader context about ML.",
        speaker_id=speaker_id,
        episode_id=episode_id or EPISODE_ID,
        start_ms=60_000,
        end_ms=90_000,
        similarity_score=0.88,
    )


def make_chunk_result(episode_id=None, display_name="Ada Sinclair") -> ChunkResult:
    eid = episode_id or EPISODE_ID
    return ChunkResult(
        chunk_id=str(uuid.uuid4()),
        text="Interesting content about machine learning.",
        parent_text="Broader context about ML.",
        episode_id=str(eid),
        episode_title="Synthetic Minds Ep. 1",
        display_name=display_name,
        timestamp_display="1:00",
        start_ms=60_000,
        end_ms=90_000,
        similarity_score=0.88,
    )


class MockEmbeddingClient:
    def __init__(self, vector: list[float] | None = None):
        self.last_texts = None
        self._vector = vector or [0.1] * 768

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.last_texts = texts
        return [self._vector]


class MockVectorStore:
    def __init__(self, results: list[RawChunkResult] | None = None):
        self.last_embedding = None
        self.last_filters = None
        self.last_top_k = None
        self._results = results or []

    async def search(self, embedding, filters, top_k=5, db=None):
        self.last_embedding = embedding
        self.last_filters = filters
        self.last_top_k = top_k
        return self._results


class MockHydrator:
    def __init__(self, results: list[ChunkResult] | None = None):
        self.last_raw = None
        self._results = results or []

    async def hydrate(self, raw, db):
        self.last_raw = raw
        return self._results


class MockDb:
    pass


# ~~~~~~ Tests ~~~~~~

@pytest.mark.asyncio
async def test_retriever_embeds_query():
    embedder = MockEmbeddingClient()
    retriever = Retriever(
        embedding_client=embedder,
        vector_store=MockVectorStore(),
        hydrator=MockHydrator(),
    )
    await retriever.search("what is reinforcement learning?", SearchFilters(), MockDb())
    assert embedder.last_texts == ["what is reinforcement learning?"]


@pytest.mark.asyncio
async def test_retriever_passes_embedding_to_vector_store():
    vector = [0.5] * 768
    embedder = MockEmbeddingClient(vector=vector)
    store = MockVectorStore()
    retriever = Retriever(
        embedding_client=embedder,
        vector_store=store,
        hydrator=MockHydrator(),
    )
    await retriever.search("test query", SearchFilters(), MockDb())
    assert store.last_embedding == vector


@pytest.mark.asyncio
async def test_retriever_passes_filters_to_vector_store():
    store = MockVectorStore()
    filters = SearchFilters(feed_id=FEED_ID, episode_ids=[EPISODE_ID])
    retriever = Retriever(
        embedding_client=MockEmbeddingClient(),
        vector_store=store,
        hydrator=MockHydrator(),
    )
    await retriever.search("test query", filters, MockDb())
    assert store.last_filters is filters


@pytest.mark.asyncio
async def test_retriever_passes_top_k_to_vector_store():
    store = MockVectorStore()
    retriever = Retriever(
        embedding_client=MockEmbeddingClient(),
        vector_store=store,
        hydrator=MockHydrator(),
    )
    await retriever.search("test query", SearchFilters(), MockDb(), top_k=10)
    assert store.last_top_k == 10


@pytest.mark.asyncio
async def test_retriever_passes_raw_results_to_hydrator():
    raw = [make_raw(), make_raw()]
    store = MockVectorStore(results=raw)
    hydrator = MockHydrator()
    retriever = Retriever(
        embedding_client=MockEmbeddingClient(),
        vector_store=store,
        hydrator=hydrator,
    )
    await retriever.search("test query", SearchFilters(), MockDb())
    assert hydrator.last_raw == raw


@pytest.mark.asyncio
async def test_retriever_returns_hydrated_results():
    hydrated = [make_chunk_result(), make_chunk_result()]
    retriever = Retriever(
        embedding_client=MockEmbeddingClient(),
        vector_store=MockVectorStore(),
        hydrator=MockHydrator(results=hydrated),
    )
    results = await retriever.search("test query", SearchFilters(), MockDb())
    assert results == hydrated


@pytest.mark.asyncio
async def test_retriever_returns_empty_list_when_no_results():
    retriever = Retriever(
        embedding_client=MockEmbeddingClient(),
        vector_store=MockVectorStore(results=[]),
        hydrator=MockHydrator(results=[]),
    )
    results = await retriever.search("test query", SearchFilters(), MockDb())
    assert results == []


@pytest.mark.asyncio
async def test_retriever_default_top_k_is_five():
    store = MockVectorStore()
    retriever = Retriever(
        embedding_client=MockEmbeddingClient(),
        vector_store=store,
        hydrator=MockHydrator(),
    )
    await retriever.search("test query", SearchFilters(), MockDb())
    assert store.last_top_k == 5
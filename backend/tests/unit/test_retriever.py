# tests/unit/test_retriever.py

import uuid
import pytest
from src.query.retriever import Retriever
from src.query.result_hydrator import ResultHydrator, ChunkResult
from src.storage.vector_store import SearchFilters, RawChunkResult
from tests.conftest import MockVectorStore, MockHydrator, MockEmbeddingClient, make_chunk_result


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
    filters = SearchFilters(feed_ids=[FEED_ID], episode_ids=[EPISODE_ID])
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
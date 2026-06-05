# src/query/retriever.py

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.llm.base import EmbeddingClient
from src.storage.vector_store import VectorStore, SearchFilters
from src.query.result_hydrator import ResultHydrator, ChunkResult

class Retriever:
    """
    Composes EmbeddingClient, VectorStore, and ResultHydrator into a single
    search operation. Callers pass a natural language query and get back
    hydrated ChunkResults — display names resolved, timestamps formatted.
    """

    def __init__(
        self,
        embedding_client: EmbeddingClient,
        vector_store: VectorStore,
        hydrator: ResultHydrator,
    ) -> None:
        self._embedding_client = embedding_client
        self._vector_store = vector_store
        self._hydrator = hydrator

    async def search(
        self,
        query: str,
        filters: SearchFilters,
        db: AsyncSession,
        top_k: int = 5,
    ) -> list[ChunkResult]:
        embeddings = await self._embedding_client.embed([query])
        raw = await self._vector_store.search(
            embedding=embeddings[0],
            filters=filters,
            top_k=top_k,
            db=db,
        )
        return await self._hydrator.hydrate(raw, db)
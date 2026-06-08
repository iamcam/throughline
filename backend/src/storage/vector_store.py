# src/storage/vector_store.py

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import Chunk
from src.ingestion.chunker import ChunkData


# ~~~~~~ Search filters ~~~~~~

@dataclass
class SearchFilters:
    """
    All fields optional. Unset fields are not applied as WHERE clauses.
    feed_id requires a join to episodes — handled in PgvectorStore.search().
    """
    feed_ids: list[uuid.UUID] | None = None
    episode_ids: list[uuid.UUID] | None = None
    speaker_id: str | None = None


# ---------------------------------------------------------------------------
# Raw result — speaker_id only, no display_name
# Hydration to display_name happens in ResultHydrator (Phase 5)
# ---------------------------------------------------------------------------

@dataclass
class RawChunkResult:
    chunk_id: uuid.UUID
    text: str
    parent_text: str | None     # fetched alongside leaf for LLM context
    speaker_id: str
    episode_id: uuid.UUID
    start_ms: int
    end_ms: int
    similarity_score: float



# ~~~~~~ Protocol ~~~~~~

@runtime_checkable
class VectorStore(Protocol):
    async def search(
        self,
        embedding: list[float],
        filters: SearchFilters,
        top_k: int = 5,
        db: AsyncSession = ...,
    ) -> list[RawChunkResult]: ...

    async def upsert(
        self,
        chunks: list[ChunkData],
        db: AsyncSession,
    ) -> None: ...



# ~~~~~~ PgvectorStore ~~~~~~

class PgvectorStore:
    """
    PostgreSQL + pgvector implementation of VectorStore.
    Searches leaf chunks only - the partial index on chunk_level='leaf'
    ensures the vector index is never consulted for parent chunks.
    """

    async def search(
        self,
        embedding: list[float],
        filters: SearchFilters,
        top_k: int = 5,
        db: AsyncSession = None,
    ) -> list[RawChunkResult]:
        from sqlalchemy import and_
        from src.models.db import Episode

        conditions = [
            Chunk.chunk_level == "leaf",
            Chunk.embedding.isnot(None),
        ]

        if filters.episode_ids:
            conditions.append(Chunk.episode_id.in_(filters.episode_ids))

        if filters.speaker_id:
            conditions.append(Chunk.speaker_id == filters.speaker_id)

        stmt = (
            select(
                Chunk,
                Chunk.embedding.cosine_distance(embedding).label("distance"),
            )
            .where(and_(*conditions))
            .order_by(Chunk.embedding.cosine_distance(embedding))
            .limit(top_k)
        )

        if filters.feed_ids:
            stmt = stmt.join(Episode, Chunk.episode_id == Episode.id).where(
                Episode.feed_id.in_(filters.feed_ids)
            )

        result = await db.execute(stmt)
        rows = result.fetchall()

        # Fetch parent text in a single query by primary key
        parent_ids = [row.Chunk.parent_id for row in rows if row.Chunk.parent_id]
        parent_texts: dict[uuid.UUID, str] = {}

        if parent_ids:
            parent_result = await db.execute(
                select(Chunk.id, Chunk.text).where(Chunk.id.in_(parent_ids))
            )
            parent_texts = {row.id: row.text for row in parent_result.fetchall()}

        return [
            RawChunkResult(
                chunk_id=row.Chunk.id,
                text=row.Chunk.text,
                parent_text=parent_texts.get(row.Chunk.parent_id),
                speaker_id=row.Chunk.speaker_id,
                episode_id=row.Chunk.episode_id,
                start_ms=row.Chunk.start_ms,
                end_ms=row.Chunk.end_ms,
                similarity_score=1 - row.distance,
            )
            for row in rows
        ]

    async def upsert(
        self,
        chunks: list[ChunkData],
        db: AsyncSession,
    ) -> None:
        if not chunks:
            return

        # Clear existing chunks for these episodes before reinserting.
        # Simpler than true upsert and correct for re-ingestion — the whole
        # chunk set for an episode is always replaced together.
        episode_ids = {chunk.episode_id for chunk in chunks}
        await db.execute(
            delete(Chunk).where(Chunk.episode_id.in_(episode_ids))
        )

        for chunk in chunks:
            db.add(Chunk(
                id=chunk.id,
                episode_id=chunk.episode_id,
                parent_id=chunk.parent_id,
                chunk_level=chunk.chunk_level,
                speaker_id=chunk.speaker_id,
                text=chunk.text,
                start_ms=chunk.start_ms,
                end_ms=chunk.end_ms,
                token_count=chunk.token_count,
                embedding=chunk.embedding,
            ))

        await db.commit()
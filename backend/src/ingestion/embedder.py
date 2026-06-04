# src/ingestion/embedder.py

from __future__ import annotations

import logging
from dataclasses import replace

from src.ingestion.chunker import ChunkData
from src.llm.base import EmbeddingClient

logger = logging.getLogger(__name__)


class Embedder:
    """
    Embeds leaf chunks using the injected EmbeddingClient.

    Parent chunks pass through with embedding=None -- they are never
    searched directly and do not need vectors.

    Processes leaves in batches to avoid oversized requests to the
    embedding endpoint.
    """

    def __init__(self, embedding_client: EmbeddingClient, batch_size: int = 100):
        self._client = embedding_client
        self._batch_size = batch_size

    async def embed(self, chunks: list[ChunkData]) -> list[ChunkData]:
        """
        Returns the same chunk list with embedding populated on leaf chunks.
        Order is preserved. Parent chunks are returned unchanged.
        """
        leaves = [(i, chunk) for i, chunk in enumerate(chunks) if chunk.chunk_level == "leaf"]

        if not leaves:
            logger.debug("No leaf chunks to embed")
            return chunks

        # ~~~~~~ Batch embedding ~~~~~~

        result = list(chunks)  # shallow copy -- we replace individual items

        for batch_start in range(0, len(leaves), self._batch_size):
            batch = leaves[batch_start : batch_start + self._batch_size]
            texts = [chunk.text for _, chunk in batch]

            logger.debug("Embedding batch of %d leaf chunks", len(texts))
            vectors = await self._client.embed(texts)

            for (original_index, chunk), vector in zip(batch, vectors):
                result[original_index] = replace(chunk, embedding=vector)

        return result

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embeds arbitrary texts. Used by the pipeline for segment embeddings."""
        return await self._client.embed(texts)

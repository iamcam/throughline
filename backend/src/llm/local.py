# src/llm/local.py

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


def resolve_device() -> str:
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class LocalEmbeddingClient:
    """
    Embedding client backed by a local sentence-transformers model.
    Selected when EMBEDDING_BASE_URL="local" -- see src/shared/llm.py.
    """

    def __init__(self, model_name: str, device: str | None = None):
        """
        The model is loaded once, eagerly, at init, and kept warm for the life of the process.
        """
        from sentence_transformers import SentenceTransformer

        self._device = device or resolve_device()
        logger.info(f"Loading local embedding model {model_name!r} (device={self._device})")
        self._model = SentenceTransformer(model_name, device=self._device)
        self._executor = ThreadPoolExecutor(max_workers=1)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_running_loop()
        vectors = await loop.run_in_executor(self._executor, self._encode, texts)
        return vectors.tolist()

    def _encode(self, texts: list[str]):
        """
        Encodes the texts to emmbeddings.

        This is a blocking call, so it's offloaded to a small thread
        pool rather than run directly on the event loop. Runs in both the API
        process (query-time embedding) and the worker process (ingestion), so
        it can't assume a ProcessPoolExecutor is available.
        """
        return self._model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
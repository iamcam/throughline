# src/ingestion/audio_downloader.py
import asyncio
import logging
from pathlib import Path
from uuid import UUID

import httpx
from opentelemetry import trace

from src.config import get_settings
from src.telemetry.tracer import tracer

logger = logging.getLogger(__name__)


class AudioDownloader:
    def __init__(self, storage_path: str):
        self._storage_path = Path(storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)

    async def  download(
            self,
            episode_id: UUID,
            audio_url: str,
            on_progress = None #async callable: (progress:float) -> None
    ) -> str:
        """
        Download audio file for episode. Returns local file path.
        on_progress is called with a 0.0-1.0 float as download progresses.
        """
        suffix = Path(audio_url.split("?")[0]).suffix or ".mp3"
        dest = self._storage_path/f"{episode_id}{suffix}"

        if dest.exists():
            return str(dest)

        with tracer.start_as_current_span("audio_download") as span:
            span.set_attribute("openinference.span.kind", "CHAIN")

            span.set_attribute("episode.id", str(episode_id))
            span.set_attribute("audio.url", audio_url)

            try:
                async with httpx.AsyncClient(follow_redirects=True, timeout=300) as client:
                    async with client.stream("GET", audio_url) as response:
                        response.raise_for_status()

                        total = int(response.headers.get("content-length", 0))
                        if total:
                            span.set_attribute("audio.size_bytes", total)

                        received = 0

                        tmp = dest.with_suffix(".tmp")
                        try:
                            with open(tmp, "wb") as f:
                                async for chunk in response.aiter_bytes(chunk_size=65536):
                                    f.write(chunk)
                                    received += len(chunk)

                                    if on_progress and total:
                                        progress = received / total
                                        await on_progress(progress)
                            tmp.rename(dest)

                        except Exception:
                            if tmp.exists():
                                tmp.unlink()
                            raise
                span.set_attribute("audio.bytes_received", received)
                span.set_status(trace.StatusCode.OK)
            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, str(e))
                raise

        return str(dest)

    async def delete(self, path: str) -> None:
        """Remove a downloaded audio file. Safe to call even if it's already gone."""
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as e:
            logger.warning(f"Failed to delete audio file {path}: {e}")
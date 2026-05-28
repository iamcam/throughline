# src/ingestion/audio_downloader.py
import asyncio
from pathlib import Path
from uuid import UUID

import httpx

from src.config import get_settings


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

        async with httpx.AsyncClient(follow_redirects=True, timeout=300) as client:
            async with client.stream("GET", audio_url) as response:
                response.raise_for_status()

                total = int(response.headers.get("content-length", 0))
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

        return str(dest)
# src/query/result_hydrator.py
from __future__ import annotations
from dataclasses import dataclass
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import Episode, EpisodeSpeaker
from src.storage.vector_store import RawChunkResult

@dataclass
class ChunkResult:
    chunk_id: str
    text: str
    parent_text: str | None
    episode_id: str
    episode_title: str | None
    audio_url: str | None
    display_name: str | None #from episode_speakers; None == unknown
    timestamp_display: str # human-readable
    start_ms: int
    end_ms: int
    similarity_score: float

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "parent_text": self.parent_text,
            "episode_id": self.episode_id,
            "episode_title": self.episode_title,
            "audio_url": self.audio_url,
            "display_name": self.display_name,
            "timestamp_display": self.timestamp_display,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "similarity_score": round(self.similarity_score, 4),
        }


# ~~~~~~ Helpers ~~~~~~

def _format_timestamp(ms: int) -> str:
    """Convert milliseconds to H:MM:SS or M:SS string."""
    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"



# ~~~~~~ ResultHydrator ~~~~~~

class ResultHydrator:
    """
    Resolves speaker_id --> display_name and episode_id --> title for a batch fo RawChunkResults.
    All DB lookups are batched - one query per table rather than one per result row.
    """

    async def hydrate(
        self,
        raw: list[RawChunkResult],
        db: AsyncSession,
    ) -> list[ChunkResult]:
        if not raw:
            return []

        # Collect unique IDs so we can batch both lookups
        episode_ids = list({r.episode_id for r in raw})
        speaker_keys = list({(r.episode_id, r.speaker_id) for r in raw})

        # Single query for all episode titles
        episode_rows = await db.execute(
            select(Episode.id, Episode.title, Episode.audio_url).where(Episode.id.in_(episode_ids))
        )

        episode_data: dict = {
            row.id: {"title": row.title, "audio_url": row.audio_url}
            for row in episode_rows
        }

        # Single query for all speaker display names
        ep_ids_for_speakers = [ep_id for ep_id, _ in speaker_keys]
        speaker_rows = await db.execute(
            select(
                EpisodeSpeaker.episode_id,
                EpisodeSpeaker.speaker_id,
                EpisodeSpeaker.display_name,
            ).where(EpisodeSpeaker.episode_id.in_(ep_ids_for_speakers))
        )

        # Keyed as (episode_id, speaker_id) for lookup
        speaker_names: dict = {
            (row.episode_id, row.speaker_id): row.display_name
            for row in speaker_rows
        }
        return [
            ChunkResult(
                chunk_id=str(r.chunk_id),
                text=r.text,
                parent_text=r.parent_text,
                episode_id=str(r.episode_id),
                episode_title=episode_data.get(r.episode_id, {}).get("title"),
                audio_url=episode_data.get(r.episode_id, {}).get("audio_url"),
                display_name=speaker_names.get((r.episode_id, r.speaker_id)),
                timestamp_display=_format_timestamp(r.start_ms),
                start_ms=r.start_ms,
                end_ms=r.end_ms,
                similarity_score=r.similarity_score,
            )
            for r in raw
        ]

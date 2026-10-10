from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion import feed_service
from src.models.db import Episode


async def require_ready_episode(episode_id: UUID, db: AsyncSession) -> Episode:
    """404 if the episode doesn't exist; 409 unless ingestion completed.
    Only READY guarantees the episode's data is complete -- any other
    status may hold partial output from an interrupted run."""
    episode = await feed_service.get_episode(episode_id, db)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    if episode.pipeline_status != "READY":
        raise HTTPException(
            status_code=409,
            detail=f"Only available once ingestion completes (status: {episode.pipeline_status}).",
        )
    return episode
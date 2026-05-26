from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from src.api.dependencies import get_db
from src.models.schemas import EpisodeResponse, PipelineStatusUpdate
from src.ingestion import feed_service

router = APIRouter(prefix="/episodes", tags=["episodes"])


@router.get("/{episode_id}", response_model=EpisodeResponse)
async def get_episode(episode_id: UUID, db: AsyncSession = Depends(get_db)):
    episode = await feed_service.get_episode(episode_id, db)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    return EpisodeResponse.model_validate(episode)


@router.get("/{episode_id}/status", response_model=PipelineStatusUpdate)
async def get_episode_status(episode_id: UUID, db: AsyncSession = Depends(get_db)):
    episode = await feed_service.get_episode(episode_id, db)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    return PipelineStatusUpdate(
        status=episode.pipeline_status,
        stage=episode.pipeline_stage,
        progress=episode.pipeline_progress,
        error=episode.pipeline_error,
    )
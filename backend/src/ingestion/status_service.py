# src/ingestion/status_service.py
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update

from src.models.db import Episode

class PipelineStatusService:
    async def set(
        self,
        episode_id: UUID,
        status: str,
        db: AsyncSession,
        stage: str | None = None,
        progress: float | None = None,
        error: str | None = None
    ) -> None:

        await db.execute(
            update(Episode)
            .where(Episode.id == episode_id)
            .values(
                pipeline_status=status,
                pipeline_stage=stage,
                pipeline_progress=progress,
                pipeline_error=error if error else None
            )
        )
        await db.commit()

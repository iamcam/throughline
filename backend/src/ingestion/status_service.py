# src/ingestion/status_service.py
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, case, func

from src.models.db import Episode

from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession



class PipelineStatusService:
    def __init__(self, job_id: str | None = None):
        self._job_id = job_id

    def for_job(self, job_id: str) -> "PipelineStatusService":
        """A copy whose writes only apply while job_id still owns the episode."""
        return PipelineStatusService(job_id=job_id)

    async def set(
        self,
        episode_id: UUID,
        status: str,
        db: AsyncSession,
        *,
        progress: float | None = None,
        error: str | None = None,
        job_id: str | None = None,
    ) -> bool:
        owner_job_id = job_id if job_id is not None else self._job_id
        stmt = (
            update(Episode)
            .where(Episode.id == episode_id)
            .values(
                pipeline_status=status,
                pipeline_progress=progress,
                pipeline_error=error if error else None,
                status_changed_at=case(
                    (Episode.pipeline_status.is_distinct_from(status), func.now()),
                    else_=Episode.status_changed_at,
                ),
            )
        )
        if owner_job_id is not None:
            stmt = stmt.where(Episode.ingestion_job_id == owner_job_id)

        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount > 0


    async def claim_for_queue(
        self,
        episode_id: UUID,
        job_id: str,
        db: AsyncSession,
        *,
        allowed_from: tuple[str, ...],
    ) -> bool:
        """
        Atomically move an episode to QUEUED and record job_id as its owner,
        but only if its current status is in allowed_from. Returns False when
        another request got there first (or the status doesn't allow it).

        Does NOT commit -- the caller owns the transaction, so it can bundle
        other work (reingest's data wipe) into the same commit, or roll back.
        """
        result = await db.execute(
            update(Episode)
            .where(
                Episode.id == episode_id,
                Episode.pipeline_status.in_(allowed_from),
            )
                .values(
                    pipeline_status="QUEUED",
                    pipeline_progress=None,
                    pipeline_error=None,
                    ingestion_job_id=job_id,
                    queued_at=func.now(),
                    status_changed_at=func.now(),
                )
            )
        return result.rowcount > 0


    async def still_owns(self, episode_id: UUID, db: AsyncSession) -> bool:
        """
        True if this service's job still owns the episode. Takes FOR SHARE on
        the episode row: held until the caller's next commit/rollback, so a
        reset or claim (both UPDATEs on that row) waits for the guarded write
        to commit, and a waiting check re-reads the row and sees lost ownership.
        Callers must not commit between this check and the write it guards.
        """
        stmt = select(Episode.id).where(Episode.id == episode_id)
        if self._job_id is not None:
            stmt = stmt.where(Episode.ingestion_job_id == self._job_id)
        stmt = stmt.with_for_update(read=True)  # FOR SHARE
        return (await db.execute(stmt)).first() is not None
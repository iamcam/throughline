from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.ingestion.pipeline_stages import ACTIVE_STAGES
from src.models.db import Episode

# Pipeline position of each active stage: DOWNLOADING=0 ... EMBEDDING=5.
# Forward order for now; reversing the In-progress group means reversing this.
_STAGE_POSITION = case(
    {stage: position for position, stage in enumerate(ACTIVE_STAGES)},
    value=Episode.pipeline_status,
)


def _groups(since: datetime) -> dict:
    """group name -> (WHERE condition, ORDER BY columns)"""
    return {
        "queued": (
            Episode.pipeline_status == "QUEUED",
            [Episode.queued_at.asc().nulls_last(), Episode.id],
        ),
        "in_progress": (
            Episode.pipeline_status.in_(ACTIVE_STAGES),
            [_STAGE_POSITION, Episode.queued_at.asc().nulls_last(), Episode.id],
        ),
        "finished": (
            and_(Episode.pipeline_status == "READY", Episode.status_changed_at >= since),
            [Episode.status_changed_at.desc(), Episode.id],
        ),
        "error": (
            and_(Episode.pipeline_status == "ERROR", Episode.status_changed_at >= since),
            [Episode.status_changed_at.desc(), Episode.id],
        ),
    }

@dataclass
class QueueGroupRows:
    total: int
    episodes: list[Episode]


async def get_queue_overview(
    db: AsyncSession,
    *,
    since: datetime,
    limit: int | None = None,
) -> dict[str, QueueGroupRows]:
    overview: dict[str, QueueGroupRows] = {}

    for name, (condition, ordering) in _groups(since).items():
        stmt = (
            select(Episode)
            .options(joinedload(Episode.feed))
            .where(condition)
            .order_by(*ordering)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        episodes = list((await db.execute(stmt)).scalars().all())

        if limit is None:
            total = len(episodes)
        else:
            total = await db.scalar(select(func.count()).select_from(Episode).where(condition))

        overview[name] = QueueGroupRows(total=total, episodes=episodes)

    return overview
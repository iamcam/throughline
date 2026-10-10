from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, get_settings
from src.ingestion.pipeline_stages import is_possibly_stuck, stuck_thresholds
from src.ingestion import feed_service
from src.ingestion.queue_overview import QueueGroupRows, get_queue_overview
from src.models.db import Episode
from src.models.schemas import QueueEpisodeItem, QueueFeedSummary, QueueGroup, QueueResponse, ResetCountResponse
from src.shared.db import get_db

router = APIRouter(prefix="/queue", tags=["queue"])

DEFAULT_WINDOW = timedelta(hours=24)


def _to_item(episode: Episode, now: datetime, thresholds) -> QueueEpisodeItem:
    return QueueEpisodeItem(
        id=episode.id,
        title=episode.title,
        image_url=episode.image_url,
        published_at=episode.published_at,
        duration_seconds=episode.duration_seconds,
        pipeline_status=episode.pipeline_status,
        pipeline_error=episode.pipeline_error,
        queued_at=episode.queued_at,
        status_changed_at=episode.status_changed_at,
        possibly_stuck=is_possibly_stuck(
            episode.pipeline_status, episode.status_changed_at, now, thresholds
        ),
        feed=QueueFeedSummary(
            id=episode.feed.id,
            title=episode.feed.title,
            image_url=episode.feed.image_url,
        ),
    )


def _to_group(rows: QueueGroupRows, now: datetime, thresholds) -> QueueGroup:
    return QueueGroup(
        total=rows.total,
        items=[_to_item(episode, now, thresholds) for episode in rows.episodes],
    )


@router.get("", response_model=QueueResponse)
async def get_queue(
    since: datetime | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> QueueResponse:
    now = datetime.now(timezone.utc)
    if since is None:
        since = now - DEFAULT_WINDOW
    elif since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)

    overview = await get_queue_overview(db, since=since, limit=limit)
    thresholds = stuck_thresholds(settings)

    return QueueResponse(
        **{name: _to_group(rows, now, thresholds) for name, rows in overview.items()}
    )

@router.post("/errors/reset", response_model=ResetCountResponse)
async def reset_errored_episodes_handler(db: AsyncSession = Depends(get_db)) -> ResetCountResponse:
    count = await feed_service.reset_errored_episodes(db)
    return ResetCountResponse(reset=count)
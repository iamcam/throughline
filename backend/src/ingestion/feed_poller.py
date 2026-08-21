# src/ingestion/feed_poller.py
import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import Feed
from src.ingestion import feed_service

logger = logging.getLogger(__name__)


@dataclass
class PollResult:
    feeds_checked: int = 0
    new_episodes: int = 0
    errors: list[tuple[UUID, str]] = field(default_factory=list)


async def poll_all_feeds(db: AsyncSession) -> PollResult:
    result = PollResult()

    feed_ids = (await db.execute(select(Feed.id))).scalars().all()

    for feed_id in feed_ids:
        result.feeds_checked += 1
        try:
            new_episodes = await feed_service.refresh_feed(feed_id, db)
            result.new_episodes += len(new_episodes)
        except Exception:
            logger.exception("Feed poll failed for feed_id=%s", feed_id)
            await db.rollback()
            result.errors.append((feed_id, "refresh failed - see logs"))

    return result
# src/ingestion/feed_service.py
from typing import Literal
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from uuid import UUID
from src.models.db import Feed, Episode
from src.ingestion.rss_parser import parse_feed


async def add_feed(rss_url: str, db: AsyncSession) -> Feed:
    # Check for existing feed
    result = await db.execute(select(Feed).where(Feed.rss_url == rss_url))
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    parsed = parse_feed(rss_url)

    feed = Feed(
        rss_url=rss_url,
        title=parsed.title,
        description=parsed.description,
        image_url=parsed.image_url,
        last_fetched_at=datetime.now(timezone.utc)
    )
    db.add(feed)
    await db.flush()  # get feed.id before inserting episodes

    for ep in parsed.episodes:
        episode = Episode(
            feed_id=feed.id,
            guid=ep.guid,
            title=ep.title,
            description=ep.description,
            published_at=ep.published_at,
            audio_url=ep.audio_url,
            duration_seconds=ep.duration_seconds,
            transcript_url=ep.transcript_url,
            pipeline_status="PENDING",
        )
        db.add(episode)

    await db.commit()
    await db.refresh(feed)
    return feed


async def refresh_feed(feed_id: UUID, db: AsyncSession) -> list[Episode]:
    result = await db.execute(select(Feed).where(Feed.id == feed_id))
    feed = result.scalar_one_or_none()
    if not feed:
        raise ValueError(f"Feed {feed_id} not found")

    parsed = parse_feed(feed.rss_url)

    # Fetch existing guids to avoid duplicates
    existing = await db.execute(
        select(Episode.guid).where(Episode.feed_id == feed_id)
    )
    existing_guids = {row[0] for row in existing.fetchall()}

    new_episodes = []
    for ep in parsed.episodes:
        if ep.guid in existing_guids:
            continue
        episode = Episode(
            feed_id=feed_id,
            guid=ep.guid,
            title=ep.title,
            description=ep.description,
            published_at=ep.published_at,
            audio_url=ep.audio_url,
            duration_seconds=ep.duration_seconds,
            transcript_url=ep.transcript_url,
            pipeline_status="PENDING",
        )
        db.add(episode)
        new_episodes.append(episode)
    feed.last_fetched_at = datetime.now(timezone.utc)
    await db.commit()
    return new_episodes


FeedSort = Literal["created_at", "latest_episode"]

async def list_feeds(db: AsyncSession, sort: FeedSort = "created_at") -> list[tuple[Feed, int, datetime | None]]:
    latest_episode = func.max(Episode.published_at).label("latest_episode_published_at")

    query = (
        select(Feed, func.count(Episode.id).label("episode_count"), latest_episode)
        .outerjoin(Episode, Episode.feed_id == Feed.id)
        .group_by(Feed.id)
    )

    if sort == "latest_episode":
        query = query.order_by(latest_episode.desc().nulls_last())
    else:
        query = query.order_by(Feed.created_at.desc())

    result = await db.execute(query)
    return result.all()


async def get_feed(feed_id: UUID, db: AsyncSession) -> Feed | None:
    result = await db.execute(select(Feed).where(Feed.id == feed_id))
    return result.scalar_one_or_none()


async def delete_feed(feed_id: UUID, db: AsyncSession) -> bool:
    feed = await get_feed(feed_id, db)
    if not feed:
        return False
    await db.delete(feed)
    await db.commit()
    return True


async def list_episodes(feed_id: UUID, db: AsyncSession) -> list[Episode]:
    result = await db.execute(
        select(Episode)
        .where(Episode.feed_id == feed_id)
        .order_by(Episode.published_at.desc())
    )
    return result.scalars().all()


async def get_feed_stats(feed_id: UUID, db: AsyncSession) -> tuple[int, datetime | None]:
    result = await db.execute(
        select(
            func.count(Episode.id),
            func.max(Episode.published_at),
        )
        .where(Episode.feed_id == feed_id)
    )
    count, latest_episode = result.one()
    return count, latest_episode


async def get_episode(episode_id: UUID, db: AsyncSession) -> Episode | None:
    result = await db.execute(select(Episode).where(Episode.id == episode_id))
    return result.scalar_one_or_none()
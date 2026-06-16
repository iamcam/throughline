# src/api/routers/feeds.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from src.api.dependencies import get_db
from src.models.schemas import AddFeedRequest, FeedResponse, EpisodeResponse
from src.ingestion import feed_service
from src.ingestion.itunes import is_itunes_url, resolve_itunes_url

router = APIRouter(prefix="/feeds", tags=["feeds"])


@router.post("", response_model=FeedResponse)
async def add_feed(body: AddFeedRequest, db: AsyncSession = Depends(get_db)):
    rss_url = str(body.rss_url)

    if is_itunes_url(rss_url):
        try:
            rss_url = await resolve_itunes_url(rss_url)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    feed = await feed_service.add_feed(rss_url, db)
    episode_count = await feed_service.list_episodes(feed.id, db)
    return FeedResponse(
        id=feed.id,
        rss_url=feed.rss_url,
        title=feed.title,
        description=feed.description,
        image_url=feed.image_url,
        episode_count=len(episode_count),
        created_at=feed.created_at,
    )


@router.get("", response_model=list[FeedResponse])
async def list_feeds(db: AsyncSession = Depends(get_db)):
    rows = await feed_service.list_feeds(db)
    return [
        FeedResponse(
            id=feed.id,
            rss_url=feed.rss_url,
            title=feed.title,
            description=feed.description,
            image_url=feed.image_url,
            episode_count=count,
            created_at=feed.created_at,
        )
        for feed, count in rows
    ]


@router.get("/{feed_id}", response_model=FeedResponse)
async def get_feed(feed_id: UUID, db: AsyncSession = Depends(get_db)):
    feed = await feed_service.get_feed(feed_id, db)
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    episodes = await feed_service.list_episodes(feed_id, db)
    return FeedResponse(
        id=feed.id,
        rss_url=feed.rss_url,
        title=feed.title,
        description=feed.description,
        image_url=feed.image_url,
        episode_count=len(episodes),
        created_at=feed.created_at,
    )


@router.delete("/{feed_id}", status_code=204)
async def delete_feed(feed_id: UUID, db: AsyncSession = Depends(get_db)):
    deleted = await feed_service.delete_feed(feed_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Feed not found")


@router.post("/{feed_id}/refresh", response_model=list[EpisodeResponse])
async def refresh_feed(feed_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        new_episodes = await feed_service.refresh_feed(feed_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return [EpisodeResponse.model_validate(ep) for ep in new_episodes]


@router.get("/{feed_id}/episodes", response_model=list[EpisodeResponse])
async def list_episodes(feed_id: UUID, db: AsyncSession = Depends(get_db)):
    episodes = await feed_service.list_episodes(feed_id, db)
    return [EpisodeResponse.model_validate(ep) for ep in episodes]
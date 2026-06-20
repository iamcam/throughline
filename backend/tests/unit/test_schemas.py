# tests/unit/test_schemas.py
from datetime import datetime, timezone
from uuid import uuid4

from src.models.schemas import FeedResponse


def test_feed_response_accepts_null_latest_episode_published_at():
    feed = FeedResponse(
        id=uuid4(),
        rss_url="https://example.com/feed.xml",
        title="Test Feed",
        description=None,
        image_url=None,
        episode_count=0,
        latest_episode_published_at=None,
        created_at=datetime.now(timezone.utc),
    )
    assert feed.latest_episode_published_at is None
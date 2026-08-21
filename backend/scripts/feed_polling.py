#!/usr/bin/env python
# scripts/feed_polling.py
import asyncio
import logging

from src.shared.db import AsyncSessionLocal
from src.ingestion.feed_poller import poll_all_feeds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await poll_all_feeds(db)

    logger.info(
        "Feed poll complete: %d feeds checked, %d new episodes, %d errors",
        result.feeds_checked,
        result.new_episodes,
        len(result.errors),
    )
    for feed_id, message in result.errors:
        logger.error("feed_id=%s: %s", feed_id, message)


if __name__ == "__main__":
    asyncio.run(main())
# src/ingestion/itunes.py
import re
import logging
import httpx

logger = logging.getLogger(__name__)

ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"
ITUNES_URL_PATTERN = re.compile(r"podcasts\.apple\.com|itunes\.apple\.com")
ITUNES_ID_PATTERN = re.compile(r"/id(\d+)")


def is_itunes_url(url: str) -> bool:
    return bool(ITUNES_URL_PATTERN.search(url))


async def resolve_itunes_url(url: str) -> str:
    """
    Given an iTunes/Apple Podcasts URL, return the RSS feed URL.
    Raises ValueError if the podcast ID cannot be found or the lookup fails.
    """
    match = ITUNES_ID_PATTERN.search(url)
    if not match:
        raise ValueError(f"Could not extract podcast ID from iTunes URL: {url}")

    podcast_id = match.group(1)
    logger.info(f"Resolving iTunes podcast ID {podcast_id}")

    async with httpx.AsyncClient() as client:
        response = await client.get(
            ITUNES_LOOKUP_URL,
            params={"id": podcast_id},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()

    if data.get("resultCount", 0) == 0:
        raise ValueError(f"No podcast found for iTunes ID {podcast_id}")

    feed_url = data["results"][0].get("feedUrl")
    if not feed_url:
        raise ValueError(f"iTunes lookup returned no feedUrl for ID {podcast_id}")

    logger.info(f"Resolved iTunes ID {podcast_id} → {feed_url}")
    return feed_url
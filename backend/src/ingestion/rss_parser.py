# src/ingestion/rss_parser.py
import feedparser
from dataclasses import dataclass
from datetime import datetime, timezone
import re

from src.ingestion.html import html_to_markdown


@dataclass
class ParsedEpisode:
    guid: str
    title: str | None
    description: str | None
    published_at: datetime | None
    audio_url: str | None
    duration_seconds: int | None
    transcript_url: str | None


@dataclass
class ParsedFeed:
    title: str | None
    description: str | None
    image_url: str | None
    episodes: list[ParsedEpisode]


def parse_duration(raw: str | None) -> int | None:
    """
    Accepts HH:MM:SS, MM:SS, or raw integer seconds.
    Returns total seconds as int, or None if unparseable.
    """
    if not raw:
        return None
    raw = raw.strip()
    if re.match(r"^\d+$", raw):
        return int(raw)
    parts = raw.split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def parse_feed(rss_url: str) -> ParsedFeed:
    data = feedparser.parse(rss_url)
    feed = data.feed

    image_url = None
    if hasattr(feed, "image") and hasattr(feed.image, "href"):
        image_url = feed.image.href

    episodes = []
    for entry in data.entries:
        # Audio URL from enclosures
        audio_url = None
        for enc in getattr(entry, "enclosures", []):
            if enc.get("type", "").startswith("audio/"):
                audio_url = enc.get("href")
                break

        # Duration
        itunes = getattr(entry, "itunes_duration", None)
        duration_seconds = parse_duration(itunes)

        # Transcript URL — podcast:transcript tag
        transcript_url = None
        pt = entry.get("podcast_transcript")
        if pt:
            transcript_url = pt.get("url")

        # published_at
        published_at = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

        episodes.append(ParsedEpisode(
            guid=entry.get("id", entry.get("link", "")),
            title=entry.get("title"),
            description=html_to_markdown(entry.get("summary")),
            published_at=published_at,
            audio_url=audio_url,
            duration_seconds=duration_seconds,
            transcript_url=transcript_url,
        ))

    return ParsedFeed(
        title=feed.get("title"),
        description=html_to_markdown(feed.get("subtitle") or feed.get("description")),
        image_url=image_url,
        episodes=episodes,
    )
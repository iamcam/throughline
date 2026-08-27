# tests/unit/test_rss_parser.py

import pytest
from pathlib import Path
from src.ingestion.rss_parser import parse_feed, parse_duration
import feedparser

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "sample_feed.xml"


def test_parse_feed_extracts_title():
    result = parse_feed(str(FIXTURE_PATH))
    assert result.title == "The Sample Podcast"


def test_parse_feed_extracts_episode_count():
    result = parse_feed(str(FIXTURE_PATH))
    assert len(result.episodes) == 3


def test_parse_episodes_extracts_guid():
    result = parse_feed(str(FIXTURE_PATH))
    guids = [ep.guid for ep in result.episodes]
    assert "ep-001" in guids


def test_parse_duration_hhmmss():
    assert parse_duration("1:03:42") == 3822


def test_parse_duration_mmss():
    assert parse_duration("45:30") == 2730


def test_parse_duration_raw_seconds():
    assert parse_duration("3600") == 3600


def test_parse_duration_none():
    assert parse_duration(None) is None


def test_parse_audio_url_from_enclosure():
    result = parse_feed(str(FIXTURE_PATH))
    ep1 = next(ep for ep in result.episodes if ep.guid == "ep-001")
    assert ep1.audio_url == "https://example.com/ep1.mp3"


def test_parse_episode_extracts_image_url():
    result = parse_feed(str(FIXTURE_PATH))
    ep2 = next(ep for ep in result.episodes if ep.guid == "ep-002")
    assert ep2.image_url == "https://example.com/ep2-cover.jpg"


def test_parse_episode_image_url_none_when_absent():
    result = parse_feed(str(FIXTURE_PATH))
    ep1 = next(ep for ep in result.episodes if ep.guid == "ep-001")
    assert ep1.image_url is None
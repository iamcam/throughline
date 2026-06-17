# tests/unit/test_itunes.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.ingestion.itunes import is_itunes_url, resolve_itunes_url


# ── is_itunes_url ─────────────────────────────────────────────────────────────

def test_is_itunes_url_detects_apple_podcasts():
    url = "https://podcasts.apple.com/us/podcast/some-show/id123456789"
    assert is_itunes_url(url) is True

def test_is_itunes_url_detects_itunes():
    url = "https://itunes.apple.com/us/podcast/some-show/id123456789"
    assert is_itunes_url(url) is True

def test_is_itunes_url_rejects_rss():
    url = "https://feeds.example.com/podcast.rss"
    assert is_itunes_url(url) is False

def test_is_itunes_url_rejects_plain_url():
    assert is_itunes_url("https://example.com") is False


# ── resolve_itunes_url ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_itunes_url_no_id_raises():
    with pytest.raises(ValueError, match="Could not extract podcast ID"):
        await resolve_itunes_url("https://podcasts.apple.com/us/podcast/some-show")


def _mock_httpx_response(data: dict):
    """Build a mock httpx response returning the given JSON data."""
    mock_response = MagicMock()
    mock_response.json.return_value = data
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


@pytest.mark.asyncio
async def test_resolve_itunes_url_not_found_raises():
    mock_client = _mock_httpx_response({"resultCount": 0, "results": []})
    with patch("src.ingestion.itunes.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="No podcast found"):
            await resolve_itunes_url("https://podcasts.apple.com/us/podcast/show/id999")


@pytest.mark.asyncio
async def test_resolve_itunes_url_no_feed_url_raises():
    mock_client = _mock_httpx_response({
        "resultCount": 1,
        "results": [{"collectionName": "Some Show"}]  # no feedUrl
    })
    with patch("src.ingestion.itunes.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="no feedUrl"):
            await resolve_itunes_url("https://podcasts.apple.com/us/podcast/show/id123")


@pytest.mark.asyncio
async def test_resolve_itunes_url_returns_feed_url():
    mock_client = _mock_httpx_response({
        "resultCount": 1,
        "results": [{"feedUrl": "https://feeds.example.com/podcast.rss"}]
    })
    with patch("src.ingestion.itunes.httpx.AsyncClient", return_value=mock_client):
        result = await resolve_itunes_url(
            "https://podcasts.apple.com/us/podcast/show/id123456789"
        )
    assert result == "https://feeds.example.com/podcast.rss"
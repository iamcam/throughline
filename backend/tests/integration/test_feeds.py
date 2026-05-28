# tests/integration/test_feeds.py
from httpx import AsyncClient

SAMPLE_FEED_URL = "https://orvisffguide.libsyn.com/rss"


async def test_add_feed_creates_episodes(client: AsyncClient):
    response = await client.post("/api/v1/feeds", json={"rss_url": SAMPLE_FEED_URL})
    assert response.status_code == 200
    data = response.json()
    assert data["title"] is not None
    assert data["episode_count"] > 0


async def test_add_feed_idempotent(client: AsyncClient):
    await client.post("/api/v1/feeds", json={"rss_url": SAMPLE_FEED_URL})
    response = await client.post("/api/v1/feeds", json={"rss_url": SAMPLE_FEED_URL})
    assert response.status_code == 200
    list_response = await client.get("/api/v1/feeds")
    assert len(list_response.json()) == 1


async def test_list_feeds(client: AsyncClient):
    await client.post("/api/v1/feeds", json={"rss_url": SAMPLE_FEED_URL})
    response = await client.get("/api/v1/feeds")
    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_delete_feed_cascades(client: AsyncClient):
    add_response = await client.post("/api/v1/feeds", json={"rss_url": SAMPLE_FEED_URL})
    feed_id = add_response.json()["id"]

    delete_response = await client.delete(f"/api/v1/feeds/{feed_id}")
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/v1/feeds/{feed_id}")
    assert get_response.status_code == 404


async def test_refresh_adds_only_new_episodes(client: AsyncClient):
    add_response = await client.post("/api/v1/feeds", json={"rss_url": SAMPLE_FEED_URL})
    feed_id = add_response.json()["id"]

    refresh_response = await client.post(f"/api/v1/feeds/{feed_id}/refresh")
    assert refresh_response.status_code == 200
    assert refresh_response.json() == []
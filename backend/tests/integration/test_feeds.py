import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from src.api.main import app
from src.api.dependencies import get_db
from src.models.db import Base
from src.config import get_settings

settings = get_settings()
TEST_DATABASE_URL = f"{settings.database_url}_test"

SAMPLE_FEED_URL = "https://orvisffguide.libsyn.com/rss"


@pytest.fixture
async def client():
    engine = create_async_engine(TEST_DATABASE_URL)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


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
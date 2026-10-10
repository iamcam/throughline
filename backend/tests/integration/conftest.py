# tests/integration/conftest.py
from datetime import datetime

import pytest
import time

from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text
from sqlalchemy.engine import make_url
import uuid


from src.api.dependencies import get_ingestion_queue
from src.api.main import app
from src.config import get_settings
from src.shared.db import get_db
from src.models.db import Base, Episode, Feed
from src.llm.base import LLMResponse, ToolCall
from src.shared.llm import get_embedding_client

from tests.conftest import FakeIngestionQueue, MockEmbeddingClient

settings = get_settings()
TEST_DATABASE_URL = f"{settings.database_url}_test"


## Setup
async def _ensure_database_exists(target_url: str) -> None:
    url = make_url(target_url)
    target_db_name = url.database

    # Connect to the default 'postgres' maintenance DB instead of the
    # (possibly nonexistent) target DB.
    maintenance_url = url.set(database="postgres")
    maintenance_engine = create_async_engine(
        maintenance_url, isolation_level="AUTOCOMMIT"
    )

    async with maintenance_engine.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": target_db_name},
        )
        if not exists:
            # Can't parameterize a database name -- quote_ident is the
            # standard safe way to interpolate an identifier here.
            await conn.execute(
                text(f'CREATE DATABASE "{target_db_name}"')
            )

    await maintenance_engine.dispose()


async def _ensure_pgvector_extension(target_url: str) -> None:
    engine = create_async_engine(target_url)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    await engine.dispose()



@pytest.fixture
async def make_episode(db_session):
    """Factory: insert a feed + episode with the given pipeline state."""
    async def _make(
            status: str = "PENDING",
            job_id: str | None = None,
            status_changed_at: datetime | None = None,
            queued_at: datetime | None = None,
        ) -> Episode:

        feed = Feed(rss_url=f"https://example.com/{uuid.uuid4()}.xml")
        db_session.add(feed)
        await db_session.flush()

        episode = Episode(
            feed_id=feed.id,
            guid=str(uuid.uuid4()),
            pipeline_status=status,
            ingestion_job_id=job_id,
            status_changed_at=status_changed_at,
            queued_at=queued_at
        )
        db_session.add(episode)
        await db_session.commit()
        return episode

    return _make


@pytest.fixture(scope="session")
async def _test_database_ready():
    await _ensure_database_exists(TEST_DATABASE_URL)
    await _ensure_pgvector_extension(TEST_DATABASE_URL)

# Remaining test config

@pytest.fixture
async def db_engine(_test_database_ready):
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture
async def client(db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_ingestion_queue] = lambda: FakeIngestionQueue()
    app.dependency_overrides[get_embedding_client] = lambda: MockEmbeddingClient()

    async with LifespanManager(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac

    app.dependency_overrides.clear()

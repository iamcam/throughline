from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from fastapi import Request
from src.config import get_settings

from src.ingestion.queue import BackgroundTaskQueue, IngestionQueue
from fastapi import Request

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False)

# Session factory
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_ingestion_queue(request: Request) -> IngestionQueue:
    return request.app.state.ingestion_queue
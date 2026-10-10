from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.ingestion.status_service import PipelineStatusService
from src.api.dependencies import get_ingestion_queue
from src.api.main import app

from tests.conftest import FakeIngestionQueue


def _use_queue(queue: FakeIngestionQueue) -> FakeIngestionQueue:
    app.dependency_overrides[get_ingestion_queue] = lambda: queue
    return queue


async def test_reset_ready_episode_does_not_cancel(client, db_session, make_episode):
    episode = await make_episode(status="READY", job_id="job-a")
    queue = _use_queue(FakeIngestionQueue())

    response = await client.post(f"/api/v1/episodes/{episode.id}/reset")

    await db_session.refresh(episode)
    assert response.status_code == 204
    assert episode.pipeline_status == "PENDING"
    assert episode.ingestion_job_id is None
    assert episode.status_changed_at is not None
    assert queue.cancelled == []


async def test_reset_queued_episode_cancels_its_job(client, db_session, make_episode):
    episode = await make_episode(
        status="QUEUED",
        job_id="job-a",
        status_changed_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    queue = _use_queue(FakeIngestionQueue())

    response = await client.post(f"/api/v1/episodes/{episode.id}/reset")

    await db_session.refresh(episode)
    assert response.status_code == 204
    assert episode.pipeline_status == "PENDING"
    assert episode.ingestion_job_id is None
    assert queue.cancelled == ["job-a"]


async def test_reset_active_episode_cancels_its_job(client, db_session, make_episode):
    episode = await make_episode(
        status="TRANSCRIBING",
        job_id="job-a",
        status_changed_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    queue = _use_queue(FakeIngestionQueue())

    response = await client.post(f"/api/v1/episodes/{episode.id}/reset")

    await db_session.refresh(episode)
    assert response.status_code == 204
    assert episode.pipeline_status == "PENDING"
    assert episode.ingestion_job_id is None
    assert queue.cancelled == ["job-a"]


async def test_reset_stuck_episode_allowed(client, db_session, make_episode):
    episode = await make_episode(
        status="TRANSCRIBING",
        job_id="job-a",
        status_changed_at=datetime.now(timezone.utc) - timedelta(hours=1, minutes=50),
    )
    queue = _use_queue(FakeIngestionQueue())

    response = await client.post(f"/api/v1/episodes/{episode.id}/reset")

    await db_session.refresh(episode)
    assert response.status_code == 204
    assert episode.pipeline_status == "PENDING"
    assert queue.cancelled == ["job-a"]


async def test_reset_pending_is_noop(client, make_episode):
    episode = await make_episode(status="PENDING")

    response = await client.post(f"/api/v1/episodes/{episode.id}/reset")

    assert response.status_code == 204


async def test_reset_unknown_episode_404(client):
    response = await client.post(
        "/api/v1/episodes/00000000-0000-0000-0000-000000000000/reset"
    )

    assert response.status_code == 404


async def test_delete_transcript_route_removed(client, make_episode):
    episode = await make_episode("READY")

    response = await client.delete(f"/api/v1/episodes/{episode.id}/transcript")

    assert response.status_code == 405

async def test_transcript_requires_ready(client, make_episode):
    episode = await make_episode(status="ERROR")

    response = await client.get(f"/api/v1/episodes/{episode.id}/transcript")

    assert response.status_code == 409

import pytest


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("GET", "speakers", None),
        ("GET", "speakers/preview", None),
        ("PUT", "speakers", []),
    ],
    ids=["list", "preview", "update"],
)
async def test_speaker_routes_require_ready(client, make_episode, method, path, body):
    episode = await make_episode(status="ERROR")

    response = await client.request(method, f"/api/v1/episodes/{episode.id}/{path}", json=body)

    assert response.status_code == 409


async def test_reset_returns_409_when_row_is_locked(client, db_engine, make_episode):
    episode = await make_episode(status="EMBEDDING", job_id="job-a")
    _use_queue(FakeIngestionQueue())
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async with factory() as worker_db:
        assert await PipelineStatusService(job_id="job-a").still_owns(episode.id, worker_db)

        response = await client.post(f"/api/v1/episodes/{episode.id}/reset")

        assert response.status_code == 409
        await worker_db.rollback()
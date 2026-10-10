from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.ingestion import pipeline_runner
from src.ingestion.pipeline import PipelineServices
from src.ingestion.status_service import PipelineStatusService
from tests.conftest import make_pipeline_services

@pytest.fixture
def recorded_runs(db_engine, monkeypatch):
    runs = []

    async def fake_ingest_episode(episode, job_args, services, db):
        runs.append((episode.id, services.status))

    monkeypatch.setattr(
        pipeline_runner,
        "AsyncSessionLocal",
        async_sessionmaker(db_engine, expire_on_commit=False),
    )
    monkeypatch.setattr(pipeline_runner, "ingest_episode", fake_ingest_episode)
    return runs


@pytest.mark.parametrize("owner_job_id", ["newer-job", None], ids=["superseded", "reset"])
async def test_run_ingest_skips_non_owner(make_episode, recorded_runs, owner_job_id):
    episode = await make_episode(status="QUEUED", job_id=owner_job_id)
    services = make_pipeline_services()

    await pipeline_runner.run_ingest(episode.id, {}, services, job_id="old-job")

    assert recorded_runs == []


async def test_run_ingest_runs_owner_with_bound_status(db_session, make_episode, recorded_runs):
    episode = await make_episode(status="TRANSCRIBING", job_id="job-a")
    services = make_pipeline_services()
    caller_status = services.status

    await pipeline_runner.run_ingest(episode.id, {}, services, job_id="job-a")

    assert services.status is caller_status  # caller's object untouched
    assert len(recorded_runs) == 1
    _, bound_status = recorded_runs[0]
    assert bound_status is not caller_status
    applied = await bound_status.set(episode.id, "CHUNKING", db_session)
    assert applied is True
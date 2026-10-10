from src.api.dependencies import get_ingestion_queue
from src.api.main import app
from src.ingestion.queue import QueueConnectionError
from src.ingestion.status_service import PipelineStatusService

from tests.conftest import FakeIngestionQueue


class _RacingQueue(FakeIngestionQueue):
    """Runs a side effect just before the claim -- simulates another
    request winning the race between the pre-check and the claim."""

    def __init__(self, before_claim):
        super().__init__()
        self._before_claim = before_claim

    async def enqueue(self, episode_id, job_args, *, before_submit):
        await self._before_claim()
        return await super().enqueue(episode_id, job_args, before_submit=before_submit)


class _FailingPushQueue(FakeIngestionQueue):
    """Claim succeeds, then the push to the queue fails."""

    async def enqueue(self, episode_id, job_args, *, before_submit):
        await before_submit("doomed-job")
        raise QueueConnectionError("redis down")


async def test_ingest_claims_episode(client, db_session, make_episode):
    episode = await make_episode(status="PENDING")

    response = await client.post(f"/api/v1/episodes/{episode.id}/ingest")

    await db_session.refresh(episode)
    assert response.status_code == 200
    assert episode.pipeline_status == "QUEUED"
    assert episode.ingestion_job_id == "fake-job-id"
    assert episode.queued_at is not None


async def test_lost_claim_returns_409_and_pushes_nothing(client, db_session, make_episode):
    episode = await make_episode(status="PENDING")

    async def other_request_wins():
        await PipelineStatusService().claim_for_queue(
            episode.id, "other-job", db_session, allowed_from=("PENDING",)
        )
        await db_session.commit()

    queue = _RacingQueue(other_request_wins)
    app.dependency_overrides[get_ingestion_queue] = lambda: queue

    response = await client.post(f"/api/v1/episodes/{episode.id}/ingest")

    await db_session.refresh(episode)
    assert response.status_code == 409
    assert queue.enqueued == []
    assert episode.ingestion_job_id == "other-job"


async def test_failed_push_marks_episode_error(client, db_session, make_episode):
    episode = await make_episode(status="PENDING")
    app.dependency_overrides[get_ingestion_queue] = lambda: _FailingPushQueue()

    response = await client.post(f"/api/v1/episodes/{episode.id}/ingest")

    await db_session.refresh(episode)
    assert response.status_code == 503
    assert episode.pipeline_status == "ERROR"
    assert episode.ingestion_job_id == "doomed-job"
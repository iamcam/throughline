import asyncio
from datetime import datetime, timezone
import asyncpg
import pytest
import uuid
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.ingestion import feed_service
from src.ingestion.status_service import PipelineStatusService




@pytest.fixture
def status_service():
    return PipelineStatusService()


async def test_status_change_stamps_status_changed_at(db_session, make_episode, status_service):
    episode = await make_episode()
    assert episode.status_changed_at is None

    await status_service.set(episode.id, "DOWNLOADING", db_session)

    await db_session.refresh(episode)
    assert episode.pipeline_status == "DOWNLOADING"
    assert episode.status_changed_at is not None


async def test_same_status_write_keeps_timestamp(db_session, make_episode, status_service):
    episode = await make_episode()
    await status_service.set(episode.id, "DOWNLOADING", db_session)
    await db_session.refresh(episode)
    first_stamp = episode.status_changed_at

    await status_service.set(episode.id, "DOWNLOADING", db_session, progress=0.5)

    await db_session.refresh(episode)
    assert episode.pipeline_progress == 0.5
    assert episode.status_changed_at == first_stamp


async def test_new_status_moves_timestamp(db_session, make_episode, status_service):
    episode = await make_episode()
    await status_service.set(episode.id, "DOWNLOADING", db_session)
    await db_session.refresh(episode)
    first_stamp = episode.status_changed_at

    await status_service.set(episode.id, "TRANSCRIBING", db_session)

    await db_session.refresh(episode)
    assert episode.status_changed_at > first_stamp


async def test_matching_job_id_applies(db_session, make_episode, status_service):
    episode = await make_episode(status="DOWNLOADING", job_id="job-a")

    applied = await status_service.set(episode.id, "TRANSCRIBING", db_session, job_id="job-a")

    await db_session.refresh(episode)
    assert applied is True
    assert episode.pipeline_status == "TRANSCRIBING"


@pytest.mark.parametrize("owner_job_id", ["job-b", None], ids=["superseded", "reset"])
async def test_non_owner_job_id_is_noop(db_session, make_episode, status_service, owner_job_id):
    episode = await make_episode(status="DOWNLOADING", job_id=owner_job_id)

    applied = await status_service.set(
        episode.id, "ERROR", db_session, error="boom", job_id="job-a"
    )

    await db_session.refresh(episode)
    assert applied is False
    assert episode.pipeline_status == "DOWNLOADING"
    assert episode.pipeline_error is None
    assert episode.status_changed_at is None


async def test_write_without_job_id_applies_unconditionally(db_session, make_episode, status_service):
    episode = await make_episode(status="DOWNLOADING", job_id="job-b")

    applied = await status_service.set(episode.id, "READY", db_session)

    await db_session.refresh(episode)
    assert applied is True
    assert episode.pipeline_status == "READY"

async def test_status_change_clears_stale_progress_and_error(db_session, make_episode, status_service):
    episode = await make_episode()
    await status_service.set(episode.id, "DOWNLOADING", db_session, progress=0.9)
    await status_service.set(episode.id, "ERROR", db_session, error="boom")

    await status_service.set(episode.id, "QUEUED", db_session)

    await db_session.refresh(episode)
    assert episode.pipeline_progress is None
    assert episode.pipeline_error is None


async def test_empty_error_string_stored_as_null(db_session, make_episode, status_service):
    episode = await make_episode()

    await status_service.set(episode.id, "ERROR", db_session, error="")

    await db_session.refresh(episode)
    assert episode.pipeline_error is None


async def test_unknown_episode_returns_false(db_session, status_service):
    applied = await status_service.set(uuid.uuid4(), "DOWNLOADING", db_session)

    assert applied is False


async def test_only_target_episode_is_updated(db_session, make_episode, status_service):
    target = await make_episode(status="DOWNLOADING", job_id="job-a")
    bystander = await make_episode(status="DOWNLOADING", job_id="job-a")

    await status_service.set(target.id, "TRANSCRIBING", db_session, job_id="job-a")

    await db_session.refresh(bystander)
    assert bystander.pipeline_status == "DOWNLOADING"
    assert bystander.status_changed_at is None


async def test_optional_args_are_keyword_only(db_session, make_episode, status_service):
    episode = await make_episode()

    with pytest.raises(TypeError):
        await status_service.set(episode.id, "DOWNLOADING", db_session, 0.5)


async def test_claim_from_allowed_status(db_session, make_episode, status_service):
    episode = await make_episode(status="ERROR")
    await status_service.set(episode.id, "ERROR", db_session, error="old failure")

    claimed = await status_service.claim_for_queue(
        episode.id, "job-a", db_session, allowed_from=("PENDING", "ERROR")
    )
    await db_session.commit()

    await db_session.refresh(episode)
    assert claimed is True
    assert episode.pipeline_status == "QUEUED"
    assert episode.ingestion_job_id == "job-a"
    assert episode.pipeline_error is None
    assert episode.queued_at is not None
    assert episode.status_changed_at == episode.queued_at


async def test_claim_from_disallowed_status_is_rejected(db_session, make_episode, status_service):
    episode = await make_episode(status="DOWNLOADING", job_id="job-a")

    claimed = await status_service.claim_for_queue(
        episode.id, "job-b", db_session, allowed_from=("PENDING", "ERROR")
    )
    await db_session.commit()

    await db_session.refresh(episode)
    assert claimed is False
    assert episode.pipeline_status == "DOWNLOADING"
    assert episode.ingestion_job_id == "job-a"


async def test_second_claim_loses(db_session, make_episode, status_service):
    episode = await make_episode()
    await status_service.claim_for_queue(
        episode.id, "job-a", db_session, allowed_from=("PENDING", "ERROR")
    )
    await db_session.commit()

    claimed = await status_service.claim_for_queue(
        episode.id, "job-b", db_session, allowed_from=("PENDING", "ERROR")
    )
    await db_session.commit()

    await db_session.refresh(episode)
    assert claimed is False
    assert episode.ingestion_job_id == "job-a"


async def test_reclaim_overwrites_queued_at(db_session, make_episode, status_service):
    episode = await make_episode()
    await status_service.claim_for_queue(
        episode.id, "job-a", db_session, allowed_from=("PENDING",)
    )
    await db_session.commit()
    await status_service.set(episode.id, "READY", db_session, job_id="job-a")
    await db_session.refresh(episode)
    first_queued_at = episode.queued_at

    await status_service.claim_for_queue(
        episode.id, "job-b", db_session, allowed_from=("ERROR", "READY")
    )
    await db_session.commit()

    await db_session.refresh(episode)
    assert episode.queued_at > first_queued_at
    assert episode.ingestion_job_id == "job-b"


async def test_claim_does_not_commit(db_session, make_episode, status_service):
    episode = await make_episode()

    await status_service.claim_for_queue(
        episode.id, "job-a", db_session, allowed_from=("PENDING",)
    )
    await db_session.rollback()

    await db_session.refresh(episode)
    assert episode.pipeline_status == "PENDING"
    assert episode.ingestion_job_id is None


async def test_job_bound_service_scopes_writes(db_session, make_episode):
    episode = await make_episode(status="DOWNLOADING", job_id="job-b")
    bound = PipelineStatusService().for_job("job-a")

    applied = await bound.set(episode.id, "ERROR", db_session, error="boom")

    await db_session.refresh(episode)
    assert applied is False
    assert episode.pipeline_status == "DOWNLOADING"


async def test_job_bound_service_applies_for_owner(db_session, make_episode):
    episode = await make_episode(status="DOWNLOADING", job_id="job-a")
    bound = PipelineStatusService().for_job("job-a")

    applied = await bound.set(episode.id, "TRANSCRIBING", db_session)

    assert applied is True

@pytest.mark.parametrize(
    "bound_job_id, owner_job_id, expected",
    [
        ("job-a", "job-a", True),
        ("job-a", "job-b", False),
        ("job-a", None, False),
        (None, "job-b", True),
    ],
    ids=["owner", "superseded", "reset", "unbound"],
)
async def test_still_owns(db_session, make_episode, bound_job_id, owner_job_id, expected):
    episode = await make_episode(status="TRANSCRIBING", job_id=owner_job_id)
    service = PipelineStatusService(job_id=bound_job_id)

    assert await service.still_owns(episode.id, db_session) is expected


async def test_still_owns_missing_episode(db_session):
    assert await PipelineStatusService().still_owns(uuid.uuid4(), db_session) is False


async def test_ownership_check_blocks_reset_until_write_commits(db_engine, make_episode):
    episode = await make_episode(status="EMBEDDING", job_id="job-a")
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    service = PipelineStatusService(job_id="job-a")

    async with factory() as worker_db, factory() as api_db:
        assert await service.still_owns(episode.id, worker_db)  # FOR SHARE now held

        await api_db.execute(text("SET LOCAL lock_timeout = '200ms'"))
        with pytest.raises(DBAPIError) as exc_info:
            await feed_service.reset_episode(
                episode.id, api_db, expected_status="EMBEDDING", expected_job_id="job-a"
            )
        assert isinstance(exc_info.value.orig.__cause__, asyncpg.exceptions.LockNotAvailableError)
        await api_db.rollback()

        await worker_db.commit()  # guarded write done -> lock released

        assert await feed_service.reset_episode(
            episode.id, api_db, expected_status="EMBEDDING", expected_job_id="job-a"
        )


async def test_ownership_check_waits_for_reset_then_sees_lost_ownership(db_engine, make_episode):
    episode = await make_episode(status="EMBEDDING", job_id="job-a")
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    service = PipelineStatusService(job_id="job-a")

    async with factory() as worker_db, factory() as api_db:
        # Reset's UPDATE takes the row lock, uncommitted.
        await api_db.execute(
            text("UPDATE episodes SET ingestion_job_id = NULL, pipeline_status = 'PENDING' WHERE id = :id"),
            {"id": episode.id},
        )

        check = asyncio.create_task(service.still_owns(episode.id, worker_db))
        await asyncio.sleep(0.2)
        assert not check.done()  # blocked behind the reset

        await api_db.commit()
        assert await check is False  # re-read the committed row: job-a no longer owns it

async def test_started_at_set_on_first_download_only(db_session, make_episode):
    episode = await make_episode(status="QUEUED", job_id="job-a")
    service = PipelineStatusService(job_id="job-a")

    assert await service.set(episode.id, "DOWNLOADING", db_session)
    await db_session.refresh(episode)
    started = episode.started_at
    assert started is not None

    await service.set(episode.id, "DOWNLOADING", db_session, progress=0.5)
    await service.set(episode.id, "TRANSCRIBING", db_session)
    await db_session.refresh(episode)
    assert episode.started_at == started


async def test_claim_and_reset_clear_started_at(db_session, make_episode):
    episode = await make_episode(status="READY")
    episode.started_at = datetime.now(timezone.utc)
    await db_session.commit()

    service = PipelineStatusService()
    assert await service.claim_for_queue(episode.id, "job-b", db_session, allowed_from=("READY",))
    await db_session.commit()
    await db_session.refresh(episode)
    assert episode.started_at is None
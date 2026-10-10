from src.ingestion import feed_service


async def test_reset_episode_misses_when_status_changed(db_session, make_episode):
    episode = await make_episode(status="DOWNLOADING", job_id="job-b")

    reset = await feed_service.reset_episode(
        episode.id, db_session, expected_status="TRANSCRIBING", expected_job_id="job-b"
    )

    await db_session.refresh(episode)
    assert reset is False
    assert episode.pipeline_status == "DOWNLOADING"
    assert episode.ingestion_job_id == "job-b"


async def test_reset_episode_matches_null_job_id(db_session, make_episode):
    episode = await make_episode(status="ERROR", job_id=None)

    reset = await feed_service.reset_episode(
        episode.id, db_session, expected_status="ERROR", expected_job_id=None
    )

    await db_session.refresh(episode)
    assert reset is True
    assert episode.pipeline_status == "PENDING"
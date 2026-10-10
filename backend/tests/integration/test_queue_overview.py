from datetime import datetime, timedelta, timezone

from src.ingestion.queue_overview import get_queue_overview

NOW = datetime.now(timezone.utc)
SINCE = NOW - timedelta(days=1)


def _ids(group):
    return [episode.id for episode in group.episodes]


async def test_each_status_lands_in_its_group(db_session, make_episode):
    pending = await make_episode(status="PENDING")
    queued = await make_episode(status="QUEUED", queued_at=NOW)
    active = await make_episode(status="TRANSCRIBING", status_changed_at=NOW)
    ready = await make_episode(status="READY", status_changed_at=NOW)
    errored = await make_episode(status="ERROR", status_changed_at=NOW)

    overview = await get_queue_overview(db_session, since=SINCE)

    assert _ids(overview["queued"]) == [queued.id]
    assert _ids(overview["in_progress"]) == [active.id]
    assert _ids(overview["finished"]) == [ready.id]
    assert _ids(overview["error"]) == [errored.id]
    all_ids = [i for group in overview.values() for i in _ids(group)]
    assert pending.id not in all_ids


async def test_queued_oldest_first(db_session, make_episode):
    newer = await make_episode(status="QUEUED", queued_at=NOW)
    older = await make_episode(status="QUEUED", queued_at=NOW - timedelta(minutes=5))

    overview = await get_queue_overview(db_session, since=SINCE)

    assert _ids(overview["queued"]) == [older.id, newer.id]


async def test_in_progress_ordered_by_pipeline_stage(db_session, make_episode):
    embedding = await make_episode(status="EMBEDDING", queued_at=NOW - timedelta(hours=1))
    downloading = await make_episode(status="DOWNLOADING", queued_at=NOW)

    overview = await get_queue_overview(db_session, since=SINCE)

    assert _ids(overview["in_progress"]) == [downloading.id, embedding.id]


async def test_since_filters_finished_but_not_active(db_session, make_episode):
    old_ready = await make_episode(status="READY", status_changed_at=NOW - timedelta(days=3))
    old_active = await make_episode(status="DOWNLOADING", status_changed_at=NOW - timedelta(days=3))

    overview = await get_queue_overview(db_session, since=SINCE)

    assert old_ready.id not in _ids(overview["finished"])
    assert _ids(overview["in_progress"]) == [old_active.id]


async def test_limit_caps_items_but_not_total(db_session, make_episode):
    for minutes in range(3):
        await make_episode(status="READY", status_changed_at=NOW - timedelta(minutes=minutes))

    overview = await get_queue_overview(db_session, since=SINCE, limit=2)

    assert len(overview["finished"].episodes) == 2
    assert overview["finished"].total == 3


async def test_feed_is_eager_loaded(db_session, make_episode):
    episode = await make_episode(status="QUEUED", queued_at=NOW)

    overview = await get_queue_overview(db_session, since=SINCE)

    loaded = overview["queued"].episodes[0]
    assert loaded.feed.id == episode.feed_id
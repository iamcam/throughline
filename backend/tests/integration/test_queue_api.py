from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc)
URL = "/api/v1/queue"


async def test_response_shape_includes_feed(client, make_episode):
    episode = await make_episode(status="QUEUED", queued_at=NOW)

    response = await client.get(URL)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"queued", "in_progress", "finished", "error"}
    item = body["queued"]["items"][0]
    assert item["id"] == str(episode.id)
    assert item["feed"]["id"] == str(episode.feed_id)
    assert body["queued"]["total"] == 1


async def test_possibly_stuck_flag(client, make_episode):
    stuck = await make_episode(status="TRANSCRIBING", status_changed_at=NOW - timedelta(hours=1, minutes=50))
    fresh = await make_episode(status="TRANSCRIBING", status_changed_at=NOW - timedelta(minutes=5))

    response = await client.get(URL)

    flags = {item["id"]: item["possibly_stuck"] for item in response.json()["in_progress"]["items"]}
    assert flags == {str(stuck.id): True, str(fresh.id): False}


async def test_default_window_is_24_hours(client, make_episode):
    old_ready = await make_episode(status="READY", status_changed_at=NOW - timedelta(days=2))

    default = await client.get(URL)
    widened = await client.get(URL, params={"since": (NOW - timedelta(days=3)).isoformat()})

    assert default.json()["finished"]["items"] == []
    assert [i["id"] for i in widened.json()["finished"]["items"]] == [str(old_ready.id)]


async def test_naive_since_treated_as_utc(client):
    response = await client.get(URL, params={"since": "2026-01-01T00:00:00"})

    assert response.status_code == 200


async def test_limit_must_be_positive(client):
    response = await client.get(URL, params={"limit": 0})

    assert response.status_code == 422

async def test_reset_all_errors(client, db_session, make_episode):
    first = await make_episode(status="ERROR", status_changed_at=NOW)
    second = await make_episode(status="ERROR", status_changed_at=NOW)
    ready = await make_episode(status="READY", status_changed_at=NOW)

    response = await client.post(f"{URL}/errors/reset")

    assert response.status_code == 200
    assert response.json() == {"reset": 2}
    for episode in (first, second):
        await db_session.refresh(episode)
        assert episode.pipeline_status == "PENDING"
    await db_session.refresh(ready)
    assert ready.pipeline_status == "READY"


async def test_reset_all_errors_with_none(client):
    response = await client.post(f"{URL}/errors/reset")

    assert response.json() == {"reset": 0}
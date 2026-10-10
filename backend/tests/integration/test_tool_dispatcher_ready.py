import json

from src.models.db import EpisodeSpeaker, TranscriptSegment
from src.query.tool_dispatcher import ToolDispatcher


async def _seed(db, episode, name="Ada"):
    db.add(
        TranscriptSegment(
            episode_id=episode.id,
            speaker_id="SPEAKER_00",
            text="hello",
            start_ms=0,
            end_ms=1000,
            sequence_order=0,
        )
    )
    db.add(EpisodeSpeaker(episode_id=episode.id, speaker_id="SPEAKER_00", display_name=name))
    await db.commit()


async def test_episode_context_only_serves_ready_episodes(db_session, make_episode):
    ready = await make_episode(status="READY")
    pending = await make_episode(status="PENDING")
    await _seed(db_session, ready)
    await _seed(db_session, pending)
    dispatcher = ToolDispatcher(retriever=None)  # retriever unused by this tool

    ready_result = json.loads(
        await dispatcher._get_episode_context(db_session, str(ready.id), timestamp_ms=500)
    )
    pending_result = json.loads(
        await dispatcher._get_episode_context(db_session, str(pending.id), timestamp_ms=500)
    )

    assert ready_result["segments"][0]["speaker"] == "Ada"
    assert "error" in pending_result


async def test_speaker_profile_lists_only_ready_episodes(db_session, make_episode):
    ready = await make_episode(status="READY")
    pending = await make_episode(status="PENDING")
    await _seed(db_session, ready)
    await _seed(db_session, pending)
    dispatcher = ToolDispatcher(retriever=None)

    result = json.loads(await dispatcher._get_speaker_profile(db_session, "Ada"))

    assert [e["episode_id"] for e in result["episodes"]] == [str(ready.id)]
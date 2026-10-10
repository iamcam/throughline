from types import SimpleNamespace

from tests.conftest import make_pipeline_services
from src.ingestion import pipeline
from src.ingestion.pipeline import PipelineServices, ingest_episode
from src.ingestion.status_service import PipelineStatusService


class _Recorder:
    """An async callable that counts calls, optionally runs a side effect,
    and returns a canned result."""

    def __init__(self, on_call=None, result=None):
        self.calls = 0
        self._on_call = on_call
        self._result = result

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        if self._on_call:
            await self._on_call()
        return self._result


def _fake_downloader() -> SimpleNamespace:
    return SimpleNamespace(
        download=_Recorder(result="/tmp/fake-audio.mp3"),
        delete=_Recorder(),
    )


async def test_non_owner_stops_before_downloading(db_session, make_episode):
    episode = await make_episode(status="QUEUED", job_id="job-b")
    downloader = _fake_downloader()
    services = make_pipeline_services(
        status=PipelineStatusService().for_job("job-a"),
        downloader=downloader,
    )

    await ingest_episode(episode, {}, services, db_session)

    await db_session.refresh(episode)
    assert downloader.download.calls == 0
    assert episode.pipeline_status == "QUEUED"


async def test_reset_mid_transcription_stops_before_diarizing(db_session, make_episode):
    episode = await make_episode(status="QUEUED", job_id="job-a")

    async def reset_during_transcription():
        episode.ingestion_job_id = None
        episode.pipeline_status = "PENDING"
        await db_session.commit()

    transcribe = _Recorder(on_call=reset_during_transcription, result=object())
    diarize = _Recorder()
    services = make_pipeline_services(
        status=PipelineStatusService().for_job("job-a"),
        downloader=_fake_downloader(),
        transcription=SimpleNamespace(transcribe=transcribe),
        diarization=SimpleNamespace(diarize=diarize),
    )

    await ingest_episode(episode, {}, services, db_session)

    await db_session.refresh(episode)
    assert transcribe.calls == 1
    assert diarize.calls == 0
    assert episode.pipeline_status == "PENDING"
    assert episode.pipeline_error is None


async def test_reset_during_diarization_skips_transcript_save(db_session, make_episode, monkeypatch):
    episode = await make_episode(status="QUEUED", job_id="job-a")
    monkeypatch.setattr(pipeline, "align_segments", lambda segments, diarization: segments)

    async def reset_during_diarization():
        episode.ingestion_job_id = None
        episode.pipeline_status = "PENDING"
        await db_session.commit()

    save = _Recorder()
    services = make_pipeline_services(
        status=PipelineStatusService().for_job("job-a"),
        downloader=_fake_downloader(),
        transcription=SimpleNamespace(transcribe=_Recorder(result=SimpleNamespace(segments=[]))),
        diarization=SimpleNamespace(
            diarize=_Recorder(on_call=reset_during_diarization, result=SimpleNamespace(speaker_count=0))
        ),
        transcript_store=SimpleNamespace(save=save),
    )

    await ingest_episode(episode, {}, services, db_session)

    await db_session.refresh(episode)
    assert save.calls == 0
    assert episode.pipeline_status == "PENDING"
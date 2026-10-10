# tests/unit/test_pipeline_stages.py
import pytest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.config import Settings
from src.ingestion.pipeline_stages import stuck_thresholds, is_possibly_stuck

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
THRESHOLDS = {"DOWNLOADING": timedelta(minutes=60)}


@pytest.mark.parametrize(
    "minutes_in_stage, expected",
    [(59, False), (60, False), (61, True)],
    ids=["under", "at-boundary", "over"],
)
def test_threshold_boundary(minutes_in_stage, expected):
    changed_at = NOW - timedelta(minutes=minutes_in_stage)

    assert is_possibly_stuck("DOWNLOADING", changed_at, NOW, THRESHOLDS) is expected


@pytest.mark.parametrize("status", ["QUEUED", "READY", "ERROR", "PENDING"])
def test_non_active_status_never_stuck(status):
    long_ago = NOW - timedelta(days=30)

    assert is_possibly_stuck(status, long_ago, NOW, THRESHOLDS) is False


def test_missing_timestamp_never_stuck():
    assert is_possibly_stuck("DOWNLOADING", None, NOW, THRESHOLDS) is False


def test_every_active_stage_has_a_threshold():
    from src.config import get_settings
    from src.ingestion.pipeline_stages import ACTIVE_STAGES, stuck_thresholds

    assert set(stuck_thresholds(get_settings())) == set(ACTIVE_STAGES)


def test_each_stage_reads_its_own_setting():
    settings = SimpleNamespace(
        stuck_threshold_downloading_min=1,
        stuck_threshold_transcribing_min=2,
        stuck_threshold_diarizing_min=3,
        stuck_threshold_inferring_speakers_min=4,
        stuck_threshold_chunking_min=5,
        stuck_threshold_embedding_min=6,
    )

    thresholds = stuck_thresholds(settings)

    assert {stage: t.total_seconds() / 60 for stage, t in thresholds.items()} == {
        "DOWNLOADING": 1,
        "TRANSCRIBING": 2,
        "DIARIZING": 3,
        "INFERRING_SPEAKERS": 4,
        "CHUNKING": 5,
        "EMBEDDING": 6,
    }


def test_threshold_overridable_from_env(monkeypatch):
    monkeypatch.setenv("STUCK_THRESHOLD_TRANSCRIBING_MIN", "120")

    assert Settings().stuck_threshold_transcribing_min == 120

def test_default_thresholds_below_task_timeout():
    settings = Settings()
    task_timeout = timedelta(seconds=settings.streaq_task_timeout)

    assert all(t < task_timeout for t in stuck_thresholds(settings).values())


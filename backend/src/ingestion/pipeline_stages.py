from datetime import datetime, timedelta

# Pipeline order. Single source for queue ordering (task 7) and stuck
# detection -- the frontend's ACTIVE_STATUSES mirrors this list.
ACTIVE_STAGES: tuple[str, ...] = (
    "DOWNLOADING",
    "TRANSCRIBING",
    "DIARIZING",
    "INFERRING_SPEAKERS",
    "CHUNKING",
    "EMBEDDING",
)

def stuck_thresholds(settings) -> dict[str, timedelta]:
    return {
        "DOWNLOADING": timedelta(minutes=settings.stuck_threshold_downloading_min),
        "TRANSCRIBING": timedelta(minutes=settings.stuck_threshold_transcribing_min),
        "DIARIZING": timedelta(minutes=settings.stuck_threshold_diarizing_min),
        "INFERRING_SPEAKERS": timedelta(minutes=settings.stuck_threshold_inferring_speakers_min),
        "CHUNKING": timedelta(minutes=settings.stuck_threshold_chunking_min),
        "EMBEDDING": timedelta(minutes=settings.stuck_threshold_embedding_min),
    }

def is_possibly_stuck(
    status: str,
    status_changed_at: datetime | None,
    now: datetime,
    thresholds: dict[str, timedelta],
) -> bool:
    threshold = thresholds.get(status)
    if threshold is None or status_changed_at is None:
        return False
    return now - status_changed_at > threshold

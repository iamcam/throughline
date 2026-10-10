# src/models/schemas.py
from pydantic import BaseModel, HttpUrl
from datetime import datetime
from uuid import UUID


class AddFeedRequest(BaseModel):
    rss_url: str  # validated as URL at the service layer


class FeedResponse(BaseModel):
    id: UUID
    rss_url: str
    title: str | None
    description: str | None
    image_url: str | None
    episode_count: int
    latest_episode_published_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class EpisodeResponse(BaseModel):
    id: UUID
    feed_id: UUID
    title: str | None
    description: str | None
    published_at: datetime | None
    duration_seconds: int | None
    pipeline_status: str
    pipeline_progress: float | None
    pipeline_error: str | None
    audio_url: str | None
    image_url: str | None

    model_config = {"from_attributes": True}


class TranscriptSegmentResponse(BaseModel):
    speaker_id: str
    display_name: str | None
    text: str
    start_ms: int
    end_ms: int
    sequence_order: int

class TranscriptResponse(BaseModel):
    episode_id: str
    segments: list[TranscriptSegmentResponse]


class PipelineStatusUpdate(BaseModel):
    status: str
    progress: float | None = None
    error: str | None = None

class IngestRequest(BaseModel):
    run_label: str | None = None

class SpeakerResponse(BaseModel):
    speaker_id: str
    display_name: str | None
    name_inferred: bool
    name_confirmed: bool
    confidence: str | None

    model_config = {"from_attributes": True}

class SpeakerPreviewResponse(BaseModel):
    speaker_id: str
    sample_quote: str
    sample_timestamp_ms: int

class UpdateSpeakerRequest(BaseModel):
    speaker_id: str
    display_name: str | None

class QueueFeedSummary(BaseModel):
    id: UUID
    title: str | None
    image_url: str | None

class QueueEpisodeItem(BaseModel):
    id: UUID
    title: str | None
    image_url: str | None
    published_at: datetime | None
    duration_seconds: int | None
    pipeline_status: str
    pipeline_error: str | None
    queued_at: datetime | None
    started_at: datetime | None
    status_changed_at: datetime | None
    possibly_stuck: bool
    feed: QueueFeedSummary

class QueueGroup(BaseModel):
    total: int
    items: list[QueueEpisodeItem]

class QueueResponse(BaseModel):
    queued: QueueGroup
    in_progress: QueueGroup
    finished: QueueGroup
    error: QueueGroup

class ResetCountResponse(BaseModel):
    reset: int
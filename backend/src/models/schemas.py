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
    created_at: datetime

    model_config = {"from_attributes": True}


class EpisodeResponse(BaseModel):
    id: UUID
    feed_id: UUID
    title: str | None
    published_at: datetime | None
    duration_seconds: int | None
    pipeline_status: str
    pipeline_stage: str | None
    pipeline_progress: float | None
    audio_url: str | None

    model_config = {"from_attributes": True}


class PipelineStatusUpdate(BaseModel):
    status: str
    stage: str | None = None
    progress: float | None = None
    position: int | None = None
    error: str | None = None

class IngestRequest(BaseModel):
    speaker_count_hint: int | None = None
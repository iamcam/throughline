from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, Text, Integer, Boolean, Float, DateTime, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from pgvector.sqlalchemy import Vector
import datetime
import uuid
from typing import List


class Base(DeclarativeBase):
    pass


class Feed(Base):
    __tablename__ = "feeds"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rss_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    last_fetched_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    episodes: Mapped[List["Episode"]] = relationship(
        back_populates="feed",
        cascade="all, delete-orphan"
    )


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    feed_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("feeds.id", ondelete="CASCADE"))

    guid: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    audio_url: Mapped[str | None] = mapped_column(Text)
    audio_local_path: Mapped[str | None] = mapped_column(Text)
    transcript_url: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)

    # Pipeline state — DB is source of truth, SSE reads from here
    pipeline_status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    pipeline_stage: Mapped[str | None] = mapped_column(Text)
    pipeline_progress: Mapped[float | None] = mapped_column(Float)
    pipeline_error: Mapped[str | None] = mapped_column(Text)
    ingestion_job_id: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    feed: Mapped["Feed"] = relationship(back_populates="episodes")
    speakers: Mapped[List["EpisodeSpeaker"]] = relationship(
        back_populates="episode",
        cascade="all, delete-orphan"
    )
    transcript_segments: Mapped[List["TranscriptSegment"]] = relationship(
        back_populates="episode",
        cascade="all, delete-orphan"
    )
    chunks: Mapped[List["Chunk"]] = relationship(
        back_populates="episode",
        cascade="all, delete-orphan"
    )


class EpisodeSpeaker(Base):
    __tablename__ = "episode_speakers"
    __table_args__ = (
        UniqueConstraint("episode_id", "speaker_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"))
    speaker_id: Mapped[str] = mapped_column(Text, nullable=False)  # "SPEAKER_00" - immutable - just one per episode (eg only one SPEAKER_00, ...01, etc per episode; maps to real name for display
    display_name: Mapped[str | None] = mapped_column(Text)  # the speaker's name to display
    name_inferred: Mapped[bool] = mapped_column(Boolean, default=False)
    name_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    episode: Mapped["Episode"] = relationship(back_populates="speakers")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"))
    speaker_id: Mapped[str] = mapped_column(Text, nullable=False)   # eg "SPEAKER_00"
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    sequence_order: Mapped[int] = mapped_column(Integer)

    episode: Mapped["Episode"] = relationship(back_populates="transcript_segments")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chunks.id"), nullable=True)
    chunk_level: Mapped[str] = mapped_column(Text, nullable=False)  # "parent" | "leaf"
    speaker_id: Mapped[str] = mapped_column(Text, nullable=False)   # eg "SPEAKER_00" from speaker diarisation
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    token_count: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list | None] = mapped_column(Vector(768))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    episode: Mapped["Episode"] = relationship(back_populates="chunks")
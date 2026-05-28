# src/ingestion/speaker_store.py
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from src.models.db import EpisodeSpeaker
from src.transcription.base import TranscriptResult

class SpeakerStore:
    async def initialize_from_transcript(
            self,
            episode_id: UUID,
            result: TranscriptResult,
            db: AsyncSession
    ) -> None:
        """
        Create one episode_speakers row per distinct speaker_id found in the transcript.
        display_name is null and will be filled by inference or user input. Safe to call on reingest,
        which will clear eisting rows first
        """
        await db.execute(
            delete(EpisodeSpeaker).where(
                EpisodeSpeaker.episode_id == episode_id
            )
        )

        seen = set()
        for segment in result.segments:
            if segment.speaker_id not in seen:
                seen.add(segment.speaker_id)
                db.add(EpisodeSpeaker(
                    id=uuid4(),
                    episode_id=episode_id,
                    speaker_id=segment.speaker_id,
                    display_name=None,
                    name_inferred=False,
                    name_confirmed=False
                ))

        await db.commit()

    async def save_inferred(
            self,
            episode_id: UUID,
            names: dict[str, str | None],
            db: AsyncSession
    ) -> None:
        """
        Update display_name and name_inferred for each speaker_id wher ethe LLM returns a name.
        Speakers with None are left with display_name=NULL
        """
        from sqlalchemy import update

        for speaker_id, name in names.items():
            if name is not None:
                await db.execute(
                    update(EpisodeSpeaker)
                    .where(EpisodeSpeaker.episode_id == episode_id)
                    .where(EpisodeSpeaker.speaker_id == speaker_id)
                    .values(display_name=name, name_inferred=True)
                )
        await db.commit()

    async def confirm_names(
            self,
            episode_id: UUID,
            names: list[dict],
            db: AsyncSession
    ) -> None:
        """
        Called from PUT at /speakers. Sets display_name and name_confirmed=True
        name_inferred preserved as-is, reflecting how the name was first obtained.
        """
        from sqlalchemy import update

        for entry in names:
            await db.execute(
                update(EpisodeSpeaker)
                .where(EpisodeSpeaker.episode_id == episode_id)
                .where(EpisodeSpeaker.speaker_id == entry["speaker_id"])
                .values(display_name=entry["display_name"], name_confirmed=True)
            )

        await db.commit()

    async def get_speakers(
            self,
            episode_id: UUID,
            db: AsyncSession
    ) -> list[EpisodeSpeaker]:
        result = await db.execute(
            select(EpisodeSpeaker)
            .where(EpisodeSpeaker.episode_id == episode_id)
            .order_by(EpisodeSpeaker.speaker_id)

        )
        return list(result.scalars().all())

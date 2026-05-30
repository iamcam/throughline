# src/ingestion/speaker_store.py
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update

from src.models.db import EpisodeSpeaker
from src.transcription.base import TranscriptResult
from src.ingestion.speaker_resolver import InferredSpeaker

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
            result: InferredSpeaker | None,
            db: AsyncSession
    ) -> None:
        """
        Update the SPEAKER_00 row ith the inferred name and confidence.
        If result is None, inference found nothing - leave row unchanged and let the pipeline continue with display_name = NULL.
        """
        if result is None:
            return

        await db.execute(
            update(EpisodeSpeaker)
            .where(EpisodeSpeaker.episode_id == episode_id)
            .where(EpisodeSpeaker.speaker_id == "UNKNOWN")
            .values(
                display_name=result.name,
                name_inferred=True,
                name_confirmed=False,
                confidence=result.confidence,
            )
        )
        await db.commit()

    async def confirm_names(
            self,
            episode_id: UUID,
            names: list[dict],
            db: AsyncSession
    ) -> None:
        """
        Called from PUT at /speakers. Sets display_name and name_confirmed=True.

        name_inferred reflects how the name was first obtained:
        - User confirms without editing: name_inferred unchanged, stays true
        - User edits the name: name_inferred=False (made as manual entry)
        """
        from sqlalchemy import update

        for entry in names:
            speaker = await db.scalar(
                select(EpisodeSpeaker)
                .where(EpisodeSpeaker.episode_id == episode_id)
                .where(EpisodeSpeaker.speaker_id == entry["speaker_id"])
            )
            if speaker is None:
                continue

            name_changed = speaker.display_name != entry["display_name"]
            await db.execute(
                update(EpisodeSpeaker)
                .where(EpisodeSpeaker.episode_id == episode_id)
                .where(EpisodeSpeaker.speaker_id == entry["speaker_id"])
                .values(
                    display_name=entry["display_name"],
                    name_confirmed=True,
                    name_inferred=False if name_changed else speaker.name_inferred
                )
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

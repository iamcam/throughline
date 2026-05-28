# src/ingestion/transcript_store.py
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete

from src.models.db import TranscriptSegment as TranscriptSegmentModel
from src.transcription.base import TranscriptResult


class TranscriptStore:
    async def save(
        self,
        episode_id: UUID,
        result: TranscriptResult,
        db: AsyncSession
    ) -> None:
        # Clear and start fresh in case we are re-ingesting
        await db.execute(
            delete(TranscriptSegmentModel).where(
                TranscriptSegmentModel.episode_id == episode_id
            )
        )

        for i, segment in enumerate(result.segments):
            db.add(TranscriptSegmentModel(
                episode_id=episode_id,
                speaker_id=segment.speaker_id, #eg "SPEAKER_00" label
                text=segment.text,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                sequence_order=i
            ))

        await db.commit()

    async def get_segments(
            self,
            episode_id: UUID,
            db: AsyncSession
    ) -> list[TranscriptSegmentModel]:
        from sqlalchemy import select
        result = await db.execute(
            select(TranscriptSegmentModel)
            .where(TranscriptSegmentModel.episode == episode_id)
            .order_by(TranscriptSegmentModel.sequence_order)
        )
        return list(result.scalars().all())
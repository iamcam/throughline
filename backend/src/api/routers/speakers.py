# src/api/routers/speakers.py
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.api.dependencies import get_db, get_speaker_store
from src.ingestion.speaker_store import SpeakerStore
from src.models.db import TranscriptSegment
from src.models.schemas import SpeakerResponse, SpeakerPreviewResponse, UpdateSpeakerRequest

router = APIRouter(prefix="/episodes", tags=["speakers"])

@router.get("/{episode_id}/speakers", response_model=list[SpeakerResponse])
async def get_speakers(
    episode_id: UUID,
    db: AsyncSession = Depends(get_db),
    speaker_store: SpeakerStore = Depends(get_speaker_store)
):
    speakers = await speaker_store.get_speakers(episode_id, db)
    if not speakers:
        raise HTTPException(status_code=404, detail="No speakers found for this episode")
    return speakers

# FYI: Route order matters with FastAPI. Path components get gobbled up by variable matching where there are similar paths, eg /speakers/preview would get gobbled by /speakers/{somevar} if the {somevar} came first, assuming "previewe" was just another var.

@router.get("/{episode_id}/speakers/preview", response_model=list[SpeakerPreviewResponse])
async def get_speakers_preview(
    episode_id: UUID,
    db: AsyncSession = Depends(get_db),
    speaker_store: SpeakerStore = Depends(get_speaker_store),
):
    """
    Returns a sample quote per speaker - the first segment with more than 20 words.
    Useful for the UI to show the user who is speaking before they confirm or correct the inferred name.
    """
    # NOTE: this could be optimized if we were to include inference or diarization hints into the episode_speakers table, such as inference_start_ms, which would map to start_ms on transcript_segments.

    speakers = await speaker_store.get_speakers(episode_id, db)
    if not speakers:
        raise HTTPException(status_code=404, detail="No speakers found for this episode")

    previews = []
    for speaker in speakers:
        result = await db.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.episode_id == episode_id)
            .where(TranscriptSegment.speaker_id == speaker.speaker_id)
            .order_by(TranscriptSegment.sequence_order)
        )
        segments = result.scalars().all()

        sample = next(
            (s for s in segments if len(s.text.split()) > 20),
            segments[0] if segments else None,
        )
        if sample:
            previews.append(SpeakerPreviewResponse(
                speaker_id=speaker.speaker_id,
                sample_quote=sample.text,
                sample_timestamp_ms=sample.start_ms,
            ))

    return previews

@router.put("/{episode_id}/speakers", status_code=200)
async def update_speakers(
    episode_id: UUID,
    updates: list[UpdateSpeakerRequest],
    db: AsyncSession = Depends(get_db),
    speaker_store: SpeakerStore = Depends(get_speaker_store),
):
    """
    Confirm or correct speaker names. No pipeline effect — this is a metadata-only operation. Chunks and embeddings are unchanged.
    """
    speakers = await speaker_store.get_speakers(episode_id, db)
    if not speakers:
        raise HTTPException(status_code=404, detail="No speakers found for this episode")

    await speaker_store.confirm_names(
        episode_id,
        [u.model_dump() for u in updates],
        db,
    )
    return {"status": "ok"}
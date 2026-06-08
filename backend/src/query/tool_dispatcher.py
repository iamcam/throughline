# src/query/tool_dispatcher.py
from __future__ import annotations
import json
import logging
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import EpisodeSpeaker, TranscriptSegment, Episode
from src.models.db import EpisodeSpeaker, TranscriptSegment
from src.query.retriever import Retriever
from src.query.session_store import ChatSession
from src.storage.vector_store import SearchFilters
from src.llm.base import ToolCall

logger = logging.getLogger(__name__)


class ToolDispatcher:

    def __init__(self, retriever: Retriever):
        self._retriever = retriever


    async def dispatch(
        self,
        tool_call: ToolCall,
        session: ChatSession,
        db: AsyncSession,
    ) -> str:
        try:
            if tool_call.name == "search_knowledge_base":
                return await self._search_knowledge_base(
                    db, session, **tool_call.arguments
                )
            elif tool_call.name == "get_episode_context":
                return await self._get_episode_context(
                    db, **tool_call.arguments
                )
            elif tool_call.name == "get_speaker_profile":
                return await self._get_speaker_profile(
                    db, **tool_call.arguments
                )
            else:
                logger.warning(f"Unknown tool called: {tool_call.name}")
                return json.dumps({"error": f"Unknown tool: {tool_call.name}"})
        except Exception as e:
            logger.exception(f"Tool dispatch failed for {tool_call.name}: {e}")
            return json.dumps({"error": f"Tool execution failed: {str(e)}"})


    # ~~~~~~ Tools ~~~~~~


    async def _search_knowledge_base(
        self,
        db: AsyncSession,
        session: ChatSession,
        query: str,
        speaker_name: str | None = None,
        episode_id: str | None = None,
        top_k: int = 5,
    ) -> str:
        # Resolve speaker display name → speaker_id if provided
        speaker_id: str | None = None
        if speaker_name:
            speaker_query = (
                select(EpisodeSpeaker.speaker_id, EpisodeSpeaker.episode_id)
                .join(Episode, EpisodeSpeaker.episode_id == Episode.id)
                .where(EpisodeSpeaker.display_name == speaker_name)
            )
            if session.scope_feed_ids:
                speaker_query = speaker_query.where(
                    Episode.feed_id.in_(session.scope_feed_ids)
                )
            row = await db.execute(speaker_query.limit(1))
            result = row.first()
            if result:
                speaker_id = result.speaker_id
            else:
                logger.info(f"Speaker name '{speaker_name}' not found in episode_speakers")

        filters = SearchFilters(
            feed_ids=session.scope_feed_ids or None,
            episode_ids=(
                [UUID(episode_id)] if episode_id
                else session.scope_episode_ids or None
            ),
            speaker_id=speaker_id,
        )

        chunks = await self._retriever.search(
            query=query,
            filters=filters,
            db=db,
            top_k=top_k,
        )

        if not chunks:
            return json.dumps({"results": [], "message": "No relevant content found."})

        session.citations.extend([c.to_dict() for c in chunks])

        return json.dumps({
            "results": [c.to_dict() for c in chunks]
        })


    async def _get_episode_context(
        self,
        db: AsyncSession,
        episode_id: str,
        timestamp_ms: int,
        padding_ms: int = 30_000,
    ) -> str:
        window_start = timestamp_ms - padding_ms
        window_end = timestamp_ms + padding_ms

        rows = await db.execute(
            select(TranscriptSegment)
            .where(
                TranscriptSegment.episode_id == UUID(episode_id),
                TranscriptSegment.end_ms >= window_start,
                TranscriptSegment.start_ms <= window_end,
            )
            .order_by(TranscriptSegment.start_ms)
        )
        segments = rows.scalars().all()

        if not segments:
            return json.dumps({"error": "No transcript content found at that timestamp."})

        # Resolve speaker display names for all segments in one query
        speaker_ids = list({s.speaker_id for s in segments})
        ep_uuid = UUID(episode_id)
        name_rows = await db.execute(
            select(EpisodeSpeaker.speaker_id, EpisodeSpeaker.display_name)
            .where(
                EpisodeSpeaker.episode_id == ep_uuid,
                EpisodeSpeaker.speaker_id.in_(speaker_ids),
            )
        )
        display_names = {row.speaker_id: row.display_name for row in name_rows}

        formatted = [
            {
                "speaker": display_names.get(s.speaker_id) or "Unknown Speaker",
                "timestamp": s.start_ms,
                "text": s.text,
            }
            for s in segments
        ]

        return json.dumps({"episode_id": episode_id, "segments": formatted})


    async def _get_speaker_profile(
        self,
        db: AsyncSession,
        speaker_name: str,
    ) -> str:
        rows = await db.execute(
            select(EpisodeSpeaker)
            .where(EpisodeSpeaker.display_name == speaker_name)
        )
        speakers = rows.scalars().all()

        if not speakers:
            return json.dumps({"error": f"Speaker '{speaker_name}' not found."})

        episodes = [
            {
                "episode_id": str(s.episode_id),
                "speaker_id": s.speaker_id,
                "name_confirmed": s.name_confirmed,
            }
            for s in speakers
        ]

        return json.dumps({
            "speaker_name": speaker_name,
            "appears_in_episodes": len(episodes),
            "episodes": episodes,
        })
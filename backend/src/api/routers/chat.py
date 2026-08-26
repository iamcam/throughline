# src/api/routers/chat.py
from __future__ import annotations
import json
import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from uuid import UUID

from src.shared.db import get_db
from src.api.dependencies import get_session_store, get_query_engine
from src.query.engine import QueryEngine, LLMTimeoutError, DoneEvent, StatusEvent, TokenEvent
from src.query.session_store import SessionStore, ChatSession



logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


# ~~~~~~ Schemas ~~~~~~

class CreateSessionRequest(BaseModel):
    scope_feed_ids: list[UUID] = []
    scope_episode_ids: list[UUID] = []

class CreateSessionResponse(BaseModel):
    session_id: str
    scope_feed_ids: list[UUID]
    scope_episode_ids: list[UUID]


class ChatMessageRequest(BaseModel):
    message: str


class ChatMessageResponse(BaseModel):
    message: str
    session_id: str
    citations: list[dict] = []


class SessionHistoryResponse(BaseModel):
    session_id: str
    messages: list[dict]


# ~~~~~~ Endpoints ~~~~~~

@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(
    body: CreateSessionRequest,
    session_store: SessionStore = Depends(get_session_store),
) -> CreateSessionResponse:
    session_id = str(uuid.uuid4())
    session = ChatSession(
        session_id=session_id,
        scope_feed_ids=body.scope_feed_ids,
        scope_episode_ids=body.scope_episode_ids,
    )

    await session_store.save(session)
    return CreateSessionResponse(
        session_id=session_id,
        scope_feed_ids=body.scope_feed_ids,
        scope_episode_ids=body.scope_episode_ids,
    )


@router.post("/{session_id}/message", response_model=ChatMessageResponse)
async def send_message(
    session_id: str,
    body: ChatMessageRequest,
    db: AsyncSession = Depends(get_db),
    engine: QueryEngine = Depends(get_query_engine),
) -> ChatMessageResponse:
    try:
        response = await engine.chat(
            session_id=session_id,
            user_message=body.message,
            db=db,
        )
        return ChatMessageResponse(
            message=response.message,
            session_id=response.session_id,
            citations=response.citations
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except LLMTimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))


@router.post("/{session_id}/message/stream")
async def send_message_stream(
    session_id: str,
    body: ChatMessageRequest,
    db: AsyncSession = Depends(get_db),
    engine: QueryEngine = Depends(get_query_engine),
) -> EventSourceResponse:
    return EventSourceResponse(_sse_event_stream(engine, session_id, body.message, db))

@router.get("/{session_id}/history", response_model=SessionHistoryResponse)
async def get_history(
    session_id: str,
    session_store: SessionStore = Depends(get_session_store),
) -> SessionHistoryResponse:
    session = await session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return SessionHistoryResponse(
        session_id=session_id,
        messages=session.messages,
    )


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    session_store: SessionStore = Depends(get_session_store),
) -> None:
    session = await session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    await session_store.delete(session_id)


# ~~~~~~ Supporting ~~~~~~

def _error_type(e: Exception) -> str:
    if isinstance(e, ValueError):
        return "session_not_found"
    if isinstance(e, LLMTimeoutError):
        return "timeout"
    return "internal_error"


async def _sse_event_stream(
    engine: QueryEngine,
    session_id: str,
    message: str,
    db: AsyncSession,
):
    try:
        async for event in engine.chat_stream(session_id=session_id, user_message=message, db=db):
            if isinstance(event, StatusEvent):
                yield {"event": "status", "data": "{}"}
            elif isinstance(event, TokenEvent):
                yield {"event": "token", "data": json.dumps({"delta": event.delta})}
            elif isinstance(event, DoneEvent):
                yield {
                    "event": "done",
                    "data": json.dumps({"citations": event.citations, "session_id": event.session_id}),
                }
    except Exception as e:
        logger.warning(f"Error during chat stream (session={session_id}): {type(e).__name__}: {e}")
        yield {
            "event": "error",
            "data": json.dumps({"detail": str(e), "error_type": _error_type(e)}),
        }


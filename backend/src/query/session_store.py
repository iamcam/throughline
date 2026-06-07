# src/query/session_store.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID


# ~~~~~~ Session model ~~~~~~

@dataclass
class ChatSession:
    session_id: str
    scope_feed_id: UUID | None = None
    scope_episode_ids: list[UUID] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)


# ~~~~~~ Protocol ~~~~~~

class SessionStore(Protocol):
    async def get(self, session_id: str) -> ChatSession | None: ...
    async def save(self, session: ChatSession) -> None: ...
    async def delete(self, session_id: str) -> None: ...
    async def list_sessions(self) -> list[str]: ...


# ~~~~~~ In-memory implementation ~~~~~~

class InMemorySessionStore:
    def __init__(self):
        self._sessions: dict[str, ChatSession] = {}

    async def get(self, session_id: str) -> ChatSession | None:
        return self._sessions.get(session_id)

    async def save(self, session: ChatSession) -> None:
        self._sessions[session.session_id] = session

    async def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    async def list_sessions(self) -> list[str]:
        return list(self._sessions.keys())
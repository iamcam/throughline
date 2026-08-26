# src/query/engine.py
from __future__ import annotations
import logging
import json
import asyncio
import time

from dataclasses import dataclass
from sqlalchemy.ext.asyncio import AsyncSession
from opentelemetry import trace

from collections.abc import AsyncIterator

from src.llm.base import LLMClient, LLMResponse
from src.query.async_utils import with_heartbeat
from src.query.prompt_builder import PromptBuilder
from src.query.query_rewriter import QueryRewriter
from src.query.session_store import SessionStore, ChatSession
from src.query.stream_accumulator import StreamAccumulator
from src.query.tool_dispatcher import ToolDispatcher
from src.query.tools import TOOLS
from src.telemetry.tracer import tracer

STATUS_HEARTBEAT_SECONDS = 10.0

@dataclass
class StatusEvent:
    pass

@dataclass
class TokenEvent:
    delta: str

@dataclass
class DoneEvent:
    citations: list[dict]
    session_id: str

logger = logging.getLogger(__name__)

LLM_REQUEST_TIMEOUT_SECONDS = 60.0

@dataclass
class ChatResponse:
    message: str
    session_id: str
    citations: list[dict]

class LLMTimeoutError(Exception):
    """Raised when an LLM call exceeds the configured timeout."""



class QueryEngine:

    def __init__(
        self,
        llm_client: LLMClient,
        session_store: SessionStore,
        prompt_builder: PromptBuilder,
        tool_dispatcher: ToolDispatcher,
        query_rewriter: QueryRewriter,
        max_tool_rounds: int = 3,
    ):
        self._llm = llm_client
        self._session_store = session_store
        self._prompt_builder = prompt_builder
        self._dispatcher = tool_dispatcher
        self._rewriter = query_rewriter
        self._max_tool_rounds = max_tool_rounds
        self._stream_accumulator = StreamAccumulator()


    async def chat(
        self,
        session_id: str,
        user_message: str,
        db: AsyncSession,
    ) -> ChatResponse:
        content_parts: list[str] = []
        citations: list[dict] = []

        async for event in self.chat_stream(session_id, user_message, db):
            if isinstance(event, TokenEvent):
                content_parts.append(event.delta)
            elif isinstance(event, DoneEvent):
                citations = event.citations
            # StatusEvent ignored -- no client here to notify

        return ChatResponse(
            message="".join(content_parts),
            session_id=session_id,
            citations=citations,
        )


    async def chat_stream(
        self,
        session_id: str,
        user_message: str,
        db: AsyncSession,
    ) -> AsyncIterator[StatusEvent | TokenEvent | DoneEvent]:
        with tracer.start_as_current_span("chat") as span:
            span.set_attribute("openinference.span.kind", "CHAIN")
            span.set_attribute("session.id", session_id)

            try:
                session = await self._session_store.get(session_id)
                if session is None:
                    raise ValueError(f"Session not found: {session_id}")

                rewritten_query = await self._rewriter.rewrite(session, user_message)
                span.set_attribute("chat.original_query", user_message)
                span.set_attribute("chat.rewritten_query", rewritten_query)

                session.messages.append({"role": "user", "content": user_message})

                for round_num in range(self._max_tool_rounds):
                    messages = self._prompt_builder.build_messages(session)
                    if round_num == 0:
                        messages[-1] = {**messages[-1], "content": rewritten_query}

                    response = None
                    async for item in self._stream_round(messages, TOOLS, session_id, str(round_num)):
                        if isinstance(item, StatusEvent):
                            yield item
                        elif isinstance(item, str):
                            yield TokenEvent(delta=item)
                        else:
                            response = item  # this round's final LLMResponse

                    logger.info(f"finish_reason={response.finish_reason} tool_calls={len(response.tool_calls)}")

                    if not response.tool_calls:
                        break

                    session.messages.append({
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                            }
                            for tc in response.tool_calls
                        ],
                    })

                    for tc in response.tool_calls:
                        logger.info(f"Tool call: {tc.name} args={tc.arguments}")
                        result = await self._dispatcher.dispatch(tc, session, db)
                        session.messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })

                else:
                    logger.warning(f"Max tool rounds ({self._max_tool_rounds}) reached for session {session_id}")
                    synthesis_messages = self._prompt_builder.build_messages(session)
                    synthesis_messages.append({
                        "role": "user",
                        "content": "Based on the search results above, please provide your best answer now."
                    })
                    response = None
                    async for item in self._stream_round(synthesis_messages, None, session_id, "synthesis"):
                        if isinstance(item, StatusEvent):
                            yield item
                        elif isinstance(item, str):
                            yield TokenEvent(delta=item)
                        else:
                            response = item

                final_content = response.content or ""
                session.messages.append({"role": "assistant", "content": final_content})
                await self._session_store.save(session)

                span.set_attribute("chat.tool_rounds_used", round_num + 1)
                span.set_attribute("chat.citation_count", len(session.citations))
                span.set_status(trace.StatusCode.OK)

                yield DoneEvent(citations=session.citations, session_id=session_id)

            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, str(e))
                raise

    async def _stream_round(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        session_id: str,
        round_label: str,
    ) -> AsyncIterator[StatusEvent | str | LLMResponse]:
        ticked = with_heartbeat(
            self._stream_accumulator.accumulate(self._llm.stream(messages, tools=tools)),
            STATUS_HEARTBEAT_SECONDS,
        )
        start = time.monotonic()
        try:
            async for item in ticked:
                if time.monotonic() - start > LLM_REQUEST_TIMEOUT_SECONDS:
                    logger.warning(
                        f"LLM call timed out after {LLM_REQUEST_TIMEOUT_SECONDS}s "
                        f"(session={session_id}, round={round_label})"
                    )
                    raise LLMTimeoutError(f"LLM did not respond within {LLM_REQUEST_TIMEOUT_SECONDS}s")
                yield StatusEvent() if item is None else item
        finally:
            await ticked.aclose()
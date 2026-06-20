# src/query/engine.py
from __future__ import annotations
import logging
import json
import asyncio
from dataclasses import dataclass
from sqlalchemy.ext.asyncio import AsyncSession
from opentelemetry import trace

from src.llm.base import LLMClient, ToolCall
from src.query.prompt_builder import PromptBuilder
from src.query.session_store import SessionStore, ChatSession
from src.query.tool_dispatcher import ToolDispatcher
from src.query.tools import TOOLS
from src.telemetry.tracer import tracer


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
        max_tool_rounds: int = 3,
    ):
        self._llm = llm_client
        self._session_store = session_store
        self._prompt_builder = prompt_builder
        self._dispatcher = tool_dispatcher
        self._max_tool_rounds = max_tool_rounds

    async def chat(
        self,
        session_id: str,
        user_message: str,
        db: AsyncSession,
    ) -> ChatResponse:
        with tracer.start_as_current_span("chat") as span:
            span.set_attribute("session.id", session_id)

            try:
                session = await self._session_store.get(session_id)
                if session is None:
                    raise ValueError(f"Session not found: {session_id}")

                session.messages.append({"role": "user", "content": user_message})

                for round_num in range(self._max_tool_rounds):
                    messages = self._prompt_builder.build_messages(session)
                    try:
                        response = await asyncio.wait_for(
                            self._llm.complete(messages, tools=TOOLS),
                            timeout=LLM_REQUEST_TIMEOUT_SECONDS
                        )

                    except asyncio.TimeoutError:
                        logger.warning(
                            f"LLM call timed out after {LLM_REQUEST_TIMEOUT_SECONDS}s "
                            f"(session={session_id}, round={round_num})"
                        )
                        raise LLMTimeoutError(
                            f"LLM did not respond within {LLM_REQUEST_TIMEOUT_SECONDS}s"
                        )

                    logger.info(f"finish_reason={response.finish_reason} tool_calls={len(response.tool_calls)}")

                    if not response.tool_calls:
                        # LLM has a final answer — exit the loop
                        break

                    # Append the assistant's tool call message to history
                    # The LLM needs to see its own tool calls in context
                    session.messages.append({
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in response.tool_calls
                        ],
                    })

                    # Execute each tool call and append results
                    for tc in response.tool_calls:
                        logger.info(f"Tool call: {tc.name} args={tc.arguments}")
                        result = await self._dispatcher.dispatch(tc, session, db)
                        session.messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })

                else:
                    # Loop exhausted without a clean break
                    logger.warning(f"Max tool rounds ({self._max_tool_rounds}) reached for session {session_id}")
                    # Explicitly instruct the model to synthesize from what it found
                    synthesis_messages = self._prompt_builder.build_messages(session)
                    synthesis_messages.append({
                        "role": "user",
                        "content": "Based on the search results above, please provide your best answer now."
                    })
                    try:
                        response = await asyncio.wait_for(
                            self._llm.complete(synthesis_messages),
                            timeout=LLM_REQUEST_TIMEOUT_SECONDS
                        )

                    except asyncio.TimeoutError:
                        logger.warning(
                            f"LLM synthesis call timed out after {LLM_REQUEST_TIMEOUT_SECONDS}s "
                            f"(session={session_id})"
                        )
                        raise LLMTimeoutError(
                            f"LLM did not respond within {LLM_REQUEST_TIMEOUT_SECONDS}s"
                        )


                final_content = response.content or ""
                session.messages.append({"role": "assistant", "content": final_content})
                await self._session_store.save(session)

                span.set_attribute("chat.tool_rounds_used", round_num + 1)
                span.set_attribute("chat.citation_count", len(session.citations))

                return ChatResponse(
                    message=final_content,
                    session_id=session_id,
                    citations=session.citations
                )

            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, str(e))
                raise
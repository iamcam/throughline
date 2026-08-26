# tests/unit/test_engine.py
from __future__ import annotations
import asyncio
import json
import pytest
import uuid

from src.query.engine import QueryEngine, ChatResponse, StatusEvent, TokenEvent, DoneEvent, LLMTimeoutError
from src.query.session_store import InMemorySessionStore, ChatSession
from src.query.prompt_builder import PromptBuilder
from src.query.stream_accumulator import MixedStreamResponseError
from src.query.tool_dispatcher import ToolDispatcher
from src.llm.base import ToolCall, LLMResponse, StreamChunk, ToolCallDelta
from tests.conftest import MockLLMClient
from unittest.mock import AsyncMock, MagicMock

import src.query.engine as engine_module

# ~~~~~~ Helpers ~~~~~~

def make_session(session_id: str = "test-session") -> ChatSession:
    return ChatSession(session_id=session_id)


def make_mock_dispatcher():
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value='{"results": []}')
    return dispatcher


def content_round(text: str) -> list[StreamChunk]:
    """One round's StreamChunk sequence for a plain-text (non-tool) response."""
    return [StreamChunk(content_delta=text, finish_reason="stop")]


def tool_call_round(tool_calls: list[ToolCall]) -> list[StreamChunk]:
    """One round's StreamChunk sequence for a tool-call response. Each
    ToolCall's arguments are serialized whole in a single delta -- fragmented
    argument reconstruction is already covered by test_stream_accumulator.py;
    here we only care that the right ToolCall ends up dispatched."""
    deltas = [
        ToolCallDelta(index=i, id=tc.id, name=tc.name, arguments_delta=json.dumps(tc.arguments))
        for i, tc in enumerate(tool_calls)
    ]
    return [StreamChunk(tool_call_deltas=deltas, finish_reason="tool_calls")]


class PassthroughQueryRewriter:
    """Stub QueryRewriter that returns the user message unchanged. Used by
    tests that aren't exercising rewrite behavior itself, so they don't
    depend on -- or consume response slots from -- a real rewrite call."""
    async def rewrite(self, session, user_message):
        return user_message


class StubQueryRewriter:
    """Configurable QueryRewriter stub for tests that ARE exercising rewrite
    behavior. Records the session's message history as it existed at call
    time (a snapshot, since session.messages is mutated in place afterward)
    so tests can assert on call ordering."""
    def __init__(self, rewritten: str):
        self._rewritten = rewritten
        self.captured_history = None
        self.captured_user_message = None

    async def rewrite(self, session, user_message):
        self.captured_history = list(session.messages)
        self.captured_user_message = user_message
        return self._rewritten


def make_engine(llm, session_store=None, dispatcher=None, rewriter=None, max_tool_rounds=3) -> QueryEngine:
    store = session_store or InMemorySessionStore()
    return QueryEngine(
        llm_client=llm,
        session_store=store,
        prompt_builder=PromptBuilder(),
        tool_dispatcher=dispatcher or make_mock_dispatcher(),
        query_rewriter=rewriter or PassthroughQueryRewriter(),
        max_tool_rounds=max_tool_rounds,
    )

class MockDb:
    pass


# ~~~~~~ Tests ~~~~~~

@pytest.mark.asyncio
async def test_direct_response_requires_no_tool_calls():
    llm = MockLLMClient(stream_chunks=[content_round("I know some things.")])
    store = InMemorySessionStore()
    session = make_session()
    await store.save(session)

    engine = make_engine(llm, session_store=store)
    response = await engine.chat("test-session", "Tell me something.", MockDb())

    assert response.message == "I know some things."
    assert response.session_id == "test-session"


@pytest.mark.asyncio
async def test_tool_call_dispatched_and_result_appended():
    # Only round configured -- clamp-to-last means the synthesis call (round
    # exhausted at max_tool_rounds=1) replays the same tool-call chunks too,
    # same as the old MockLLMClient(tool_calls=...) shorthand did with complete().
    llm = MockLLMClient(stream_chunks=[
        tool_call_round([ToolCall(id="tc1", name="search_knowledge_base", arguments={"query": "consciousness"})])
    ])
    dispatcher = make_mock_dispatcher()
    store = InMemorySessionStore()
    session = make_session()
    await store.save(session)

    engine = make_engine(llm, session_store=store, dispatcher=dispatcher, max_tool_rounds=1)
    await engine.chat("test-session", "What does Marcus think about consciousness?", MockDb())

    dispatcher.dispatch.assert_called_once()
    call_args = dispatcher.dispatch.call_args
    assert call_args[0][0].name == "search_knowledge_base"


@pytest.mark.asyncio
async def test_multi_turn_history_maintained():
    llm = MockLLMClient(stream_chunks=[content_round("That's an interesting follow-up.")])
    store = InMemorySessionStore()
    session = make_session()
    await store.save(session)
    engine = make_engine(llm, session_store=store)

    await engine.chat("test-session", "First message.", MockDb())
    await engine.chat("test-session", "Follow-up message.", MockDb())

    saved = await store.get("test-session")
    roles = [m["role"] for m in saved.messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert saved.messages[0]["content"] == "First message."
    assert saved.messages[2]["content"] == "Follow-up message."


@pytest.mark.asyncio
async def test_session_not_found_raises_value_error():
    llm = MockLLMClient(stream_chunks=[content_round("anything")])
    engine = make_engine(llm)
    with pytest.raises(ValueError, match="Session not found"):
        await engine.chat("nonexistent-session", "Hello.", MockDb())


@pytest.mark.asyncio
async def test_max_tool_rounds_respected():
    # Always returns a tool call -- should hit the round limit
    llm = MockLLMClient(stream_chunks=[
        tool_call_round([ToolCall(id="tc1", name="search_knowledge_base", arguments={"query": "test"})])
    ])
    dispatcher = make_mock_dispatcher()
    store = InMemorySessionStore()
    session = make_session()
    await store.save(session)

    engine = make_engine(llm, session_store=store, dispatcher=dispatcher, max_tool_rounds=2)
    await engine.chat("test-session", "Keep searching.", MockDb())

    assert dispatcher.dispatch.call_count == 2


@pytest.mark.asyncio
async def test_assistant_tool_call_message_appended_before_result():
    llm = MockLLMClient(stream_chunks=[
        tool_call_round([ToolCall(id="tc1", name="search_knowledge_base", arguments={"query": "test"})]),
        content_round("Here is my answer."),
    ])
    store = InMemorySessionStore()
    session = make_session()
    await store.save(session)

    engine = make_engine(llm, session_store=store, max_tool_rounds=1)
    await engine.chat("test-session", "Search for something.", MockDb())

    saved = await store.get("test-session")
    roles = [m["role"] for m in saved.messages]
    # user --> assistant (tool call) --> tool (result) -> assistant (final)
    assert roles == ["user", "assistant", "tool", "assistant"]


@pytest.mark.asyncio
async def test_final_response_saved_to_session():
    llm = MockLLMClient(stream_chunks=[content_round("Final answer here.")])
    store = InMemorySessionStore()
    session = make_session()
    await store.save(session)

    engine = make_engine(llm, session_store=store)
    await engine.chat("test-session", "A question.", MockDb())

    saved = await store.get("test-session")
    last_message = saved.messages[-1]
    assert last_message["role"] == "assistant"
    assert last_message["content"] == "Final answer here."


@pytest.mark.asyncio
async def test_none_content_returns_empty_string():
    # A round with no content and no tool calls at all.
    llm = MockLLMClient(stream_chunks=[[StreamChunk(finish_reason="stop")]])
    store = InMemorySessionStore()
    session = make_session()
    await store.save(session)

    engine = make_engine(llm, session_store=store)
    response = await engine.chat("test-session", "Hello.", MockDb())

    assert response.message == ""


@pytest.mark.asyncio
async def test_citations_returned_in_response():
    llm = MockLLMClient(stream_chunks=[
        tool_call_round([ToolCall(id="tc1", name="search_knowledge_base", arguments={"query": "consciousness"})]),
        content_round("Here is what I found."),
    ])
    dispatcher = make_mock_dispatcher()
    store = InMemorySessionStore()
    session = make_session()
    session.citations = [{"chunk_id": "abc", "display_name": "Marcus Webb"}]
    await store.save(session)

    engine = make_engine(llm, session_store=store, dispatcher=dispatcher, max_tool_rounds=1)
    response = await engine.chat("test-session", "What does Marcus think?", MockDb())

    assert len(response.citations) > 0


# ~~~~~~ Query rewriting ~~~~~~

@pytest.mark.asyncio
async def test_round_zero_llm_call_uses_rewritten_query():
    llm = MockLLMClient(stream_chunks=[content_round("Marcus has said he's skeptical of near-term AGI.")])
    rewriter = StubQueryRewriter(rewritten="Marcus Webb views on AGI timelines")
    store = InMemorySessionStore()
    session = make_session()
    await store.save(session)

    engine = make_engine(llm, session_store=store, rewriter=rewriter)
    await engine.chat("test-session", "what does he think about that?", MockDb())

    # last_stream_messages, not last_messages -- chat() now calls stream(), never complete()
    assert llm.last_stream_messages[-1]["content"] == "Marcus Webb views on AGI timelines"


@pytest.mark.asyncio
async def test_original_user_message_persisted_not_rewritten():
    llm = MockLLMClient(stream_chunks=[content_round("Marcus has said he's skeptical of near-term AGI.")])
    rewriter = StubQueryRewriter(rewritten="Marcus Webb views on AGI timelines")
    store = InMemorySessionStore()
    session = make_session()
    await store.save(session)

    engine = make_engine(llm, session_store=store, rewriter=rewriter)
    await engine.chat("test-session", "what does he think about that?", MockDb())

    saved = await store.get("test-session")
    assert saved.messages[0]["content"] == "what does he think about that?"


@pytest.mark.asyncio
async def test_rewriter_called_before_current_turn_appended_to_history():
    llm = MockLLMClient(stream_chunks=[content_round("anything")])
    rewriter = StubQueryRewriter(rewritten="anything")
    store = InMemorySessionStore()
    session = make_session()
    await store.save(session)

    engine = make_engine(llm, session_store=store, rewriter=rewriter)
    await engine.chat("test-session", "first message", MockDb())

    # rewrite() should have seen an empty history -- the current turn hadn't
    # been appended to session.messages yet when it was called
    assert rewriter.captured_history == []
    assert rewriter.captured_user_message == "first message"


@pytest.mark.asyncio
async def test_rewrite_not_reapplied_on_later_tool_rounds():
    llm = MockLLMClient(stream_chunks=[
        tool_call_round([ToolCall(id="tc1", name="search_knowledge_base", arguments={"query": "test"})]),
        content_round("Here is my answer."),
    ])
    rewriter = StubQueryRewriter(rewritten="rewritten text that should not leak into round 1")
    dispatcher = make_mock_dispatcher()
    store = InMemorySessionStore()
    session = make_session()
    await store.save(session)

    engine = make_engine(llm, session_store=store, dispatcher=dispatcher, rewriter=rewriter, max_tool_rounds=2)
    await engine.chat("test-session", "search for something", MockDb())

    # round 1's messages should end with the tool result, not a
    # re-substituted rewritten query
    assert llm.last_stream_messages[-1]["role"] == "tool"


# ~~~~~~ chat_stream() ~~~~~~

@pytest.mark.asyncio
async def test_chat_stream_yields_tokens_for_content_round():
    llm = MockLLMClient(stream_chunks=[content_round("Hello there")])
    store = InMemorySessionStore()
    session = make_session()
    await store.save(session)
    engine = make_engine(llm, session_store=store)

    events = [event async for event in engine.chat_stream("test-session", "hi", MockDb())]

    token_events = [e for e in events if isinstance(e, TokenEvent)]
    assert "".join(e.delta for e in token_events) == "Hello there"
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].session_id == "test-session"


@pytest.mark.asyncio
async def test_chat_stream_no_tokens_during_tool_round():
    llm = MockLLMClient(stream_chunks=[
        tool_call_round([ToolCall(id="tc1", name="search_knowledge_base", arguments={"query": "test"})]),
        content_round("Found it."),
    ])
    dispatcher = make_mock_dispatcher()
    store = InMemorySessionStore()
    session = make_session()
    await store.save(session)
    engine = make_engine(llm, session_store=store, dispatcher=dispatcher, max_tool_rounds=2)

    events = [event async for event in engine.chat_stream("test-session", "search please", MockDb())]

    token_events = [e for e in events if isinstance(e, TokenEvent)]
    assert "".join(e.delta for e in token_events) == "Found it."
    dispatcher.dispatch.assert_called_once()
    assert isinstance(events[-1], DoneEvent)


@pytest.mark.asyncio
async def test_chat_stream_propagates_mixed_stream_error():
    class MixedLLMClient:
        async def stream(self, messages, tools=None, temperature=0.7):
            yield StreamChunk(content_delta="partial answer")
            yield StreamChunk(tool_call_deltas=[
                ToolCallDelta(index=0, id="tc1", name="search_knowledge_base", arguments_delta="{}")
            ], finish_reason="tool_calls")

    store = InMemorySessionStore()
    session = make_session()
    await store.save(session)
    engine = make_engine(MixedLLMClient(), session_store=store)

    with pytest.raises(MixedStreamResponseError):
        async for _event in engine.chat_stream("test-session", "hello", MockDb()):
            pass


@pytest.mark.asyncio
async def test_llm_timeout_raises(monkeypatch):
    monkeypatch.setattr(engine_module, "STATUS_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(engine_module, "LLM_REQUEST_TIMEOUT_SECONDS", 0.03)

    class HangingLLMClient:
        async def stream(self, messages, tools=None, temperature=0.7):
            await asyncio.Event().wait()
            yield  # pragma: no cover -- never reached

    store = InMemorySessionStore()
    session = make_session()
    await store.save(session)
    engine = make_engine(HangingLLMClient(), session_store=store)

    with pytest.raises(LLMTimeoutError):
        async for _event in engine.chat_stream("test-session", "hello", MockDb()):
            pass
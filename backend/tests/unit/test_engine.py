# tests/unit/test_engine.py
from __future__ import annotations
import uuid
import pytest

from src.query.engine import QueryEngine, ChatResponse
from src.query.session_store import InMemorySessionStore, ChatSession
from src.query.prompt_builder import PromptBuilder
from src.query.tool_dispatcher import ToolDispatcher
from src.llm.base import ToolCall, LLMResponse
from tests.conftest import MockLLMClient
from unittest.mock import AsyncMock, MagicMock


# ~~~~~~ Helpers ~~~~~~

def make_session(session_id: str = "test-session") -> ChatSession:
    return ChatSession(session_id=session_id)


def make_mock_dispatcher():
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value='{"results": []}')
    return dispatcher


def make_engine(llm, session_store=None, dispatcher=None, max_tool_rounds=3) -> QueryEngine:
    store = session_store or InMemorySessionStore()
    return QueryEngine(
        llm_client=llm,
        session_store=store,
        prompt_builder=PromptBuilder(),
        tool_dispatcher=dispatcher or make_mock_dispatcher(),
        max_tool_rounds=max_tool_rounds,
    )


class MockDb:
    pass


# ~~~~~~ Tests ~~~~~~

@pytest.mark.asyncio
async def test_direct_response_requires_no_tool_calls():
    llm = MockLLMClient(response_content="I know some things.")
    store = InMemorySessionStore()
    session = make_session()
    await store.save(session)

    engine = make_engine(llm, session_store=store)
    response = await engine.chat("test-session", "Tell me something.", MockDb())

    assert response.message == "I know some things."
    assert response.session_id == "test-session"


@pytest.mark.asyncio
async def test_tool_call_dispatched_and_result_appended():
    # First call returns a tool call, second returns the final answer
    llm = MockLLMClient(tool_calls=[
        ToolCall(id="tc1", name="search_knowledge_base", arguments={"query": "consciousness"})
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
    llm = MockLLMClient(response_content="That's an interesting follow-up.")
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
    llm = MockLLMClient(response_content="anything")
    engine = make_engine(llm)
    with pytest.raises(ValueError, match="Session not found"):
        await engine.chat("nonexistent-session", "Hello.", MockDb())


@pytest.mark.asyncio
async def test_max_tool_rounds_respected():
    # Always returns tool calls — should hit the round limit
    llm = MockLLMClient(tool_calls=[
        ToolCall(id="tc1", name="search_knowledge_base", arguments={"query": "test"})
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
    llm = MockLLMClient(responses=[
        LLMResponse(tool_calls=[
            ToolCall(id="tc1", name="search_knowledge_base", arguments={"query": "test"})
        ]),
        LLMResponse(content="Here is my answer."),
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
    llm = MockLLMClient(response_content="Final answer here.")
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
    llm = MockLLMClient(response_content=None)
    store = InMemorySessionStore()
    session = make_session()
    await store.save(session)

    engine = make_engine(llm, session_store=store)
    response = await engine.chat("test-session", "Hello.", MockDb())

    assert response.message == ""


@pytest.mark.asyncio
async def test_citations_returned_in_response():
    llm = MockLLMClient(responses=[
        LLMResponse(tool_calls=[
            ToolCall(id="tc1", name="search_knowledge_base", arguments={"query": "consciousness"})
        ]),
        LLMResponse(content="Here is what I found."),
    ])
    dispatcher = make_mock_dispatcher()
    store = InMemorySessionStore()
    session = make_session()
    session.citations = [{"chunk_id": "abc", "display_name": "Marcus Webb"}]
    await store.save(session)

    engine = make_engine(llm, session_store=store, dispatcher=dispatcher, max_tool_rounds=1)
    response = await engine.chat("test-session", "What does Marcus think?", MockDb())

    assert len(response.citations) > 0
# tests/unit/test_query_rewriter.py
import asyncio
import pytest

from src.llm.base import LLMResponse
from src.query.query_rewriter import QueryRewriter
from src.query.session_store import ChatSession
from tests.conftest import MockLLMClient


class SlowLLMClient:
    """Sleeps past whatever timeout the test configures, to exercise the
    fallback path without waiting on the real QUERY_REWRITE_TIMEOUT_SECONDS."""
    def __init__(self, delay: float):
        self._delay = delay

    async def complete(self, messages, tools=None, response_format=None, temperature=0.7):
        await asyncio.sleep(self._delay)
        return LLMResponse(content='{"rewritten_query": "should never arrive"}')


class ErrorLLMClient:
    async def complete(self, messages, tools=None, response_format=None, temperature=0.7):
        raise RuntimeError("LLM backend unreachable")


def make_session(messages: list[dict] | None = None) -> ChatSession:
    return ChatSession(session_id="sess-1", messages=messages or [])


# --- happy path ---

@pytest.mark.asyncio
async def test_rewrites_vague_query_using_context():
    mock = MockLLMClient('{"rewritten_query": "Marcus Webb views on consciousness and AI"}')
    rewriter = QueryRewriter(llm_client=mock)
    session = make_session([
        {"role": "user", "content": "What has Marcus Webb said about consciousness?"},
        {"role": "assistant", "content": "Marcus has argued that consciousness may not require biological substrates."},
    ])
    result = await rewriter.rewrite(session, "What does he think about that?")
    assert result == "Marcus Webb views on consciousness and AI"


@pytest.mark.asyncio
async def test_passthrough_when_already_specific():
    mock = MockLLMClient('{"rewritten_query": "Elena Vasquez views on synthetic biology regulation"}')
    rewriter = QueryRewriter(llm_client=mock)
    session = make_session()
    result = await rewriter.rewrite(session, "Elena Vasquez views on synthetic biology regulation")
    assert result == "Elena Vasquez views on synthetic biology regulation"


@pytest.mark.asyncio
async def test_temperature_zero_used():
    mock = MockLLMClient('{"rewritten_query": "unchanged"}')
    rewriter = QueryRewriter(llm_client=mock)
    await rewriter.rewrite(make_session(), "unchanged")
    assert mock.last_temperature == 0.0


# --- prompt / history construction ---

@pytest.mark.asyncio
async def test_history_formatted_with_role_labels():
    mock = MockLLMClient('{"rewritten_query": "x"}')
    rewriter = QueryRewriter(llm_client=mock)
    session = make_session([
        {"role": "user", "content": "What has Marcus Webb said about AI?"},
        {"role": "assistant", "content": "Marcus discussed AI consciousness at length."},
    ])
    await rewriter.rewrite(session, "what about risk?")
    prompt = mock.last_messages[0]["content"]
    assert "user: What has Marcus Webb said about AI?" in prompt
    assert "assistant: Marcus discussed AI consciousness at length." in prompt


@pytest.mark.asyncio
async def test_history_excludes_tool_call_and_tool_result_messages():
    mock = MockLLMClient('{"rewritten_query": "x"}')
    rewriter = QueryRewriter(llm_client=mock)
    session = make_session([
        {"role": "user", "content": "What has Marcus Webb said about AI?"},
        {"role": "assistant", "tool_calls": [
            {"id": "tc1", "type": "function", "function": {"name": "search_knowledge_base", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "tc1", "content": '{"results": []}'},
        {"role": "assistant", "content": "Marcus discussed AI consciousness at length."},
    ])
    await rewriter.rewrite(session, "what about risk?")
    prompt = mock.last_messages[0]["content"]
    assert "search_knowledge_base" not in prompt
    assert "tool_call_id" not in prompt


@pytest.mark.asyncio
async def test_no_prior_turns_uses_placeholder():
    mock = MockLLMClient('{"rewritten_query": "x"}')
    rewriter = QueryRewriter(llm_client=mock)
    await rewriter.rewrite(make_session(), "hello")
    prompt = mock.last_messages[0]["content"]
    assert "(no prior turns)" in prompt


# --- fallback cases: always return usable text, never raise ---

@pytest.mark.asyncio
async def test_falls_back_to_original_on_malformed_json():
    mock = MockLLMClient("Sorry, I'm not sure how to rewrite that.")
    rewriter = QueryRewriter(llm_client=mock)
    result = await rewriter.rewrite(make_session(), "what about that?")
    assert result == "what about that?"


@pytest.mark.asyncio
async def test_falls_back_to_original_when_field_missing():
    mock = MockLLMClient('{"note": "no rewritten_query key here"}')
    rewriter = QueryRewriter(llm_client=mock)
    result = await rewriter.rewrite(make_session(), "what about that?")
    assert result == "what about that?"


@pytest.mark.asyncio
async def test_falls_back_to_original_when_field_empty_string():
    mock = MockLLMClient('{"rewritten_query": ""}')
    rewriter = QueryRewriter(llm_client=mock)
    result = await rewriter.rewrite(make_session(), "what about that?")
    assert result == "what about that?"


@pytest.mark.asyncio
async def test_falls_back_to_original_when_field_not_a_string():
    mock = MockLLMClient('{"rewritten_query": 42}')
    rewriter = QueryRewriter(llm_client=mock)
    result = await rewriter.rewrite(make_session(), "what about that?")
    assert result == "what about that?"


@pytest.mark.asyncio
async def test_falls_back_to_original_on_timeout():
    rewriter = QueryRewriter(llm_client=SlowLLMClient(delay=0.2), timeout_seconds=0.05)
    result = await rewriter.rewrite(make_session(), "what about that?")
    assert result == "what about that?"


@pytest.mark.asyncio
async def test_falls_back_to_original_on_llm_exception():
    rewriter = QueryRewriter(llm_client=ErrorLLMClient())
    result = await rewriter.rewrite(make_session(), "what about that?")
    assert result == "what about that?"
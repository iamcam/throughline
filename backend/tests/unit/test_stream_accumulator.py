# tests/unit/test_stream_accumulator.py
import pytest

from src.llm.base import LLMResponse, StreamChunk, ToolCall, ToolCallDelta
from src.query.stream_accumulator import StreamAccumulator


async def _achunks(chunks: list[StreamChunk]):
    for chunk in chunks:
        yield chunk


async def _collect(accumulator: StreamAccumulator, chunks: list[StreamChunk]) -> list:
    return [item async for item in accumulator.accumulate(_achunks(chunks))]


@pytest.mark.asyncio
async def test_content_only_round_joins_deltas():
    chunks = [
        StreamChunk(content_delta="Hello "),
        StreamChunk(content_delta="world"),
        StreamChunk(finish_reason="stop"),
    ]
    items = await _collect(StreamAccumulator(), chunks)

    assert items == [
        "Hello ",
        "world",
        LLMResponse(content="Hello world", tool_calls=[], finish_reason="stop"),
    ]


@pytest.mark.asyncio
async def test_single_tool_call_round_reconstructs_arguments():
    chunks = [
        StreamChunk(tool_call_deltas=[
            ToolCallDelta(index=0, id="call_1", name="search_knowledge_base", arguments_delta='{"que'),
        ]),
        StreamChunk(tool_call_deltas=[
            ToolCallDelta(index=0, arguments_delta='ry": "AGI"}'),
        ], finish_reason="tool_calls"),
    ]
    items = await _collect(StreamAccumulator(), chunks)

    assert items == [
        LLMResponse(
            content=None,
            tool_calls=[ToolCall(id="call_1", name="search_knowledge_base", arguments={"query": "AGI"})],
            finish_reason="tool_calls",
        ),
    ]


@pytest.mark.asyncio
async def test_parallel_tool_calls_reconstruct_by_index_regardless_of_interleaving():
    chunks = [
        StreamChunk(tool_call_deltas=[
            ToolCallDelta(index=0, id="call_1", name="search_knowledge_base", arguments_delta='{"query": "AGI"}'),
            ToolCallDelta(index=1, id="call_2", name="get_speaker_profile", arguments_delta='{"speaker_'),
        ]),
        StreamChunk(tool_call_deltas=[
            ToolCallDelta(index=1, arguments_delta='name": "Marcus"}'),
        ], finish_reason="tool_calls"),
    ]
    items = await _collect(StreamAccumulator(), chunks)

    assert items == [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCall(id="call_1", name="search_knowledge_base", arguments={"query": "AGI"}),
                ToolCall(id="call_2", name="get_speaker_profile", arguments={"speaker_name": "Marcus"}),
            ],
            finish_reason="tool_calls",
        ),
    ]


@pytest.mark.asyncio
async def test_content_before_tool_calls(caplog):
    """Content already streamed live before tool-call deltas arrive can't be
    unsent -- it's still yielded -- but the final response discards it and
    resolves as tool-only, with a warning logged."""
    chunks = [
        StreamChunk(content_delta="Hi"),
        StreamChunk(tool_call_deltas=[ToolCallDelta(index=0, id="call_1", name="x", arguments_delta="{}")],
                    finish_reason="tool_calls"),
    ]
    with caplog.at_level("WARNING"):
        items = await _collect(StreamAccumulator(), chunks)

    assert items == [
        "Hi",
        LLMResponse(content=None, tool_calls=[ToolCall(id="call_1", name="x", arguments={})], finish_reason="tool_calls"),
    ]
    assert "tool call deltas after content" in caplog.text


@pytest.mark.asyncio
async def test_content_after_tool_calls(caplog):
    """Content arriving after tool-call deltas have started hasn't been
    yielded yet, so it's dropped entirely rather than ever reaching the
    frontend."""
    chunks = [
        StreamChunk(tool_call_deltas=[ToolCallDelta(index=0, id="call_1", name="x", arguments_delta="{}")]),
        StreamChunk(content_delta="surprise"),
    ]
    with caplog.at_level("WARNING"):
        items = await _collect(StreamAccumulator(), chunks)

    assert items == [
        LLMResponse(content=None, tool_calls=[ToolCall(id="call_1", name="x", arguments={})], finish_reason="stop"),
    ]
    assert "content delta after tool call deltas" in caplog.text


@pytest.mark.asyncio
async def test_empty_stream_yields_empty_response():
    items = await _collect(StreamAccumulator(), [])

    assert items == [LLMResponse(content=None, tool_calls=[], finish_reason="stop")]


@pytest.mark.asyncio
async def test_malformed_tool_call_arguments_falls_back_to_empty_dict():
    chunks = [
        StreamChunk(tool_call_deltas=[
            ToolCallDelta(index=0, id="call_1", name="search_knowledge_base", arguments_delta="not json"),
        ], finish_reason="tool_calls"),
    ]
    items = await _collect(StreamAccumulator(), chunks)

    assert items == [
        LLMResponse(
            content=None,
            tool_calls=[ToolCall(id="call_1", name="search_knowledge_base", arguments={})],
            finish_reason="tool_calls",
        ),
    ]

@pytest.mark.asyncio
async def test_whitespace_only_content_before_tool_calls_does_not_raise():
    async def chunks():
        yield StreamChunk(content_delta="\n\n")
        yield StreamChunk(
            tool_call_deltas=[
                ToolCallDelta(index=0, id="call_1", name="search", arguments_delta="{}")
            ]
        )
        yield StreamChunk(finish_reason="tool_calls")

    accumulator = StreamAccumulator()
    items = [item async for item in accumulator.accumulate(chunks())]

    # whitespace-only delta should not be yielded as a token
    assert all(not isinstance(i, str) for i in items)
    final = items[-1]
    assert final.content is None
    assert final.tool_calls[0].name == "search"
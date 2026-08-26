# tests/unit/test_stream_accumulator.py
import pytest

from src.llm.base import LLMResponse, StreamChunk, ToolCall, ToolCallDelta
from src.query.stream_accumulator import MixedStreamResponseError, StreamAccumulator


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
async def test_content_then_tool_calls_raises_mixed_stream_error():
    chunks = [
        StreamChunk(content_delta="Hi"),
        StreamChunk(tool_call_deltas=[ToolCallDelta(index=0, id="call_1", name="x", arguments_delta="{}")]),
    ]
    with pytest.raises(MixedStreamResponseError):
        await _collect(StreamAccumulator(), chunks)


@pytest.mark.asyncio
async def test_tool_calls_then_content_raises_mixed_stream_error():
    chunks = [
        StreamChunk(tool_call_deltas=[ToolCallDelta(index=0, id="call_1", name="x", arguments_delta="{}")]),
        StreamChunk(content_delta="surprise"),
    ]
    with pytest.raises(MixedStreamResponseError):
        await _collect(StreamAccumulator(), chunks)


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
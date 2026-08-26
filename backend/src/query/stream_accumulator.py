# src/query/stream_accumulator.py
from collections.abc import AsyncIterator
import json
import logging

from src.llm.base import LLMResponse, StreamChunk, ToolCall

logger = logging.getLogger(__name__)


class MixedStreamResponseError(Exception):
    """Raised when a single round's stream produces both content and tool-call deltas."""


class _PendingToolCall:
    def __init__(self):
        self.id: str | None = None
        self.name: str | None = None
        self.arguments = ""


class StreamAccumulator:
    async def accumulate(
        self, chunks: AsyncIterator[StreamChunk]
    ) -> AsyncIterator[str | LLMResponse]:
        content_parts: list[str] = []
        tool_calls_by_index: dict[int, _PendingToolCall] = {}
        finish_reason = "stop"
        saw_content = False
        saw_tool_calls = False

        async for chunk in chunks:
            has_content = bool(chunk.content_delta and chunk.content_delta.strip())
            if has_content:
                if saw_tool_calls:
                    raise MixedStreamResponseError(
                        "Received content after tool call deltas in the same round"
                    )
                saw_content = True
                content_parts.append(chunk.content_delta)
                yield chunk.content_delta

            if chunk.tool_call_deltas:
                if saw_content:
                    raise MixedStreamResponseError(
                        "Received tool call deltas after content in the same round"
                    )
                saw_tool_calls = True
                for delta in chunk.tool_call_deltas:
                    pending = tool_calls_by_index.setdefault(delta.index, _PendingToolCall())
                    if delta.id is not None:
                        pending.id = delta.id
                    if delta.name is not None:
                        pending.name = delta.name
                    if delta.arguments_delta is not None:
                        pending.arguments += delta.arguments_delta

            if chunk.finish_reason is not None:
                finish_reason = chunk.finish_reason

        tool_calls = [
            self._finalize_tool_call(pending)
            for _, pending in sorted(tool_calls_by_index.items())
        ]

        yield LLMResponse(
            content="".join(content_parts) if saw_content else None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )

    def _finalize_tool_call(self, pending: _PendingToolCall) -> ToolCall:
        try:
            arguments = json.loads(pending.arguments) if pending.arguments else {}
        except (json.JSONDecodeError, TypeError):
            logger.info(f"Malformed streamed tool call arguments json string: {pending.arguments}")
            arguments = {}
        return ToolCall(id=pending.id, name=pending.name, arguments=arguments)
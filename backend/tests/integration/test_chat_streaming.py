# tests/integration/test_chat_streaming.py
import json
import pytest

from src.api.main import app
from src.llm.base import StreamChunk
from src.shared.llm import get_llm_client
from tests.conftest import MockLLMClient


def _parse_sse(raw_lines: list[str]) -> list[tuple[str, str]]:
    """Reconstruct (event, data) pairs from raw SSE text lines."""
    events = []
    event_type = None
    data_lines = []

    for line in raw_lines:
        if line.startswith("event:"):
            event_type = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].strip())
        elif line == "":
            if event_type is not None:
                events.append((event_type, "\n".join(data_lines)))
            event_type = None
            data_lines = []
    return events


@pytest.mark.asyncio
async def test_message_stream_returns_token_and_done_events(client):
    mock_llm = MockLLMClient(stream_chunks=[
        [StreamChunk(content_delta="Marcus talks about consciousness a lot.", finish_reason="stop")]
    ])
    app.dependency_overrides[get_llm_client] = lambda: mock_llm

    try:
        create_response = await client.post("/api/v1/chat/sessions", json={})
        session_id = create_response.json()["session_id"]

        raw_lines = []
        async with client.stream(
            "POST",
            f"/api/v1/chat/{session_id}/message/stream",
            json={"message": "What does Marcus think?"},
        ) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            async for line in response.aiter_lines():
                raw_lines.append(line)

        events = _parse_sse(raw_lines)
    finally:
        del app.dependency_overrides[get_llm_client]

    token_events = [json.loads(data)["delta"] for event, data in events if event == "token"]
    assert "".join(token_events) == "Marcus talks about consciousness a lot."

    done_events = [json.loads(data) for event, data in events if event == "done"]
    assert len(done_events) == 1
    assert done_events[0]["session_id"] == session_id
    assert done_events[0]["citations"] == []
# src/conftest.py
import uuid
from src.llm.base import LLMResponse, ToolCall
from src.query.result_hydrator import ChunkResult
from src.storage.vector_store import RawChunkResult


class MockLLMClient:
    """
    Configurable mock for LLMClient.

    For simple text responses:
        MockLLMClient(response_content='{"name": "Marcus", "confidence": "high"}')

    For tool call responses:
        MockLLMClient(tool_calls=[ToolCall(id="tc1", name="search_knowledge_base", arguments={"query": "consciousness"})])

    Inspect last_messages and last_temperature after calling complete()
    to assert on what was sent to the LLM.
    """
    def __init__(
        self,
        response_content: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        responses: list[LLMResponse] | None = None,
    ):
        if responses is not None:
            self._responses = responses
        else:
            self._responses = [
                LLMResponse(content=response_content, tool_calls=tool_calls or [])
            ]
        self._call_count = 0
        self.last_messages = None
        self.last_tools = None
        self.last_temperature = None

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_format: dict | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self.last_messages = messages
        self.last_tools = tools
        self.last_temperature = temperature
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        return self._responses[idx]

class MockEmbeddingClient:
    def __init__(self, vector: list[float] | None = None):
        self.last_texts = None
        self._vector = vector or [0.1] * 768

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.last_texts = texts
        return [self._vector]


class MockVectorStore:
    def __init__(self, results: list[RawChunkResult] | None = None):
        self.last_embedding = None
        self.last_filters = None
        self.last_top_k = None
        self._results = results or []

    async def search(self, embedding, filters, top_k=5, db=None):
        self.last_embedding = embedding
        self.last_filters = filters
        self.last_top_k = top_k
        return self._results


class MockHydrator:
    def __init__(self, results: list[ChunkResult] | None = None):
        self.last_raw = None
        self._results = results or []

    async def hydrate(self, raw, db):
        self.last_raw = raw
        return self._results


def make_chunk_result(episode_id=None, display_name="Ada Sinclair") -> ChunkResult:
    eid = episode_id or uuid.uuid4()
    return ChunkResult(
        chunk_id=str(uuid.uuid4()),
        text="Interesting content about machine learning.",
        parent_text="Broader context about ML.",
        episode_id=str(eid),
        episode_title="Synthetic Minds Ep. 1",
        audio_url="https://domain.ext/file.mp3",
        display_name=display_name,
        timestamp_display="1:00",
        start_ms=60_000,
        end_ms=90_000,
        similarity_score=0.88
    )

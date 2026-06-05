# src/api/routers/query.py

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from uuid import UUID

from src.api.dependencies import get_db, get_retriever
from src.query.retriever import Retriever
from src.query.result_hydrator import ChunkResult
from src.storage.vector_store import SearchFilters
from src.llm.base import LLMClient
from src.api.dependencies import get_llm_client
from src.llm.base import LLMResponse

router = APIRouter(prefix="/query", tags=["query"])


# ~~~~~~ Schemas ~~~~~~

class SimpleQueryRequest(BaseModel):
    question: str
    feed_id: UUID | None = None
    episode_ids: list[UUID] | None = None
    top_k: int = 5


class CitationResponse(BaseModel):
    chunk_id: str
    episode_id: str
    episode_title: str | None
    display_name: str | None
    timestamp_display: str
    text: str
    similarity_score: float


class SimpleQueryResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]


# ~~~~~~ Helpers ~~~~~~

def _build_context(chunks: list[ChunkResult]) -> str:
    """
    Format retrieved chunks into a context block for the LLM prompt.
    Each chunk is labelled with speaker and timestamp so the model
    can cite them accurately.
    """
    parts = []
    for i, chunk in enumerate(chunks, 1):
        speaker = chunk.display_name or "Unknown Speaker"
        context_text = chunk.parent_text or chunk.text
        parts.append(
            f"[{i}] {speaker} at {chunk.timestamp_display}\n{context_text}"
        )
    return "\n\n".join(parts)


def _build_messages(question: str, context: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant that answers questions about podcast content. "
                "Answer based only on the provided transcript excerpts. "
                "Always reference the speaker and timestamp when citing specific content. "
                "If the context does not contain enough information to answer, say so."
            ),
        },
        {
            "role": "user",
            "content": f"Context:\n{context}\n\nQuestion: {question}",
        },
    ]


# ~~~~~~ Endpoint ~~~~~~

@router.post("/simple", response_model=SimpleQueryResponse)
async def simple_query(
    body: SimpleQueryRequest,
    db: AsyncSession = Depends(get_db),
    retriever: Retriever = Depends(get_retriever),
    llm: LLMClient = Depends(get_llm_client),
):
    filters = SearchFilters(
        feed_id=body.feed_id,
        episode_ids=body.episode_ids,
    )

    chunks = await retriever.search(
        query=body.question,
        filters=filters,
        db=db,
        top_k=body.top_k,
    )

    context = _build_context(chunks)
    messages = _build_messages(body.question, context)
    response = await llm.complete(messages)

    citations = [
        CitationResponse(
            chunk_id=chunk.chunk_id,
            episode_id=chunk.episode_id,
            episode_title=chunk.episode_title,
            display_name=chunk.display_name,
            timestamp_display=chunk.timestamp_display,
            text=chunk.text,
            similarity_score=chunk.similarity_score
        )
        for chunk in chunks
    ]

    return SimpleQueryResponse(
        answer=response.content,
        citations=citations,
    )
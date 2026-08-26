# src/api/dependencies.py

from fastapi import Request, Depends

from src.config import get_settings
from src.ingestion.chunker import Chunker
from src.ingestion.embedder import Embedder
from src.ingestion.queue import IngestionQueue
from src.ingestion.speaker_store import SpeakerStore
from src.llm.base import EmbeddingClient, LLMClient
from src.query.engine import QueryEngine
from src.query.prompt_builder import PromptBuilder
from src.query.query_rewriter import QueryRewriter
from src.query.retriever import Retriever
from src.query.result_hydrator import ResultHydrator
from src.query.session_store import SessionStore
from src.query.tool_dispatcher import ToolDispatcher
from src.shared.llm import get_llm_client, get_embedding_client
from src.storage.vector_store import PgvectorStore, VectorStore


settings = get_settings()

def get_session_store(request: Request) -> SessionStore:
    return request.app.state.session_store


# ~~~~~~ Stores ~~~~~~


def get_speaker_store() -> SpeakerStore:
    return SpeakerStore()


def get_vector_store() -> VectorStore:
    return PgvectorStore()


# ~~~~~~ Query ~~~~~~

def get_retriever(
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
    vector_store: VectorStore = Depends(get_vector_store),
) -> Retriever:
    return Retriever(
        embedding_client=embedding_client,
        vector_store=vector_store,
        hydrator=ResultHydrator(),
    )


# ~~~~~~ Queue ~~~~~~


def get_ingestion_queue(request: Request) -> IngestionQueue:
    return request.app.state.ingestion_queue


# ~~~~~~ LLM + Embedding ~~~~~~

def get_prompt_builder() -> PromptBuilder:
    return PromptBuilder()

def get_query_rewriter(llm: LLMClient = Depends(get_llm_client)) -> QueryRewriter:
    return QueryRewriter(llm_client=llm)

def get_tool_dispatcher(
    retriever: Retriever = Depends(get_retriever),
) -> ToolDispatcher:
    return ToolDispatcher(retriever=retriever)

def get_query_engine(
    llm: LLMClient = Depends(get_llm_client),
    session_store: SessionStore = Depends(get_session_store),
    prompt_builder: PromptBuilder = Depends(get_prompt_builder),
    tool_dispatcher: ToolDispatcher = Depends(get_tool_dispatcher),
    query_rewriter: QueryRewriter = Depends(get_query_rewriter),

) -> QueryEngine:
    return QueryEngine(
        llm_client=llm,
        session_store=session_store,
        prompt_builder=prompt_builder,
        tool_dispatcher=tool_dispatcher,
        query_rewriter=query_rewriter,
    )



# ~~~~~~ Pipeline ~~~~~~


def get_chunker() -> Chunker:
    return Chunker(
        chunk_size_tokens=settings.chunk_size_tokens,
        chunk_overlap_tokens=settings.chunk_overlap_tokens,
        min_tokens=settings.chunk_min_tokens,
        topic_similarity_threshold=settings.topic_similarity_threshold
    )


def get_embedder(
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
) -> Embedder:
    return Embedder(embedding_client=embedding_client)
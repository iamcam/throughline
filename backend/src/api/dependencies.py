# src/api/dependencies.py

from fastapi import Request, Depends

from src.config import get_settings
from src.ingestion.chunker import Chunker
from src.ingestion.embedder import Embedder
from src.ingestion.queue import IngestionQueue
from src.ingestion.speaker_store import SpeakerStore
from src.llm.base import LLMClient
from src.query.engine import QueryEngine
from src.query.prompt_builder import PromptBuilder
from src.query.retriever import Retriever
from src.query.result_hydrator import ResultHydrator
from src.query.session_store import SessionStore
from src.query.tool_dispatcher import ToolDispatcher
from src.shared.llm import get_llm_client, get_embedding_client
from src.storage.vector_store import PgvectorStore, VectorStore


settings = get_settings()

def get_session_store(request: Request) -> SessionStore:
    return request.app.state.session_store


# ~~~~~~ Query ~~~~~~

def get_retriever() -> Retriever:
    return Retriever(
        embedding_client=get_embedding_client(),
        vector_store=get_vector_store(),
        hydrator=ResultHydrator(),
    )


# ~~~~~~ Queue ~~~~~~


def get_ingestion_queue(request: Request) -> IngestionQueue:
    return request.app.state.ingestion_queue


# ~~~~~~ Stores ~~~~~~


def get_speaker_store() -> SpeakerStore:
    return SpeakerStore()


def get_vector_store() -> VectorStore:
    return PgvectorStore()


# ~~~~~~ LLM + Embedding ~~~~~~

def get_prompt_builder() -> PromptBuilder:
    return PromptBuilder()

def get_tool_dispatcher(
    retriever: Retriever = Depends(get_retriever),
) -> ToolDispatcher:
    return ToolDispatcher(retriever=retriever)

def get_query_engine(
    llm: LLMClient = Depends(get_llm_client),
    session_store: SessionStore = Depends(get_session_store),
    prompt_builder: PromptBuilder = Depends(get_prompt_builder),
    tool_dispatcher: ToolDispatcher = Depends(get_tool_dispatcher),
) -> QueryEngine:
    return QueryEngine(
        llm_client=llm,
        session_store=session_store,
        prompt_builder=prompt_builder,
        tool_dispatcher=tool_dispatcher,
    )



# ~~~~~~ Pipeline ~~~~~~


def get_chunker() -> Chunker:
    return Chunker(
        chunk_size_tokens=settings.chunk_size_tokens,
        chunk_overlap_tokens=settings.chunk_overlap_tokens,
        min_tokens=settings.chunk_min_tokens,
        topic_similarity_threshold=settings.topic_similarity_threshold
    )


def get_embedder() -> Embedder:
    return Embedder(embedding_client=get_embedding_client())


# src/query/query_rewriter.py
from __future__ import annotations
import asyncio
import json
import logging

from src.llm.base import LLMClient
from src.query.session_store import ChatSession

logger = logging.getLogger(__name__)

#
QUERY_REWRITE_TIMEOUT_SECONDS = 15.0


class QueryRewriter:
    """Resolves conversation-dependent user queries (pronouns, implicit topic
    references) into a self-contained, retrievable phrase before retrieval.

    Runs on every turn but is written to pass through messages that are
    already self-contained -- see the prompt. Never raises: any failure to
    rewrite (parse error, timeout, LLM error) falls back to the original
    message so this optimization can never block a chat turn.
    """

    def __init__(self, llm_client: LLMClient, timeout_seconds: float = QUERY_REWRITE_TIMEOUT_SECONDS):
        self._llm = llm_client
        self._timeout = timeout_seconds

    async def rewrite(self, session: ChatSession, user_message: str) -> str:
        prompt = self._build_prompt(session, user_message)

        try:
            response = await asyncio.wait_for(
                self._llm.complete(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                ),
                timeout=self._timeout,
            )
            raw = response.content.strip().strip("```json").strip("```").strip()
            data = json.loads(raw)
            rewritten = data.get("rewritten_query")
            if rewritten and isinstance(rewritten, str):
                return rewritten
            logger.warning("Query rewrite returned no usable text; using original")
        except asyncio.TimeoutError:
            logger.warning(
                f"Query rewrite timed out after {self._timeout}s; using original"
            )
        except (json.JSONDecodeError, AttributeError) as e:
            logger.warning(f"Query rewrite failed to parse response: {e}; using original")
        except Exception as e:
            logger.warning(f"Query rewrite call failed: {e}; using original")

        return user_message

    def _build_prompt(self, session: ChatSession, user_message: str) -> str:
        history = self._format_history(session)
        return f"""You resolve conversational references in podcast-search queries.

Given the conversation so far and the user's latest message, decide whether the
latest message depends on that context to be understood on its own -- pronouns
like "he"/"that", implicit topic references, follow-up phrasing like "what
about...".

- If it depends on context, rewrite it into a self-contained, specific phrase
  suitable for a search engine. Resolve names and topics explicitly.
- If it is already self-contained and specific, return it unchanged.

Never answer the question. Only return the query text itself.

Conversation so far:
{history}

Latest message: "{user_message}"

Respond with ONLY a JSON object, no explanation, no markdown, no backticks: {{"rewritten_query": "[query text]"}}"""

    def _format_history(self, session: ChatSession) -> str:
        lines = [
            f"{msg['role']}: {msg['content']}"
            for msg in session.messages
            if msg.get("role") in ("user", "assistant") and isinstance(msg.get("content"), str) and msg["content"]
        ]
        return "\n".join(lines) if lines else "(no prior turns)"
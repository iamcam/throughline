# src/query/prompt_builder.py
from __future__ import annotations
from src.query.session_store import ChatSession

class PromptBuilder:

    def build_system_prompt(self, session: ChatSession) -> str:
        parts = [
            "You are a helpful research assistant with access to a podcast knowledge base. ",
            "Never explain tools to the user or suggest they use a function. ",
            "If you need information from the knowledge base, call the tool yourself. ",
            "If you cannot answer without searching, search — do not ask the user to search.",
            "Answer questions based on the podcast content retrieved for you. ",
            "When citing content, always reference the speaker and timestamp. ",
            "If retrieved content does not answer the question, say so — do not speculate. ",
            "If no retrieval is needed to answer (greetings, clarifications, follow-ups "
            "from context already in the conversation), answer directly without searching.",
        ]

        if session.scope_feed_id:
            parts.append(
                f"\nThis conversation is scoped to feed {session.scope_feed_id}. "
                "Only discuss content from this feed."
            )

        if session.scope_episode_ids:
            ids = ", ".join(str(e) for e in session.scope_episode_ids)
            parts.append(
                f"\nThis conversation is scoped to episodes: {ids}. "
                "Only discuss content from these episodes."
            )

        return "".join(parts)


    def build_messages(self, session: ChatSession) -> list[dict]:
        system = {
            "role": "system",
            "content": self.build_system_prompt(session)
        }
        return [system] + session.messages

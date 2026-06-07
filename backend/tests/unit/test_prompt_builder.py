# tests/unit/test_prompt_builder.py
import pytest
from src.query.prompt_builder import PromptBuilder
from src.query.session_store import ChatSession
import uuid

def test_system_prompt_included_as_first_message():
    session = ChatSession(session_id="abc")
    builder = PromptBuilder()
    prompt = builder.build_system_prompt(session)
    assert prompt.startswith("You are a helpful research assistant")


def test_session_messages_appended_after_system():
    episode_id = uuid.uuid4()
    session = ChatSession(session_id="def",
                            scope_feed_id=uuid.uuid4(),
                            scope_episode_ids=[episode_id],
                            messages=[
                                {"role": "user", "content": "this is user content"}
                            ]
                        )
    builder = PromptBuilder()
    messages = builder.build_messages(session)
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "this is user content"


def test_scope_feed_id_mentioned_in_system_prompt():
    feed_id = uuid.uuid4()
    session = ChatSession(session_id="def",
                            scope_feed_id=feed_id,
                            scope_episode_ids=[uuid.uuid4()],
                            messages=[
                                {"role": "user", "content": "this is user content"}
                            ]
                        )
    builder = PromptBuilder()
    messages = builder.build_messages(session)
    assert f"feed {feed_id}" in messages[0]["content"]

def test_scope_episode_ids_mentioned_in_system_prompt():
    ep_ids = [uuid.uuid4(), uuid.uuid4()]
    session = ChatSession(session_id="def",
                            scope_feed_id=uuid.uuid4(),
                            scope_episode_ids=ep_ids,
                            messages=[
                                {"role": "user", "content": "this is user content"}
                            ]
                        )
    builder = PromptBuilder()
    messages = builder.build_messages(session)
    assert str(ep_ids[0]) in messages[0]["content"]
    assert str(ep_ids[1]) in messages[0]["content"]

def test_no_scope_produces_clean_prompt():
    session = ChatSession(session_id="def", messages=[])
    builder = PromptBuilder()
    messages = builder.build_messages(session)
    assert "scoped" not in messages[0]["content"]
    assert "feed" not in messages[0]["content"]
    assert "episodes" not in messages[0]["content"]



def test_empty_session_messages_returns_only_system():
    ep_ids = [uuid.uuid4(), uuid.uuid4()]
    session = ChatSession(session_id="def",
                            scope_episode_ids=ep_ids,
                            messages=[]
                        )
    builder = PromptBuilder()
    messages = builder.build_messages(session)
    assert messages[0]["role"] == "system"
    assert len(messages) == 1


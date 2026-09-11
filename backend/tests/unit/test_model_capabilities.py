# tests/unit/test_model_capabilities.py

import pytest

from src.llm.model_capabilities import needs_reasoning_effort_none, supports_temperature


@pytest.mark.parametrize(
    "model_name, expected",
    [
        ("gpt-3.5-turbo", True),
        ("gpt-4o", True),
        ("gpt-4.1", True),
        ("gpt-5", False),
        ("gpt-5-mini", False),
        ("gpt-5.1", False),
        ("gpt-5.6-luna", False),
        ("llama3.1:8b", True),
    ],
)
def test_supports_temperature(model_name, expected):
    assert supports_temperature(model_name) is expected


@pytest.mark.parametrize(
    "model_name, expected",
    [
        ("gpt-3.5-turbo", False),
        ("gpt-4o", False),
        ("gpt-4.1", False),
        ("gpt-5", True),
        ("gpt-5-mini", True),
        ("gpt-5.1", True),
        ("gpt-5.6-luna", True),
        ("llama3.1:8b", False),
    ],
)
def test_needs_reasoning_effort_none(model_name, expected):
    assert needs_reasoning_effort_none(model_name) is expected
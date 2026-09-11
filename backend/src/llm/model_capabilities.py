# src/llm/model_capabilities.py

import re

# Escape hatches: add a model name here if a specific model doesn't match
# the naming pattern below for that capability.
_FORCE_TEMPERATURE_FIXED: set[str] = set()
_FORCE_TEMPERATURE_ADJUSTABLE: set[str] = set()
_FORCE_REASONING_EFFORT_NONE_REQUIRED: set[str] = set()
_FORCE_REASONING_EFFORT_NONE_NOT_REQUIRED: set[str] = set()

# gpt-<N> where N (an int or decimal) is >= 5. Matches "gpt-5", "gpt-5-mini",
# "gpt-5.1", and "gpt-5.6-luna"; does not match "gpt-4o", "gpt-4.1", or
# "gpt-3.5-turbo".
_GPT_VERSION_PATTERN = re.compile(r"^gpt-(\d+(?:\.\d+)?)")


def _is_gpt5_plus(model_name: str) -> bool:
    """True for gpt-<N> where N >= 5."""
    normalized = model_name.strip().lower()
    match = _GPT_VERSION_PATTERN.match(normalized)
    if not match:
        return False
    return float(match.group(1)) >= 5


def supports_temperature(model_name: str) -> bool:
    """False for models that error on any temperature other than their default (1)."""
    normalized = model_name.strip().lower()
    if normalized in _FORCE_TEMPERATURE_FIXED:
        return False
    if normalized in _FORCE_TEMPERATURE_ADJUSTABLE:
        return True
    return not _is_gpt5_plus(normalized)


def needs_reasoning_effort_none(model_name: str) -> bool:
    """True for models that require reasoning_effort="none" to use function tools."""
    normalized = model_name.strip().lower()
    if normalized in _FORCE_REASONING_EFFORT_NONE_NOT_REQUIRED:
        return False
    if normalized in _FORCE_REASONING_EFFORT_NONE_REQUIRED:
        return True
    return _is_gpt5_plus(normalized)
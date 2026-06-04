from __future__ import annotations

from typing import Any

import bumpkin.providers.llm as _impl

LLMResponseError = _impl.LLMResponseError
LLMUnavailableError = _impl.LLMUnavailableError

_build_messages = _impl._build_messages
_call_github_models = _impl._call_github_models
_coerce_recommendation_payload = _impl._coerce_recommendation_payload
_extract_content = _impl._extract_content
_extract_json_payload = _impl._extract_json_payload
_split_diff_into_chunks = _impl._split_diff_into_chunks

get_no_bump_recommendation = _impl.get_no_bump_recommendation
get_stub_recommendation = _impl.get_stub_recommendation
validate_recommendation = _impl.validate_recommendation


def get_recommendation(
    *args: Any, **kwargs: Any
) -> tuple[dict[str, Any], str, str | None, str | None]:
    # Preserve test monkeypatch behavior against legacy llm._call_github_models.
    _impl._call_github_models = _call_github_models
    return _impl.get_recommendation(*args, **kwargs)


__all__ = [
    "LLMResponseError",
    "LLMUnavailableError",
    "_build_messages",
    "_call_github_models",
    "_coerce_recommendation_payload",
    "_extract_content",
    "_extract_json_payload",
    "_split_diff_into_chunks",
    "get_no_bump_recommendation",
    "get_recommendation",
    "get_stub_recommendation",
    "validate_recommendation",
]

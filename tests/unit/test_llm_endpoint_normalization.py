from __future__ import annotations

from bumpkin.providers import llm


def test_normalize_request_endpoint_accepts_openai_base_url() -> None:
    assert (
        llm._normalize_request_endpoint(
            "https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )


def test_normalize_request_endpoint_preserves_full_chat_completions_url() -> None:
    assert (
        llm._normalize_request_endpoint(
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        )
        == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )

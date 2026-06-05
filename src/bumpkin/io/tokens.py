from __future__ import annotations

import os

GITHUB_MODELS_ENDPOINT = "https://models.github.ai/inference/chat/completions"
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


def _looks_like_openrouter_token(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().startswith("sk-or-v1-")


def is_openrouter_endpoint(endpoint: str | None) -> bool:
    if not endpoint:
        return False
    return "openrouter.ai" in endpoint.strip().lower()


def is_github_models_endpoint(endpoint: str | None) -> bool:
    if not endpoint:
        return False
    return "models.github.ai" in endpoint.strip().lower()


def resolve_models_endpoint() -> str:
    explicit = (
        os.getenv("BUMPKIN_MODELS_ENDPOINT")
        or os.getenv("GITHUB_MODELS_ENDPOINT")
        or os.getenv("OPENROUTER_ENDPOINT")
    )
    if explicit and explicit.strip():
        return explicit.strip()
    return ""


def resolve_models_token(*, endpoint: str | None = None) -> str:
    normalized_endpoint = endpoint or resolve_models_endpoint()
    if is_openrouter_endpoint(normalized_endpoint):
        return (
            os.getenv("OPENROUTER_API")
            or os.getenv("OPENROUTER_API_KEY")
            or os.getenv("MODELS_TOKEN")
            or os.getenv("GITHUB_MODELS_TOKEN")
            or ""
        )

    return (
        os.getenv("MODELS_TOKEN")
        or os.getenv("GITHUB_MODELS_TOKEN")
        or os.getenv("OPENROUTER_API_KEY")
        or os.getenv("OPENROUTER_API")
        or ""
    )


__all__ = [
    "GITHUB_MODELS_ENDPOINT",
    "OPENROUTER_ENDPOINT",
    "is_github_models_endpoint",
    "is_openrouter_endpoint",
    "resolve_models_endpoint",
    "resolve_models_token",
]

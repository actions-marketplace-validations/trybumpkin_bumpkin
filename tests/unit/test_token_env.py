from token_env import (
    OPENROUTER_ENDPOINT,
    is_openrouter_endpoint,
    is_valid_models_endpoint,
    resolve_models_endpoint,
    resolve_models_token,
)


def test_resolve_models_token_prefers_models_token(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API", raising=False)
    monkeypatch.delenv("BUMPKIN_MODELS_ENDPOINT", raising=False)
    monkeypatch.delenv("GITHUB_MODELS_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENROUTER_ENDPOINT", raising=False)
    monkeypatch.setenv("MODELS_TOKEN", "models-token")
    monkeypatch.setenv("GITHUB_MODELS_TOKEN", "github-models-token")
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")

    assert resolve_models_token() == "models-token"


def test_resolve_models_token_falls_back_to_github_models_token(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API", raising=False)
    monkeypatch.delenv("BUMPKIN_MODELS_ENDPOINT", raising=False)
    monkeypatch.delenv("GITHUB_MODELS_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENROUTER_ENDPOINT", raising=False)
    monkeypatch.delenv("MODELS_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_MODELS_TOKEN", "github-models-token")
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")

    assert resolve_models_token() == "github-models-token"


def test_resolve_models_token_returns_empty_without_model_provider_token(monkeypatch) -> None:
    monkeypatch.delenv("BUMPKIN_MODELS_ENDPOINT", raising=False)
    monkeypatch.delenv("GITHUB_MODELS_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENROUTER_ENDPOINT", raising=False)
    monkeypatch.delenv("MODELS_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_MODELS_TOKEN", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")

    assert resolve_models_token() == ""


def test_resolve_models_token_prefers_openrouter_api_for_openrouter_endpoint(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MODELS_TOKEN", "github-token")
    monkeypatch.setenv("OPENROUTER_API", "sk-or-v1-openrouter-token")

    assert (
        resolve_models_token(endpoint="https://openrouter.ai/api/v1/chat/completions")
        == "sk-or-v1-openrouter-token"
    )


def test_resolve_models_endpoint_prefers_explicit_env(monkeypatch) -> None:
    monkeypatch.setenv("BUMPKIN_MODELS_ENDPOINT", "https://example.com/custom")
    monkeypatch.setenv("OPENROUTER_API", "sk-or-v1-openrouter-token")

    assert resolve_models_endpoint() == "https://example.com/custom"


def test_resolve_models_endpoint_uses_openrouter_env(monkeypatch) -> None:
    monkeypatch.delenv("BUMPKIN_MODELS_ENDPOINT", raising=False)
    monkeypatch.delenv("GITHUB_MODELS_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENROUTER_ENDPOINT", raising=False)
    monkeypatch.setenv("OPENROUTER_ENDPOINT", OPENROUTER_ENDPOINT)

    assert resolve_models_endpoint() == OPENROUTER_ENDPOINT


def test_resolve_models_endpoint_returns_empty_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("BUMPKIN_MODELS_ENDPOINT", raising=False)
    monkeypatch.delenv("GITHUB_MODELS_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENROUTER_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API", raising=False)
    monkeypatch.delenv("MODELS_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_MODELS_TOKEN", raising=False)

    assert resolve_models_endpoint() == ""


def test_is_openrouter_endpoint_detects_hostname() -> None:
    assert is_openrouter_endpoint("https://openrouter.ai/api/v1/chat/completions")
    assert not is_openrouter_endpoint("https://models.github.ai/inference/chat/completions")


def test_is_valid_models_endpoint_requires_http_scheme() -> None:
    assert is_valid_models_endpoint("https://generativelanguage.googleapis.com/v1beta/openai/")
    assert is_valid_models_endpoint("http://localhost:1234/v1/chat/completions")
    assert not is_valid_models_endpoint("generativelanguage.googleapis.com/v1beta/openai/")
    assert not is_valid_models_endpoint("***")
    assert not is_valid_models_endpoint("")

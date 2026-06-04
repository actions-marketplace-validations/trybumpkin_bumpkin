import pytest

import llm
from llm import LLMResponseError, LLMUnavailableError, get_recommendation


def test_get_recommendation_uses_fallback_model_when_primary_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_call(*, model: str, **_: object) -> dict[str, str]:
        if model == "primary/model":
            raise LLMUnavailableError("primary down")
        return {
            "label": "MINOR",
            "confidence": "high",
            "reasoning": "Added exported API function in src/api.ts without breaking signatures.",
            "changelog": "feat: add API helper",
        }

    monkeypatch.setattr(llm, "_call_github_models", fake_call)

    result, mode, fallback_reason, model_used = get_recommendation(
        mode="auto",
        diff_text="+ export function helper() {}",
        truncated=False,
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        surface_area_hints=None,
        language_hints=None,
        model="primary/model",
        fallback_model="fallback/model",
        endpoint="https://models.github.ai/inference/chat/completions",
        token="token",
        max_retries=1,
    )
    assert mode == "github-models"
    assert fallback_reason is None
    assert model_used == "fallback/model"
    assert result["status"] == "classified"
    assert result["label"] == "MINOR"


def test_get_recommendation_openrouter_mode_reports_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_call(**_: object) -> dict[str, str]:
        return {
            "label": "PATCH",
            "confidence": "medium",
            "reasoning": "OpenRouter model classified this as internal implementation behavior.",
            "changelog": "fix: update internal implementation",
        }

    monkeypatch.setattr(llm, "_call_github_models", fake_call)

    result, mode, fallback_reason, model_used = get_recommendation(
        mode="openrouter",
        diff_text="+ const flag = true",
        truncated=False,
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        surface_area_hints=None,
        language_hints=None,
        model="openrouter/model",
        fallback_model=None,
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        token="token",
        max_retries=1,
    )
    assert mode == "openrouter"
    assert fallback_reason is None
    assert model_used == "openrouter/model"
    assert result["status"] == "classified"
    assert result["label"] == "PATCH"


def test_get_recommendation_returns_manual_review_when_models_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def always_fail(**_: object) -> dict[str, str]:
        raise LLMUnavailableError("all providers down")

    monkeypatch.setattr(llm, "_call_github_models", always_fail)

    result, mode, fallback_reason, model_used = get_recommendation(
        mode="auto",
        diff_text="+ export function helper() {}",
        truncated=False,
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        surface_area_hints=None,
        language_hints=None,
        model="primary/model",
        fallback_model="fallback/model",
        endpoint="https://models.github.ai/inference/chat/completions",
        token="token",
        use_semantic_fallback=False,
        max_retries=1,
    )
    assert mode == "github-models"
    assert model_used is None
    assert fallback_reason is not None
    assert result["status"] == "manual_review"
    assert result["label"] is None
    assert result["confidence"] is None
    assert result["changelog"] is None


def test_get_recommendation_returns_manual_review_when_model_response_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid_response(**_: object) -> dict[str, str]:
        raise LLMResponseError("bad schema")

    monkeypatch.setattr(llm, "_call_github_models", invalid_response)

    result, mode, fallback_reason, model_used = get_recommendation(
        mode="auto",
        diff_text="+ export function helper() {}",
        truncated=False,
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        surface_area_hints=None,
        language_hints=None,
        model="primary/model",
        fallback_model=None,
        endpoint="https://models.github.ai/inference/chat/completions",
        token="token",
        use_semantic_fallback=False,
        max_retries=1,
    )
    assert mode == "github-models"
    assert model_used is None
    assert fallback_reason is not None
    assert result["status"] == "manual_review"
    assert result["label"] is None


def test_get_recommendation_stub_mode_still_returns_classified_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def should_not_call_models(**_: object) -> dict[str, str]:
        raise AssertionError("model call should not happen in stub mode")

    monkeypatch.setattr(llm, "_call_github_models", should_not_call_models)
    result, mode, fallback_reason, model_used = get_recommendation(
        mode="stub",
        diff_text="+ docs only",
        truncated=False,
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        surface_area_hints=None,
        language_hints=None,
        model="primary/model",
        fallback_model="fallback/model",
        endpoint="https://models.github.ai/inference/chat/completions",
        token="token",
        use_semantic_fallback=False,
        max_retries=1,
    )
    assert mode == "stub"
    assert fallback_reason is None
    assert model_used == "stub"
    assert result["status"] == "classified"
    assert result["label"] == "PATCH"


def test_get_recommendation_uses_semantic_fallback_for_major_when_models_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def always_fail(**_: object) -> dict[str, str]:
        raise LLMUnavailableError("rate limited")

    monkeypatch.setattr(llm, "_call_github_models", always_fail)

    result, mode, fallback_reason, model_used = get_recommendation(
        mode="auto",
        diff_text="- export function oldApi(user) {}\n+ function oldApi(user) {}\n",
        truncated=False,
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        surface_area_hints=None,
        language_hints=None,
        model="primary/model",
        fallback_model=None,
        endpoint="https://models.github.ai/inference/chat/completions",
        token="token",
        max_retries=1,
    )

    assert mode == "fallback-heuristic"
    assert model_used == "semantic-fallback"
    assert fallback_reason is not None
    assert result["status"] == "classified"
    assert result["label"] == "MAJOR"


def test_get_recommendation_uses_semantic_fallback_for_minor_when_model_response_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid_response(**_: object) -> dict[str, str]:
        raise LLMResponseError("bad schema")

    monkeypatch.setattr(llm, "_call_github_models", invalid_response)

    result, mode, fallback_reason, model_used = get_recommendation(
        mode="auto",
        diff_text="+ export function helper() {}\n",
        truncated=False,
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        surface_area_hints=None,
        language_hints=None,
        model="primary/model",
        fallback_model=None,
        endpoint="https://models.github.ai/inference/chat/completions",
        token="token",
        max_retries=1,
    )

    assert mode == "fallback-heuristic"
    assert model_used == "semantic-fallback"
    assert fallback_reason is not None
    assert result["status"] == "classified"
    assert result["label"] == "MINOR"


def test_get_recommendation_returns_manual_review_for_ambiguous_semantic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def always_fail(**_: object) -> dict[str, str]:
        raise LLMUnavailableError("rate limited")

    monkeypatch.setattr(llm, "_call_github_models", always_fail)

    result, mode, fallback_reason, model_used = get_recommendation(
        mode="auto",
        diff_text="- export { helper }\n+ export { helper }\n",
        truncated=False,
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        surface_area_hints=["src/public/index.ts"],
        language_hints=None,
        model="primary/model",
        fallback_model=None,
        endpoint="https://models.github.ai/inference/chat/completions",
        token="token",
        max_retries=1,
    )

    assert mode == "fallback-heuristic"
    assert model_used == "semantic-fallback"
    assert fallback_reason is not None
    assert result["status"] == "manual_review"
    assert result["label"] is None


def test_get_recommendation_semantic_fallback_detects_docs_only_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def always_fail(**_: object) -> dict[str, str]:
        raise LLMUnavailableError("rate limited")

    monkeypatch.setattr(llm, "_call_github_models", always_fail)

    result, mode, fallback_reason, model_used = get_recommendation(
        mode="auto",
        diff_text="+ update README wording\n+ branch protection policy clarified\n",
        truncated=False,
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        surface_area_hints=None,
        language_hints=None,
        model="primary/model",
        fallback_model=None,
        endpoint="https://models.github.ai/inference/chat/completions",
        token="token",
        max_retries=1,
    )

    assert mode == "fallback-heuristic"
    assert model_used == "semantic-fallback"
    assert fallback_reason is not None
    assert result["status"] == "classified"
    assert result["label"] == "NO_BUMP"


def test_get_recommendation_semantic_fallback_uses_surface_area_for_signature_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def always_fail(**_: object) -> dict[str, str]:
        raise LLMUnavailableError("rate limited")

    monkeypatch.setattr(llm, "_call_github_models", always_fail)

    result, mode, fallback_reason, model_used = get_recommendation(
        mode="auto",
        diff_text="- function normalizeBilling(user, opts) {}\n+ function normalizeBilling(user, opts, audit) {}\n",
        truncated=False,
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        surface_area_hints=["src/billing/public.ts"],
        language_hints=None,
        model="primary/model",
        fallback_model=None,
        endpoint="https://models.github.ai/inference/chat/completions",
        token="token",
        max_retries=1,
    )

    assert mode == "fallback-heuristic"
    assert model_used == "semantic-fallback"
    assert fallback_reason is not None
    assert result["status"] == "classified"
    assert result["label"] == "MAJOR"


def test_get_recommendation_semantic_fallback_treats_optional_export_param_as_minor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def always_fail(**_: object) -> dict[str, str]:
        raise LLMUnavailableError("rate limited")

    monkeypatch.setattr(llm, "_call_github_models", always_fail)

    result, mode, fallback_reason, model_used = get_recommendation(
        mode="auto",
        diff_text=(
            "- export function fixtureNormalizeTag(tag: string): string { return tag.toLowerCase(); }\n"
            "+ export function fixtureNormalizeTag(tag: string, opts?: { preserveCase?: boolean }): string { return opts?.preserveCase ? tag : tag.toLowerCase(); }\n"
        ),
        truncated=False,
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        surface_area_hints=None,
        language_hints=None,
        model="primary/model",
        fallback_model=None,
        endpoint="https://models.github.ai/inference/chat/completions",
        token="token",
        max_retries=1,
    )

    assert mode == "fallback-heuristic"
    assert model_used == "semantic-fallback"
    assert fallback_reason is not None
    assert result["status"] == "classified"
    assert result["label"] == "MINOR"


def test_get_recommendation_semantic_fallback_uses_low_confidence_for_ambiguous_signatures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def always_fail(**_: object) -> dict[str, str]:
        raise LLMUnavailableError("rate limited")

    monkeypatch.setattr(llm, "_call_github_models", always_fail)

    result, mode, fallback_reason, model_used = get_recommendation(
        mode="auto",
        diff_text="- function normalizeUser(user) {}\n+ function normalizeUser(user, opts) {}\n",
        truncated=False,
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        surface_area_hints=None,
        language_hints=None,
        model="primary/model",
        fallback_model=None,
        endpoint="https://models.github.ai/inference/chat/completions",
        token="token",
        max_retries=1,
    )

    assert mode == "fallback-heuristic"
    assert model_used == "semantic-fallback"
    assert fallback_reason is not None
    assert result["status"] == "classified"
    assert result["label"] == "PATCH"
    assert result["confidence"] == "low"

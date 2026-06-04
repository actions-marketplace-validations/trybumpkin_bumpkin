from bumpkin.planner import plan_analysis_route


def test_plan_analysis_route_uses_full_when_within_budget(monkeypatch) -> None:
    monkeypatch.setenv("BUMPKIN_GITHUB_MODELS_MAX_PROMPT_TOKENS", "8000")
    decision = plan_analysis_route(
        mode="auto",
        endpoint="https://models.github.ai/inference/chat/completions",
        has_model_token=True,
        approx_prompt_tokens=1200,
        request_timeout=45,
        chunking_enabled=True,
        chunk_max_tokens=1200,
        chunk_max_count=24,
    )
    assert decision.route == "full"
    assert decision.allow_model_call is True
    assert decision.reason == "within_provider_budget"


def test_plan_analysis_route_uses_chunked_when_single_shot_exceeded(
    monkeypatch,
) -> None:
    monkeypatch.setenv("BUMPKIN_GITHUB_MODELS_MAX_PROMPT_TOKENS", "2000")
    decision = plan_analysis_route(
        mode="auto",
        endpoint="https://models.github.ai/inference/chat/completions",
        has_model_token=True,
        approx_prompt_tokens=4000,
        request_timeout=45,
        chunking_enabled=True,
        chunk_max_tokens=300,
        chunk_max_count=20,
    )
    assert decision.route == "chunked"
    assert decision.allow_model_call is True


def test_plan_analysis_route_uses_evidence_targeted_when_chunk_capacity_exceeded(
    monkeypatch,
) -> None:
    monkeypatch.setenv("BUMPKIN_OPENROUTER_MAX_PROMPT_TOKENS", "2600")
    decision = plan_analysis_route(
        mode="openrouter",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        has_model_token=True,
        approx_prompt_tokens=12000,
        request_timeout=45,
        chunking_enabled=True,
        chunk_max_tokens=1200,
        chunk_max_count=4,
    )
    assert decision.route == "evidence_targeted"
    assert decision.allow_model_call is True


def test_plan_analysis_route_blocks_without_token() -> None:
    decision = plan_analysis_route(
        mode="auto",
        endpoint="https://models.github.ai/inference/chat/completions",
        has_model_token=False,
        approx_prompt_tokens=1000,
        request_timeout=45,
        chunking_enabled=True,
        chunk_max_tokens=1200,
        chunk_max_count=24,
    )
    assert decision.route == "manual_review"
    assert decision.allow_model_call is False


def test_plan_analysis_route_stub_mode_allows_stub_execution() -> None:
    decision = plan_analysis_route(
        mode="stub",
        endpoint="https://models.github.ai/inference/chat/completions",
        has_model_token=False,
        approx_prompt_tokens=1200,
        request_timeout=45,
        chunking_enabled=True,
        chunk_max_tokens=1200,
        chunk_max_count=24,
    )
    assert decision.route == "full"
    assert decision.reason == "stub_mode"
    assert decision.allow_model_call is True

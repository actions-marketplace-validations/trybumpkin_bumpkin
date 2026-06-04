from __future__ import annotations

import os
from dataclasses import dataclass

from bumpkin.io.tokens import is_github_models_endpoint, is_openrouter_endpoint

DECISION_VERSION = "decision_contract_v3"
DEFAULT_GITHUB_MAX_PROMPT = 12000
DEFAULT_OPENROUTER_MAX_PROMPT = 2600
DEFAULT_OPENAI_COMPAT_MAX_PROMPT = 6000
DEFAULT_MAX_OUTPUT = 400


@dataclass(frozen=True)
class ProviderProfile:
    provider: str
    max_prompt_tokens: int
    max_output_tokens: int
    request_timeout_s: int

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "max_prompt_tokens": self.max_prompt_tokens,
            "max_output_tokens": self.max_output_tokens,
            "request_timeout_s": self.request_timeout_s,
        }


@dataclass(frozen=True)
class PlannerDecision:
    version: str
    route: str
    reason: str
    allow_model_call: bool
    provider_profile: ProviderProfile
    used_token_budget: int
    chunk_capacity: int

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "route": self.route,
            "reason": self.reason,
            "allow_model_call": self.allow_model_call,
            "provider_profile": self.provider_profile.to_dict(),
            "used_token_budget": self.used_token_budget,
            "chunk_capacity": self.chunk_capacity,
        }


def _parse_int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, value)


def _provider_name(mode: str, endpoint: str) -> str:
    normalized_mode = mode.strip().lower()
    if normalized_mode == "openrouter":
        return "openrouter"
    if normalized_mode == "github-models":
        return "github-models"
    if is_openrouter_endpoint(endpoint):
        return "openrouter"
    if is_github_models_endpoint(endpoint):
        return "github-models"
    return "openai-compatible"


def resolve_provider_profile(
    *,
    mode: str,
    endpoint: str,
    request_timeout: int,
) -> ProviderProfile:
    provider = _provider_name(mode, endpoint)
    if provider == "openrouter":
        max_prompt = _parse_int_env(
            "BUMPKIN_OPENROUTER_MAX_PROMPT_TOKENS",
            DEFAULT_OPENROUTER_MAX_PROMPT,
        )
    elif provider == "github-models":
        max_prompt = _parse_int_env(
            "BUMPKIN_GITHUB_MODELS_MAX_PROMPT_TOKENS",
            DEFAULT_GITHUB_MAX_PROMPT,
        )
    else:
        max_prompt = _parse_int_env(
            "BUMPKIN_OPENAI_COMPAT_MAX_PROMPT_TOKENS",
            DEFAULT_OPENAI_COMPAT_MAX_PROMPT,
        )
    max_output = _parse_int_env("BUMPKIN_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT)
    return ProviderProfile(
        provider=provider,
        max_prompt_tokens=max_prompt,
        max_output_tokens=max_output,
        request_timeout_s=max(1, request_timeout),
    )


def plan_analysis_route(
    *,
    mode: str,
    endpoint: str,
    has_model_token: bool,
    approx_prompt_tokens: int,
    request_timeout: int,
    chunking_enabled: bool,
    chunk_max_tokens: int,
    chunk_max_count: int,
) -> PlannerDecision:
    profile = resolve_provider_profile(
        mode=mode,
        endpoint=endpoint,
        request_timeout=request_timeout,
    )
    normalized_mode = mode.strip().lower()
    chunk_capacity = max(0, chunk_max_tokens) * max(0, chunk_max_count)

    if normalized_mode == "stub":
        return PlannerDecision(
            version=DECISION_VERSION,
            route="full",
            reason="stub_mode",
            allow_model_call=True,
            provider_profile=profile,
            used_token_budget=approx_prompt_tokens,
            chunk_capacity=chunk_capacity,
        )

    if not has_model_token:
        return PlannerDecision(
            version=DECISION_VERSION,
            route="manual_review",
            reason="missing_model_token",
            allow_model_call=False,
            provider_profile=profile,
            used_token_budget=approx_prompt_tokens,
            chunk_capacity=chunk_capacity,
        )

    if approx_prompt_tokens <= profile.max_prompt_tokens:
        return PlannerDecision(
            version=DECISION_VERSION,
            route="full",
            reason="within_provider_budget",
            allow_model_call=True,
            provider_profile=profile,
            used_token_budget=approx_prompt_tokens,
            chunk_capacity=chunk_capacity,
        )

    if chunking_enabled and chunk_capacity > 0 and approx_prompt_tokens <= chunk_capacity:
        return PlannerDecision(
            version=DECISION_VERSION,
            route="chunked",
            reason="exceeds_single_shot_budget_but_fits_chunk_capacity",
            allow_model_call=True,
            provider_profile=profile,
            used_token_budget=approx_prompt_tokens,
            chunk_capacity=chunk_capacity,
        )

    return PlannerDecision(
        version=DECISION_VERSION,
        route="evidence_targeted",
        reason="provider_or_chunk_budget_exceeded",
        allow_model_call=True,
        provider_profile=profile,
        used_token_budget=approx_prompt_tokens,
        chunk_capacity=chunk_capacity,
    )

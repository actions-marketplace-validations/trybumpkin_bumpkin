from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bumpkin.analysis.language import get_language_hints_for_groups
from bumpkin.providers.llm import get_recommendation


def categorize_failure_reason(reason: str | None) -> str | None:
    if not reason:
        return None

    normalized = reason.strip().lower()
    if "no token available" in normalized:
        return "missing_token"
    if "429" in normalized or "too many requests" in normalized:
        return "rate_limited"
    if "401" in normalized or "403" in normalized or "bad credentials" in normalized:
        return "invalid_token"
    if "certificate_verify_failed" in normalized or "ssl:" in normalized:
        return "ssl_failure"
    if "nodename nor servname provided" in normalized or "name or service not known" in normalized:
        return "dns_failure"
    if "http 5" in normalized or "timed out" in normalized or "connection refused" in normalized:
        return "endpoint_failure"
    if "schema" in normalized or "non-json output" in normalized:
        return "response_schema_error"
    return "unknown_failure"


def invoke_recommend_fn(
    recommend_fn: Callable[..., tuple[dict[str, Any], str, str | None, str | None]],
    **kwargs: Any,
) -> tuple[dict[str, Any], str, str | None, str | None]:
    signature = inspect.signature(recommend_fn)
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if accepts_kwargs:
        return recommend_fn(**kwargs)
    filtered = {key: value for key, value in kwargs.items() if key in signature.parameters}
    return recommend_fn(**filtered)


def normalize_recommendation_result(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") in {"classified", "manual_review"}:
        return result
    if (
        isinstance(result.get("label"), str)
        and isinstance(result.get("confidence"), str)
        and isinstance(result.get("reasoning"), str)
        and isinstance(result.get("changelog"), str)
    ):
        normalized = dict(result)
        normalized["status"] = "classified"
        return normalized
    return result


def run_eval_preflight(
    *,
    mode: str,
    language_group: str,
    prompt_version: str,
    model: str,
    endpoint: str,
    token: str,
    max_retries: int,
    request_timeout: int = 45,
    recommend_fn: Callable[
        ..., tuple[dict[str, Any], str, str | None, str | None]
    ] = get_recommendation,
) -> dict[str, Any]:
    normalized_mode = mode.strip().lower()
    if normalized_mode == "stub":
        return {
            "status": "skipped",
            "reason": "stub mode does not require model preflight.",
            "failure_category": None,
            "failure_reason": None,
            "mode_used": "stub",
            "model_used": "stub",
        }

    synthetic_diff = (
        "+ export function ping() {}"
        if language_group == "javascript-typescript"
        else "+ public API delta"
    )
    result, mode_used, fallback_reason, model_used = invoke_recommend_fn(
        recommend_fn,
        mode=mode,
        diff_text=synthetic_diff,
        truncated=False,
        language_group=language_group,
        prompt_version=prompt_version,
        surface_area_hints=None,
        language_hints=get_language_hints_for_groups([language_group]),
        model=model,
        fallback_model=None,
        endpoint=endpoint,
        token=token,
        max_retries=max_retries,
        request_timeout=request_timeout,
    )
    result = normalize_recommendation_result(result)
    if result.get("status") == "classified":
        if mode_used not in {"github-models", "openrouter", "openai-compatible"}:
            failure_reason = (
                f"model preflight degraded to {mode_used} (model_used={model_used or 'n/a'})."
            )
            if fallback_reason:
                failure_reason += f" root_cause={fallback_reason}"
            return {
                "status": "failed",
                "reason": "model preflight succeeded only via fallback/degraded mode.",
                "failure_category": (categorize_failure_reason(fallback_reason) or "degraded_mode"),
                "failure_reason": failure_reason,
                "mode_used": mode_used,
                "model_used": model_used,
            }
        return {
            "status": "ok",
            "reason": "model preflight succeeded.",
            "failure_category": None,
            "failure_reason": None,
            "mode_used": mode_used,
            "model_used": model_used,
        }

    return {
        "status": "failed",
        "reason": "model preflight returned manual_review.",
        "failure_category": categorize_failure_reason(fallback_reason),
        "failure_reason": fallback_reason,
        "mode_used": mode_used,
        "model_used": model_used,
    }


def select_batch_cases(
    cases: list[Any],
    *,
    batch_size: int | None,
    batch_index: int,
) -> tuple[list[Any], dict[str, Any]]:
    ordered = sorted(cases, key=lambda case: case.name)
    total_case_count = len(ordered)
    if not batch_size or batch_size <= 0:
        return ordered, {
            "batch_index": 0,
            "batch_size": total_case_count,
            "batch_case_count": total_case_count,
            "total_case_count": total_case_count,
            "is_subset_run": False,
            "is_empty_batch": False,
        }

    if batch_index < 0:
        raise ValueError("batch_index must be >= 0")

    start = batch_index * batch_size
    end = start + batch_size
    if start >= total_case_count:
        return [], {
            "batch_index": batch_index,
            "batch_size": batch_size,
            "batch_case_count": 0,
            "total_case_count": total_case_count,
            "is_subset_run": True,
            "is_empty_batch": True,
        }

    selected = ordered[start:end]
    return selected, {
        "batch_index": batch_index,
        "batch_size": batch_size,
        "batch_case_count": len(selected),
        "total_case_count": total_case_count,
        "is_subset_run": len(selected) != total_case_count,
        "is_empty_batch": len(selected) == 0,
    }


def aggregate_results_from_json_dir(
    json_dir: Path,
    *,
    expected_cases: list[Any],
    result_factory: Callable[..., Any],
) -> tuple[list[Any], dict[str, Any]]:
    paths = sorted(json_dir.glob("*.json"))
    if not paths:
        raise ValueError(f"No JSON result files found in {json_dir}")

    aggregated: list[Any] = []
    seen_names: set[str] = set()
    duplicate_names: list[str] = []

    for path in paths:
        payload = json.loads(path.read_text())
        for row in payload.get("results", []):
            name = str(row["name"])
            if name in seen_names:
                duplicate_names.append(name)
                continue
            seen_names.add(name)
            aggregated.append(
                result_factory(
                    name=name,
                    expected=row["expected"],
                    actual=row["actual"],
                    passed=bool(row["passed"]),
                    category=str(row["category"]),
                )
            )

    if duplicate_names:
        rendered = ", ".join(sorted(set(duplicate_names)))
        raise ValueError(f"Found duplicate fixture results in aggregate input: {rendered}")

    aggregated.sort(key=lambda row: row.name)
    expected_names = sorted(case.name for case in expected_cases)
    actual_names = sorted(row.name for row in aggregated)
    missing_fixture_names = sorted(set(expected_names) - set(actual_names))
    unexpected_fixture_names = sorted(set(actual_names) - set(expected_names))

    return aggregated, {
        "baseline_coverage_complete": not missing_fixture_names and not unexpected_fixture_names,
        "missing_fixture_names": missing_fixture_names,
        "unexpected_fixture_names": unexpected_fixture_names,
    }

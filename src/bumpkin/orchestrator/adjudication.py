from __future__ import annotations

from bumpkin.analysis.findings import SEVERITY_ORDER, AggregatedFindingResult

DEFAULT_CHANGELOG_BY_LABEL = {
    "MAJOR": "feat: introduce breaking api changes",
    "MINOR": "feat: add backward-compatible api changes",
    "PATCH": "fix: update internal implementation",
    "NO_BUMP": "chore: no release required",
}


def categorize_failure_reason(reason: str | None) -> str | None:
    if not reason:
        return None

    normalized = reason.strip().lower()
    if "no token available" in normalized:
        return "missing_token"
    if "429" in normalized or "too many requests" in normalized:
        return "rate_limited"
    if "tokens_limit_reached" in normalized or "request body too large" in normalized:
        return "payload_too_large"
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


def source_from_mode(mode_used: str) -> str:
    if mode_used in {"github-models", "openrouter", "openai-compatible"}:
        return "model"
    if mode_used == "fallback-heuristic":
        return "semantic-fallback"
    if mode_used in {"deterministic-findings", "deterministic-heuristic", "deterministic-engine"}:
        return "deterministic-findings"
    if mode_used == "deterministic-no-diff":
        return "deterministic-no-diff"
    if mode_used == "no-bump":
        return "no-diff-heuristic"
    if mode_used == "stub":
        return "stub"
    return "unknown"


def derive_analysis_state(
    *,
    status: str,
    classification_source: str,
) -> tuple[str, str]:
    if status == "manual_review":
        return "manual_review", classification_source
    if classification_source in {
        "deterministic-findings",
        "deterministic-heuristic",
        "deterministic-no-diff",
        "court",
        "model",
        "hybrid",
    }:
        return "authoritative", classification_source
    return "degraded_fallback", classification_source


def apply_findings_adjudication(
    model_result: dict[str, object],
    *,
    aggregated_findings: AggregatedFindingResult | None,
    mode_used: str,
    notes: list[str],
) -> tuple[dict[str, object], str | None, str]:
    base_source = source_from_mode(mode_used)

    if aggregated_findings is None:
        notes.append("No deterministic JS/TS exported API findings were produced.")
        return model_result, None, base_source

    notes.append(
        "Deterministic findings engine produced "
        f"{aggregated_findings.contributing_findings} finding(s)."
    )
    notes.append(f"Aggregation trace: {aggregated_findings.aggregation_trace}")
    deterministic_result = aggregated_findings.to_result_dict()
    deterministic_status = str(deterministic_result.get("status", "manual_review"))
    deterministic_label = (
        str(deterministic_result.get("label", "")).upper()
        if deterministic_status == "classified"
        else ""
    )
    model_status = str(model_result.get("status", "manual_review"))
    model_label = str(model_result.get("label", "")).upper() if model_status == "classified" else ""

    if deterministic_status != "classified":
        notes.append(
            "Deterministic findings require manual review; overriding model recommendation."
        )
        return deterministic_result, aggregated_findings.aggregation_trace, "deterministic-findings"

    if deterministic_label == "MAJOR":
        notes.append(
            "Deterministic MAJOR finding is hard-authoritative and overrides model recommendation."
        )
        return deterministic_result, aggregated_findings.aggregation_trace, "deterministic-findings"

    if base_source != "model":
        notes.append(
            "Deterministic findings took precedence because model classification was unavailable."
        )
        return deterministic_result, aggregated_findings.aggregation_trace, "deterministic-findings"

    if model_status != "classified" or model_label not in SEVERITY_ORDER:
        notes.append(
            "Model did not produce a classified label; using deterministic findings classification."
        )
        return deterministic_result, aggregated_findings.aggregation_trace, "deterministic-findings"

    floor_level = SEVERITY_ORDER.get(deterministic_label)
    model_level = SEVERITY_ORDER.get(model_label)
    if floor_level is None or model_level is None:
        notes.append(
            "Hybrid adjudication unavailable due unknown severity label; using model classification."
        )
        return model_result, aggregated_findings.aggregation_trace, "model"

    if model_level >= floor_level:
        notes.append(
            "Hybrid adjudication: deterministic findings set a minimum floor; model classification met or exceeded it."
        )
        return model_result, aggregated_findings.aggregation_trace, "hybrid"

    promoted = dict(model_result)
    promoted["status"] = "classified"
    promoted["label"] = deterministic_label
    promoted["confidence"] = deterministic_result.get("confidence") or model_result.get(
        "confidence"
    )
    promoted["changelog"] = DEFAULT_CHANGELOG_BY_LABEL.get(
        deterministic_label, model_result.get("changelog")
    )
    model_reasoning = str(model_result.get("reasoning", "")).strip()
    deterministic_reasoning = str(deterministic_result.get("reasoning", "")).strip()
    promoted["reasoning"] = (
        f"Hybrid adjudication raised model label {model_label} to deterministic floor {deterministic_label}. "
        f"Deterministic rationale: {deterministic_reasoning} "
        f"Model rationale: {model_reasoning}"
    ).strip()
    notes.append(
        f"Hybrid adjudication: model label {model_label} raised to deterministic floor {deterministic_label}."
    )
    return promoted, aggregated_findings.aggregation_trace, "hybrid"

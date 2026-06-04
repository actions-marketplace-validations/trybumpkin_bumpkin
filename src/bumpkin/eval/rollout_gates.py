from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RolloutGateResult:
    ok: bool
    failures: tuple[str, ...]


def evaluate_rollout_gate(
    metrics: dict[str, Any],
    *,
    min_pass_rate: float = 0.70,
    max_unexpected_manual_review_rate: float = 0.20,
    max_unexpected_critical_missing_proofs_total: int = 0,
    max_contradiction_count: int = 0,
    expect_evaluated_count: int | None = None,
) -> RolloutGateResult:
    failures: list[str] = []

    evaluated = int(metrics.get("evaluated_fixture_count", 0) or 0)
    if expect_evaluated_count is not None and evaluated != expect_evaluated_count:
        failures.append(
            f"evaluated_fixture_count expected {expect_evaluated_count}, got {evaluated}"
        )

    pass_rate = float(metrics.get("overall_pass_rate", 0.0) or 0.0)
    if pass_rate < min_pass_rate:
        failures.append(f"overall_pass_rate {pass_rate:.2%} < {min_pass_rate:.2%}")

    manual_review_rate = float(metrics.get("manual_review_rate", 0.0) or 0.0)
    unexpected_manual_review_rate = float(
        metrics.get("unexpected_manual_review_rate", manual_review_rate) or 0.0
    )
    if unexpected_manual_review_rate > max_unexpected_manual_review_rate:
        failures.append(
            "unexpected_manual_review_rate "
            f"{unexpected_manual_review_rate:.2%} > {max_unexpected_manual_review_rate:.2%}"
        )

    critical_missing_proofs_total = int(metrics.get("critical_missing_proofs_total", 0) or 0)
    unexpected_critical_missing_proofs_total = int(
        metrics.get("unexpected_critical_missing_proofs_total", critical_missing_proofs_total) or 0
    )
    if unexpected_critical_missing_proofs_total > max_unexpected_critical_missing_proofs_total:
        failures.append(
            "unexpected_critical_missing_proofs_total "
            f"{unexpected_critical_missing_proofs_total} > "
            f"{max_unexpected_critical_missing_proofs_total}"
        )

    contradiction_count = int(metrics.get("contradiction_count", 0) or 0)
    if contradiction_count > max_contradiction_count:
        failures.append(f"contradiction_count {contradiction_count} > {max_contradiction_count}")

    return RolloutGateResult(ok=not failures, failures=tuple(failures))


def evaluate_preflight_gate(
    preflight: dict[str, Any],
    *,
    require_status: str,
) -> RolloutGateResult:
    status = str(preflight.get("status", "")).strip().lower()
    if require_status == "any":
        return RolloutGateResult(ok=True, failures=())
    if status == require_status:
        return RolloutGateResult(ok=True, failures=())
    return RolloutGateResult(
        ok=False,
        failures=(f"preflight.status expected {require_status!r}, got {status or 'unknown'!r}",),
    )

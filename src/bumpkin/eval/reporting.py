from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any


def serialize_results(results: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": row.name,
            "expected": row.expected,
            "actual": row.actual,
            "passed": row.passed,
            "category": row.category,
        }
        for row in results
    ]


def write_output_json(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def print_case_results(
    results: list[Any],
    *,
    build_observed_summary_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    for row in results:
        status = "PASS" if row.passed else "FAIL"
        expected_json = json.dumps(row.expected, sort_keys=True)
        observed_json = json.dumps(build_observed_summary_fn(row.actual), sort_keys=True)
        print(
            f"{status} {row.name} category={row.category} "
            f"expected={expected_json} observed={observed_json}"
        )


def print_metrics_summary(
    *,
    passed_count: int,
    result_count: int,
    pass_rate: float,
    mode_used_for_summary: str,
    avg_latency_ms: float,
    avg_tokens: float,
    metrics: dict[str, Any],
) -> None:
    print(
        f"Summary: {passed_count}/{result_count} passed "
        f"({pass_rate:.0%}) in mode={mode_used_for_summary}"
    )
    print(
        "Benchmark baseline: "
        f"pass_rate={pass_rate:.2%} avg_latency_ms={avg_latency_ms:.1f} "
        f"avg_tokens={avg_tokens:.1f}"
    )
    print(
        "Prompt metrics: "
        f"prompt_version={metrics['prompt_version']} "
        f"language_group={metrics['language_group']} "
        f"promotion_status={metrics['promotion_status']} "
        f"schema_valid_rate={metrics['schema_valid_rate']:.2%} "
        f"labeled_fixture_count={metrics['labeled_fixture_count']} "
        f"mixed_fixture_count={metrics['mixed_fixture_count']} "
        f"ambiguous_total={metrics['ambiguous_total']} "
        f"ambiguous_low_confidence_rate={metrics['ambiguous_low_confidence_rate']:.2%} "
        f"no_bump_total={metrics['no_bump_total']} "
        f"no_bump_pass_rate={metrics['no_bump_pass_rate']:.2%} "
        f"finding_precision={metrics['finding_precision']:.2%} "
        f"finding_recall={metrics['finding_recall']:.2%} "
        f"finding_f1={metrics['finding_f1']:.2%} "
        f"manual_review_rate={metrics['manual_review_rate']:.2%} "
        f"unexpected_manual_review_rate={metrics['unexpected_manual_review_rate']:.2%} "
        f"critical_missing_proofs_total={metrics['critical_missing_proofs_total']} "
        f"unexpected_critical_missing_proofs_total={metrics['unexpected_critical_missing_proofs_total']} "
        f"contradiction_count={metrics['contradiction_count']}"
    )
    for category, category_pass_rate in metrics["category_pass_rates"].items():
        print(f"Category metric: {category} pass_rate={category_pass_rate:.2%}")
    for label, label_pass_rate in metrics["label_pass_rates"].items():
        print(f"Label metric: {label} pass_rate={label_pass_rate:.2%}")
    for expected_label, actual_counts in sorted(metrics["label_confusion"].items()):
        rendered = ",".join(
            f"{actual_label}:{count}" for actual_label, count in sorted(actual_counts.items())
        )
        print(f"Label confusion: expected={expected_label} observed={rendered}")

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast


def _as_object_list(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return cast("list[object]", value)


def _as_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, Any]", value)


def is_schema_valid(actual: dict[str, Any]) -> bool:
    status = actual.get("status")
    reasoning = actual.get("reasoning")
    if status not in {"classified", "manual_review"}:
        return False
    if not isinstance(reasoning, str) or not reasoning.strip():
        return False
    if status == "manual_review":
        return actual.get("label") is None and actual.get("changelog") is None
    return (
        isinstance(actual.get("label"), str)
        and isinstance(actual.get("confidence"), str)
        and isinstance(actual.get("changelog"), str)
    )


def build_observed_summary(actual: dict[str, Any]) -> dict[str, Any]:
    observed = {
        "status": actual.get("status"),
        "label": actual.get("label"),
        "confidence": actual.get("confidence"),
        "mode_used": actual.get("mode_used"),
        "advisory_status": actual.get("advisory_status"),
    }
    if actual.get("fallback_reason"):
        observed["fallback_reason"] = actual["fallback_reason"]
    if actual.get("failure_category"):
        observed["failure_category"] = actual["failure_category"]
    findings = _as_object_list(actual.get("findings"))
    if findings is not None:
        observed["finding_count"] = len(findings)
    contradictions = _as_object_list(actual.get("contradictions"))
    if contradictions is not None:
        observed["contradiction_count"] = len(contradictions)
    return observed


def extract_expected_finding_specs(expected: dict[str, Any]) -> list[tuple[str, str | None]]:
    findings = _as_object_list(expected.get("findings"))
    if findings is None:
        return []

    specs: list[tuple[str, str | None]] = []
    for item in findings:
        if isinstance(item, str):
            token = item.strip().lower()
            if token:
                specs.append((token, None))
            continue
        finding = _as_dict(item)
        if finding is None:
            continue
        rule = str(finding.get("rule", "")).strip().lower()
        if not rule:
            continue
        severity_value = finding.get("severity")
        severity = (
            str(severity_value).strip().upper()
            if isinstance(severity_value, str) and severity_value.strip()
            else None
        )
        specs.append((rule, severity))
    return specs


def extract_actual_finding_specs(actual: dict[str, Any]) -> list[tuple[str, str]]:
    findings = _as_object_list(actual.get("findings"))
    if findings is None:
        return []

    specs: list[tuple[str, str]] = []
    for item in findings:
        finding = _as_dict(item)
        if finding is None:
            continue
        rule = str(finding.get("rule", "")).strip().lower()
        severity = str(finding.get("severity", "")).strip().upper()
        if not rule:
            continue
        specs.append((rule, severity))
    return specs


def compute_eval_metrics(
    results: Sequence[Any],
    *,
    prompt_version: str,
    language_group: str,
    promotion_status: str,
    total_case_count: int | None = None,
) -> dict[str, Any]:
    total = len(results)
    passed_count = sum(1 for row in results if row.passed)
    schema_valid_count = sum(1 for row in results if is_schema_valid(row.actual))

    category_totals: dict[str, int] = {}
    category_passed: dict[str, int] = {}
    label_totals: dict[str, int] = {}
    label_passed: dict[str, int] = {}
    label_confusion: dict[str, dict[str, int]] = {}
    labeled_fixture_count = 0
    mixed_fixture_count = 0
    ambiguous_total = 0
    ambiguous_low_confidence = 0
    no_bump_total = 0
    no_bump_passed = 0
    finding_annotated_fixtures = 0
    finding_expected_total = 0
    finding_predicted_total = 0
    finding_true_positives = 0
    finding_false_positives = 0
    finding_false_negatives = 0
    finding_exact_match_fixtures = 0
    deterministic_eval_total = 0
    deterministic_eval_matches = 0
    advisory_observed = 0
    advisory_aligned = 0
    advisory_disagreements = 0
    advisory_degraded = 0
    advisory_skipped = 0
    case_file_stats_observed = 0
    case_file_budget_compliant = 0
    manual_review_total = 0
    expected_manual_review_total = 0
    unexpected_manual_review_total = 0
    critical_missing_proofs_total = 0
    unexpected_critical_missing_proofs_total = 0
    contradiction_count = 0

    for row in results:
        status = str(row.actual.get("status", "")).strip().lower()
        expected_status = str(row.expected.get("status", "")).strip().lower()
        expected_manual_review = expected_status == "manual_review"
        if expected_manual_review:
            expected_manual_review_total += 1
        if status == "manual_review":
            manual_review_total += 1
            if not expected_manual_review:
                unexpected_manual_review_total += 1
        category_totals[row.category] = category_totals.get(row.category, 0) + 1
        if row.passed:
            category_passed[row.category] = category_passed.get(row.category, 0) + 1
        expected_label = str(row.expected.get("label", "")).strip().upper()
        actual_label = str(row.actual.get("label", "")).strip().upper()
        expected_findings = extract_expected_finding_specs(row.expected)
        expected_finding_severities = {
            severity for _, severity in expected_findings if severity is not None
        }
        if row.category.startswith("mixed_") or len(expected_finding_severities) >= 2:
            mixed_fixture_count += 1
        if expected_label:
            label_totals[expected_label] = label_totals.get(expected_label, 0) + 1
            labeled_fixture_count += 1
            if row.passed:
                label_passed[expected_label] = label_passed.get(expected_label, 0) + 1
            if actual_label:
                observed = label_confusion.setdefault(expected_label, {})
                observed[actual_label] = observed.get(actual_label, 0) + 1
            deterministic_label = (
                str(row.actual.get("deterministic_label") or row.actual.get("label") or "")
                .strip()
                .upper()
            )
            if deterministic_label:
                deterministic_eval_total += 1
                if deterministic_label == expected_label:
                    deterministic_eval_matches += 1
        if expected_label == "NO_BUMP":
            no_bump_total += 1
            if row.passed:
                no_bump_passed += 1
        if str(row.expected.get("confidence", "")).strip().lower() == "low":
            ambiguous_total += 1
            if str(row.actual.get("confidence", "")).strip().lower() == "low":
                ambiguous_low_confidence += 1

        if expected_findings:
            finding_annotated_fixtures += 1
            finding_expected_total += len(expected_findings)
            actual_findings = extract_actual_finding_specs(row.actual)
            finding_predicted_total += len(actual_findings)

            consumed_actual_indexes: set[int] = set()
            fixture_true_positives = 0
            fixture_false_negatives = 0

            for expected_rule, expected_severity in expected_findings:
                matched_index: int | None = None
                for index, (actual_rule, actual_severity) in enumerate(actual_findings):
                    if index in consumed_actual_indexes:
                        continue
                    if actual_rule != expected_rule:
                        continue
                    if expected_severity is not None and actual_severity != expected_severity:
                        continue
                    matched_index = index
                    break

                if matched_index is None:
                    fixture_false_negatives += 1
                    continue

                consumed_actual_indexes.add(matched_index)
                fixture_true_positives += 1

            fixture_false_positives = len(actual_findings) - len(consumed_actual_indexes)
            finding_true_positives += fixture_true_positives
            finding_false_negatives += fixture_false_negatives
            finding_false_positives += fixture_false_positives
            if fixture_false_negatives == 0 and fixture_false_positives == 0:
                finding_exact_match_fixtures += 1

        advisory_status = str(row.actual.get("advisory_status", "")).strip().lower()
        if advisory_status in {"aligned", "manual_review", "degraded", "skipped"}:
            advisory_observed += 1
            if advisory_status == "aligned":
                advisory_aligned += 1
            elif advisory_status == "manual_review":
                advisory_disagreements += 1
            elif advisory_status == "degraded":
                advisory_degraded += 1
            elif advisory_status == "skipped":
                advisory_skipped += 1

        case_file_stats = _as_dict(row.actual.get("case_file_stats"))
        if case_file_stats is not None:
            token_budget = case_file_stats.get("token_budget")
            estimated = case_file_stats.get("estimated_input_tokens")
            if isinstance(token_budget, int) and isinstance(estimated, int):
                case_file_stats_observed += 1
                if estimated <= token_budget:
                    case_file_budget_compliant += 1

        proof_obligations = _as_dict(row.actual.get("proof_obligations"))
        if proof_obligations is not None:
            critical_missing = _as_object_list(proof_obligations.get("critical_missing", []))
            if critical_missing is not None:
                normalized_missing = [item for item in critical_missing if str(item).strip()]
                critical_missing_proofs_total += len(normalized_missing)
                if not expected_manual_review:
                    unexpected_critical_missing_proofs_total += len(normalized_missing)

        contradictions = _as_object_list(row.actual.get("contradictions"))
        if contradictions is not None:
            contradiction_count += sum(1 for item in contradictions if _as_dict(item) is not None)

    category_pass_rates = {
        category: category_passed.get(category, 0) / count
        for category, count in sorted(category_totals.items())
    }
    label_pass_rates = {
        label: label_passed.get(label, 0) / count for label, count in sorted(label_totals.items())
    }

    finding_precision = (
        finding_true_positives / (finding_true_positives + finding_false_positives)
        if (finding_true_positives + finding_false_positives)
        else 0.0
    )
    finding_recall = (
        finding_true_positives / (finding_true_positives + finding_false_negatives)
        if (finding_true_positives + finding_false_negatives)
        else 0.0
    )
    finding_f1 = (
        2 * finding_precision * finding_recall / (finding_precision + finding_recall)
        if (finding_precision + finding_recall) > 0
        else 0.0
    )

    return {
        "prompt_version": prompt_version,
        "language_group": language_group,
        "promotion_status": promotion_status,
        "overall_pass_rate": passed_count / total if total else 0.0,
        "schema_valid_rate": schema_valid_count / total if total else 0.0,
        "labeled_fixture_count": labeled_fixture_count,
        "mixed_fixture_count": mixed_fixture_count,
        "ambiguous_total": ambiguous_total,
        "ambiguous_low_confidence_rate": (
            ambiguous_low_confidence / ambiguous_total if ambiguous_total else 0.0
        ),
        "no_bump_total": no_bump_total,
        "no_bump_pass_rate": no_bump_passed / no_bump_total if no_bump_total else 0.0,
        "category_pass_rates": category_pass_rates,
        "label_pass_rates": label_pass_rates,
        "label_totals": label_totals,
        "label_confusion": label_confusion,
        "finding_annotated_fixtures": finding_annotated_fixtures,
        "finding_annotation_coverage": (finding_annotated_fixtures / total if total else 0.0),
        "finding_expected_total": finding_expected_total,
        "finding_predicted_total": finding_predicted_total,
        "finding_true_positives": finding_true_positives,
        "finding_false_positives": finding_false_positives,
        "finding_false_negatives": finding_false_negatives,
        "finding_precision": finding_precision,
        "finding_recall": finding_recall,
        "finding_f1": finding_f1,
        "finding_exact_match_rate": (
            finding_exact_match_fixtures / finding_annotated_fixtures
            if finding_annotated_fixtures
            else 0.0
        ),
        "deterministic_eval_total": deterministic_eval_total,
        "deterministic_accuracy": (
            deterministic_eval_matches / deterministic_eval_total
            if deterministic_eval_total
            else 0.0
        ),
        "advisory_observed": advisory_observed,
        "advisory_alignment_rate": (
            advisory_aligned / advisory_observed if advisory_observed else 0.0
        ),
        "advisory_disagreement_rate": (
            advisory_disagreements / advisory_observed if advisory_observed else 0.0
        ),
        "advisory_degraded_rate": (
            advisory_degraded / advisory_observed if advisory_observed else 0.0
        ),
        "advisory_skipped_rate": (
            advisory_skipped / advisory_observed if advisory_observed else 0.0
        ),
        "case_file_stats_observed": case_file_stats_observed,
        "case_file_budget_compliance_rate": (
            case_file_budget_compliant / case_file_stats_observed
            if case_file_stats_observed
            else 0.0
        ),
        "manual_review_rate": manual_review_total / total if total else 0.0,
        "expected_manual_review_total": expected_manual_review_total,
        "unexpected_manual_review_total": unexpected_manual_review_total,
        "unexpected_manual_review_rate": (
            unexpected_manual_review_total / (total - expected_manual_review_total)
            if total > expected_manual_review_total
            else 0.0
        ),
        "critical_missing_proofs_total": critical_missing_proofs_total,
        "unexpected_critical_missing_proofs_total": unexpected_critical_missing_proofs_total,
        "contradiction_count": contradiction_count,
        "evaluated_fixture_count": total,
        "total_case_count": total_case_count if total_case_count is not None else total,
        "is_subset_run": (total_case_count is not None and total_case_count > total),
        "evaluated_categories": sorted(category_totals),
    }


def load_prompt_gate_baseline(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text())
    if not isinstance(loaded, dict):
        raise ValueError("Prompt gate baseline must be a JSON object.")
    baseline = cast("dict[str, Any]", loaded)
    required = {
        "prompt_version",
        "language_group",
        "promotion_status",
        "fixture_set",
        "min_overall_pass_rate",
        "required_schema_valid_rate",
        "min_ambiguous_low_confidence_rate",
        "min_category_pass_rates",
    }
    missing = sorted(required - set(baseline))
    if missing:
        raise ValueError(f"Prompt gate baseline missing required keys: {', '.join(missing)}")
    min_category_pass_rates = _as_dict(baseline["min_category_pass_rates"])
    if min_category_pass_rates is None:
        raise ValueError("Prompt gate baseline `min_category_pass_rates` must be an object.")
    baseline["min_category_pass_rates"] = min_category_pass_rates
    distribution = baseline.get("required_fixture_distribution")
    if distribution is not None:
        distribution_dict = _as_dict(distribution)
        if distribution_dict is None:
            raise ValueError(
                "Prompt gate baseline `required_fixture_distribution` must be an object."
            )
        labeled_fixture_min = distribution_dict.get("labeled_fixture_min")
        if labeled_fixture_min is not None and (
            not isinstance(labeled_fixture_min, int) or labeled_fixture_min < 0
        ):
            raise ValueError(
                "Prompt gate baseline `required_fixture_distribution.labeled_fixture_min` "
                "must be a non-negative integer."
            )
        mixed_fixture_min = distribution_dict.get("mixed_fixture_min")
        if mixed_fixture_min is not None and (
            not isinstance(mixed_fixture_min, int) or mixed_fixture_min < 0
        ):
            raise ValueError(
                "Prompt gate baseline `required_fixture_distribution.mixed_fixture_min` "
                "must be a non-negative integer."
            )
        label_mins = distribution_dict.get("label_mins")
        if label_mins is not None:
            label_mins_dict = _as_dict(label_mins)
            if label_mins_dict is None:
                raise ValueError(
                    "Prompt gate baseline `required_fixture_distribution.label_mins` "
                    "must be an object."
                )
            for label, minimum in label_mins_dict.items():
                if not label.strip():
                    raise ValueError(
                        "Prompt gate baseline `required_fixture_distribution.label_mins` "
                        "keys must be non-empty strings."
                    )
                if not isinstance(minimum, int) or minimum < 0:
                    raise ValueError(
                        "Prompt gate baseline `required_fixture_distribution.label_mins` "
                        "values must be non-negative integers."
                    )
    court_thresholds = baseline.get("court_thresholds")
    if court_thresholds is not None:
        court_thresholds_dict = _as_dict(court_thresholds)
        if court_thresholds_dict is None:
            raise ValueError("Prompt gate baseline `court_thresholds` must be an object.")
        baseline["court_thresholds"] = court_thresholds_dict
        for key in (
            "min_deterministic_accuracy",
            "min_advisory_alignment_rate",
            "max_advisory_degraded_rate",
            "required_case_file_budget_compliance_rate",
        ):
            value = court_thresholds_dict.get(key)
            if value is None:
                continue
            if not isinstance(value, (int, float)):
                raise ValueError(f"Prompt gate baseline `court_thresholds.{key}` must be numeric.")
    return baseline


def compare_against_prompt_gate(
    metrics: dict[str, Any],
    baseline: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    is_subset_run = bool(metrics.get("is_subset_run"))
    present_categories_list = _as_object_list(metrics.get("evaluated_categories", [])) or []
    present_categories = {str(item) for item in present_categories_list if str(item).strip()}

    if not is_subset_run and metrics["overall_pass_rate"] < baseline["min_overall_pass_rate"]:
        failures.append(
            "overall_pass_rate below prompt gate: "
            f"{metrics['overall_pass_rate']:.2%} < {baseline['min_overall_pass_rate']:.2%}"
        )

    if metrics["schema_valid_rate"] < baseline["required_schema_valid_rate"]:
        failures.append(
            "schema_valid_rate below prompt gate: "
            f"{metrics['schema_valid_rate']:.2%} < {baseline['required_schema_valid_rate']:.2%}"
        )

    ambiguous_total = metrics.get("ambiguous_total")
    if (ambiguous_total is None or ambiguous_total > 0) and metrics[
        "ambiguous_low_confidence_rate"
    ] < baseline["min_ambiguous_low_confidence_rate"]:
        failures.append(
            "ambiguous_low_confidence_rate below prompt gate: "
            f"{metrics['ambiguous_low_confidence_rate']:.2%} "
            f"< {baseline['min_ambiguous_low_confidence_rate']:.2%}"
        )

    min_category_pass_rates = _as_dict(baseline.get("min_category_pass_rates")) or {}
    for category, minimum in sorted(min_category_pass_rates.items()):
        minimum_value = float(minimum)
        if is_subset_run and category not in present_categories:
            continue
        actual_rate = metrics["category_pass_rates"].get(category, 0.0)
        if actual_rate < minimum_value:
            failures.append(
                f"category {category} below prompt gate: {actual_rate:.2%} < {minimum_value:.2%}"
            )

    required_distribution = baseline.get("required_fixture_distribution")
    if required_distribution and not is_subset_run:
        required_distribution_dict = _as_dict(required_distribution) or {}
        labeled_fixture_min = int(required_distribution_dict.get("labeled_fixture_min", 0))
        labeled_fixture_count = int(metrics.get("labeled_fixture_count", 0))
        if labeled_fixture_count < labeled_fixture_min:
            failures.append(
                "labeled_fixture_count below prompt gate: "
                f"{labeled_fixture_count} < {labeled_fixture_min}"
            )

        mixed_fixture_min = int(required_distribution_dict.get("mixed_fixture_min", 0))
        mixed_fixture_count = int(metrics.get("mixed_fixture_count", 0))
        if mixed_fixture_count < mixed_fixture_min:
            failures.append(
                "mixed_fixture_count below prompt gate: "
                f"{mixed_fixture_count} < {mixed_fixture_min}"
            )

        label_totals = _as_dict(metrics.get("label_totals", {}))
        label_mins = _as_dict(required_distribution_dict.get("label_mins", {}))
        if label_totals is not None and label_mins is not None:
            for label, minimum in sorted(label_mins.items()):
                actual_count = int(label_totals.get(label, 0))
                minimum_count = int(minimum)
                if actual_count < minimum_count:
                    failures.append(
                        f"label count {label} below prompt gate: {actual_count} < {minimum_count}"
                    )

    court_thresholds = baseline.get("court_thresholds")
    if court_thresholds and not is_subset_run:
        court_thresholds_dict = _as_dict(court_thresholds) or {}
        min_det = court_thresholds_dict.get("min_deterministic_accuracy")
        if isinstance(min_det, (int, float)):
            actual = float(metrics.get("deterministic_accuracy", 0.0))
            if actual < float(min_det):
                failures.append(
                    f"deterministic_accuracy below prompt gate: {actual:.2%} < {float(min_det):.2%}"
                )
        min_align = court_thresholds_dict.get("min_advisory_alignment_rate")
        if isinstance(min_align, (int, float)):
            actual = float(metrics.get("advisory_alignment_rate", 0.0))
            if actual < float(min_align):
                failures.append(
                    "advisory_alignment_rate below prompt gate: "
                    f"{actual:.2%} < {float(min_align):.2%}"
                )
        max_degraded = court_thresholds_dict.get("max_advisory_degraded_rate")
        if isinstance(max_degraded, (int, float)):
            actual = float(metrics.get("advisory_degraded_rate", 0.0))
            if actual > float(max_degraded):
                failures.append(
                    "advisory_degraded_rate above prompt gate: "
                    f"{actual:.2%} > {float(max_degraded):.2%}"
                )
        required_case_budget = court_thresholds_dict.get(
            "required_case_file_budget_compliance_rate"
        )
        if isinstance(required_case_budget, (int, float)):
            actual = float(metrics.get("case_file_budget_compliance_rate", 0.0))
            if actual < float(required_case_budget):
                failures.append(
                    "case_file_budget_compliance_rate below prompt gate: "
                    f"{actual:.2%} < {float(required_case_budget):.2%}"
                )

    return failures

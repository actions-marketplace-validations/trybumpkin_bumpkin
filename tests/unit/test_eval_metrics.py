from types import SimpleNamespace

from bumpkin.eval.metrics import compare_against_prompt_gate, compute_eval_metrics


def _row(
    *,
    name: str,
    expected_label: str,
    actual_label: str,
    passed: bool,
    advisory_status: str,
    deterministic_label: str | None = None,
    case_file_budget: tuple[int, int] | None = None,
    status: str = "classified",
    proof_obligations: dict[str, object] | None = None,
    contradictions: list[dict[str, object]] | None = None,
    expected_status: str | None = None,
) -> SimpleNamespace:
    actual: dict[str, object] = {
        "status": status,
        "label": actual_label,
        "confidence": "high",
        "reasoning": "ok reasoning",
        "changelog": "fix: update",
        "advisory_status": advisory_status,
    }
    if deterministic_label is not None:
        actual["deterministic_label"] = deterministic_label
    if case_file_budget is not None:
        token_budget, estimated = case_file_budget
        actual["case_file_stats"] = {
            "token_budget": token_budget,
            "estimated_input_tokens": estimated,
        }
    if proof_obligations is not None:
        actual["proof_obligations"] = proof_obligations
    if contradictions is not None:
        actual["contradictions"] = contradictions
    expected: dict[str, object] = {"label": expected_label}
    if expected_status is not None:
        expected["status"] = expected_status
    return SimpleNamespace(
        name=name,
        category="test",
        passed=passed,
        expected=expected,
        actual=actual,
    )


def test_compute_eval_metrics_includes_court_fields() -> None:
    rows = [
        _row(
            name="a",
            expected_label="MINOR",
            actual_label="MINOR",
            passed=True,
            advisory_status="aligned",
            deterministic_label="MINOR",
            case_file_budget=(1200, 500),
            status="manual_review",
            proof_obligations={
                "critical_missing": ["semantic_fact_present"],
            },
            contradictions=[{"code": "intent_fix_vs_public_change", "message": "Mismatch"}],
        ),
        _row(
            name="b",
            expected_label="PATCH",
            actual_label="PATCH",
            passed=True,
            advisory_status="degraded",
            deterministic_label="PATCH",
            case_file_budget=(1200, 1400),
        ),
    ]
    metrics = compute_eval_metrics(
        rows,
        prompt_version="js-ts-v1",
        language_group="javascript-typescript",
        promotion_status="candidate",
    )
    assert metrics["deterministic_eval_total"] == 2
    assert metrics["deterministic_accuracy"] == 1.0
    assert metrics["advisory_observed"] == 2
    assert metrics["advisory_alignment_rate"] == 0.5
    assert metrics["advisory_degraded_rate"] == 0.5
    assert metrics["case_file_stats_observed"] == 2
    assert metrics["case_file_budget_compliance_rate"] == 0.5
    assert metrics["manual_review_rate"] == 0.5
    assert metrics["unexpected_manual_review_rate"] == 0.5
    assert metrics["critical_missing_proofs_total"] == 1
    assert metrics["unexpected_critical_missing_proofs_total"] == 1
    assert metrics["contradiction_count"] == 1


def test_compute_eval_metrics_excludes_expected_manual_reviews_from_strict_metrics() -> None:
    rows = [
        _row(
            name="manual-expected",
            expected_label="",
            expected_status="manual_review",
            actual_label="",
            passed=True,
            advisory_status="degraded",
            status="manual_review",
            proof_obligations={"critical_missing": ["semantic_fact_present"]},
        ),
        _row(
            name="classified-expected",
            expected_label="MINOR",
            actual_label="MINOR",
            passed=True,
            advisory_status="aligned",
            deterministic_label="MINOR",
        ),
    ]
    metrics = compute_eval_metrics(
        rows,
        prompt_version="js-ts-v1",
        language_group="javascript-typescript",
        promotion_status="candidate",
    )
    assert metrics["manual_review_rate"] == 0.5
    assert metrics["expected_manual_review_total"] == 1
    assert metrics["unexpected_manual_review_total"] == 0
    assert metrics["unexpected_manual_review_rate"] == 0.0
    assert metrics["critical_missing_proofs_total"] == 1
    assert metrics["unexpected_critical_missing_proofs_total"] == 0


def test_compare_against_prompt_gate_applies_optional_court_thresholds() -> None:
    metrics = {
        "is_subset_run": False,
        "overall_pass_rate": 1.0,
        "schema_valid_rate": 1.0,
        "ambiguous_total": 0,
        "ambiguous_low_confidence_rate": 1.0,
        "category_pass_rates": {"test": 1.0},
        "labeled_fixture_count": 1,
        "mixed_fixture_count": 0,
        "label_totals": {"PATCH": 1},
        "deterministic_accuracy": 0.8,
        "advisory_alignment_rate": 0.75,
        "advisory_degraded_rate": 0.2,
        "case_file_budget_compliance_rate": 0.9,
    }
    baseline = {
        "min_overall_pass_rate": 0.7,
        "required_schema_valid_rate": 1.0,
        "min_ambiguous_low_confidence_rate": 1.0,
        "min_category_pass_rates": {"test": 1.0},
        "court_thresholds": {
            "min_deterministic_accuracy": 0.9,
            "min_advisory_alignment_rate": 0.8,
            "max_advisory_degraded_rate": 0.1,
            "required_case_file_budget_compliance_rate": 1.0,
        },
    }
    failures = compare_against_prompt_gate(metrics, baseline)
    assert any("deterministic_accuracy" in item for item in failures)
    assert any("advisory_alignment_rate" in item for item in failures)
    assert any("advisory_degraded_rate" in item for item in failures)
    assert any("case_file_budget_compliance_rate" in item for item in failures)

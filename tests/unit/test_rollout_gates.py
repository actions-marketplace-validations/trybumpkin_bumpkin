from bumpkin.eval.rollout_gates import evaluate_preflight_gate, evaluate_rollout_gate


def test_rollout_gate_fails_when_manual_review_spikes() -> None:
    result = evaluate_rollout_gate(
        {
            "evaluated_fixture_count": 4,
            "overall_pass_rate": 0.90,
            "manual_review_rate": 0.50,
            "unexpected_manual_review_rate": 0.50,
            "critical_missing_proofs_total": 0,
            "unexpected_critical_missing_proofs_total": 0,
            "contradiction_count": 0,
        }
    )
    assert result.ok is False
    assert any("unexpected_manual_review_rate" in item for item in result.failures)


def test_rollout_gate_passes_when_metrics_within_thresholds() -> None:
    result = evaluate_rollout_gate(
        {
            "evaluated_fixture_count": 4,
            "overall_pass_rate": 0.95,
            "manual_review_rate": 0.05,
            "unexpected_manual_review_rate": 0.05,
            "critical_missing_proofs_total": 0,
            "unexpected_critical_missing_proofs_total": 0,
            "contradiction_count": 0,
        },
        expect_evaluated_count=4,
    )
    assert result.ok is True
    assert result.failures == ()


def test_preflight_gate_enforces_required_status() -> None:
    failed = evaluate_preflight_gate({"status": "failed"}, require_status="ok")
    assert failed.ok is False

    passed = evaluate_preflight_gate({"status": "ok"}, require_status="ok")
    assert passed.ok is True

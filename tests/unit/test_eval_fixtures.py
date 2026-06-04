from __future__ import annotations

from unittest.mock import MagicMock

from bumpkin.eval.fixtures import FixtureCase, run_eval


def test_run_eval_honors_inter_case_delay_ms(monkeypatch) -> None:
    delay_log: list[float] = []

    def fake_sleep(value: float) -> None:
        delay_log.append(value)

    monkeypatch.setattr("bumpkin.eval.fixtures.time.sleep", fake_sleep)
    recommend = MagicMock(return_value={"label": "PATCH"})

    cases = [
        FixtureCase(
            name="case-a", diff_text="+ export function a() {}", expected={"label": "PATCH"}
        ),
        FixtureCase(
            name="case-b", diff_text="+ export function b() {}", expected={"label": "PATCH"}
        ),
    ]

    results, passed_count, pass_rate, _, _ = run_eval(
        cases,
        recommend,
        inter_case_delay_ms=250,
    )

    assert len(delay_log) == 2
    assert delay_log == [0.25, 0.25]
    assert len(results) == 2
    assert passed_count == 2
    assert pass_rate == 1.0

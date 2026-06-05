import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from eval import (
    FixtureCase,
    _build_fixture_diff_result,
    _filter_cases,
    aggregate_results_from_json_dir,
    build_case_inputs,
    build_observed_summary,
    categorize_failure_reason,
    compare_against_prompt_gate,
    compute_eval_metrics,
    evaluate_fixture_cases,
    get_default_prompt_gate_baseline,
    load_fixture_cases,
    load_prompt_gate_baseline,
    run_eval_preflight,
    select_batch_cases,
)


def test_load_fixture_cases_reads_expected_files(tmp_path: Path) -> None:
    case_dir = tmp_path / "minor_add_export"
    case_dir.mkdir()
    (case_dir / "diff.txt").write_text("+ export function getUserProfile() {}")
    (case_dir / "expected.json").write_text('{"label":"MINOR"}')

    cases = load_fixture_cases(tmp_path)
    assert len(cases) == 1
    assert cases[0].name == "minor_add_export"
    assert cases[0].expected["label"] == "MINOR"


def test_filter_cases_includes_legacy_unlabeled_cases_for_default_group() -> None:
    cases = [
        FixtureCase(
            name="legacy",
            diff_text="+ export const ping = () => 'ok';",
            expected={"label": "PATCH"},
        ),
        FixtureCase(
            name="python_case",
            diff_text="+ def ping() -> str:\n+     return 'ok'\n",
            expected={"label": "MINOR"},
            language="python",
        ),
    ]

    filtered = _filter_cases(
        cases,
        language_group="javascript-typescript",
        include_tuning_targets=False,
    )

    assert [case.name for case in filtered] == ["legacy"]


def test_load_fixture_cases_reads_optional_context_metadata(tmp_path: Path) -> None:
    case_dir = tmp_path / "surface_area_required"
    case_dir.mkdir()
    (case_dir / "diff.txt").write_text("+ export const version = '1.0.0'")
    (case_dir / "expected.json").write_text('{"label":"MINOR"}')
    (case_dir / "context.json").write_text(
        '{"language":"javascript-typescript","surface_area":["src/public/index.ts"],'
        '"category":"surface_area_required","note":"Requires public API hint."}'
    )

    cases = load_fixture_cases(tmp_path)

    assert cases[0].language == "javascript-typescript"
    assert cases[0].surface_area == ["src/public/index.ts"]
    assert cases[0].category == "surface_area_required"
    assert cases[0].note == "Requires public API hint."


def test_load_fixture_cases_reads_tuning_target_flag(tmp_path: Path) -> None:
    case_dir = tmp_path / "disagreement_target_case"
    case_dir.mkdir()
    (case_dir / "diff.txt").write_text("+ export const ping = true")
    (case_dir / "expected.json").write_text('{"label":"MINOR"}')
    (case_dir / "context.json").write_text(
        '{"language":"javascript-typescript","tuning_target":true}'
    )

    cases = load_fixture_cases(tmp_path)

    assert cases[0].tuning_target is True


def test_filter_cases_excludes_tuning_targets_by_default() -> None:
    cases = [
        FixtureCase(
            name="tuning",
            diff_text="+ export const ping = true",
            expected={"label": "MINOR"},
            language="javascript-typescript",
            tuning_target=True,
        ),
        FixtureCase(
            name="normal",
            diff_text="+ export const pong = true",
            expected={"label": "MINOR"},
            language="javascript-typescript",
        ),
    ]

    filtered = _filter_cases(
        cases,
        language_group="javascript-typescript",
        include_tuning_targets=False,
    )
    assert [case.name for case in filtered] == ["normal"]

    included = _filter_cases(
        cases,
        language_group="javascript-typescript",
        include_tuning_targets=True,
    )
    assert [case.name for case in included] == ["tuning", "normal"]


def test_load_fixture_cases_accepts_expected_findings_metadata(tmp_path: Path) -> None:
    case_dir = tmp_path / "major_export_removed"
    case_dir.mkdir()
    (case_dir / "diff.txt").write_text("- export function oldApi() {}")
    (case_dir / "expected.json").write_text(
        """
        {
          "label": "MAJOR",
          "findings": [
            {"rule": "export_symbol_removed", "severity": "MAJOR"}
          ]
        }
        """
    )

    cases = load_fixture_cases(tmp_path)

    assert len(cases) == 1
    assert isinstance(cases[0].expected["findings"], list)
    assert cases[0].expected["findings"][0]["rule"] == "export_symbol_removed"


def test_load_fixture_cases_rejects_invalid_expected_findings_payload(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "invalid_case"
    case_dir.mkdir()
    (case_dir / "diff.txt").write_text("+ export function ping() {}")
    (case_dir / "expected.json").write_text(
        """
        {
          "label": "MINOR",
          "findings": [{"severity": "MINOR"}]
        }
        """
    )

    try:
        load_fixture_cases(tmp_path)
    except ValueError as err:
        assert "findings[0].rule" in str(err)
    else:
        raise AssertionError("Expected invalid findings payload to raise ValueError")


def test_evaluate_fixture_cases_checks_expected_subset() -> None:
    cases = [
        FixtureCase(
            name="patch_docs_only",
            diff_text="+ update README wording",
            expected={"label": "NO_BUMP"},
        )
    ]

    results = evaluate_fixture_cases(
        cases,
        lambda _: {
            "status": "classified",
            "label": "NO_BUMP",
            "confidence": "low",
            "reasoning": "Docs-only update in README.",
            "changelog": "chore: no release required",
        },
    )
    assert len(results) == 1
    assert results[0].passed is True


def test_evaluate_fixture_cases_ignores_expected_findings_for_label_pass_fail() -> None:
    cases = [
        FixtureCase(
            name="major_export_removed",
            diff_text="- export function oldApi() {}",
            expected={
                "label": "MAJOR",
                "findings": [{"rule": "export_symbol_removed", "severity": "MAJOR"}],
            },
            category="major_export_removed",
        )
    ]

    results = evaluate_fixture_cases(
        cases,
        lambda _: {
            "status": "classified",
            "label": "MAJOR",
            "confidence": "high",
            "reasoning": "Removed exported API symbol oldApi.",
            "changelog": "feat: remove exported api symbols",
        },
    )

    assert len(results) == 1
    assert results[0].passed is True


def test_build_case_inputs_uses_context_language_and_surface_area() -> None:
    case = FixtureCase(
        name="major_signature_change",
        diff_text="- export function login(user, pass) {}\n+ export function login(credentials) {}",
        expected={"label": "MAJOR"},
        language="javascript-typescript",
        surface_area=["src/api/**"],
        category="major_signature_change",
        note=None,
    )

    surface_area_hints, language_hints = build_case_inputs(case)

    assert surface_area_hints == ["src/api/**"]
    assert len(language_hints) == 1
    assert "JavaScript/TypeScript" in language_hints[0]


def test_build_case_inputs_uses_python_language_hints() -> None:
    case = FixtureCase(
        name="minor_add_python_function",
        diff_text="+ def ping() -> str:\n+     return 'ok'\n",
        expected={"label": "MINOR"},
        language="python",
        surface_area=[],
        category="minor_export_added",
        note=None,
    )

    surface_area_hints, language_hints = build_case_inputs(case)

    assert surface_area_hints == []
    assert len(language_hints) == 1
    assert "Python" in language_hints[0]


def test_build_fixture_diff_result_seeds_synthetic_path_for_headerless_diff() -> None:
    case = FixtureCase(
        name="headerless_case",
        diff_text="+ export const ping = true",
        expected={"label": "MINOR"},
    )

    diff_result = _build_fixture_diff_result(case)

    assert diff_result.analyzed_files == ["fixture/headerless_case.diff"]
    assert diff_result.changed_files_total == 1
    assert diff_result.file_units[0].path == "fixture/headerless_case.diff"


def test_build_fixture_diff_result_keeps_real_paths_from_git_headers() -> None:
    case = FixtureCase(
        name="headered_case",
        diff_text=(
            "diff --git a/src/a.ts b/src/a.ts\n"
            "index 1111111..2222222 100644\n"
            "--- a/src/a.ts\n"
            "+++ b/src/a.ts\n"
            "@@ -1 +1 @@\n"
            "-export const a = 1;\n"
            "+export const a = 2;\n"
        ),
        expected={"label": "PATCH"},
    )

    diff_result = _build_fixture_diff_result(case)

    assert diff_result.analyzed_files == ["src/a.ts"]
    assert diff_result.changed_files_total == 1
    assert diff_result.file_units[0].path == "src/a.ts"


def test_compute_eval_metrics_reports_category_schema_and_ambiguity() -> None:
    cases = [
        FixtureCase(
            name="minor_add_export",
            diff_text="+ export function ping() {}",
            expected={"label": "MINOR"},
            language="javascript-typescript",
            surface_area=[],
            category="minor_export_added",
            note=None,
        ),
        FixtureCase(
            name="low_confidence_ambiguous",
            diff_text="+ changed publicish thing",
            expected={"confidence": "low"},
            language="javascript-typescript",
            surface_area=[],
            category="ambiguous_public_surface",
            note=None,
        ),
    ]

    results = evaluate_fixture_cases(
        cases,
        lambda case: {
            "status": "classified",
            "label": "MINOR" if case.name == "minor_add_export" else "PATCH",
            "confidence": "high" if case.name == "minor_add_export" else "low",
            "reasoning": "Reasoning text that satisfies schema requirements.",
            "changelog": "feat: emit stable changelog text",
        },
    )

    metrics = compute_eval_metrics(results, prompt_version="js-ts-v1")

    assert metrics["prompt_version"] == "js-ts-v1"
    assert metrics["overall_pass_rate"] == 1.0
    assert metrics["schema_valid_rate"] == 1.0
    assert metrics["ambiguous_low_confidence_rate"] == 1.0
    assert metrics["ambiguous_total"] == 1
    assert metrics["labeled_fixture_count"] == 1
    assert metrics["mixed_fixture_count"] == 0
    assert metrics["category_pass_rates"]["minor_export_added"] == 1.0
    assert metrics["label_pass_rates"]["MINOR"] == 1.0
    assert metrics["label_totals"]["MINOR"] == 1
    assert metrics["label_confusion"]["MINOR"]["MINOR"] == 1


def test_compute_eval_metrics_tracks_no_bump_cases() -> None:
    cases = [
        FixtureCase(
            name="no_bump_docs_only",
            diff_text="+ update README wording",
            expected={"label": "NO_BUMP"},
            language="javascript-typescript",
            surface_area=[],
            category="no_bump_docs_only",
            note=None,
        )
    ]

    results = evaluate_fixture_cases(
        cases,
        lambda _: {
            "status": "classified",
            "label": "NO_BUMP",
            "confidence": "high",
            "reasoning": "Only documentation changed with no runtime API impact.",
            "changelog": "chore: no release required",
        },
    )

    metrics = compute_eval_metrics(results, prompt_version="js-ts-v1")

    assert metrics["no_bump_total"] == 1
    assert metrics["no_bump_pass_rate"] == 1.0


def test_compute_eval_metrics_reports_finding_precision_recall() -> None:
    cases = [
        FixtureCase(
            name="major_export_removed",
            diff_text="- export function oldApi() {}",
            expected={
                "label": "MAJOR",
                "findings": [{"rule": "export_symbol_removed", "severity": "MAJOR"}],
            },
            language="javascript-typescript",
            category="major_export_removed",
        ),
        FixtureCase(
            name="minor_export_added",
            diff_text="+ export function newApi() {}",
            expected={
                "label": "MINOR",
                "findings": [{"rule": "export_symbol_added", "severity": "MINOR"}],
            },
            language="javascript-typescript",
            category="minor_export_added",
        ),
    ]

    def fake_recommend(case: FixtureCase) -> dict[str, object]:
        if case.name == "major_export_removed":
            return {
                "status": "classified",
                "label": "MAJOR",
                "confidence": "high",
                "reasoning": "Breaking export removed.",
                "changelog": "feat: remove exported api symbols",
                "findings": [
                    {"rule": "export_symbol_removed", "severity": "MAJOR"},
                    {"rule": "export_symbol_added", "severity": "MINOR"},
                ],
            }
        return {
            "status": "classified",
            "label": "MINOR",
            "confidence": "high",
            "reasoning": "Added export.",
            "changelog": "feat: add exported api symbols",
            "findings": [
                {"rule": "export_symbol_added", "severity": "PATCH"},
            ],
        }

    results = evaluate_fixture_cases(cases, fake_recommend)
    metrics = compute_eval_metrics(results, prompt_version="js-ts-v1")

    assert metrics["finding_annotated_fixtures"] == 2
    assert metrics["finding_expected_total"] == 2
    assert metrics["finding_predicted_total"] == 3
    assert metrics["finding_true_positives"] == 1
    assert metrics["finding_false_positives"] == 2
    assert metrics["finding_false_negatives"] == 1
    assert metrics["finding_precision"] == 1 / 3
    assert metrics["finding_recall"] == 0.5
    assert metrics["finding_f1"] == 0.4
    assert metrics["finding_exact_match_rate"] == 0.0


def test_compute_eval_metrics_tracks_mixed_fixture_count() -> None:
    cases = [
        FixtureCase(
            name="mixed_major_minor_case",
            diff_text="- export function oldApi() {}\n+ export function newApi() {}",
            expected={
                "label": "MAJOR",
                "findings": [
                    {"rule": "export_symbol_removed", "severity": "MAJOR"},
                    {"rule": "export_symbol_added", "severity": "MINOR"},
                ],
            },
            language="javascript-typescript",
            category="mixed_major_minor",
        )
    ]

    results = evaluate_fixture_cases(
        cases,
        lambda _: {
            "status": "classified",
            "label": "MAJOR",
            "confidence": "high",
            "reasoning": "Breaking symbol removal dominates.",
            "changelog": "feat: introduce breaking api changes",
        },
    )
    metrics = compute_eval_metrics(results, prompt_version="js-ts-v1")

    assert metrics["mixed_fixture_count"] == 1
    assert metrics["labeled_fixture_count"] == 1
    assert metrics["label_totals"]["MAJOR"] == 1


def test_load_prompt_gate_baseline_reads_required_fields(tmp_path: Path) -> None:
    baseline_path = tmp_path / "js-ts-v1.json"
    baseline_path.write_text(
        """
        {
          "prompt_version": "js-ts-v1",
          "language_group": "javascript-typescript",
          "promotion_status": "promoted",
          "fixture_set": "test-diffs",
          "min_overall_pass_rate": 0.7,
          "required_schema_valid_rate": 1.0,
          "min_ambiguous_low_confidence_rate": 1.0,
          "min_category_pass_rates": {
            "major_export_removed": 1.0
          },
          "required_fixture_distribution": {
            "labeled_fixture_min": 20,
            "mixed_fixture_min": 3,
            "label_mins": {
              "NO_BUMP": 4,
              "PATCH": 4
            }
          }
        }
        """
    )

    baseline = load_prompt_gate_baseline(baseline_path)

    assert baseline["prompt_version"] == "js-ts-v1"
    assert baseline["language_group"] == "javascript-typescript"
    assert baseline["promotion_status"] == "promoted"
    assert baseline["min_category_pass_rates"]["major_export_removed"] == 1.0
    assert baseline["required_fixture_distribution"]["labeled_fixture_min"] == 20


def test_load_prompt_gate_baseline_rejects_invalid_fixture_distribution(
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "js-ts-v1.json"
    baseline_path.write_text(
        """
        {
          "prompt_version": "js-ts-v1",
          "language_group": "javascript-typescript",
          "promotion_status": "promoted",
          "fixture_set": "test-diffs",
          "min_overall_pass_rate": 0.7,
          "required_schema_valid_rate": 1.0,
          "min_ambiguous_low_confidence_rate": 1.0,
          "min_category_pass_rates": {
            "major_export_removed": 1.0
          },
          "required_fixture_distribution": {
            "labeled_fixture_min": -1
          }
        }
        """
    )

    try:
        load_prompt_gate_baseline(baseline_path)
    except ValueError as err:
        assert "labeled_fixture_min" in str(err)
    else:
        raise AssertionError("Expected invalid fixture distribution to raise ValueError")


def test_compare_against_prompt_gate_reports_regressions() -> None:
    metrics = {
        "prompt_version": "js-ts-v2",
        "language_group": "javascript-typescript",
        "promotion_status": "candidate",
        "overall_pass_rate": 0.6,
        "schema_valid_rate": 1.0,
        "ambiguous_low_confidence_rate": 0.0,
        "labeled_fixture_count": 10,
        "mixed_fixture_count": 1,
        "label_totals": {"MAJOR": 2, "MINOR": 3, "PATCH": 3, "NO_BUMP": 2},
        "category_pass_rates": {
            "major_export_removed": 0.5,
            "minor_export_added": 1.0,
        },
    }
    baseline = {
        "prompt_version": "js-ts-v1",
        "language_group": "javascript-typescript",
        "promotion_status": "promoted",
        "fixture_set": "test-diffs",
        "min_overall_pass_rate": 0.7,
        "required_schema_valid_rate": 1.0,
        "min_ambiguous_low_confidence_rate": 1.0,
        "min_category_pass_rates": {
            "major_export_removed": 1.0,
            "minor_export_added": 0.5,
        },
        "required_fixture_distribution": {
            "labeled_fixture_min": 20,
            "mixed_fixture_min": 3,
            "label_mins": {"NO_BUMP": 4, "PATCH": 4},
        },
    }

    failures = compare_against_prompt_gate(metrics, baseline)

    assert any("overall_pass_rate" in failure for failure in failures)
    assert any("ambiguous_low_confidence_rate" in failure for failure in failures)
    assert any("major_export_removed" in failure for failure in failures)
    assert any("labeled_fixture_count" in failure for failure in failures)
    assert any("mixed_fixture_count" in failure for failure in failures)
    assert any("label count NO_BUMP" in failure for failure in failures)


def test_compare_against_prompt_gate_skips_missing_categories_for_subset_runs() -> None:
    metrics = {
        "prompt_version": "js-ts-v1",
        "language_group": "javascript-typescript",
        "promotion_status": "promoted",
        "overall_pass_rate": 1.0,
        "schema_valid_rate": 1.0,
        "ambiguous_total": 0,
        "ambiguous_low_confidence_rate": 0.0,
        "no_bump_total": 0,
        "no_bump_pass_rate": 0.0,
        "labeled_fixture_count": 3,
        "mixed_fixture_count": 0,
        "label_totals": {"PATCH": 3},
        "category_pass_rates": {
            "patch_internal_refactor": 1.0,
        },
        "label_pass_rates": {
            "PATCH": 1.0,
        },
        "label_confusion": {
            "PATCH": {"PATCH": 1},
        },
        "is_subset_run": True,
        "baseline_coverage_complete": False,
        "missing_baseline_categories": [
            "major_export_removed",
            "minor_export_added",
        ],
    }
    baseline = {
        "prompt_version": "js-ts-v1",
        "language_group": "javascript-typescript",
        "promotion_status": "promoted",
        "fixture_set": "test-diffs",
        "min_overall_pass_rate": 0.7,
        "required_schema_valid_rate": 1.0,
        "min_ambiguous_low_confidence_rate": 1.0,
        "min_category_pass_rates": {
            "major_export_removed": 1.0,
            "patch_internal_refactor": 1.0,
        },
        "required_fixture_distribution": {
            "labeled_fixture_min": 20,
            "mixed_fixture_min": 3,
            "label_mins": {"PATCH": 4},
        },
    }

    failures = compare_against_prompt_gate(metrics, baseline)

    assert failures == []


def test_categorize_failure_reason_maps_common_failures() -> None:
    assert categorize_failure_reason("HTTP 429: Too many requests") == "rate_limited"
    assert categorize_failure_reason("HTTP 401: bad credentials") == "invalid_token"
    assert categorize_failure_reason("[SSL: CERTIFICATE_VERIFY_FAILED]") == "ssl_failure"
    assert (
        categorize_failure_reason("[Errno 8] nodename nor servname provided, or not known")
        == "dns_failure"
    )
    assert categorize_failure_reason("No token available for GitHub Models.") == "missing_token"


def test_run_eval_preflight_reports_manual_review_failure_category() -> None:
    def fake_recommend(
        **_: object,
    ) -> tuple[dict[str, object], str, str | None, str | None]:
        return (
            {
                "status": "manual_review",
                "label": None,
                "confidence": None,
                "reasoning": "Automatic model analysis was unavailable. Please classify this PR manually.",
                "changelog": None,
            },
            "github-models",
            "HTTP 429: Too many requests",
            None,
        )

    preflight = run_eval_preflight(
        mode="auto",
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        model="openai/gpt-5-mini",
        endpoint="https://models.github.ai/inference/chat/completions",
        token="token",
        max_retries=1,
        recommend_fn=fake_recommend,
    )

    assert preflight["status"] == "failed"
    assert preflight["failure_category"] == "rate_limited"
    assert preflight["mode_used"] == "github-models"


def test_run_eval_preflight_fails_when_model_degrades_to_fallback() -> None:
    def fake_recommend(
        **_: object,
    ) -> tuple[dict[str, object], str, str | None, str | None]:
        return (
            {
                "status": "classified",
                "label": "PATCH",
                "confidence": "medium",
                "reasoning": "Semantic fallback detected internal changes.",
                "changelog": "fix: internal implementation update",
            },
            "fallback-heuristic",
            "No token available for GitHub Models.",
            "semantic-fallback",
        )

    preflight = run_eval_preflight(
        mode="auto",
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        model="openai/gpt-5-mini",
        endpoint="https://models.github.ai/inference/chat/completions",
        token="",
        max_retries=1,
        recommend_fn=fake_recommend,
    )

    assert preflight["status"] == "failed"
    assert preflight["failure_category"] == "missing_token"
    assert preflight["mode_used"] == "fallback-heuristic"
    assert preflight["model_used"] == "semantic-fallback"


def test_run_eval_preflight_supports_legacy_recommend_signature() -> None:
    def fake_recommend_legacy(
        *,
        mode: str,
        diff_text: str,
        truncated: bool,
        surface_area_hints: list[str] | None,
        language_hints: list[str] | None,
        model: str,
        fallback_model: str | None,
        endpoint: str,
        token: str,
        max_retries: int,
    ) -> tuple[dict[str, object], str, str | None, str | None]:
        return (
            {
                "label": "PATCH",
                "confidence": "high",
                "reasoning": "Legacy output shape without explicit status field.",
                "changelog": "fix: compatibility adapter",
            },
            "github-models",
            None,
            model,
        )

    preflight = run_eval_preflight(
        mode="auto",
        language_group="javascript-typescript",
        prompt_version="js-ts-v1",
        model="openai/gpt-5-mini",
        endpoint="https://models.github.ai/inference/chat/completions",
        token="token",
        max_retries=1,
        recommend_fn=fake_recommend_legacy,
    )

    assert preflight["status"] == "ok"
    assert preflight["mode_used"] == "github-models"


def test_select_batch_cases_slices_sorted_fixture_names() -> None:
    cases = [
        FixtureCase(name="c", diff_text="", expected={}),
        FixtureCase(name="a", diff_text="", expected={}),
        FixtureCase(name="b", diff_text="", expected={}),
    ]

    selected, meta = select_batch_cases(cases, batch_size=2, batch_index=0)

    assert [case.name for case in selected] == ["a", "b"]
    assert meta["batch_case_count"] == 2
    assert meta["total_case_count"] == 3
    assert meta["is_subset_run"] is True


def test_select_batch_cases_returns_empty_batch_when_index_out_of_range() -> None:
    cases = [
        FixtureCase(name="a", diff_text="", expected={}),
        FixtureCase(name="b", diff_text="", expected={}),
        FixtureCase(name="c", diff_text="", expected={}),
    ]

    selected, meta = select_batch_cases(cases, batch_size=2, batch_index=3)

    assert selected == []
    assert meta["batch_case_count"] == 0
    assert meta["total_case_count"] == 3
    assert meta["is_empty_batch"] is True


def test_aggregate_results_from_json_dir_merges_results_and_detects_coverage(
    tmp_path: Path,
) -> None:
    batch_one = tmp_path / "batch-1.json"
    batch_one.write_text(
        """
        {
          "language_group": "javascript-typescript",
          "results": [
            {
              "name": "case-a",
              "expected": {"label": "PATCH"},
              "actual": {"status": "classified", "label": "PATCH", "confidence": "high", "reasoning": "ok", "changelog": "fix: a"},
              "passed": true,
              "category": "patch_internal_refactor"
            }
          ]
        }
        """
    )
    batch_two = tmp_path / "batch-2.json"
    batch_two.write_text(
        """
        {
          "language_group": "javascript-typescript",
          "results": [
            {
              "name": "case-b",
              "expected": {"label": "MINOR"},
              "actual": {"status": "classified", "label": "MINOR", "confidence": "high", "reasoning": "ok", "changelog": "feat: b"},
              "passed": true,
              "category": "minor_export_added"
            }
          ]
        }
        """
    )

    expected_cases = [
        FixtureCase(
            name="case-a",
            diff_text="",
            expected={"label": "PATCH"},
            category="patch_internal_refactor",
        ),
        FixtureCase(
            name="case-b",
            diff_text="",
            expected={"label": "MINOR"},
            category="minor_export_added",
        ),
    ]

    results, coverage = aggregate_results_from_json_dir(tmp_path, expected_cases=expected_cases)

    assert [row.name for row in results] == ["case-a", "case-b"]
    assert coverage["baseline_coverage_complete"] is True
    assert coverage["missing_fixture_names"] == []


def test_aggregate_results_from_json_dir_reports_duplicate_fixture_names(
    tmp_path: Path,
) -> None:
    batch_one = tmp_path / "batch-1.json"
    batch_one.write_text(
        """
        {
          "language_group": "javascript-typescript",
          "results": [
            {
              "name": "case-a",
              "expected": {"label": "PATCH"},
              "actual": {"status": "classified", "label": "PATCH", "confidence": "high", "reasoning": "ok", "changelog": "fix: a"},
              "passed": true,
              "category": "patch_internal_refactor"
            }
          ]
        }
        """
    )
    batch_two = tmp_path / "batch-2.json"
    batch_two.write_text(batch_one.read_text())

    expected_cases = [
        FixtureCase(
            name="case-a",
            diff_text="",
            expected={"label": "PATCH"},
            category="patch_internal_refactor",
        ),
    ]

    try:
        aggregate_results_from_json_dir(tmp_path, expected_cases=expected_cases)
    except ValueError as err:
        assert "duplicate fixture results" in str(err)
    else:
        raise AssertionError("Expected duplicate fixture detection to raise ValueError")


def test_default_prompt_gate_baseline_exists() -> None:
    assert get_default_prompt_gate_baseline("javascript-typescript").exists()


def test_default_prompt_gate_baseline_exists_for_supported_language_groups() -> None:
    for language_group in ("python", "go", "rust", "java-kotlin"):
        assert get_default_prompt_gate_baseline(language_group).exists()


def test_default_prompt_gate_baseline_includes_surface_area_required() -> None:
    baseline = load_prompt_gate_baseline(get_default_prompt_gate_baseline("javascript-typescript"))

    assert baseline["min_category_pass_rates"]["surface_area_required"] == 1.0


def test_build_observed_summary_includes_fallback_reason_for_manual_review() -> None:
    observed = build_observed_summary(
        {
            "status": "manual_review",
            "label": None,
            "confidence": None,
            "mode_used": "github-models",
            "fallback_reason": "HTTP 401: bad credentials",
        }
    )

    assert observed["status"] == "manual_review"
    assert observed["mode_used"] == "github-models"
    assert observed["fallback_reason"] == "HTTP 401: bad credentials"


def test_main_strict_fails_when_language_filter_selects_zero_fixtures(
    monkeypatch, tmp_path: Path
) -> None:
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    case_dir = fixtures_dir / "python_case"
    case_dir.mkdir()
    (case_dir / "diff.txt").write_text("+ def ping() -> str:\n+     return 'ok'\n")
    (case_dir / "expected.json").write_text('{"label":"MINOR"}')
    (case_dir / "context.json").write_text('{"language":"python"}')
    output_json = tmp_path / "result.json"

    args = argparse.Namespace(
        fixtures_dir=str(fixtures_dir),
        aggregate_json_dir="",
        language_group="javascript-typescript",
        prompt_version="",
        prompt_gate_baseline="",
        mode="stub",
        include_tuning_targets=False,
        model="openai/gpt-5-mini",
        endpoint="https://models.github.ai/inference/chat/completions",
        max_retries=1,
        batch_size=0,
        batch_index=0,
        output_json=str(output_json),
        preflight_only=False,
        strict=True,
        min_pass_rate=0.8,
    )

    monkeypatch.setattr("eval._parse_args", lambda: args)

    from eval import main

    exit_code = main()

    assert exit_code == 1
    payload = json.loads(output_json.read_text())
    assert payload["metrics"]["evaluated_fixture_count"] == 0
    assert payload["gate"]["failure_codes"] == ["no_fixtures_for_language_group"]


def test_main_strict_fails_for_aggregate_input_with_zero_evaluated_fixtures(
    monkeypatch, tmp_path: Path
) -> None:
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    case_dir = fixtures_dir / "js_case"
    case_dir.mkdir()
    (case_dir / "diff.txt").write_text("+ export const ping = () => 'ok';\n")
    (case_dir / "expected.json").write_text('{"label":"MINOR"}')
    (case_dir / "context.json").write_text(
        '{"language":"javascript-typescript","category":"minor_export_added"}'
    )

    aggregate_dir = tmp_path / "aggregate"
    aggregate_dir.mkdir()
    (aggregate_dir / "batch-1.json").write_text(
        """
        {
          "language_group": "javascript-typescript",
          "results": []
        }
        """
    )
    output_json = tmp_path / "aggregate-result.json"

    args = argparse.Namespace(
        fixtures_dir=str(fixtures_dir),
        aggregate_json_dir=str(aggregate_dir),
        language_group="javascript-typescript",
        prompt_version="",
        prompt_gate_baseline="",
        mode="stub",
        include_tuning_targets=False,
        model="openai/gpt-5-mini",
        endpoint="https://models.github.ai/inference/chat/completions",
        max_retries=1,
        batch_size=0,
        batch_index=0,
        output_json=str(output_json),
        preflight_only=False,
        strict=True,
        min_pass_rate=0.0,
    )

    monkeypatch.setattr("eval._parse_args", lambda: args)

    from eval import main

    exit_code = main()

    assert exit_code == 1
    payload = json.loads(output_json.read_text())
    assert payload["metrics"]["evaluated_fixture_count"] == 0
    assert "no_evaluated_fixtures" in payload["gate"]["failure_codes"]


def test_main_uses_deterministic_findings_for_hard_major_fixture_labels(
    monkeypatch, tmp_path: Path
) -> None:
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    case_dir = fixtures_dir / "mixed_major_minor"
    case_dir.mkdir()
    (case_dir / "diff.txt").write_text(
        "- export function login(user, pass) {}\n"
        "+ export function login(credentials) {}\n"
        "+ export function listTeams() {}\n"
    )
    (case_dir / "expected.json").write_text('{"label":"MAJOR"}')
    (case_dir / "context.json").write_text(
        '{"language":"javascript-typescript","category":"mixed_major_minor"}'
    )
    output_json = tmp_path / "result.json"

    args = argparse.Namespace(
        fixtures_dir=str(fixtures_dir),
        aggregate_json_dir="",
        language_group="javascript-typescript",
        prompt_version="",
        prompt_gate_baseline="",
        mode="stub",
        include_tuning_targets=False,
        model="openai/gpt-5-mini",
        endpoint="https://models.github.ai/inference/chat/completions",
        max_retries=1,
        batch_size=0,
        batch_index=0,
        output_json=str(output_json),
        preflight_only=False,
        strict=False,
        min_pass_rate=0.8,
    )

    monkeypatch.setattr("eval._parse_args", lambda: args)

    from eval import main

    exit_code = main()

    assert exit_code == 0
    payload = json.loads(output_json.read_text())
    assert payload["results"][0]["actual"]["label"] == "MAJOR"
    assert payload["results"][0]["actual"]["classification_source"] == "court"
    assert payload["results"][0]["passed"] is True


def test_main_eval_applies_hybrid_adjudication_for_non_breaking_findings(
    monkeypatch, tmp_path: Path
) -> None:
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    case_dir = fixtures_dir / "hybrid_floor_raise_case"
    case_dir.mkdir()
    (case_dir / "diff.txt").write_text(
        "+ export function listTeams() {}\n+ const internalCache = new Map();\n"
    )
    (case_dir / "expected.json").write_text('{"label":"MINOR","classification_source":"hybrid"}')
    (case_dir / "context.json").write_text(
        '{"language":"javascript-typescript","category":"hybrid_floor_raise"}'
    )
    output_json = tmp_path / "result.json"

    args = argparse.Namespace(
        fixtures_dir=str(fixtures_dir),
        aggregate_json_dir="",
        language_group="javascript-typescript",
        prompt_version="",
        prompt_gate_baseline="",
        mode="auto",
        include_tuning_targets=False,
        model="openai/gpt-5-mini",
        endpoint="https://models.github.ai/inference/chat/completions",
        max_retries=1,
        batch_size=0,
        batch_index=0,
        output_json=str(output_json),
        preflight_only=False,
        strict=False,
        min_pass_rate=0.8,
    )

    monkeypatch.setattr("eval._parse_args", lambda: args)
    monkeypatch.setattr("eval.resolve_models_token", lambda **_: "test-token")
    monkeypatch.setattr(
        "eval.run_eval_preflight",
        lambda **_: {
            "status": "ok",
            "reason": "mocked preflight success",
            "failure_category": None,
            "failure_reason": None,
            "mode_used": "github-models",
            "model_used": "openai/gpt-5-mini",
        },
    )
    monkeypatch.setattr(
        "eval.orchestrator_core.analyze_diff_core",
        lambda **_: SimpleNamespace(
            output={
                "status": "classified",
                "label": "MINOR",
                "confidence": "high",
                "reasoning": "Deterministic findings floor raised to MINOR.",
                "changelog": "feat: add backward-compatible api changes",
                "mode": "deterministic-findings",
                "analysis_state": "authoritative",
                "classification_source": "hybrid",
                "decision_authority": "deterministic",
                "deterministic_label": "MINOR",
                "advisory_status": "skipped",
                "advisory_label": "MINOR",
                "advisory_confidence": "high",
                "court_skipped_reason": "deterministic_high_confidence_minor",
                "case_file_stats": {
                    "token_budget": 1200,
                    "estimated_input_tokens": 100,
                    "findings_included": 1,
                    "findings_omitted": 0,
                },
                "findings": [],
                "decision_trace": {},
                "policy_effects": [],
                "fallback_reason": None,
                "failure_category": None,
            }
        ),
    )

    from eval import main

    exit_code = main()

    assert exit_code == 0
    payload = json.loads(output_json.read_text())
    assert payload["results"][0]["actual"]["label"] == "MINOR"
    assert payload["results"][0]["actual"]["classification_source"] == "hybrid"
    assert payload["results"][0]["passed"] is True


def test_main_continues_eval_when_preflight_fails_if_flag_set(monkeypatch, tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    case_dir = fixtures_dir / "patch_internal_case"
    case_dir.mkdir()
    (case_dir / "diff.txt").write_text("+ const cache = new Map();\n")
    (case_dir / "expected.json").write_text('{"label":"PATCH"}')
    (case_dir / "context.json").write_text(
        '{"language":"javascript-typescript","category":"patch_internal_refactor"}'
    )
    output_json = tmp_path / "result.json"

    args = argparse.Namespace(
        fixtures_dir=str(fixtures_dir),
        aggregate_json_dir="",
        language_group="javascript-typescript",
        prompt_version="",
        prompt_gate_baseline="",
        mode="auto",
        include_tuning_targets=False,
        model="openai/gpt-5-mini",
        endpoint="https://models.github.ai/inference/chat/completions",
        max_retries=1,
        batch_size=0,
        batch_index=0,
        output_json=str(output_json),
        preflight_only=False,
        strict=False,
        min_pass_rate=0.8,
        continue_on_preflight_failure=True,
    )

    monkeypatch.setattr("eval._parse_args", lambda: args)
    monkeypatch.setattr("eval.resolve_models_token", lambda **_: "")
    monkeypatch.setattr(
        "eval.run_eval_preflight",
        lambda **_: {
            "status": "failed",
            "reason": "mocked degraded provider",
            "failure_category": "missing_token",
            "failure_reason": "No token available for model provider.",
            "mode_used": "fallback-heuristic",
            "model_used": "semantic-fallback",
        },
    )
    monkeypatch.setattr(
        "eval.orchestrator_core.analyze_diff_core",
        lambda **_: SimpleNamespace(
            output={
                "status": "classified",
                "label": "PATCH",
                "confidence": "medium",
                "reasoning": "Deterministic semantic fallback.",
                "changelog": "fix: internal implementation update",
                "mode": "deterministic-heuristic",
                "analysis_state": "authoritative",
                "classification_source": "deterministic-heuristic",
                "decision_authority": "deterministic",
                "deterministic_label": "PATCH",
                "advisory_status": "skipped",
                "advisory_label": "PATCH",
                "advisory_confidence": "medium",
                "court_skipped_reason": "deterministic_patch",
                "case_file_stats": {
                    "token_budget": 1200,
                    "estimated_input_tokens": 60,
                    "findings_included": 0,
                    "findings_omitted": 0,
                },
                "findings": [],
                "decision_trace": {},
                "policy_effects": [],
                "fallback_reason": "No token available for model provider.",
                "failure_category": "missing_token",
            }
        ),
    )

    from eval import main

    exit_code = main()

    assert exit_code == 0
    payload = json.loads(output_json.read_text())
    assert payload["preflight"]["status"] == "failed"
    assert payload["preflight"]["continued"] is True
    assert payload["metrics"]["evaluated_fixture_count"] == 1
    assert payload["results"][0]["actual"]["mode_used"] == "deterministic-heuristic"

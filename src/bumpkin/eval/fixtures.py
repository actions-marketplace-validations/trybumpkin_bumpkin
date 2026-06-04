from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from bumpkin.analysis.language import get_language_hints_for_groups


def _empty_string_list() -> list[str]:
    return []


@dataclass
class FixtureCase:
    name: str
    diff_text: str
    expected: dict[str, Any]
    language: str | None = None
    surface_area: list[str] = field(default_factory=_empty_string_list)
    category: str = "uncategorized"
    note: str | None = None
    tuning_target: bool = False


@dataclass
class FixtureResult:
    name: str
    expected: dict[str, Any]
    actual: dict[str, Any]
    passed: bool
    category: str


def ensure_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Fixture context `surface_area` must be a list of strings.")
    items = cast("list[object]", value)
    if any(not isinstance(item, str) for item in items):
        raise ValueError("Fixture context `surface_area` must contain only strings.")
    string_items = cast("list[str]", items)
    return [item.strip() for item in string_items if item.strip()]


def validate_expected_payload(
    expected: object,
    *,
    path: Path,
) -> dict[str, Any]:
    if not isinstance(expected, dict):
        raise ValueError(f"Fixture expected payload must be an object: {path}")
    expected_payload = cast("dict[str, Any]", expected)

    findings = expected_payload.get("findings")
    if findings is None:
        return expected_payload
    if not isinstance(findings, list):
        raise ValueError(f"Fixture expected `findings` must be a list: {path}")
    findings_items = cast("list[object]", findings)
    for index, item in enumerate(findings_items):
        if isinstance(item, str):
            if not item.strip():
                raise ValueError(f"Fixture expected `findings[{index}]` must be non-empty: {path}")
            continue
        if not isinstance(item, dict):
            raise ValueError(
                f"Fixture expected `findings[{index}]` must be string or object: {path}"
            )
        finding_item = cast("dict[str, object]", item)
        rule = finding_item.get("rule")
        if not isinstance(rule, str) or not rule.strip():
            raise ValueError(
                f"Fixture expected `findings[{index}].rule` must be a non-empty string: {path}"
            )
        severity = finding_item.get("severity")
        if severity is not None and (not isinstance(severity, str) or not severity.strip()):
            raise ValueError(
                f"Fixture expected `findings[{index}].severity` must be a non-empty string when present: {path}"
            )
    return expected_payload


def load_fixture_cases(
    fixtures_dir: Path,
    *,
    case_factory: Callable[..., Any] = FixtureCase,
    validate_expected_payload_fn: Callable[..., dict[str, Any]] = validate_expected_payload,
    ensure_string_list_fn: Callable[[object], list[str]] = ensure_string_list,
) -> list[Any]:
    cases: list[Any] = []
    for case_dir in sorted(p for p in fixtures_dir.iterdir() if p.is_dir()):
        diff_path = case_dir / "diff.txt"
        expected_path = case_dir / "expected.json"
        context_path = case_dir / "context.json"
        if not diff_path.exists() or not expected_path.exists():
            continue

        context: dict[str, Any] = {}
        if context_path.exists():
            parsed_context = json.loads(context_path.read_text())
            if not isinstance(parsed_context, dict):
                raise ValueError(f"Fixture context must be an object: {context_path}")
            context = cast("dict[str, Any]", parsed_context)

        language = context.get("language")
        if language is not None and not isinstance(language, str):
            raise ValueError(f"Fixture context `language` must be a string: {context_path}")

        note = context.get("note")
        if note is not None and not isinstance(note, str):
            raise ValueError(f"Fixture context `note` must be a string: {context_path}")

        category = context.get("category")
        if category is not None and not isinstance(category, str):
            raise ValueError(f"Fixture context `category` must be a string: {context_path}")
        tuning_target = context.get("tuning_target")
        if tuning_target is not None and not isinstance(tuning_target, bool):
            raise ValueError(f"Fixture context `tuning_target` must be a boolean: {context_path}")

        cases.append(
            case_factory(
                name=case_dir.name,
                diff_text=diff_path.read_text(),
                expected=validate_expected_payload_fn(
                    json.loads(expected_path.read_text()),
                    path=expected_path,
                ),
                language=language.strip()
                if isinstance(language, str) and language.strip()
                else None,
                surface_area=ensure_string_list_fn(context.get("surface_area")),
                category=category.strip()
                if isinstance(category, str) and category.strip()
                else case_dir.name,
                note=note.strip() if isinstance(note, str) and note.strip() else None,
                tuning_target=bool(tuning_target) if isinstance(tuning_target, bool) else False,
            )
        )
    return cases


def matches_expected(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    for key, value in expected.items():
        if key == "findings":
            continue
        if key not in actual:
            return False
        if isinstance(value, str) and isinstance(actual[key], str):
            if value.strip().lower() != actual[key].strip().lower():
                return False
        elif actual[key] != value:
            return False
    return True


def evaluate_fixture_cases(
    cases: list[Any],
    recommend_fn: Callable[[Any], dict[str, Any]],
    *,
    result_factory: Callable[..., Any] = FixtureResult,
    matches_expected_fn: Callable[[dict[str, Any], dict[str, Any]], bool] = matches_expected,
) -> list[Any]:
    results: list[Any] = []
    for case in cases:
        actual = recommend_fn(case)
        results.append(
            result_factory(
                name=case.name,
                expected=case.expected,
                actual=actual,
                passed=matches_expected_fn(case.expected, actual),
                category=case.category,
            )
        )
    return results


def build_case_inputs(
    case: Any,
    *,
    get_language_hints_for_groups_fn: Callable[
        [list[str]], list[str]
    ] = get_language_hints_for_groups,
) -> tuple[list[str], list[str]]:
    surface_area_hints = case.surface_area
    language_hints = get_language_hints_for_groups_fn([case.language]) if case.language else []
    return surface_area_hints, language_hints


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def run_eval(
    cases: list[Any],
    recommend_fn: Callable[[Any], dict[str, Any]],
    *,
    result_factory: Callable[..., Any] = FixtureResult,
    matches_expected_fn: Callable[[dict[str, Any], dict[str, Any]], bool] = matches_expected,
    estimate_tokens_fn: Callable[[str], int] = estimate_tokens,
    inter_case_delay_ms: int = 0,
) -> tuple[list[Any], int, float, float, float]:
    results: list[Any] = []
    total_latency_ms = 0.0
    total_tokens = 0
    delay_seconds = max(0.0, inter_case_delay_ms) / 1000.0

    for case in cases:
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        started = time.perf_counter()
        actual = recommend_fn(case)
        total_latency_ms += (time.perf_counter() - started) * 1000
        total_tokens += estimate_tokens_fn(case.diff_text)
        results.append(
            result_factory(
                name=case.name,
                expected=case.expected,
                actual=actual,
                passed=matches_expected_fn(case.expected, actual),
                category=case.category,
            )
        )

    passed_count = sum(1 for row in results if row.passed)
    pass_rate = passed_count / len(results) if results else 0.0
    avg_latency_ms = total_latency_ms / len(results) if results else 0.0
    avg_tokens = total_tokens / len(results) if results else 0.0
    return results, passed_count, pass_rate, avg_latency_ms, avg_tokens


def filter_cases(
    cases: list[Any],
    *,
    language_group: str | None,
    include_tuning_targets: bool,
    default_language_group: str,
) -> list[Any]:
    filtered: list[Any] = []
    for case in cases:
        if case.tuning_target and not include_tuning_targets:
            continue
        if not language_group:
            filtered.append(case)
            continue
        if case.language == language_group:
            filtered.append(case)
            continue
        if case.language is None and language_group == default_language_group:
            filtered.append(case)
    return filtered

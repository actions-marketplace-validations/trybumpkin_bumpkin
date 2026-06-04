from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import cast

from bumpkin.analysis.findings import Finding


def normalize_repo_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    normalized = normalized.removeprefix("./")
    return normalized.lstrip("/")


def _to_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def is_docs_or_config_path(path: str) -> bool:
    normalized = str(path or "").strip().lower()
    normalized = normalized.removeprefix("./")
    normalized = normalized.lstrip("/")
    if not normalized:
        return True

    if normalized.startswith(
        (
            "docs/",
            ".github/",
            ".vscode/",
            ".idea/",
            "coverage/",
            "dist/",
        )
    ):
        return True

    if normalized.endswith((".md", ".mdx", ".rst", ".txt", ".adoc", ".lock")):
        return True

    base = Path(normalized).name
    return base in {
        ".gitignore",
        ".gitattributes",
        "license",
        "license.md",
        "readme",
        "readme.md",
        "changelog.md",
        "renovate.json",
    }


def surface_area_touched(analyzed_files: list[str], surface_area_hints: list[str]) -> bool:
    if not analyzed_files or not surface_area_hints:
        return False
    normalized_files = [path.strip().strip("/") for path in analyzed_files if path.strip()]
    if not normalized_files:
        return False

    for hint in surface_area_hints:
        pattern = hint.strip().strip("/")
        if not pattern:
            continue
        for file_path in normalized_files:
            if fnmatch.fnmatch(file_path, pattern) or file_path.startswith(
                pattern.replace("**", "").rstrip("/")
            ):
                return True
    return False


def uncertain_no_bump_result(policy: str, reasoning: str) -> dict[str, object]:
    if policy.upper() == "PATCH":
        return {
            "status": "classified",
            "label": "PATCH",
            "confidence": "low",
            "reasoning": reasoning,
            "changelog": "fix: conservative patch bump due to uncertain diff context",
        }
    return {
        "status": "manual_review",
        "label": None,
        "confidence": None,
        "reasoning": reasoning,
        "changelog": None,
    }


def apply_truncated_no_bump_guard(
    result: dict[str, object],
    *,
    truncated: bool,
    analyzed_files: list[str],
    policy: str,
    notes: list[str],
) -> tuple[dict[str, object], bool]:
    if not truncated:
        return result, False
    if str(result.get("status", "classified")) != "classified":
        return result, False
    if str(result.get("label", "")).upper() != "NO_BUMP":
        return result, False

    if all(is_docs_or_config_path(path) for path in analyzed_files):
        return result, False

    notes.append("Safety guard: truncated diff with non-doc/config paths rejected NO_BUMP.")
    return (
        uncertain_no_bump_result(
            policy,
            (
                "Diff was truncated and includes non-doc/config paths, so NO_BUMP is not reliable. "
                "Please review manually."
            ),
        ),
        True,
    )


def apply_truncated_surface_area_guard(
    result: dict[str, object],
    *,
    truncated: bool,
    analyzed_files: list[str],
    surface_area_hints: list[str],
    chunking_meta: dict[str, object] | None,
    notes: list[str],
) -> tuple[dict[str, object], bool]:
    if not truncated:
        return result, False
    if str(result.get("status", "classified")) != "classified":
        return result, False
    if not surface_area_touched(analyzed_files, surface_area_hints):
        return result, False

    if chunking_meta:
        enabled = bool(chunking_meta.get("enabled", False))
        chunk_count = _to_int(chunking_meta.get("chunk_count", 0), default=0)
        succeeded = _to_int(chunking_meta.get("succeeded", 0), default=0)
        failed = _to_int(chunking_meta.get("failed", 0), default=0)
        skipped = _to_int(chunking_meta.get("skipped", 0), default=0)
        if (
            enabled
            and chunk_count > 0
            and succeeded >= chunk_count
            and failed == 0
            and skipped == 0
        ):
            notes.append(
                "Safety guard bypassed: truncated diff touched surface_area, but chunking covered all chunks successfully."
            )
            return result, False

    notes.append(
        "Safety guard: truncated diff touched configured surface_area paths; downgraded to manual_review."
    )
    return (
        {
            "status": "manual_review",
            "label": None,
            "confidence": None,
            "reasoning": (
                "Diff was truncated and touched configured surface_area paths, so automated SemVer "
                "classification is not reliable. Please review manually."
            ),
            "changelog": None,
        },
        True,
    )


def apply_large_pr_no_bump_guard(
    result: dict[str, object],
    *,
    analyzed_files_count: int,
    approx_prompt_tokens: int,
    max_files: int,
    max_tokens: int,
    policy: str,
    notes: list[str],
) -> tuple[dict[str, object], bool]:
    if str(result.get("status", "classified")) != "classified":
        return result, False
    if str(result.get("label", "")).upper() != "NO_BUMP":
        return result, False

    over_files = analyzed_files_count > max_files
    over_tokens = approx_prompt_tokens > max_tokens
    if not (over_files or over_tokens):
        return result, False

    reasons: list[str] = []
    if over_files:
        reasons.append(f"file count {analyzed_files_count} exceeded large_pr_max_files={max_files}")
    if over_tokens:
        reasons.append(
            f"prompt tokens {approx_prompt_tokens} exceeded large_pr_max_tokens={max_tokens}"
        )
    note = "Safety guard: large PR rejected NO_BUMP (" + "; ".join(reasons) + ")."
    notes.append(note)
    return (
        uncertain_no_bump_result(
            policy,
            "Large PR thresholds were exceeded, so NO_BUMP is not reliable. Please review manually.",
        ),
        True,
    )


def apply_analysis_coverage_guard(
    result: dict[str, object],
    *,
    analyzed_files: list[str],
    findings: list[Finding],
    chunking_meta: dict[str, object] | None,
    notes: list[str],
) -> tuple[dict[str, object], bool]:
    if str(result.get("status", "classified")) != "classified":
        return result, False

    analyzed = {normalize_repo_path(path) for path in analyzed_files if normalize_repo_path(path)}
    if not analyzed:
        return result, False

    deterministic_paths: set[str] = set()
    for finding in findings:
        for evidence in finding.evidence:
            raw_path = normalize_repo_path(str(evidence.get("path", "")))
            if raw_path and raw_path != "<unknown>.ts":
                deterministic_paths.add(raw_path)

    chunk_meta = chunking_meta or {}
    raw_omitted = chunk_meta.get("omitted_files", [])
    omitted_items = cast("list[object]", raw_omitted) if isinstance(raw_omitted, list) else []
    omitted_files = {
        normalized
        for item in omitted_items
        for normalized in [normalize_repo_path(str(item))]
        if normalized
    }
    llm_covered = analyzed - omitted_files
    covered_union = deterministic_paths | llm_covered
    uncovered = sorted(analyzed - covered_union)
    if not uncovered:
        return result, False

    notes.append(
        "Coverage guard: one or more changed files were omitted from model chunks and lacked deterministic findings."
    )
    notes.append(f"Coverage guard omitted sample: {', '.join(uncovered[:5])}.")
    return (
        {
            "status": "manual_review",
            "label": None,
            "confidence": None,
            "reasoning": (
                "Analysis coverage was incomplete: at least one changed file was not covered by "
                "LLM chunk analysis or deterministic findings. Manual review is required."
            ),
            "changelog": None,
        },
        True,
    )

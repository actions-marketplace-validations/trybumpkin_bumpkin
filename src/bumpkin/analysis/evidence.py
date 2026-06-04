from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from bumpkin.analysis.findings import Finding

DIFF_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")
REMOVED_GUARD_RE = re.compile(
    r"\bif\s*\(\s*(![A-Za-z_][A-Za-z0-9_]*|.+==\s*null|.+===\s*undefined|.+==\s*undefined)\s*\)"
)
PATH_MARKER_MAX_ITEMS = 8


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    type: str
    rule: str
    severity: str
    confidence: str
    path: str
    snippet: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {
            "evidence_id": self.evidence_id,
            "type": self.type,
            "rule": self.rule,
            "severity": self.severity,
            "confidence": self.confidence,
            "path": self.path,
            "snippet": self.snippet,
            "source": self.source,
        }


def _normalize_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    normalized = normalized.removeprefix("./")
    return normalized.lstrip("/")


def _iter_diff_lines(diff_text: str) -> list[tuple[str, str, str]]:
    current_path = "<unknown>"
    rows: list[tuple[str, str, str]] = []
    for raw in diff_text.splitlines():
        header = DIFF_HEADER.match(raw.strip())
        if header:
            current_path = _normalize_path(header.group(2))
            continue
        if raw.startswith(("---", "+++", "@@", "index ")):
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            rows.append((current_path, "+", raw[1:].strip()))
        elif raw.startswith("-") and not raw.startswith("---"):
            rows.append((current_path, "-", raw[1:].strip()))
    return rows


def _build_behavioral_markers(diff_text: str, *, start_index: int) -> list[EvidenceItem]:
    markers: list[EvidenceItem] = []
    index = start_index
    seen_throw: set[str] = set()
    seen_side_effect: set[str] = set()
    seen_removed_guard: set[str] = set()
    for path, op, line in _iter_diff_lines(diff_text):
        lowered = line.lower()
        if op == "+" and "throw " in line:
            key = f"{path}:{line}"
            if key in seen_throw:
                continue
            seen_throw.add(key)
            index += 1
            markers.append(
                EvidenceItem(
                    evidence_id=f"behavior_marker:{index}",
                    type="behavior_marker",
                    rule="added_throw_statement",
                    severity="PATCH",
                    confidence="medium",
                    path=path,
                    snippet=line[:180],
                    source="behavioral-diff",
                )
            )
            continue

        if op == "+" and any(
            token in lowered
            for token in ("fetch(", "axios.", "request(", "console.", "process.exit(")
        ):
            key = f"{path}:{line}"
            if key in seen_side_effect:
                continue
            seen_side_effect.add(key)
            index += 1
            markers.append(
                EvidenceItem(
                    evidence_id=f"behavior_marker:{index}",
                    type="behavior_marker",
                    rule="added_external_side_effect",
                    severity="PATCH",
                    confidence="medium",
                    path=path,
                    snippet=line[:180],
                    source="behavioral-diff",
                )
            )
            continue

        if op == "-" and REMOVED_GUARD_RE.search(line):
            key = f"{path}:{line}"
            if key in seen_removed_guard:
                continue
            seen_removed_guard.add(key)
            index += 1
            markers.append(
                EvidenceItem(
                    evidence_id=f"behavior_marker:{index}",
                    type="behavior_marker",
                    rule="removed_guard_branch",
                    severity="PATCH",
                    confidence="medium",
                    path=path,
                    snippet=line[:180],
                    source="behavioral-diff",
                )
            )
    return markers


def _build_contract_markers(
    behavior_contract_signals: dict[str, object],
    *,
    start_index: int,
) -> list[EvidenceItem]:
    raw_sample_files = behavior_contract_signals.get("sample_files", [])
    if not isinstance(raw_sample_files, list):
        return []
    sample_files = cast("list[object]", raw_sample_files)
    markers: list[EvidenceItem] = []
    index = start_index
    for raw in sample_files:
        path = _normalize_path(str(raw))
        if not path:
            continue
        index += 1
        markers.append(
            EvidenceItem(
                evidence_id=f"contract_signal:{index}",
                type="contract_signal",
                rule="behavior_contract_path_signal",
                severity="MINOR",
                confidence="medium",
                path=path,
                snippet=path,
                source="path-signals",
            )
        )
    return markers


def _build_path_markers(
    diff_text: str,
    *,
    start_index: int,
    max_items: int = PATH_MARKER_MAX_ITEMS,
) -> list[EvidenceItem]:
    paths: list[str] = []
    seen: set[str] = set()
    first_change_snippet_by_path: dict[str, str] = {}
    for path, _op, _line in _iter_diff_lines(diff_text):
        if not path or path == "<unknown>" or path in seen:
            if path and path != "<unknown>" and path not in first_change_snippet_by_path:
                compact = _line.strip()
                if compact:
                    first_change_snippet_by_path[path] = compact[:180]
            continue
        seen.add(path)
        paths.append(path)
        compact = _line.strip()
        if compact and path not in first_change_snippet_by_path:
            first_change_snippet_by_path[path] = compact[:180]
        if len(paths) >= max_items:
            break

    markers: list[EvidenceItem] = []
    index = start_index
    for path in paths:
        index += 1
        markers.append(
            EvidenceItem(
                evidence_id=f"path_marker:{index}",
                type="path_marker",
                rule="changed_file_path",
                severity="PATCH",
                confidence="medium",
                path=path,
                snippet=first_change_snippet_by_path.get(path, path),
                source="diff-paths",
            )
        )
    return markers


def build_evidence_items(
    *,
    findings: Sequence[object],
    diff_text: str,
    behavior_contract_signals: dict[str, object],
) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    counter = 0
    for finding in findings:
        if not isinstance(finding, Finding):
            continue
        base = finding.evidence[0] if finding.evidence else {}
        path = _normalize_path(str(base.get("path", "")))
        snippet = str(base.get("snippet", "")).strip()
        counter += 1
        evidence.append(
            EvidenceItem(
                evidence_id=f"finding:{finding.id}",
                type="finding",
                rule=finding.rule,
                severity=finding.severity,
                confidence=finding.confidence,
                path=path or "<unknown>",
                snippet=snippet[:180],
                source="deterministic-findings",
            )
        )

    behavior_markers = _build_behavioral_markers(diff_text, start_index=counter)
    evidence.extend(behavior_markers)
    counter += len(behavior_markers)
    contract_markers = _build_contract_markers(behavior_contract_signals, start_index=counter)
    evidence.extend(contract_markers)
    counter += len(contract_markers)
    evidence.extend(_build_path_markers(diff_text, start_index=counter))
    return evidence


def build_evidence_prompt_text(
    *,
    evidence_items: list[EvidenceItem],
    diff_text: str,
    max_chars: int = 12000,
) -> str:
    lines: list[str] = [
        "Evidence-first analysis context:",
        "Use these evidence records as primary signals, then validate against included diff excerpt.",
        "",
        "Evidence records:",
    ]
    if not evidence_items:
        lines.append("- none")
    lines.extend(
        [
            f"- [{item.evidence_id}] type={item.type} rule={item.rule} severity={item.severity} "
            f"confidence={item.confidence} path={item.path} snippet={item.snippet}"
            for item in evidence_items[:30]
        ]
    )

    lines.append("")
    lines.append("Diff excerpt:")
    remaining = max(0, max_chars - len("\n".join(lines)))
    excerpt = diff_text[:remaining] if remaining else ""
    lines.append(excerpt)
    return "\n".join(lines)


def summarize_evidence_items(evidence_items: list[EvidenceItem]) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for item in evidence_items:
        by_type[item.type] = by_type.get(item.type, 0) + 1
        by_severity[item.severity] = by_severity.get(item.severity, 0) + 1
    return {
        "total": len(evidence_items),
        "by_type": by_type,
        "by_severity": by_severity,
    }

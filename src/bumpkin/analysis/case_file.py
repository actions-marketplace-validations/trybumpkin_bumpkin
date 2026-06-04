from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from bumpkin.analysis.evidence import EvidenceItem
from bumpkin.analysis.findings import Finding

CASE_FILE_VERSION = "case_file_v1"
DEFAULT_CASE_FILE_TOKEN_BUDGET = 1200
DEFAULT_CASE_FILE_MAX_FINDINGS = 8
DEFAULT_CASE_FILE_MAX_EVIDENCE_RECORDS = 12
DEFAULT_CASE_FILE_MAX_POLICY_EFFECTS = 8
DEFAULT_CASE_FILE_MAX_NOTES = 6
_CHARS_PER_TOKEN = 4


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


def _normalize_snippet(snippet: str, *, max_lines: int = 3, max_chars: int = 220) -> str:
    lines = [line.strip() for line in str(snippet or "").splitlines() if line.strip()]
    if not lines:
        return ""
    compact = " | ".join(lines[:max_lines])
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _estimate_tokens_for_payload(payload: dict[str, Any]) -> int:
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _build_findings_payload(
    findings: list[Finding], evidence_items: list[EvidenceItem]
) -> list[dict[str, str]]:
    evidence_by_finding: dict[str, EvidenceItem] = {}
    for item in evidence_items:
        if not item.evidence_id.startswith("finding:"):
            continue
        _, finding_id = item.evidence_id.split(":", 1)
        if finding_id not in evidence_by_finding:
            evidence_by_finding[finding_id] = item

    out: list[dict[str, str]] = []
    for finding in findings:
        first_evidence = finding.evidence[0] if finding.evidence else {}
        evidence_item = evidence_by_finding.get(finding.id)
        path = str(first_evidence.get("path", "")).strip() or (
            evidence_item.path if evidence_item else "<unknown>"
        )
        snippet = str(first_evidence.get("snippet", "")).strip()
        if not snippet and evidence_item:
            snippet = evidence_item.snippet
        out.append(
            {
                "finding_id": finding.id,
                "severity": finding.severity,
                "rule": finding.rule,
                "path": path,
                "title": finding.title,
                "why": _normalize_snippet(finding.why, max_lines=1, max_chars=180),
                "snippet": _normalize_snippet(snippet),
            }
        )
    return out


def _build_evidence_records_payload(evidence_items: list[EvidenceItem]) -> list[dict[str, str]]:
    return [
        {
            "evidence_id": item.evidence_id,
            "type": item.type,
            "rule": item.rule,
            "severity": item.severity,
            "confidence": item.confidence,
            "path": item.path,
            "snippet": _normalize_snippet(item.snippet, max_lines=2, max_chars=160),
        }
        for item in evidence_items
    ]


@dataclass(frozen=True)
class CaseFileBuildResult:
    case_file: dict[str, Any]
    stats: dict[str, int]


def build_case_file(
    *,
    engine_result: dict[str, Any],
    findings: list[Finding],
    evidence_items: list[EvidenceItem],
    policy_effects: list[str],
    notes: list[str],
    coverage_contract: dict[str, object],
    boundary_summary: dict[str, int],
    evidence_summary: dict[str, int],
    token_budget: int = DEFAULT_CASE_FILE_TOKEN_BUDGET,
    max_findings: int = DEFAULT_CASE_FILE_MAX_FINDINGS,
) -> CaseFileBuildResult:
    findings_payload = _build_findings_payload(findings, evidence_items)
    selected_findings = findings_payload[: max(0, max_findings)]
    omitted_findings = max(0, len(findings_payload) - len(selected_findings))
    evidence_records = _build_evidence_records_payload(evidence_items)
    selected_evidence_records = evidence_records[:DEFAULT_CASE_FILE_MAX_EVIDENCE_RECORDS]

    case_file: dict[str, Any] = {
        "version": CASE_FILE_VERSION,
        "engine_decision": {
            "status": str(engine_result.get("status", "manual_review")),
            "label": engine_result.get("label"),
            "confidence": engine_result.get("confidence"),
            "reasoning": _normalize_snippet(
                str(engine_result.get("reasoning", "")), max_lines=2, max_chars=220
            ),
            "changelog": str(engine_result.get("changelog", "")).strip(),
        },
        "top_findings": selected_findings,
        "evidence_records": selected_evidence_records,
        "policy_effects": [
            str(item) for item in policy_effects[:DEFAULT_CASE_FILE_MAX_POLICY_EFFECTS]
        ],
        "coverage_flags": {
            "coverage_status": str(coverage_contract.get("status", "unknown")),
            "critical_files_total": _to_int(
                coverage_contract.get("critical_files_total", 0), default=0
            ),
            "critical_files_covered": _to_int(
                coverage_contract.get("critical_files_covered", 0), default=0
            ),
            "omitted_files_total": _to_int(
                coverage_contract.get("omitted_files_total", 0), default=0
            ),
        },
        "evidence_summary": {
            "strong_public_evidence": _to_int(
                evidence_summary.get("strong_public_evidence", 0), default=0
            ),
            "strong_breaking_evidence": _to_int(
                evidence_summary.get("strong_breaking_evidence", 0), default=0
            ),
            "unknown_impactful_findings": _to_int(
                evidence_summary.get("unknown_impactful_findings", 0), default=0
            ),
            "boundary_public": _to_int(boundary_summary.get("public", 0), default=0),
            "boundary_unknown": _to_int(boundary_summary.get("unknown", 0), default=0),
        },
        "notes": [str(item) for item in notes[:DEFAULT_CASE_FILE_MAX_NOTES]],
    }

    estimated_tokens = _estimate_tokens_for_payload(case_file)
    while estimated_tokens > token_budget and case_file["top_findings"]:
        case_file["top_findings"].pop()
        omitted_findings += 1
        estimated_tokens = _estimate_tokens_for_payload(case_file)

    while estimated_tokens > token_budget and case_file["evidence_records"]:
        case_file["evidence_records"].pop()
        estimated_tokens = _estimate_tokens_for_payload(case_file)

    if estimated_tokens > token_budget and not case_file["evidence_records"]:
        case_file.pop("evidence_records", None)
        estimated_tokens = _estimate_tokens_for_payload(case_file)

    while estimated_tokens > token_budget and case_file["policy_effects"]:
        case_file["policy_effects"].pop()
        estimated_tokens = _estimate_tokens_for_payload(case_file)

    if estimated_tokens > token_budget and case_file["notes"]:
        case_file["notes"] = []
        estimated_tokens = _estimate_tokens_for_payload(case_file)

    if estimated_tokens > token_budget:
        case_file["engine_decision"]["reasoning"] = _normalize_snippet(
            case_file["engine_decision"]["reasoning"],
            max_lines=1,
            max_chars=96,
        )
        estimated_tokens = _estimate_tokens_for_payload(case_file)

    if estimated_tokens > token_budget:
        case_file["engine_decision"]["reasoning"] = ""
        estimated_tokens = _estimate_tokens_for_payload(case_file)

    stats = {
        "token_budget": int(token_budget),
        "estimated_input_tokens": int(estimated_tokens),
        "findings_included": len(case_file["top_findings"]),
        "findings_omitted": int(omitted_findings),
        "evidence_records_included": len(case_file.get("evidence_records", [])),
    }
    return CaseFileBuildResult(case_file=case_file, stats=stats)


def render_case_file_text(case_file: dict[str, Any]) -> str:
    return json.dumps(case_file, indent=2, ensure_ascii=True)

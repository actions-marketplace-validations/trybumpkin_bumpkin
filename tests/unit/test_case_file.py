from bumpkin.analysis.case_file import build_case_file
from bumpkin.analysis.evidence import EvidenceItem
from findings import Finding


def _finding(index: int) -> Finding:
    return Finding(
        id=f"f{index}",
        severity="PATCH",
        rule="internal_change",
        confidence="medium",
        title=f"Internal change {index}",
        why="helper logic changed",
        evidence=[{"path": f"src/internal/{index}.ts", "snippet": "const x = 1;"}],
        suggested_bump="PATCH",
    )


def test_build_case_file_includes_expected_contract_fields() -> None:
    findings = [_finding(1)]
    evidence_items = [
        EvidenceItem(
            evidence_id="finding:f1",
            type="finding",
            rule="internal_change",
            severity="PATCH",
            confidence="medium",
            path="src/internal/1.ts",
            snippet="const x = 1;",
            source="deterministic-findings",
        )
    ]
    built = build_case_file(
        engine_result={
            "status": "classified",
            "label": "PATCH",
            "confidence": "medium",
            "reasoning": "Deterministic patch.",
            "changelog": "fix: internal update",
        },
        findings=findings,
        evidence_items=evidence_items,
        policy_effects=["policy_mode=pragmatic"],
        notes=["test note"],
        coverage_contract={
            "status": "pass",
            "critical_files_total": 1,
            "critical_files_covered": 1,
            "omitted_files_total": 0,
        },
        boundary_summary={"public": 0, "internal": 1, "unknown": 0},
        evidence_summary={"strong_public_evidence": 0, "strong_breaking_evidence": 0},
    )
    assert built.case_file["version"] == "case_file_v1"
    assert built.case_file["engine_decision"]["label"] == "PATCH"
    assert built.case_file["evidence_records"][0]["evidence_id"] == "finding:f1"
    assert built.stats["token_budget"] == 1200
    assert built.stats["findings_included"] == 1
    assert built.stats["evidence_records_included"] == 1


def test_build_case_file_respects_token_budget_by_omitting_findings() -> None:
    findings = [_finding(index) for index in range(1, 10)]
    evidence_items = [
        EvidenceItem(
            evidence_id=f"finding:f{index}",
            type="finding",
            rule="internal_change",
            severity="PATCH",
            confidence="medium",
            path=f"src/internal/{index}.ts",
            snippet=("line " + ("x" * 120)),
            source="deterministic-findings",
        )
        for index in range(1, 10)
    ]
    built = build_case_file(
        engine_result={
            "status": "classified",
            "label": "PATCH",
            "confidence": "low",
            "reasoning": "Deterministic patch.",
            "changelog": "fix: internal update",
        },
        findings=findings,
        evidence_items=evidence_items,
        policy_effects=["policy"] * 10,
        notes=["note"] * 10,
        coverage_contract={
            "status": "pass",
            "critical_files_total": 0,
            "critical_files_covered": 0,
            "omitted_files_total": 0,
        },
        boundary_summary={"public": 0, "internal": 9, "unknown": 0},
        evidence_summary={"strong_public_evidence": 0, "strong_breaking_evidence": 0},
        token_budget=120,
        max_findings=8,
    )
    assert built.stats["estimated_input_tokens"] <= 120
    assert built.stats["findings_omitted"] >= 1
    assert isinstance(built.case_file.get("evidence_records", []), list)

from bumpkin.analysis.evidence import (
    build_evidence_items,
    build_evidence_prompt_text,
    summarize_evidence_items,
)
from findings import Finding


def test_build_evidence_items_includes_findings_and_behavior_markers() -> None:
    findings = [
        Finding(
            id="export_symbol_removed:1",
            severity="MAJOR",
            rule="export_symbol_removed",
            confidence="high",
            title="Removed export",
            why="Breaking API change.",
            evidence=[{"path": "src/api.ts", "snippet": "export function oldApi() {}"}],
            suggested_bump="MAJOR",
        )
    ]
    diff_text = (
        "diff --git a/src/api.ts b/src/api.ts\n"
        "--- a/src/api.ts\n"
        "+++ b/src/api.ts\n"
        "- if (!user) return\n"
        "+ throw new Error('missing user')\n"
        "+ fetch('/audit')\n"
    )
    evidence = build_evidence_items(
        findings=findings,
        diff_text=diff_text,
        behavior_contract_signals={"sample_files": ["src/openapi/schema.yaml"]},
    )
    rules = {item.rule for item in evidence}
    assert "export_symbol_removed" in rules
    assert "added_throw_statement" in rules
    assert "added_external_side_effect" in rules
    assert "removed_guard_branch" in rules
    assert "behavior_contract_path_signal" in rules


def test_build_evidence_prompt_text_contains_records_and_excerpt() -> None:
    evidence = build_evidence_items(
        findings=[],
        diff_text="+ throw new Error('x')\n",
        behavior_contract_signals={"sample_files": []},
    )
    prompt_text = build_evidence_prompt_text(
        evidence_items=evidence,
        diff_text="+ throw new Error('x')\n+ console.log('y')\n",
        max_chars=500,
    )
    assert "Evidence records:" in prompt_text
    assert "Diff excerpt:" in prompt_text
    assert "added_throw_statement" in prompt_text


def test_summarize_evidence_items_counts_type_and_severity() -> None:
    evidence = build_evidence_items(
        findings=[],
        diff_text="+ throw new Error('x')\n",
        behavior_contract_signals={"sample_files": []},
    )
    summary = summarize_evidence_items(evidence)
    assert summary["total"] >= 1
    assert summary["by_type"]["behavior_marker"] >= 1


def test_build_evidence_items_includes_path_markers_for_changed_files() -> None:
    diff_text = (
        "diff --git a/src/a.py b/src/a.py\n"
        "--- a/src/a.py\n"
        "+++ b/src/a.py\n"
        "+ value = 1\n"
        "diff --git a/src/b.py b/src/b.py\n"
        "--- a/src/b.py\n"
        "+++ b/src/b.py\n"
        "- value = 1\n"
        "+ value = 2\n"
    )
    evidence = build_evidence_items(
        findings=[],
        diff_text=diff_text,
        behavior_contract_signals={"sample_files": []},
    )
    path_rules = [item for item in evidence if item.rule == "changed_file_path"]
    assert len(path_rules) >= 2
    assert any(item.path == "src/a.py" for item in path_rules)
    assert any(item.path == "src/b.py" for item in path_rules)
    assert any(item.path == "src/a.py" and item.snippet == "value = 1" for item in path_rules)
    assert any(item.path == "src/b.py" and item.snippet == "value = 1" for item in path_rules)

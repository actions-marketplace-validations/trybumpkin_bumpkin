import json
from pathlib import Path

import pytest

from config import BumpkinConfig
from findings import AggregatedFindingResult, Finding
from main import (
    PREventContext,
    _apply_analysis_coverage_guard,
    _apply_degraded_provider_policy,
    _apply_docs_only_policy,
    _apply_findings_adjudication,
    _apply_impact_evidence_threshold,
    _apply_large_pr_no_bump_guard,
    _apply_noise_suppression_policy,
    _apply_policy_mode,
    _apply_truncated_no_bump_guard,
    _apply_truncated_surface_area_guard,
    _apply_unknown_boundary_policy,
    _categorize_failure_reason,
    _derive_analysis_state,
    _derive_docs_only_policy_effect,
    _derive_pre_1_0_policy_effect,
    _evaluate_scope_mismatch,
    _fetch_pr_changed_files,
    _parse_optional_bool,
    _read_event_context,
    _resolve_override_governance,
    _resolve_override_label,
    _select_diff_scope,
    _summarize_evidence,
)


def test_read_event_context_parses_pull_request_payload(tmp_path: Path) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "pull_request": {
                    "number": 42,
                    "merge_commit_sha": "merge123",
                    "base": {"sha": "base123"},
                    "head": {"sha": "head123"},
                    "labels": [{"name": "bump:minor"}],
                }
            }
        )
    )

    context = _read_event_context(str(event_path))
    assert context.pr_number == 42
    assert context.base_sha == "base123"
    assert context.merge_sha == "merge123"
    assert context.head_sha == "head123"
    assert context.labels == ["bump:minor"]


def test_select_diff_scope_uses_merge_parent_when_available() -> None:
    context = PREventContext(9, "base456", "head456", "merge456", [])

    from_ref, to_ref, notes = _select_diff_scope(
        "",
        "",
        context,
        merge_parent_resolver=lambda merge_sha: "parent456" if merge_sha == "merge456" else None,
    )

    assert from_ref == "parent456"
    assert to_ref == "merge456"
    assert notes == ["Using merged PR diff scope (merge parent SHA → merge SHA)."]


def test_select_diff_scope_falls_back_to_base_when_merge_parent_missing() -> None:
    context = PREventContext(9, "base456", "head456", "merge456", [])

    from_ref, to_ref, notes = _select_diff_scope(
        "",
        "",
        context,
        merge_parent_resolver=lambda _merge_sha: None,
    )

    assert from_ref == "base456"
    assert to_ref == "merge456"
    assert any("scope fallback (base SHA" in note for note in notes)


def test_select_diff_scope_falls_back_to_head_sha_when_merge_absent() -> None:
    context = PREventContext(10, "base789", "head789", None, [])

    from_ref, to_ref, notes = _select_diff_scope("", "", context)

    assert from_ref == "base789"
    assert to_ref == "head789"
    assert notes == ["Using PR diff scope from event payload."]


def test_select_diff_scope_respects_cli_overrides() -> None:
    context = PREventContext(11, "base000", "head000", "merge000", [])

    from_ref, to_ref, _ = _select_diff_scope("cli-from", "cli-to", context)

    assert from_ref == "cli-from"
    assert to_ref == "cli-to"


def test_resolve_override_label_for_single_override() -> None:
    override, name, warning = _resolve_override_label(["bug", "bump:major"])
    assert override == "MAJOR"
    assert name == "bump:major"
    assert warning is None


def test_resolve_override_label_for_conflicting_overrides() -> None:
    override, name, warning = _resolve_override_label(["bump:major", "bump:patch"])
    assert override is None
    assert name is None
    assert warning is not None


def test_parse_optional_bool_values() -> None:
    assert _parse_optional_bool("") is None
    assert _parse_optional_bool("true") is True
    assert _parse_optional_bool("false") is False


def test_parse_optional_bool_rejects_invalid_value() -> None:
    with pytest.raises(ValueError):
        _parse_optional_bool("maybe")


def test_apply_docs_only_policy_can_remap_no_bump_to_patch() -> None:
    result = {
        "status": "classified",
        "label": "NO_BUMP",
        "confidence": "high",
        "reasoning": "Only docs changed.",
        "changelog": "chore: no release required",
    }
    notes: list[str] = []

    updated = _apply_docs_only_policy(
        result,
        BumpkinConfig(
            ignore_paths=[],
            surface_area=[],
            public_api_entrypoints=[],
            public_api_paths=[],
            policy_mode="pragmatic",
            bugfix_patch_bias=True,
            use_difftastic=False,
            semantic_fallback=True,
            pre_1_0_breaking_as_minor=True,
            docs_only_label="PATCH",
            large_pr_max_files=30,
            large_pr_max_tokens=6000,
            truncated_no_bump_policy="MANUAL_REVIEW",
            chunking_enabled=True,
            chunk_max_tokens=1200,
            chunk_max_count=24,
            chunk_failure_policy="MANUAL_REVIEW",
        ),
        notes,
    )

    assert updated["label"] == "PATCH"
    assert updated["changelog"] == "chore: release required by repo policy"
    assert any("docs_only_label=PATCH" in note for note in notes)


def test_apply_truncated_no_bump_guard_downgrades_for_code_paths() -> None:
    result = {
        "status": "classified",
        "label": "NO_BUMP",
        "confidence": "high",
        "reasoning": "Only internal changes.",
        "changelog": "chore: no release required",
    }
    notes: list[str] = []

    updated, triggered = _apply_truncated_no_bump_guard(
        result,
        truncated=True,
        analyzed_files=["worker/src/routes/feedback.ts", ".github/workflows/ci.yml"],
        policy="MANUAL_REVIEW",
        notes=notes,
    )

    assert triggered is True
    assert updated["status"] == "manual_review"
    assert updated["label"] is None
    assert any(
        "truncated diff with non-doc/config paths rejected NO_BUMP" in note for note in notes
    )


def test_apply_truncated_no_bump_guard_keeps_docs_only_result() -> None:
    result = {
        "status": "classified",
        "label": "NO_BUMP",
        "confidence": "high",
        "reasoning": "Only docs/config changes.",
        "changelog": "chore: no release required",
    }

    updated, triggered = _apply_truncated_no_bump_guard(
        result,
        truncated=True,
        analyzed_files=["docs/plan.md", ".github/workflows/ci.yml", ".gitignore"],
        policy="MANUAL_REVIEW",
        notes=[],
    )

    assert triggered is False
    assert updated["status"] == "classified"
    assert updated["label"] == "NO_BUMP"


def test_apply_truncated_no_bump_guard_can_emit_patch_policy() -> None:
    result = {
        "status": "classified",
        "label": "NO_BUMP",
        "confidence": "high",
        "reasoning": "Only docs/config changes.",
        "changelog": "chore: no release required",
    }

    updated, triggered = _apply_truncated_no_bump_guard(
        result,
        truncated=True,
        analyzed_files=["src/app.ts"],
        policy="PATCH",
        notes=[],
    )

    assert triggered is True
    assert updated["status"] == "classified"
    assert updated["label"] == "PATCH"


def test_apply_truncated_surface_area_guard_downgrades_even_non_no_bump() -> None:
    result = {
        "status": "classified",
        "label": "MINOR",
        "confidence": "medium",
        "reasoning": "Added a feature.",
        "changelog": "feat: add feature",
    }

    updated, triggered = _apply_truncated_surface_area_guard(
        result,
        truncated=True,
        analyzed_files=["worker/src/routes/feedback.ts"],
        surface_area_hints=["worker/src/routes/**"],
        chunking_meta=None,
        notes=[],
    )

    assert triggered is True
    assert updated["status"] == "manual_review"
    assert updated["label"] is None


def test_apply_truncated_surface_area_guard_skips_when_chunking_fully_succeeds() -> None:
    result = {
        "status": "classified",
        "label": "MINOR",
        "confidence": "medium",
        "reasoning": "Added a feature.",
        "changelog": "feat: add feature",
    }
    notes: list[str] = []

    updated, triggered = _apply_truncated_surface_area_guard(
        result,
        truncated=True,
        analyzed_files=["worker/src/routes/feedback.ts"],
        surface_area_hints=["worker/src/routes/**"],
        chunking_meta={
            "enabled": True,
            "chunk_count": 9,
            "succeeded": 9,
            "failed": 0,
            "skipped": 0,
        },
        notes=notes,
    )

    assert triggered is False
    assert updated["status"] == "classified"
    assert updated["label"] == "MINOR"
    assert any("Safety guard bypassed" in note for note in notes)


def test_apply_large_pr_no_bump_guard_rejects_no_bump() -> None:
    result = {
        "status": "classified",
        "label": "NO_BUMP",
        "confidence": "high",
        "reasoning": "No release impact.",
        "changelog": "chore: no release required",
    }

    updated, triggered = _apply_large_pr_no_bump_guard(
        result,
        analyzed_files_count=40,
        approx_prompt_tokens=1200,
        max_files=30,
        max_tokens=6000,
        policy="MANUAL_REVIEW",
        notes=[],
    )

    assert triggered is True
    assert updated["status"] == "manual_review"


def test_apply_analysis_coverage_guard_manual_review_on_uncovered_files() -> None:
    result = {
        "status": "classified",
        "label": "PATCH",
        "confidence": "medium",
        "reasoning": "Internal update",
        "changelog": "fix: internal update",
    }
    notes: list[str] = []
    updated, triggered = _apply_analysis_coverage_guard(
        result,
        analyzed_files=["src/a.ts", "src/b.ts"],
        findings=[],
        chunking_meta={
            "omitted_files": ["src/b.ts"],
        },
        notes=notes,
    )

    assert triggered is True
    assert updated["status"] == "manual_review"
    assert any("Coverage guard" in note for note in notes)


def test_apply_analysis_coverage_guard_allows_when_deterministic_covers_omitted() -> None:
    result = {
        "status": "classified",
        "label": "PATCH",
        "confidence": "medium",
        "reasoning": "Internal update",
        "changelog": "fix: internal update",
    }
    finding = Finding(
        id="f1",
        severity="PATCH",
        rule="test_rule",
        confidence="high",
        title="deterministic finding",
        why="test",
        evidence=[{"path": "src/b.ts", "snippet": "export const b = 1;"}],
        suggested_bump="PATCH",
    )
    updated, triggered = _apply_analysis_coverage_guard(
        result,
        analyzed_files=["src/a.ts", "src/b.ts"],
        findings=[finding],
        chunking_meta={
            "omitted_files": ["src/b.ts"],
        },
        notes=[],
    )

    assert triggered is False
    assert updated["status"] == "classified"


def test_derive_docs_only_policy_effect_reports_no_effect_for_non_no_bump() -> None:
    effect = _derive_docs_only_policy_effect(
        status="classified",
        label="PATCH",
        docs_only_label="PATCH",
    )
    assert "no remap applied" in effect


def test_derive_pre_1_0_policy_effect_reports_applied_for_zero_based_major() -> None:
    effect = _derive_pre_1_0_policy_effect(
        status="classified",
        label="MAJOR",
        current_tag="0.5.2",
        pre_1_0_breaking_as_minor=True,
    )
    assert effect is not None
    assert "applied" in effect


def test_derive_pre_1_0_policy_effect_reports_no_effect_for_non_major() -> None:
    effect = _derive_pre_1_0_policy_effect(
        status="classified",
        label="MINOR",
        current_tag="0.5.2",
        pre_1_0_breaking_as_minor=True,
    )
    assert effect is not None
    assert "no effect" in effect


def test_derive_analysis_state_for_authoritative_findings() -> None:
    analysis_state, source = _derive_analysis_state(
        status="classified",
        classification_source="deterministic-findings",
    )
    assert analysis_state == "authoritative"
    assert source == "deterministic-findings"


def test_derive_analysis_state_for_degraded_semantic_fallback() -> None:
    analysis_state, source = _derive_analysis_state(
        status="classified",
        classification_source="semantic-fallback",
    )
    assert analysis_state == "degraded_fallback"
    assert source == "semantic-fallback"


def test_derive_analysis_state_for_manual_review() -> None:
    analysis_state, source = _derive_analysis_state(
        status="manual_review",
        classification_source="model",
    )
    assert analysis_state == "manual_review"
    assert source == "model"


def test_apply_findings_adjudication_uses_hybrid_floor_for_non_breaking_findings() -> None:
    model_result = {
        "status": "classified",
        "label": "PATCH",
        "confidence": "high",
        "reasoning": "Internal behavior change.",
        "changelog": "fix: internal behavior update",
    }
    deterministic = AggregatedFindingResult(
        status="classified",
        label="MINOR",
        confidence="high",
        reasoning="Exported API symbol added.",
        changelog="feat: add backward-compatible api changes",
        aggregation_trace="No MAJOR findings; MINOR findings present; selected MINOR.",
        contributing_findings=1,
    )
    notes: list[str] = []

    merged, trace, source = _apply_findings_adjudication(
        model_result,
        aggregated_findings=deterministic,
        mode_used="github-models",
        notes=notes,
    )

    assert merged["status"] == "classified"
    assert merged["label"] == "MINOR"
    assert source == "hybrid"
    assert trace == deterministic.aggregation_trace
    assert any("raised to deterministic floor MINOR" in note for note in notes)


def test_apply_findings_adjudication_keeps_major_as_deterministic_authority() -> None:
    model_result = {
        "status": "classified",
        "label": "PATCH",
        "confidence": "high",
        "reasoning": "Internal behavior change.",
        "changelog": "fix: internal behavior update",
    }
    deterministic = AggregatedFindingResult(
        status="classified",
        label="MAJOR",
        confidence="high",
        reasoning="Removed exported API symbol.",
        changelog="feat: introduce breaking api changes",
        aggregation_trace="MAJOR findings present; selected MAJOR.",
        contributing_findings=1,
    )
    notes: list[str] = []

    merged, _, source = _apply_findings_adjudication(
        model_result,
        aggregated_findings=deterministic,
        mode_used="github-models",
        notes=notes,
    )

    assert merged["label"] == "MAJOR"
    assert source == "deterministic-findings"
    assert any("hard-authoritative" in note for note in notes)


def test_apply_findings_adjudication_keeps_model_label_when_above_floor() -> None:
    model_result = {
        "status": "classified",
        "label": "MAJOR",
        "confidence": "medium",
        "reasoning": "Behavioral contract changed in a breaking way.",
        "changelog": "feat: introduce breaking behavior change",
    }
    deterministic = AggregatedFindingResult(
        status="classified",
        label="MINOR",
        confidence="high",
        reasoning="Exported API symbol added.",
        changelog="feat: add backward-compatible api changes",
        aggregation_trace="No MAJOR findings; MINOR findings present; selected MINOR.",
        contributing_findings=1,
    )
    notes: list[str] = []

    merged, _, source = _apply_findings_adjudication(
        model_result,
        aggregated_findings=deterministic,
        mode_used="github-models",
        notes=notes,
    )

    assert merged["label"] == "MAJOR"
    assert source == "hybrid"
    assert any("met or exceeded" in note for note in notes)


def test_categorize_failure_reason_maps_ssl_and_auth_errors() -> None:
    assert _categorize_failure_reason("[SSL: CERTIFICATE_VERIFY_FAILED]") == "ssl_failure"
    assert _categorize_failure_reason("HTTP 401: bad credentials") == "invalid_token"
    assert _categorize_failure_reason("HTTP 413: tokens_limit_reached") == "payload_too_large"


def test_evaluate_scope_mismatch_detects_fetch_failure() -> None:
    mismatch, reason = _evaluate_scope_mismatch(
        required=True,
        fetch_error="Scope guard unavailable: missing GITHUB_TOKEN.",
        git_files_count=0,
        overlap_count=0,
        unexpected_count=0,
        missing_count=0,
    )

    assert mismatch is True
    assert "missing GITHUB_TOKEN" in str(reason)


def test_evaluate_scope_mismatch_detects_unexpected_and_missing_files() -> None:
    mismatch, reason = _evaluate_scope_mismatch(
        required=True,
        fetch_error=None,
        git_files_count=5,
        overlap_count=1,
        unexpected_count=4,
        missing_count=1,
    )

    assert mismatch is True
    assert "outside PR file allowlist" in str(reason)
    assert "missing from git diff scope" in str(reason)


def test_evaluate_scope_mismatch_passes_when_counts_align() -> None:
    mismatch, reason = _evaluate_scope_mismatch(
        required=True,
        fetch_error=None,
        git_files_count=2,
        overlap_count=2,
        unexpected_count=0,
        missing_count=0,
    )

    assert mismatch is False
    assert reason is None


def test_fetch_pr_changed_files_requires_repo_and_token() -> None:
    files, error = _fetch_pr_changed_files(token="", repo="", pr_number=12)
    assert files is None
    assert error is not None


def test_fetch_pr_changed_files_collects_and_dedupes(monkeypatch) -> None:
    calls: list[str] = []

    def fake_request(_token: str, url: str) -> list[dict[str, str]]:
        calls.append(url)
        if "page=1" in url:
            return [
                {"filename": "./src/a.ts"},
                {"filename": "src/b.ts"},
            ]
        return []

    monkeypatch.setattr("main._github_api_request", fake_request)
    files, error = _fetch_pr_changed_files(token="token", repo="owner/repo", pr_number=77)

    assert error is None
    assert files == ["src/a.ts", "src/b.ts"]
    assert calls


def test_apply_policy_mode_records_config_without_unknown_boundary_mutation() -> None:
    result = {
        "status": "classified",
        "label": "MINOR",
        "confidence": "high",
        "reasoning": "Internal bugfix with additive cleanup.",
        "changelog": "fix: improve internal behavior",
    }
    cfg = BumpkinConfig(
        ignore_paths=[],
        surface_area=[],
        public_api_entrypoints=[],
        public_api_paths=[],
        policy_mode="pragmatic",
        bugfix_patch_bias=True,
        use_difftastic=False,
        semantic_fallback=True,
        pre_1_0_breaking_as_minor=True,
        docs_only_label="NO_BUMP",
        large_pr_max_files=30,
        large_pr_max_tokens=6000,
        truncated_no_bump_policy="MANUAL_REVIEW",
        chunking_enabled=True,
        chunk_max_tokens=1200,
        chunk_max_count=24,
        chunk_failure_policy="MANUAL_REVIEW",
    )

    updated, effects, actions = _apply_policy_mode(
        result,
        boundary_summary={"public": 0, "internal": 0, "unknown": 1},
        config=cfg,
        notes=[],
    )

    assert updated["label"] == "MINOR"
    assert any("policy_mode=pragmatic" in effect for effect in effects)
    assert (
        "policy_mode recorded; boundary strictness is governed by unknown_boundary_policy."
        in actions
    )


def test_apply_unknown_boundary_policy_patch_if_bugfix_remaps_to_patch() -> None:
    result = {
        "status": "classified",
        "label": "MINOR",
        "confidence": "high",
        "reasoning": "Internal bugfix with additive cleanup.",
        "changelog": "fix: improve internal behavior",
    }
    cfg = BumpkinConfig(
        ignore_paths=[],
        surface_area=[],
        public_api_entrypoints=[],
        public_api_paths=[],
        policy_mode="pragmatic",
        bugfix_patch_bias=True,
        use_difftastic=False,
        semantic_fallback=True,
        pre_1_0_breaking_as_minor=True,
        docs_only_label="NO_BUMP",
        large_pr_max_files=30,
        large_pr_max_tokens=6000,
        truncated_no_bump_policy="MANUAL_REVIEW",
        chunking_enabled=True,
        chunk_max_tokens=1200,
        chunk_max_count=24,
        chunk_failure_policy="MANUAL_REVIEW",
        unknown_boundary_policy="patch_if_bugfix",
    )
    notes: list[str] = []
    updated, _effects, actions = _apply_unknown_boundary_policy(
        result,
        boundary_summary={"public": 0, "internal": 0, "unknown": 2},
        config=cfg,
        notes=notes,
    )

    assert updated["status"] == "classified"
    assert updated["label"] == "PATCH"
    assert "unknown_boundary_policy.patch_if_bugfix -> PATCH" in actions
    assert any("remapped impactful bugfix recommendation to PATCH" in note for note in notes)


def test_apply_unknown_boundary_policy_manual_review_for_unknown_impact() -> None:
    result = {
        "status": "classified",
        "label": "MAJOR",
        "confidence": "high",
        "reasoning": "Breaking surface change.",
        "changelog": "feat: introduce breaking api changes",
    }
    cfg = BumpkinConfig(
        ignore_paths=[],
        surface_area=[],
        public_api_entrypoints=[],
        public_api_paths=[],
        policy_mode="manual_first",
        bugfix_patch_bias=True,
        use_difftastic=False,
        semantic_fallback=True,
        pre_1_0_breaking_as_minor=True,
        docs_only_label="NO_BUMP",
        large_pr_max_files=30,
        large_pr_max_tokens=6000,
        truncated_no_bump_policy="MANUAL_REVIEW",
        chunking_enabled=True,
        chunk_max_tokens=1200,
        chunk_max_count=24,
        chunk_failure_policy="MANUAL_REVIEW",
        unknown_boundary_policy="manual_review",
    )

    updated, effects, actions = _apply_unknown_boundary_policy(
        result,
        boundary_summary={"public": 0, "internal": 0, "unknown": 2},
        config=cfg,
        notes=[],
    )

    assert updated["status"] == "manual_review"
    assert any("requires manual review" in effect for effect in effects)
    assert "unknown_boundary_policy -> manual_review" in actions


def test_apply_impact_evidence_threshold_downgrades_major_when_breaking_evidence_missing() -> None:
    result = {
        "status": "classified",
        "label": "MAJOR",
        "confidence": "medium",
        "reasoning": "Potentially breaking change.",
        "changelog": "feat: introduce breaking api changes",
    }
    cfg = BumpkinConfig(
        ignore_paths=[],
        surface_area=[],
        public_api_entrypoints=[],
        public_api_paths=[],
        policy_mode="pragmatic",
        bugfix_patch_bias=True,
        use_difftastic=False,
        semantic_fallback=True,
        pre_1_0_breaking_as_minor=True,
        docs_only_label="NO_BUMP",
        large_pr_max_files=30,
        large_pr_max_tokens=6000,
        truncated_no_bump_policy="MANUAL_REVIEW",
        chunking_enabled=True,
        chunk_max_tokens=1200,
        chunk_max_count=24,
        chunk_failure_policy="MANUAL_REVIEW",
        impact_evidence_threshold="moderate",
    )

    updated, effects, actions = _apply_impact_evidence_threshold(
        result,
        boundary_summary={"public": 1, "internal": 0, "unknown": 0},
        evidence_summary={
            "strong_public_evidence": 1,
            "strong_breaking_evidence": 0,
            "behavior_contract_evidence": 0,
            "export_public_evidence": 1,
            "export_breaking_evidence": 0,
            "unknown_impactful_findings": 0,
        },
        config=cfg,
        notes=[],
    )

    assert updated["status"] == "classified"
    assert updated["label"] == "MINOR"
    assert "impact_evidence_threshold.major_breaking_unmet -> minor" in actions
    assert any("MAJOR downgraded to MINOR" in effect for effect in effects)


def test_apply_noise_suppression_policy_forces_manual_review_under_high_noise_and_weak_evidence() -> (
    None
):
    result = {
        "status": "classified",
        "label": "MINOR",
        "confidence": "high",
        "reasoning": "Feature-like behavior",
        "changelog": "feat: add helper",
    }
    cfg = BumpkinConfig(
        ignore_paths=[],
        surface_area=[],
        public_api_entrypoints=[],
        public_api_paths=[],
        policy_mode="pragmatic",
        bugfix_patch_bias=True,
        use_difftastic=False,
        semantic_fallback=True,
        pre_1_0_breaking_as_minor=True,
        docs_only_label="NO_BUMP",
        large_pr_max_files=30,
        large_pr_max_tokens=6000,
        truncated_no_bump_policy="MANUAL_REVIEW",
        chunking_enabled=True,
        chunk_max_tokens=1200,
        chunk_max_count=24,
        chunk_failure_policy="MANUAL_REVIEW",
        noise_suppression_policy="balanced",
    )

    updated, effects, actions = _apply_noise_suppression_policy(
        result,
        noise_ratio=0.8,
        changed_files_total=18,
        evidence_summary={
            "strong_public_evidence": 0,
            "strong_breaking_evidence": 0,
            "behavior_contract_evidence": 0,
            "export_public_evidence": 0,
            "export_breaking_evidence": 0,
            "unknown_impactful_findings": 2,
        },
        config=cfg,
        notes=[],
    )

    assert updated["status"] == "manual_review"
    assert "noise_suppression_policy.weak_impactful_under_noise -> manual_review" in actions
    assert any(
        "high-noise impactful recommendation lacked strong evidence" in effect for effect in effects
    )


def test_apply_degraded_provider_policy_can_force_manual_review() -> None:
    result = {
        "status": "classified",
        "label": "MINOR",
        "confidence": "low",
        "reasoning": "Fallback semantic classification.",
        "changelog": "feat: add backward-compatible api changes",
    }
    cfg = BumpkinConfig(
        ignore_paths=[],
        surface_area=[],
        public_api_entrypoints=[],
        public_api_paths=[],
        policy_mode="pragmatic",
        bugfix_patch_bias=True,
        use_difftastic=False,
        semantic_fallback=True,
        pre_1_0_breaking_as_minor=True,
        docs_only_label="NO_BUMP",
        large_pr_max_files=30,
        large_pr_max_tokens=6000,
        truncated_no_bump_policy="MANUAL_REVIEW",
        chunking_enabled=True,
        chunk_max_tokens=1200,
        chunk_max_count=24,
        chunk_failure_policy="MANUAL_REVIEW",
        degraded_provider_policy="MANUAL_REVIEW",
    )

    updated, _, actions = _apply_degraded_provider_policy(
        result,
        mode_used="fallback-heuristic",
        classification_source="semantic-fallback",
        config=cfg,
        notes=[],
    )

    assert updated["status"] == "manual_review"
    assert "degraded_provider_policy.manual_review -> manual_review" in actions


def test_resolve_override_governance_severity_precedence_picks_major() -> None:
    resolved = _resolve_override_governance(
        ["bump:minor", "bump:major"],
        policy="severity_precedence",
    )
    assert resolved.label == "MAJOR"
    assert resolved.label_name == "bump:major"
    assert resolved.status == "conflict_resolved"


def test_summarize_evidence_counts_contract_signals() -> None:
    summary = _summarize_evidence(
        findings=[],
        public_hints=[],
        contract_signals={"total": 2},
    )
    assert summary["strong_public_evidence"] == 2
    assert summary["behavior_contract_evidence"] == 2

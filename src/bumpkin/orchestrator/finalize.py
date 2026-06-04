from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bumpkin.analysis.diffing import DiffResult
from bumpkin.analysis.findings import Finding
from bumpkin.config import BumpkinConfig
from bumpkin.orchestrator import scope as orchestrator_scope
from bumpkin.policies import engine as policy_engine
from bumpkin.prompt_pack import PromptPackMetadata
from bumpkin.versioning.tags import detect_next_version


@dataclass(frozen=True)
class FinalizationResult:
    result: dict[str, Any]
    notes: list[str]
    policy_effects: list[str]
    policy_actions: list[str]
    override_summary: str | None
    override_status: str
    override_payload: dict[str, str | bool | None]
    current_tag: str | None
    next_tag: str | None
    decision_trace: dict[str, Any]


def finalize_release(
    *,
    result: dict[str, Any],
    status: str,
    status_before_policy: str,
    label_before_policy: str | None,
    findings: list[Finding],
    aggregation_trace: str | None,
    boundary_summary: dict[str, int],
    evidence_summary: dict[str, int],
    behavior_contract_signals: dict[str, object],
    non_actionable_noise_ratio: float,
    diff_result: DiffResult,
    bumpkin_config: BumpkinConfig,
    event_labels: list[str],
    notes: list[str],
    policy_effects: list[str],
    policy_actions: list[str],
    planner_payload: dict[str, object],
    coverage_contract: dict[str, object],
) -> FinalizationResult:
    updated_result = dict(result)
    updated_notes = list(notes)
    updated_policy_effects = list(policy_effects)
    updated_policy_actions = list(policy_actions)

    override_summary: str | None = None
    override_status = "none"
    override_payload: dict[str, str | bool | None] = {
        "present": False,
        "status": "none",
        "label_name": None,
        "from_label": None,
        "to_label": None,
        "warning": None,
        "governance_policy": bumpkin_config.override_governance_policy,
        "audit_note": None,
    }
    override_resolution = orchestrator_scope.resolve_override_governance(
        event_labels,
        policy=bumpkin_config.override_governance_policy,
    )
    override_label = override_resolution.label
    override_name = override_resolution.label_name
    override_warning = override_resolution.warning
    updated_policy_effects.append(override_resolution.audit_note)
    if override_resolution.status.startswith("conflict"):
        updated_policy_actions.append(f"override_governance.{override_resolution.status}")
    elif override_resolution.status == "single":
        updated_policy_actions.append("override_governance.single_label_detected")

    if (
        status == "classified"
        and override_name
        and override_label
        and updated_result.get("label") != override_label
    ):
        original = updated_result.get("label")
        updated_result["label"] = override_label
        override_summary = (
            f"🔁 Override applied via `{override_name}`: {original} → {override_label}"
        )
        override_status = f"applied via `{override_name}`: {original} → {override_label}"
        override_payload = {
            "present": True,
            "status": "applied",
            "label_name": override_name,
            "from_label": str(original),
            "to_label": override_label,
            "warning": None,
            "governance_policy": bumpkin_config.override_governance_policy,
            "audit_note": override_resolution.audit_note,
        }
        updated_notes.append(f"Override label applied: {override_name}.")
    elif status == "classified" and override_name and override_label:
        override_status = (
            f"present via `{override_name}`; matched recommendation ({override_label})."
        )
        override_payload = {
            "present": True,
            "status": "matched",
            "label_name": override_name,
            "from_label": str(updated_result.get("label")),
            "to_label": override_label,
            "warning": None,
            "governance_policy": bumpkin_config.override_governance_policy,
            "audit_note": override_resolution.audit_note,
        }
        updated_notes.append(f"Override label `{override_name}` matched recommendation.")
    elif status != "classified" and override_name:
        override_status = (
            f"ignored `{override_name}` because no authoritative base recommendation existed."
        )
        override_payload = {
            "present": True,
            "status": "ignored",
            "label_name": override_name,
            "from_label": None,
            "to_label": override_label,
            "warning": None,
            "governance_policy": bumpkin_config.override_governance_policy,
            "audit_note": override_resolution.audit_note,
        }
        updated_notes.append("Override labels ignored because no base recommendation existed.")
    elif override_warning:
        override_status = override_warning
        override_payload = {
            "present": True,
            "status": "conflict",
            "label_name": None,
            "from_label": None,
            "to_label": None,
            "warning": override_warning,
            "governance_policy": bumpkin_config.override_governance_policy,
            "audit_note": override_resolution.audit_note,
        }
        updated_notes.append(override_warning)

    current_tag: str | None = None
    next_tag: str | None = None
    if (
        status == "classified"
        and updated_result.get("label")
        and str(updated_result["label"]).upper() != "NO_BUMP"
    ):
        current_tag, next_tag, version_notes = detect_next_version(
            str(updated_result["label"]),
            pre_1_0_breaking_as_minor=bumpkin_config.pre_1_0_breaking_as_minor,
        )
        updated_notes.extend(version_notes)
    elif status == "classified" and str(updated_result.get("label", "")).upper() == "NO_BUMP":
        updated_notes.append("NO_BUMP classification: next version not computed.")

    pre_1_0_effect = policy_engine.derive_pre_1_0_policy_effect(
        status=status,
        label=str(updated_result.get("label", "")).upper() if status == "classified" else None,
        current_tag=current_tag,
        pre_1_0_breaking_as_minor=bumpkin_config.pre_1_0_breaking_as_minor,
    )
    if pre_1_0_effect:
        updated_policy_effects.append(pre_1_0_effect)

    decision_trace = {
        "base_status": status_before_policy,
        "base_label": label_before_policy,
        "final_status": status,
        "final_label": str(updated_result.get("label", "")).upper()
        if status == "classified"
        else None,
        "findings_total": len(findings),
        "finding_severity_counts": policy_engine.finding_severity_counts(findings),
        "aggregation_trace": aggregation_trace,
        "boundary_summary": boundary_summary,
        "evidence_summary": evidence_summary,
        "behavior_contract_signals": behavior_contract_signals,
        "noise_profile": {
            "ratio": non_actionable_noise_ratio,
            "changed_files_total": diff_result.changed_files_total,
            "ignored_files_total": diff_result.ignored_files_total,
            "policy": bumpkin_config.noise_suppression_policy,
        },
        "policy_mode": bumpkin_config.policy_mode,
        "unknown_boundary_policy": bumpkin_config.unknown_boundary_policy,
        "impact_evidence_threshold": bumpkin_config.impact_evidence_threshold,
        "behavior_contract_policy": bumpkin_config.behavior_contract_policy,
        "noise_suppression_policy": bumpkin_config.noise_suppression_policy,
        "override_governance_policy": bumpkin_config.override_governance_policy,
        "degraded_provider_policy": bumpkin_config.degraded_provider_policy,
        "planner": planner_payload,
        "coverage_contract": coverage_contract,
        "policy_actions": updated_policy_actions,
        "policy_effects": updated_policy_effects,
    }

    return FinalizationResult(
        result=updated_result,
        notes=updated_notes,
        policy_effects=updated_policy_effects,
        policy_actions=updated_policy_actions,
        override_summary=override_summary,
        override_status=override_status,
        override_payload=override_payload,
        current_tag=current_tag,
        next_tag=next_tag,
        decision_trace=decision_trace,
    )


def build_output_payload(
    *,
    status: str,
    mode_used: str,
    prompt_metadata: PromptPackMetadata,
    model_used: str | None,
    analysis_state: str,
    classification_source: str,
    failure_category: str | None,
    fallback_reason: str | None,
    diff_result: DiffResult,
    result: dict[str, Any],
    findings: list[Finding],
    aggregation_trace: str | None,
    boundary_summary: dict[str, int],
    decision_trace: dict[str, Any],
    policy_effects: list[str],
    override_payload: dict[str, str | bool | None],
    impact_summary: dict[str, Any],
    evidence_summary: dict[str, int],
    behavior_contract_signals: dict[str, object],
    scope_mismatch_detected: bool,
    coverage_guard_triggered: bool,
    truncated_no_bump_guard_triggered: bool,
    surface_area_guard_triggered: bool,
    large_pr_guard_triggered: bool,
    scope_guard: dict[str, object],
    non_actionable_noise_ratio: float,
    chunking_meta: dict[str, object],
    planner_payload: dict[str, object],
    coverage_contract: dict[str, object],
    evidence_items: list[dict[str, str]],
    evidence_summary_meta: dict[str, Any],
    case_file: dict[str, Any],
    case_file_stats: dict[str, int],
    advisory: dict[str, Any],
    decision_authority: str,
    deterministic_label: str | None,
    deterministic_next_tag: str | None,
    current_tag: str | None,
    next_tag: str | None,
    explainability_rows: list[dict[str, str]],
    semantic_facts: list[dict[str, str]],
    proof_obligations: dict[str, Any],
    reasoning_trace: list[dict[str, Any]],
    contradictions: list[dict[str, Any]],
    notes: list[str],
) -> dict[str, Any]:
    return {
        "output_contract_version": "v5",
        "status": status,
        "mode": mode_used,
        "prompt_version": prompt_metadata.prompt_version,
        "language_group": prompt_metadata.language_group,
        "promotion_status": prompt_metadata.promotion_status,
        "model_used": model_used,
        "analysis_state": analysis_state,
        "classification_source": classification_source,
        "failure_category": failure_category,
        "fallback_reason": fallback_reason,
        "decision_authority": decision_authority,
        "deterministic_label": deterministic_label,
        "deterministic_next_tag": deterministic_next_tag,
        "advisory_status": advisory.get("status", "skipped"),
        "advisory_label": advisory.get("label"),
        "advisory_confidence": advisory.get("confidence"),
        "court_verdict": {
            "judge_summary": advisory.get("judge_summary"),
            "prosecutor_claims": advisory.get("prosecutor_claims", []),
            "defender_claims": advisory.get("defender_claims", []),
            "accepted_arguments": advisory.get("accepted_arguments", []),
            "rejected_arguments": advisory.get("rejected_arguments", []),
            "unresolved_risks": advisory.get("unresolved_risks", []),
            "accepted_evidence_ids": advisory.get("accepted_evidence_ids", []),
            "rejected_evidence_ids": advisory.get("rejected_evidence_ids", []),
        },
        "disagreement_reason": advisory.get("disagreement_reason"),
        "from_ref": diff_result.from_ref,
        "to_ref": diff_result.to_ref,
        "label": result["label"] if status == "classified" else None,
        "confidence": result["confidence"] if status == "classified" else None,
        "reasoning": result["reasoning"],
        "changelog": result["changelog"] if status == "classified" else None,
        "findings": [finding.to_dict() for finding in findings],
        "explainability_rows": explainability_rows,
        "semantic_facts": semantic_facts,
        "proof_obligations": proof_obligations,
        "reasoning_trace": reasoning_trace,
        "contradictions": contradictions,
        "aggregation_trace": aggregation_trace,
        "boundary_summary": boundary_summary,
        "decision_trace": decision_trace,
        "policy_effects": policy_effects,
        "override": override_payload,
        "impact_summary": impact_summary,
        "evidence_summary": evidence_summary,
        "behavior_contract_signals": behavior_contract_signals,
        "truncated": diff_result.truncated,
        "guard_flags": {
            "scope_mismatch_guard_triggered": scope_mismatch_detected,
            "coverage_guard_triggered": coverage_guard_triggered,
            "truncated_no_bump_guard_triggered": truncated_no_bump_guard_triggered,
            "surface_area_guard_triggered": surface_area_guard_triggered,
            "large_pr_guard_triggered": large_pr_guard_triggered,
        },
        "scope_guard": scope_guard,
        "non_actionable_noise_ratio": non_actionable_noise_ratio,
        "changed_files_total": diff_result.changed_files_total,
        "ignored_files_total": diff_result.ignored_files_total,
        "approx_prompt_tokens": diff_result.approx_prompt_tokens,
        "approx_full_tokens": diff_result.approx_full_tokens,
        "per_file_cap_applied_count": diff_result.capped_files,
        "chunking": chunking_meta,
        "planner": planner_payload,
        "coverage_contract": coverage_contract,
        "evidence": evidence_items,
        "evidence_summary_meta": evidence_summary_meta,
        "case_file": case_file,
        "case_file_stats": case_file_stats,
        "current_tag": current_tag,
        "next_tag": next_tag,
        "notes": notes,
    }

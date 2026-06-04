from bumpkin.contracts import build_coverage_contract, validate_output_contract


def test_build_coverage_contract_flags_omitted_critical_files() -> None:
    coverage = build_coverage_contract(
        analyzed_files=["src/api/public.ts", "src/internal/helper.ts"],
        chunking_meta={
            "omitted_files": ["src/api/public.ts"],
        },
        public_api_hints=["src/api/**"],
        behavior_contract_signals={"sample_files": []},
    )
    assert coverage["version"] == "coverage_contract_v1"
    assert coverage["status"] == "fail"
    assert coverage["critical_files_total"] == 1
    assert coverage["critical_files_covered"] == 0
    assert coverage["omitted_critical_files"] == ["src/api/public.ts"]


def test_validate_output_contract_passes_for_manual_review_payload() -> None:
    payload = {
        "output_contract_version": "v3",
        "status": "manual_review",
        "analysis_state": "manual_review",
        "classification_source": "coverage-contract",
        "reasoning": "Manual review required due to incomplete coverage.",
        "label": None,
        "confidence": None,
        "changelog": None,
        "planner": {
            "version": "decision_contract_v3",
            "route": "evidence_targeted",
            "reason": "provider_or_chunk_budget_exceeded",
        },
        "coverage_contract": {
            "version": "coverage_contract_v1",
            "status": "fail",
            "critical_files_total": 2,
            "critical_files_covered": 1,
            "omitted_critical_files": ["src/api/public.ts"],
            "omitted_files_total": 4,
        },
    }
    assert validate_output_contract(payload) == []


def test_validate_output_contract_rejects_classified_payload_without_label() -> None:
    payload = {
        "output_contract_version": "v3",
        "status": "classified",
        "analysis_state": "authoritative",
        "classification_source": "model",
        "reasoning": "Classified result.",
        "label": "",
        "confidence": "high",
        "changelog": "fix: update behavior",
        "planner": {
            "version": "decision_contract_v3",
            "route": "full",
            "reason": "within_provider_budget",
        },
        "coverage_contract": {
            "version": "coverage_contract_v1",
            "status": "pass",
            "critical_files_total": 0,
            "critical_files_covered": 0,
            "omitted_critical_files": [],
            "omitted_files_total": 0,
        },
    }
    errors = validate_output_contract(payload)
    assert any("non-empty label" in item for item in errors)


def test_validate_output_contract_accepts_v4_payload_with_advisory_fields() -> None:
    payload = {
        "output_contract_version": "v4",
        "status": "classified",
        "analysis_state": "authoritative",
        "classification_source": "deterministic-findings",
        "reasoning": "Deterministic findings selected MINOR from exported additions.",
        "label": "MINOR",
        "confidence": "high",
        "changelog": "feat: add exported api symbols",
        "decision_authority": "deterministic",
        "deterministic_label": "MINOR",
        "deterministic_next_tag": "0.16.0",
        "advisory_status": "aligned",
        "advisory_label": "MINOR",
        "advisory_confidence": "medium",
        "explainability_rows": [
            {
                "path": "src/api/public.ts",
                "rule": "export_symbol_added",
                "action": "added",
                "target": "getUserProfile",
                "impact_scope": "public_api",
                "suggested_bump": "MINOR",
                "severity": "MINOR",
            }
        ],
        "planner": {
            "version": "decision_contract_v3",
            "route": "full",
            "reason": "within_provider_budget",
        },
        "coverage_contract": {
            "version": "coverage_contract_v1",
            "status": "pass",
            "critical_files_total": 1,
            "critical_files_covered": 1,
            "omitted_critical_files": [],
            "omitted_files_total": 0,
        },
        "case_file": {
            "version": "case_file_v1",
            "engine_decision": {
                "status": "classified",
                "label": "MINOR",
                "confidence": "high",
                "reasoning": "Deterministic findings.",
                "changelog": "feat: add exported api symbols",
            },
            "top_findings": [],
            "policy_effects": [],
            "coverage_flags": {},
            "evidence_summary": {},
            "notes": [],
        },
        "case_file_stats": {
            "token_budget": 1200,
            "estimated_input_tokens": 230,
            "findings_included": 2,
            "findings_omitted": 0,
        },
    }
    assert validate_output_contract(payload) == []


def test_validate_output_contract_accepts_v4_court_authority() -> None:
    payload = {
        "output_contract_version": "v4",
        "status": "manual_review",
        "analysis_state": "manual_review",
        "classification_source": "court-unavailable",
        "reasoning": "Court authority unavailable; manual review required.",
        "label": None,
        "confidence": None,
        "changelog": None,
        "decision_authority": "court",
        "deterministic_label": "MINOR",
        "deterministic_next_tag": "0.16.0",
        "advisory_status": "degraded",
        "advisory_label": None,
        "advisory_confidence": None,
        "explainability_rows": [],
        "planner": {
            "version": "decision_contract_v3",
            "route": "manual_review",
            "reason": "missing_model_token",
        },
        "coverage_contract": {
            "version": "coverage_contract_v1",
            "status": "pass",
            "critical_files_total": 1,
            "critical_files_covered": 1,
            "omitted_critical_files": [],
            "omitted_files_total": 0,
        },
        "case_file": {
            "version": "case_file_v1",
            "engine_decision": {
                "status": "classified",
                "label": "MINOR",
                "confidence": "high",
                "reasoning": "Deterministic findings.",
                "changelog": "feat: add exported api symbols",
            },
            "top_findings": [],
            "policy_effects": [],
            "coverage_flags": {},
            "evidence_summary": {},
            "notes": [],
        },
        "case_file_stats": {
            "token_budget": 1200,
            "estimated_input_tokens": 230,
            "findings_included": 2,
            "findings_omitted": 0,
        },
    }
    assert validate_output_contract(payload) == []


def test_validate_output_contract_rejects_path_only_rows_for_classified_payload() -> None:
    payload = {
        "output_contract_version": "v4",
        "status": "classified",
        "analysis_state": "authoritative",
        "classification_source": "court",
        "reasoning": "Court selected PATCH from accepted evidence records.",
        "label": "PATCH",
        "confidence": "medium",
        "changelog": "fix(core): update behavior in court.py",
        "decision_authority": "court",
        "deterministic_label": "PATCH",
        "deterministic_next_tag": "0.16.1",
        "advisory_status": "aligned",
        "advisory_label": "PATCH",
        "advisory_confidence": "medium",
        "explainability_rows": [
            {
                "path": "src/bumpkin/orchestrator/core.py",
                "rule": "changed_file_path",
                "action": "modified",
                "target": "court evidence handling",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            }
        ],
        "planner": {
            "version": "decision_contract_v3",
            "route": "full",
            "reason": "within_provider_budget",
        },
        "coverage_contract": {
            "version": "coverage_contract_v1",
            "status": "pass",
            "critical_files_total": 1,
            "critical_files_covered": 1,
            "omitted_critical_files": [],
            "omitted_files_total": 0,
        },
        "case_file": {
            "version": "case_file_v1",
            "engine_decision": {
                "status": "classified",
                "label": "PATCH",
                "confidence": "medium",
                "reasoning": "Deterministic patch findings.",
                "changelog": "fix(core): update behavior in court.py",
            },
            "top_findings": [],
            "policy_effects": [],
            "coverage_flags": {},
            "evidence_summary": {},
            "notes": [],
        },
        "case_file_stats": {
            "token_budget": 1200,
            "estimated_input_tokens": 230,
            "findings_included": 1,
            "findings_omitted": 0,
        },
    }
    errors = validate_output_contract(payload)
    assert any("semantic explainability_rows" in item for item in errors)


def test_validate_output_contract_rejects_invalid_court_evidence_ids() -> None:
    payload = {
        "output_contract_version": "v4",
        "status": "classified",
        "analysis_state": "authoritative",
        "classification_source": "court",
        "reasoning": "Court selected PATCH from accepted evidence records.",
        "label": "PATCH",
        "confidence": "medium",
        "changelog": "fix(core): update behavior in court.py",
        "decision_authority": "court",
        "deterministic_label": "PATCH",
        "deterministic_next_tag": "0.16.1",
        "advisory_status": "aligned",
        "advisory_label": "PATCH",
        "advisory_confidence": "medium",
        "explainability_rows": [
            {
                "path": "src/bumpkin/orchestrator/core.py",
                "rule": "changed_file_path",
                "action": "modified",
                "target": "court evidence handling",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            }
        ],
        "court_verdict": {
            "accepted_evidence_ids": "finding:f1",
            "rejected_evidence_ids": [],
        },
        "planner": {
            "version": "decision_contract_v3",
            "route": "full",
            "reason": "within_provider_budget",
        },
        "coverage_contract": {
            "version": "coverage_contract_v1",
            "status": "pass",
            "critical_files_total": 1,
            "critical_files_covered": 1,
            "omitted_critical_files": [],
            "omitted_files_total": 0,
        },
        "case_file": {
            "version": "case_file_v1",
            "engine_decision": {
                "status": "classified",
                "label": "PATCH",
                "confidence": "medium",
                "reasoning": "Deterministic patch findings.",
                "changelog": "fix(core): update behavior in court.py",
            },
            "top_findings": [],
            "policy_effects": [],
            "coverage_flags": {},
            "evidence_summary": {},
            "notes": [],
        },
        "case_file_stats": {
            "token_budget": 1200,
            "estimated_input_tokens": 230,
            "findings_included": 1,
            "findings_omitted": 0,
        },
    }
    errors = validate_output_contract(payload)
    assert any("court_verdict.accepted_evidence_ids" in item for item in errors)


def test_validate_output_contract_accepts_v5_payload_with_proof_obligations() -> None:
    payload = {
        "output_contract_version": "v5",
        "status": "classified",
        "analysis_state": "authoritative",
        "classification_source": "deterministic-findings",
        "reasoning": "Deterministic semantic facts proved a backward-compatible API addition.",
        "label": "MINOR",
        "confidence": "high",
        "changelog": "feat(api): add getUserProfile",
        "decision_authority": "court",
        "deterministic_label": "MINOR",
        "deterministic_next_tag": "0.17.0",
        "advisory_status": "aligned",
        "advisory_label": "MINOR",
        "advisory_confidence": "low",
        "explainability_rows": [
            {
                "path": "src/api/public.ts",
                "rule": "export_symbol_added",
                "action": "added",
                "target": "getUserProfile",
                "impact_scope": "public_api",
                "suggested_bump": "MINOR",
                "severity": "MINOR",
            }
        ],
        "semantic_facts": [
            {
                "path": "src/api/public.ts",
                "rule": "export_symbol_added",
                "action": "added",
                "target": "getUserProfile",
                "impact_scope": "public_api",
                "suggested_bump": "MINOR",
                "severity": "MINOR",
            }
        ],
        "proof_obligations": {
            "version": "proof_obligations_v1",
            "required": ["semantic_fact_present"],
            "satisfied": ["semantic_fact_present"],
            "missing": [],
            "critical_missing": [],
        },
        "reasoning_trace": [
            {
                "claim_id": "semantic:1",
                "evidence": {
                    "path": "src/api/public.ts",
                    "span": "unspecified",
                    "rule": "export_symbol_added",
                },
                "policy": {"id": "semantic.export_symbol_added", "effect": "suggested_bump=MINOR"},
                "impact": {
                    "statement": "getUserProfile: absent -> present",
                    "implied_bump": "MINOR",
                },
            }
        ],
        "contradictions": [],
        "planner": {
            "version": "decision_contract_v3",
            "route": "full",
            "reason": "within_provider_budget",
        },
        "coverage_contract": {
            "version": "coverage_contract_v1",
            "status": "pass",
            "critical_files_total": 1,
            "critical_files_covered": 1,
            "omitted_critical_files": [],
            "omitted_files_total": 0,
        },
        "case_file": {
            "version": "case_file_v1",
            "engine_decision": {
                "status": "classified",
                "label": "MINOR",
                "confidence": "high",
                "reasoning": "Deterministic findings.",
                "changelog": "feat: add exported api symbols",
            },
            "top_findings": [],
            "policy_effects": [],
            "coverage_flags": {},
            "evidence_summary": {},
            "notes": [],
        },
        "case_file_stats": {
            "token_budget": 1200,
            "estimated_input_tokens": 230,
            "findings_included": 1,
            "findings_omitted": 0,
        },
    }
    assert validate_output_contract(payload) == []


def test_validate_output_contract_rejects_v5_with_critical_missing_proofs() -> None:
    payload = {
        "output_contract_version": "v5",
        "status": "classified",
        "analysis_state": "authoritative",
        "classification_source": "deterministic-findings",
        "reasoning": "Deterministic semantic facts unavailable.",
        "label": "PATCH",
        "confidence": "low",
        "changelog": "fix: update runtime behavior",
        "decision_authority": "court",
        "deterministic_label": "PATCH",
        "deterministic_next_tag": "0.17.1",
        "advisory_status": "aligned",
        "advisory_label": "PATCH",
        "advisory_confidence": "low",
        "explainability_rows": [
            {
                "path": "src/internal/cache.ts",
                "rule": "internal_runtime_delta",
                "action": "changed",
                "target": "buildCacheKey",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
                "before": "old",
                "after": "new",
            }
        ],
        "semantic_facts": [
            {
                "path": "src/internal/cache.ts",
                "rule": "internal_runtime_delta",
                "action": "changed",
                "target": "buildCacheKey",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
                "before": "old",
                "after": "new",
            }
        ],
        "proof_obligations": {
            "version": "proof_obligations_v1",
            "required": ["semantic_fact_present", "runtime_delta_transition_present"],
            "satisfied": ["semantic_fact_present"],
            "missing": ["runtime_delta_transition_present"],
            "critical_missing": ["runtime_delta_transition_present"],
        },
        "reasoning_trace": [
            {
                "claim_id": "semantic:1",
                "evidence": {
                    "path": "src/internal/cache.ts",
                    "span": "unspecified",
                    "rule": "internal_runtime_delta",
                },
                "policy": {
                    "id": "semantic.internal_runtime_delta",
                    "effect": "suggested_bump=PATCH",
                },
                "impact": {
                    "statement": "buildCacheKey: old -> new",
                    "implied_bump": "PATCH",
                },
            }
        ],
        "contradictions": [],
        "planner": {
            "version": "decision_contract_v3",
            "route": "full",
            "reason": "within_provider_budget",
        },
        "coverage_contract": {
            "version": "coverage_contract_v1",
            "status": "pass",
            "critical_files_total": 0,
            "critical_files_covered": 0,
            "omitted_critical_files": [],
            "omitted_files_total": 0,
        },
        "case_file": {
            "version": "case_file_v1",
            "engine_decision": {
                "status": "classified",
                "label": "PATCH",
                "confidence": "low",
                "reasoning": "Deterministic findings.",
                "changelog": "fix: update runtime behavior",
            },
            "top_findings": [],
            "policy_effects": [],
            "coverage_flags": {},
            "evidence_summary": {},
            "notes": [],
        },
        "case_file_stats": {
            "token_budget": 1200,
            "estimated_input_tokens": 130,
            "findings_included": 1,
            "findings_omitted": 0,
        },
    }
    errors = validate_output_contract(payload)
    assert any("critical missing proof obligations" in item for item in errors)


def test_validate_output_contract_rejects_v5_without_reasoning_trace() -> None:
    payload = {
        "output_contract_version": "v5",
        "status": "classified",
        "analysis_state": "authoritative",
        "classification_source": "court",
        "reasoning": "Runtime change detected with semantic evidence.",
        "label": "PATCH",
        "confidence": "low",
        "changelog": "fix(core): update runtime behavior",
        "decision_authority": "court",
        "deterministic_label": "PATCH",
        "deterministic_next_tag": "1.2.4",
        "advisory_status": "aligned",
        "advisory_label": "PATCH",
        "advisory_confidence": "low",
        "explainability_rows": [
            {
                "path": "src/core.py",
                "rule": "internal_runtime_delta",
                "action": "changed",
                "target": "cache key",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            }
        ],
        "semantic_facts": [
            {
                "path": "src/core.py",
                "rule": "internal_runtime_delta",
                "action": "changed",
                "target": "cache key",
                "impact_scope": "runtime_internal",
                "suggested_bump": "PATCH",
                "severity": "PATCH",
            }
        ],
        "proof_obligations": {
            "version": "proof_obligations_v1",
            "required": ["semantic_fact_present"],
            "satisfied": ["semantic_fact_present"],
            "missing": [],
            "critical_missing": [],
        },
        "contradictions": [],
        "planner": {
            "version": "decision_contract_v3",
            "route": "full",
            "reason": "within_provider_budget",
        },
        "coverage_contract": {
            "version": "coverage_contract_v1",
            "status": "pass",
            "critical_files_total": 0,
            "critical_files_covered": 0,
            "omitted_critical_files": [],
            "omitted_files_total": 0,
        },
        "case_file": {
            "version": "case_file_v1",
            "engine_decision": {
                "status": "classified",
                "label": "PATCH",
                "confidence": "low",
                "reasoning": "Deterministic findings.",
                "changelog": "fix: update runtime behavior",
            },
            "top_findings": [],
            "policy_effects": [],
            "coverage_flags": {},
            "evidence_summary": {},
            "notes": [],
        },
        "case_file_stats": {
            "token_budget": 1200,
            "estimated_input_tokens": 140,
            "findings_included": 1,
            "findings_omitted": 0,
        },
    }
    errors = validate_output_contract(payload)
    assert any("reasoning_trace" in item for item in errors)

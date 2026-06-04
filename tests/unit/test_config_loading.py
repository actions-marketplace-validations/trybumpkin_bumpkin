from pathlib import Path

import pytest

from config import load_bumpkin_config


def test_load_bumpkin_config_defaults_when_missing(tmp_path: Path) -> None:
    cfg = load_bumpkin_config(tmp_path / "bumpkin.yml")
    assert cfg.ignore_paths == []
    assert cfg.surface_area == []
    assert cfg.public_api_entrypoints == []
    assert cfg.public_api_paths == []
    assert cfg.policy_mode == "pragmatic"
    assert cfg.bugfix_patch_bias is True
    assert cfg.use_difftastic is False
    assert cfg.semantic_fallback is True
    assert cfg.pre_1_0_breaking_as_minor is True
    assert cfg.docs_only_label == "NO_BUMP"
    assert cfg.large_pr_max_files == 30
    assert cfg.large_pr_max_tokens == 6000
    assert cfg.truncated_no_bump_policy == "MANUAL_REVIEW"
    assert cfg.chunking_enabled is True
    assert cfg.chunk_max_tokens == 1200
    assert cfg.chunk_max_count == 24
    assert cfg.chunk_failure_policy == "MANUAL_REVIEW"
    assert cfg.impact_evidence_threshold == "moderate"
    assert cfg.unknown_boundary_policy == "patch_if_bugfix"
    assert cfg.behavior_contract_policy == "path_signals"
    assert cfg.noise_suppression_policy == "balanced"
    assert cfg.override_governance_policy == "strict_audit"
    assert cfg.degraded_provider_policy == "MANUAL_REVIEW"
    assert cfg.decision_authority_mode == "court"


def test_load_bumpkin_config_reads_surface_area_and_ignores(tmp_path: Path) -> None:
    config_path = tmp_path / "bumpkin.yml"
    config_path.write_text(
        "ignore_paths:\n"
        "  - docs/\n"
        "surface_area:\n"
        "  - src/api/**\n"
        "  - src/public/index.ts\n"
        "public_api:\n"
        "  entrypoints:\n"
        "    - src/index.ts\n"
        "  paths:\n"
        "    - src/public/**\n"
        "policy_mode: strict_semver\n"
        "bugfix_patch_bias: false\n"
        "use_difftastic: true\n"
        "semantic_fallback: false\n"
        "pre_1_0_breaking_as_minor: false\n"
        "docs_only_label: patch\n"
        "large_pr_max_files: 45\n"
        "large_pr_max_tokens: 5000\n"
        "truncated_no_bump_policy: patch\n"
        "chunking_enabled: false\n"
        "chunk_max_tokens: 900\n"
        "chunk_max_count: 16\n"
        "chunk_failure_policy: patch\n"
        "impact_evidence_threshold: strict\n"
        "unknown_boundary_policy: manual_review\n"
        "behavior_contract_policy: path_signals\n"
        "noise_suppression_policy: strict\n"
        "override_governance_policy: severity_precedence\n"
        "degraded_provider_policy: patch\n"
        "decision_authority_mode: court\n"
    )
    cfg = load_bumpkin_config(config_path)
    assert cfg.ignore_paths == ["docs/"]
    assert cfg.surface_area == ["src/api/**", "src/public/index.ts"]
    assert cfg.public_api_entrypoints == ["src/index.ts"]
    assert cfg.public_api_paths == ["src/public/**"]
    assert cfg.policy_mode == "strict_semver"
    assert cfg.bugfix_patch_bias is False
    assert cfg.use_difftastic is True
    assert cfg.semantic_fallback is False
    assert cfg.pre_1_0_breaking_as_minor is False
    assert cfg.docs_only_label == "PATCH"
    assert cfg.large_pr_max_files == 45
    assert cfg.large_pr_max_tokens == 5000
    assert cfg.truncated_no_bump_policy == "PATCH"
    assert cfg.chunking_enabled is False
    assert cfg.chunk_max_tokens == 900
    assert cfg.chunk_max_count == 16
    assert cfg.chunk_failure_policy == "PATCH"
    assert cfg.impact_evidence_threshold == "strict"
    assert cfg.unknown_boundary_policy == "manual_review"
    assert cfg.behavior_contract_policy == "path_signals"
    assert cfg.noise_suppression_policy == "strict"
    assert cfg.override_governance_policy == "severity_precedence"
    assert cfg.degraded_provider_policy == "PATCH"
    assert cfg.decision_authority_mode == "court"


def test_load_bumpkin_config_rejects_invalid_surface_area(tmp_path: Path) -> None:
    config_path = tmp_path / "bumpkin.yml"
    config_path.write_text("surface_area: 123\n")
    with pytest.raises(ValueError):
        load_bumpkin_config(config_path)


def test_load_bumpkin_config_rejects_invalid_use_difftastic(tmp_path: Path) -> None:
    config_path = tmp_path / "bumpkin.yml"
    config_path.write_text("use_difftastic: maybe\n")
    with pytest.raises(ValueError):
        load_bumpkin_config(config_path)


def test_load_bumpkin_config_rejects_invalid_semantic_fallback(tmp_path: Path) -> None:
    config_path = tmp_path / "bumpkin.yml"
    config_path.write_text("semantic_fallback: maybe\n")
    with pytest.raises(ValueError):
        load_bumpkin_config(config_path)


def test_load_bumpkin_config_rejects_invalid_docs_only_label(tmp_path: Path) -> None:
    config_path = tmp_path / "bumpkin.yml"
    config_path.write_text("docs_only_label: major\n")
    with pytest.raises(ValueError):
        load_bumpkin_config(config_path)


def test_load_bumpkin_config_rejects_invalid_policy_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "bumpkin.yml"
    config_path.write_text("policy_mode: experimental\n")
    with pytest.raises(ValueError):
        load_bumpkin_config(config_path)


def test_load_bumpkin_config_rejects_invalid_public_api_shape(tmp_path: Path) -> None:
    config_path = tmp_path / "bumpkin.yml"
    config_path.write_text("public_api: true\n")
    with pytest.raises(ValueError):
        load_bumpkin_config(config_path)


def test_load_bumpkin_config_rejects_invalid_large_pr_max_files(tmp_path: Path) -> None:
    config_path = tmp_path / "bumpkin.yml"
    config_path.write_text("large_pr_max_files: 0\n")
    with pytest.raises(ValueError):
        load_bumpkin_config(config_path)


def test_load_bumpkin_config_rejects_invalid_truncated_policy(tmp_path: Path) -> None:
    config_path = tmp_path / "bumpkin.yml"
    config_path.write_text("truncated_no_bump_policy: major\n")
    with pytest.raises(ValueError):
        load_bumpkin_config(config_path)


def test_load_bumpkin_config_rejects_invalid_chunk_failure_policy(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "bumpkin.yml"
    config_path.write_text("chunk_failure_policy: major\n")
    with pytest.raises(ValueError):
        load_bumpkin_config(config_path)


def test_load_bumpkin_config_rejects_invalid_impact_evidence_threshold(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "bumpkin.yml"
    config_path.write_text("impact_evidence_threshold: ultra\n")
    with pytest.raises(ValueError):
        load_bumpkin_config(config_path)


def test_load_bumpkin_config_rejects_invalid_unknown_boundary_policy(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "bumpkin.yml"
    config_path.write_text("unknown_boundary_policy: maybe\n")
    with pytest.raises(ValueError):
        load_bumpkin_config(config_path)


def test_load_bumpkin_config_rejects_invalid_behavior_contract_policy(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "bumpkin.yml"
    config_path.write_text("behavior_contract_policy: enabled\n")
    with pytest.raises(ValueError):
        load_bumpkin_config(config_path)


def test_load_bumpkin_config_rejects_invalid_noise_suppression_policy(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "bumpkin.yml"
    config_path.write_text("noise_suppression_policy: maybe\n")
    with pytest.raises(ValueError):
        load_bumpkin_config(config_path)


def test_load_bumpkin_config_rejects_invalid_override_governance_policy(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "bumpkin.yml"
    config_path.write_text("override_governance_policy: allow_all\n")
    with pytest.raises(ValueError):
        load_bumpkin_config(config_path)


def test_load_bumpkin_config_rejects_invalid_degraded_provider_policy(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "bumpkin.yml"
    config_path.write_text("degraded_provider_policy: minor\n")
    with pytest.raises(ValueError):
        load_bumpkin_config(config_path)


def test_load_bumpkin_config_rejects_invalid_decision_authority_mode(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "bumpkin.yml"
    config_path.write_text("decision_authority_mode: maybe\n")
    with pytest.raises(ValueError):
        load_bumpkin_config(config_path)

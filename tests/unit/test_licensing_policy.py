from __future__ import annotations

import pytest

from bumpkin.licensing.policy import (
    LicenseCheckResult,
    enforce_license_boundary,
    is_capability_allowed,
    resolve_license_policy,
)


def test_resolve_license_policy_defaults_to_oss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BUMPKIN_LICENSE_TIER", raising=False)
    monkeypatch.delenv("BUMPKIN_EDITION", raising=False)

    policy = resolve_license_policy()
    assert policy.tier == "oss"
    assert policy.allow_publish_automation is False


def test_resolve_license_policy_accepts_aliases() -> None:
    policy = resolve_license_policy("open_source")
    assert policy.tier == "oss"

    policy = resolve_license_policy("pro")
    assert policy.tier == "commercial"


def test_resolve_license_policy_rejects_unknown_tier() -> None:
    with pytest.raises(ValueError, match="Unknown license tier"):
        resolve_license_policy("enterprise")


def test_is_capability_allowed_checks_matrix() -> None:
    oss = resolve_license_policy("oss")
    commercial = resolve_license_policy("commercial")

    assert is_capability_allowed(oss, "analysis_engine") is True
    assert is_capability_allowed(oss, "publish_automation") is False
    assert is_capability_allowed(commercial, "publish_automation") is True


def test_enforce_license_boundary_blocks_disallowed_capability() -> None:
    result = enforce_license_boundary(resolve_license_policy("oss"), "publish_automation")

    assert isinstance(result, LicenseCheckResult)
    assert result.allowed is False
    assert result.reason == "capability_not_included:publish_automation"


def test_enforce_license_boundary_blocks_private_commercial_oss_use() -> None:
    result = enforce_license_boundary(
        resolve_license_policy("oss"),
        "app_control_events",
        repository_visibility="private",
        commercial_intent=True,
    )

    assert result.allowed is False
    assert result.reason == "commercial_private_usage_requires_commercial_tier"


def test_enforce_license_boundary_allows_commercial_tier() -> None:
    result = enforce_license_boundary(
        resolve_license_policy("commercial"),
        "publish_automation",
        repository_visibility="private",
        commercial_intent=True,
    )

    assert result.allowed is True
    assert result.reason is None

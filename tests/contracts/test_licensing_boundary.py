from __future__ import annotations

from bumpkin.licensing.policy import (
    SUPPORTED_CAPABILITIES,
    SUPPORTED_LICENSE_TIERS,
    enforce_license_boundary,
    resolve_license_policy,
)


def test_license_tier_inventory_is_locked() -> None:
    assert SUPPORTED_LICENSE_TIERS == ("oss", "commercial")


def test_license_capability_inventory_is_locked() -> None:
    assert SUPPORTED_CAPABILITIES == (
        "analysis_engine",
        "app_control_events",
        "publish_automation",
        "org_policy_ui",
        "managed_operations",
    )


def test_oss_publish_boundary_is_enforced() -> None:
    policy = resolve_license_policy("oss")
    assert policy.allow_publish_automation is False

    commercial = resolve_license_policy("commercial")
    assert commercial.allow_publish_automation is True


def test_private_commercial_use_requires_commercial_tier() -> None:
    oss = resolve_license_policy("oss")
    allowed = enforce_license_boundary(
        oss,
        "app_control_events",
        repository_visibility="private",
        commercial_intent=True,
    )
    assert allowed.allowed is False
    assert allowed.reason == "commercial_private_usage_requires_commercial_tier"

    commercial = resolve_license_policy("commercial")
    allowed = enforce_license_boundary(
        commercial,
        "app_control_events",
        repository_visibility="private",
        commercial_intent=True,
    )
    assert allowed.allowed is True
    assert allowed.reason is None

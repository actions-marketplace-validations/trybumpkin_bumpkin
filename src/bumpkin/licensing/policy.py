from __future__ import annotations

import os
from dataclasses import dataclass

SUPPORTED_LICENSE_TIERS = ("oss", "commercial")
SUPPORTED_CAPABILITIES = (
    "analysis_engine",
    "app_control_events",
    "publish_automation",
    "org_policy_ui",
    "managed_operations",
)

_TIER_ALIASES = {
    "oss": "oss",
    "open-source": "oss",
    "opensource": "oss",
    "open_source": "oss",
    "commercial": "commercial",
    "pro": "commercial",
    "paid": "commercial",
}

_TIER_CAPABILITIES = {
    "oss": frozenset({"analysis_engine", "app_control_events"}),
    "commercial": frozenset(SUPPORTED_CAPABILITIES),
}


@dataclass(frozen=True, slots=True)
class LicensePolicy:
    tier: str
    capabilities: frozenset[str]

    @property
    def allow_publish_automation(self) -> bool:
        return "publish_automation" in self.capabilities


@dataclass(frozen=True, slots=True)
class LicenseCheckResult:
    allowed: bool
    reason: str | None = None


def _normalize_tier(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    if not normalized:
        return "oss"
    tier = _TIER_ALIASES.get(normalized)
    if tier is None:
        raise ValueError(f"Unknown license tier: {value!r}")
    return tier


def resolve_license_policy(tier: str | None = None) -> LicensePolicy:
    configured_tier = tier or os.getenv("BUMPKIN_LICENSE_TIER") or os.getenv("BUMPKIN_EDITION")
    normalized_tier = _normalize_tier(configured_tier)
    return LicensePolicy(
        tier=normalized_tier,
        capabilities=_TIER_CAPABILITIES[normalized_tier],
    )


def is_capability_allowed(policy: LicensePolicy, capability: str) -> bool:
    normalized = str(capability).strip().lower()
    if normalized not in SUPPORTED_CAPABILITIES:
        raise ValueError(f"Unknown capability: {capability!r}")
    return normalized in policy.capabilities


def enforce_license_boundary(
    policy: LicensePolicy,
    capability: str,
    *,
    repository_visibility: str = "public",
    commercial_intent: bool = False,
) -> LicenseCheckResult:
    if not is_capability_allowed(policy, capability):
        return LicenseCheckResult(
            allowed=False,
            reason=f"capability_not_included:{capability}",
        )

    normalized_visibility = str(repository_visibility).strip().lower()
    if policy.tier == "oss" and normalized_visibility == "private" and commercial_intent:
        return LicenseCheckResult(
            allowed=False,
            reason="commercial_private_usage_requires_commercial_tier",
        )

    return LicenseCheckResult(allowed=True, reason=None)

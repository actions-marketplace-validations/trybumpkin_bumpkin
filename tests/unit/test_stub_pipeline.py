# pyright: reportMissingImports=false
import pytest

from llm import (
    LLMResponseError,
    get_no_bump_recommendation,
    get_stub_recommendation,
    validate_recommendation,
)
from version import bump_semver


def test_stub_recommendation_shape() -> None:
    out = get_stub_recommendation(truncated=False)
    assert out["status"] == "classified"
    assert out["label"] == "PATCH"
    assert "reasoning" in out
    assert "changelog" in out


def test_no_bump_recommendation_shape() -> None:
    out = get_no_bump_recommendation(truncated=False)
    assert out["status"] == "classified"
    assert out["label"] == "NO_BUMP"
    assert out["confidence"] == "high"
    assert "reasoning" in out
    assert "changelog" in out


def test_semver_helper() -> None:
    assert bump_semver("1.2.3", "PATCH") == "1.2.4"
    assert bump_semver("1.2.3", "MINOR") == "1.3.0"
    assert bump_semver("1.2.3", "MAJOR") == "2.0.0"
    assert bump_semver("1.2.3", "NO_BUMP") == "1.2.3"


def test_validate_recommendation_accepts_valid_payload() -> None:
    parsed = validate_recommendation(
        {
            "label": "minor",
            "confidence": "high",
            "reasoning": "Added new exported function getUserProfile in src/api.js.",
            "changelog": "feat: add getUserProfile API",
        }
    )
    assert parsed["label"] == "MINOR"
    assert parsed["confidence"] == "high"


def test_validate_recommendation_accepts_no_bump_payload() -> None:
    parsed = validate_recommendation(
        {
            "label": "NO_BUMP",
            "confidence": "high",
            "reasoning": "Only docs and configuration metadata changed with no runtime API impact.",
            "changelog": "chore: no release required",
        }
    )
    assert parsed["label"] == "NO_BUMP"


def test_validate_recommendation_rejects_invalid_label() -> None:
    with pytest.raises(LLMResponseError):
        validate_recommendation(
            {
                "label": "breaking",
                "confidence": "high",
                "reasoning": "Removed a public method from API surface in src/api.js.",
                "changelog": "feat: remove old method",
            }
        )

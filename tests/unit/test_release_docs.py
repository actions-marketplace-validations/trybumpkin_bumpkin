from __future__ import annotations

from pathlib import Path


def test_readme_frames_release_scoped_flow_as_primary_story() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    readme = (repo_root / "README.md").read_text(encoding="utf-8")

    assert "no always-on server required" in readme
    assert "no Bumpkin database required" in readme
    assert "release_preview" in readme
    assert "release_publish" in readme
    assert "python -m bumpkin.release_job" in readme
    assert "Bumpkin is provider-agnostic." in readme
    assert "BUMPKIN_MODEL" in readme
    assert "BUMPKIN_MODELS_ENDPOINT" in readme
    assert "Gemini OpenAI-compatible endpoint" in readme
    assert "needs_review" in readme
    assert "does not post PR comments in the release-scoped flow" in readme
    assert "Marketplace-style Action repo" in readme
    assert "scripts/export_marketplace_action_repo.py" in readme
    assert "published from this development repo's verified export shape" in readme
    assert "ROADMAP.md" in readme


def test_internal_markdown_is_gitignored() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8")

    assert "*.md" in gitignore
    assert "!README.md" in gitignore
    assert "!CHANGELOG.md" in gitignore
    assert "!SECURITY.md" in gitignore


def test_env_example_marks_app_runtime_as_optional() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env_example = (repo_root / ".env.example").read_text(encoding="utf-8")

    assert "BUMPKIN_MODEL=openai/gpt-4.1-mini" in env_example
    assert "BUMPKIN_FALLBACK_MODEL=" in env_example
    assert "BUMPKIN_MODELS_ENDPOINT=" in env_example
    assert "BUMPKIN_APP_MODE=shell" not in env_example

def test_marketplace_action_template_exists() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    action_readme = (
        repo_root / "scripts" / "templates" / "marketplace_action_readme.template"
    ).read_text(encoding="utf-8")

    assert "# Bumpkin Action" in action_readme


def test_roadmap_is_public_and_mentions_language_expansion() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8")
    roadmap = (repo_root / "ROADMAP.md").read_text(encoding="utf-8")

    assert "!ROADMAP.md" in gitignore
    assert "Better support for Python" in roadmap
    assert "Go" in roadmap
    assert "Rust" in roadmap
    assert "Java/Kotlin" in roadmap

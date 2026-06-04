from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_export_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "export_marketplace_action_repo.py"
    spec = importlib.util.spec_from_file_location("marketplace_export", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_export_marketplace_action_repo_creates_trimmed_repo(tmp_path) -> None:
    module = _load_export_module()

    output_dir = module.export_marketplace_action_repo(output_dir=tmp_path / "marketplace")

    assert (output_dir / "action.yml").exists()
    assert (output_dir / ".gitignore").exists()
    assert (output_dir / "README.md").exists()
    assert (output_dir / "requirements.txt").exists()
    assert (output_dir / "src" / "release_job.py").exists()
    assert (output_dir / "src" / "bumpkin" / "github" / "recommendations.py").exists()

    assert not (output_dir / ".github").exists()
    assert not (output_dir / "experimental").exists()
    assert not (output_dir / "src" / "bumpkin" / "app").exists()
    assert not (output_dir / "src" / "bumpkin" / "eval").exists()

    readme = (output_dir / "README.md").read_text(encoding="utf-8")
    assert "# Bumpkin Action" in readme

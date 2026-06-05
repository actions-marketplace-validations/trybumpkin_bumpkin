from __future__ import annotations

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "marketplace-action-repo"

FILE_EXPORTS: tuple[tuple[str, str], ...] = (
    ("scripts/templates/marketplace_action_gitignore.template", ".gitignore"),
    ("action.yml", "action.yml"),
    ("LICENSE", "LICENSE"),
    ("SECURITY.md", "SECURITY.md"),
    ("requirements.txt", "requirements.txt"),
    ("bumpkin.yml.example", "bumpkin.yml.example"),
    ("scripts/templates/marketplace_action_readme.template", "README.md"),
    ("src/main.py", "src/main.py"),
    ("src/release_job.py", "src/release_job.py"),
)

PACKAGE_EXCLUDE_DIRS = frozenset({"app", "eval", "__pycache__"})


def _copy_file(*, src_root: Path, output_dir: Path, source_rel: str, dest_rel: str) -> None:
    source_path = src_root / source_rel
    destination_path = output_dir / dest_rel
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination_path)


def _copy_package_tree(*, src_root: Path, output_dir: Path) -> None:
    package_root = src_root / "src" / "bumpkin"
    destination_root = output_dir / "src" / "bumpkin"
    for path in package_root.rglob("*"):
        relative = path.relative_to(package_root)
        if any(part in PACKAGE_EXCLUDE_DIRS for part in relative.parts):
            continue
        destination_path = destination_root / relative
        if path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
            continue
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination_path)


def export_marketplace_action_repo(*, output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for source_rel, dest_rel in FILE_EXPORTS:
        _copy_file(
            src_root=REPO_ROOT,
            output_dir=output_dir,
            source_rel=source_rel,
            dest_rel=dest_rel,
        )
    _copy_package_tree(src_root=REPO_ROOT, output_dir=output_dir)
    return output_dir


def main() -> int:
    output_dir = export_marketplace_action_repo()
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import ast
from pathlib import Path

SHIM_FILES = {
    "src/config.py",
    "src/findings.py",
    "src/impact.py",
    "src/language.py",
    "src/prompt_pack.py",
    "src/token_env.py",
}


def _is_docstring_expr(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def test_compat_shims_stay_thin_and_forward_only() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    violations: list[str] = []

    for rel_path in sorted(SHIM_FILES):
        module = ast.parse((repo_root / rel_path).read_text(encoding="utf-8"))
        has_bumpkin_forward_import = False
        for node in module.body:
            if _is_docstring_expr(node):
                continue
            if isinstance(node, ast.ImportFrom):
                if node.module == "__future__":
                    continue
                if node.module and node.module.startswith("bumpkin."):
                    has_bumpkin_forward_import = True
                    continue
                violations.append(f"{rel_path}: non-bumpkin forward import from {node.module!r}")
                continue
            if isinstance(node, ast.Assign):
                if any(
                    isinstance(target, ast.Name) and target.id == "__all__"
                    for target in node.targets
                ):
                    continue
                violations.append(f"{rel_path}: unexpected assignment")
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                violations.append(f"{rel_path}: defines runtime symbol {node.__class__.__name__}")
                continue
            violations.append(f"{rel_path}: unexpected node {node.__class__.__name__}")

        if not has_bumpkin_forward_import:
            violations.append(f"{rel_path}: missing bumpkin.* forwarding import")

    assert not violations, "Compatibility shim policy violated:\n" + "\n".join(violations)

"""Enforce the package's one-way API and business-logic boundaries."""

from __future__ import annotations

import ast
from pathlib import Path


PACKAGE = Path(__file__).parents[1] / "src" / "sarj_lint_configs"
REPOSITORY = Path(__file__).parents[3]


def test_top_level_domain_modules_are_compatibility_only() -> None:
    allowed = {"__init__.py", "__main__.py", "_meta.py", "api.py"}
    modules = [path for path in PACKAGE.glob("*.py") if path.name not in allowed]

    assert modules
    assert all("Compatibility alias" in path.read_text(encoding="utf-8") for path in modules)


def test_business_libraries_never_import_cli_or_public_facade() -> None:
    violations: list[str] = []
    for path in (PACKAGE / "libs").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations.extend(
            f"{path.relative_to(PACKAGE)}:{node.lineno}"
            for node in ast.walk(tree)
            if (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and node.module.startswith(("sarj_lint_configs.cli", "sarj_lint_configs.api"))
            )
        )

    assert violations == []


def test_release_automation_has_no_standalone_scripts() -> None:
    scripts = REPOSITORY / ".github" / "scripts"

    assert not list(scripts.glob("*.mjs"))

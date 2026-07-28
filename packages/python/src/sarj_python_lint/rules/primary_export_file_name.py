"""SARJ075: Rename a Python module stem to match its primary public export.

Semantic File Naming Rule:
When a Python module has a single primary public export (a sole top-level `class`
or `def`), its filename stem should semantically reflect that export's name in
`snake_case`.

Examples:
  - File `user_data.py` containing sole `class UserAccountService:` -> rename to `user_account_service.py`.
  - File `score_stuff.py` containing sole `def calculate_user_score():` -> rename to `calculate_user_score.py`.

Exemptions:
  - Framework convention filenames (`models.py`, `views.py`, `urls.py`, `settings.py`, `admin.py`, `serializers.py`, `base.py`).
  - Dunder & entrypoint files (`__init__.py`, `conftest.py`, `__main__.py`).
  - Test files (`test_*.py`, `*_test.py`, `is_test_path`).
  - Generated source files (`is_generated_source`).
  - Modules with multiple public classes/functions or public `UPPER_SNAKE` constants.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_generated_source, is_test_path

if TYPE_CHECKING:
    from pathlib import Path


_SKIPPED_FILENAMES = frozenset({"__init__.py", "conftest.py", "__main__.py"})

_FRAMEWORK_CONVENTION_FILENAMES = frozenset(
    {
        "models.py",
        "admin.py",
        "apps.py",
        "views.py",
        "urls.py",
        "forms.py",
        "serializers.py",
        "base.py",
        "settings.py",
        "conftest.py",
        "__main__.py",
        "__init__.py",
        "middleware.py",
        "tasks.py",
        "signals.py",
        "routing.py",
    }
)

_ACRONYM_OVERRIDES: dict[str, str] = {"OAuth": "Oauth", "GraphQL": "Graphql", "gRPC": "Grpc"}
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _snake_case(name: str) -> str:
    for camel, replacement in _ACRONYM_OVERRIDES.items():
        name = name.replace(camel, replacement)
    return _CAMEL_BOUNDARY_RE.sub("_", name).lower()


def _has_public_constant(tree: ast.Module) -> bool:
    targets: list[ast.expr] = []
    for stmt in tree.body:
        match stmt:
            case ast.Assign(targets=assigned):
                targets.extend(assigned)
            case ast.AnnAssign(target=target):
                targets.append(target)
            case _:
                pass
    return any(
        isinstance(t, ast.Name) and not t.id.startswith("_") and t.id == t.id.upper() and any(c.isalpha() for c in t.id)
        for t in targets
    )


class PrimaryExportFileName(Rule):
    """Rename a Python module stem to match its sole primary public class/def export."""

    id: str = "primary-export-file-name"
    code: str = "SARJ075"
    description: str = "A module with a single primary public export should be named after that export."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix not in (".py", ".pyi"):
            return []
        if path.name in _SKIPPED_FILENAMES or path.name.lower() in _FRAMEWORK_CONVENTION_FILENAMES:
            return []
        if is_test_path(path) or is_generated_source(source):
            return []

        tree = parse_or_none(path, source)
        if tree is None:
            return []

        public_defs = [
            node
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
        ]
        if len(public_defs) != 1 or _has_public_constant(tree):
            return []

        primary = public_defs[0]
        expected_stem = _snake_case(primary.name)
        if path.stem == expected_stem:
            return []

        return [
            Diagnostic(
                path=path,
                line=primary.lineno,
                col=primary.col_offset + 1,
                code=self.code,
                message=(
                    f"module stem `{path.stem}` does not match its primary public "
                    f"export `{primary.name}` — rename the file to `{expected_stem}.py` to "
                    f"describe its responsibility."
                ),
            )
        ]

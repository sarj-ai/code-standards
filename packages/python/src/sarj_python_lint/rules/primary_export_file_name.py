"""SARJ075: Rename a Python module stem to match its primary public export.

Semantic File Naming Rule:
When a Python module has a single primary public export (a sole top-level `class`
or `def`), its filename stem should semantically reflect that export's name in
`snake_case`.

Examples:
  - File `user_data.py` containing sole `class UserAccountService:` -> rename to `user_account_service.py`.
  - File `score_stuff.py` containing sole `def calculate_user_score():` -> rename to `calculate_user_score.py`.

Exemptions (Corpus-validated against noura-be, bulbul, fastapi, requests, pydantic, flask, trio):
  - Framework convention filenames (`models.py`, `views.py`, `urls.py`, `settings.py`, `config.py`, `errors.py`, `exceptions.py`, `admin.py`, `serializers.py`, `base.py`).
  - Dunder & entrypoint files (`__init__.py`, `conftest.py`, `__main__.py`, `main.py`).
  - Test and documentation paths (`test_*.py`, `*_test.py`, `docs/`, `docs_src/`, `examples/`, `tutorials/`).
  - Private modules starting with `_` (`_signature.py`).
  - Entrypoint functions (`main`, `run`, `cli`, `setup`, `teardown`, `execute`, `asyncio_detailed`, `sync_detailed`).
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


_SKIPPED_FILENAMES = frozenset({"__init__.py", "conftest.py", "__main__.py", "main.py"})

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
        "config.py",
        "configuration.py",
        "errors.py",
        "exceptions.py",
        "conftest.py",
        "__main__.py",
        "__init__.py",
        "main.py",
        "middleware.py",
        "tasks.py",
        "signals.py",
        "routing.py",
    }
)

_GENERIC_ENTRYPOINT_FUNCTIONS = frozenset(
    {"main", "run", "cli", "setup", "teardown", "execute", "asyncio_detailed", "sync_detailed"}
)

_DOCS_OR_EXAMPLES_PATTERN = re.compile(r"[/\\](docs|docs_src|examples|tutorials|samples)[/\\]|tutorial\d*|example\d*")

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
        if path.suffix not in {".py", ".pyi"}:
            return []
        if path.name in _SKIPPED_FILENAMES or path.name.lower() in _FRAMEWORK_CONVENTION_FILENAMES:
            return []
        if path.stem.startswith("_"):
            return []
        if is_test_path(path) or is_generated_source(source):
            return []
        if _DOCS_OR_EXAMPLES_PATTERN.search(str(path)):
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
        if primary.name in _GENERIC_ENTRYPOINT_FUNCTIONS:
            return []

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

"""SARJ022 — Rename a junk-drawer module stem with a single public export.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_single_public_export.py
Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/SARJ022.md
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_SKIPPED_FILENAMES = frozenset({"__init__.py", "conftest.py"})

# Filenames whose stem is fixed by a framework or tool convention and therefore
# cannot be renamed without breaking discovery: Django reads models/views/urls/
# admin/apps/forms/settings/middleware/signals by filename, DRF `serializers.py`,
# Channels `routing.py`, Celery `tasks.py`, pytest `conftest.py`, `__main__.py`.
# Even when the stem is also a junk-drawer name (`models.py`, `base.py`), the
# rename the rule would suggest is not actionable, so these are never flagged.
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

# Generic module stems that describe no responsibility. Curated conservatively:
# every entry is a name that, standing alone as a module, tells a reader nothing
# about what lives inside. Idiomatic domain stems (pagination, retry, warmup,
# client, service, ...) are deliberately excluded.
_JUNK_DRAWER_STEMS = frozenset(
    {
        "base",
        "common",
        "constant",
        "constants",
        "core",
        "enum",
        "enums",
        "helper",
        "helpers",
        "misc",
        "model",
        "models",
        "shared",
        "stuff",
        "type",
        "types",
        "util",
        "utils",
    }
)

# Multi-word acronyms whose community-accepted snake_case is a single token
# rather than the letter-by-letter split (`OAuth` -> `oauth`, not `o_auth`).
_ACRONYM_OVERRIDES: dict[str, str] = {"OAuth": "Oauth", "GraphQL": "Graphql", "gRPC": "Grpc"}

# Split on camelCase boundaries while keeping runs of capitals (acronyms)
# together: `HTTPServer` -> `HTTP` + `Server`, `JWTHandler` -> `JWT` + `Handler`.
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


class SinglePublicExport(Rule):
    id: str = "single-public-export"
    code: str = "SARJ022"
    has_evidence: bool = True
    description: str = "A junk-drawer module with a single public def/class should be renamed after that export."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        if _is_skipped_path(path):
            return []
        if path.stem.lower() not in _JUNK_DRAWER_STEMS:
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
                    f"module stem `{path.stem}` is a generic junk-drawer name; its sole public "
                    f"export is `{primary.name}` — rename the file to `{expected_stem}.py` to "
                    f"describe its responsibility."
                ),
            )
        ]


def _has_public_constant(tree: ast.Module) -> bool:
    """Report whether the module exports a public `UPPER_SNAKE` constant."""
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


def _snake_case(name: str) -> str:
    for camel, replacement in _ACRONYM_OVERRIDES.items():
        name = name.replace(camel, replacement)
    return _CAMEL_BOUNDARY_RE.sub("_", name).lower()


def _is_skipped_path(path: Path) -> bool:
    if path.name in _SKIPPED_FILENAMES:
        return True
    if path.name.lower() in _FRAMEWORK_CONVENTION_FILENAMES:
        return True
    if path.name.startswith("test_"):
        return True
    return "tests" in path.parts

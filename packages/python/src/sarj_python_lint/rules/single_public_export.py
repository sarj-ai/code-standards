"""SARJ022 — Rename a junk-drawer module stem with a single public export.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_single_public_export.py
"""

from __future__ import annotations

import ast
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_SKIPPED_FILENAMES = frozenset({"__init__.py", "conftest.py"})

# Framework-owned filenames cannot take the rename this rule would otherwise require.
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

# Generic module stems that describe no responsibility.
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
_ACRONYM_OVERRIDES = MappingProxyType({"OAuth": "Oauth", "GraphQL": "Graphql", "gRPC": "Grpc"})

# Split on camelCase boundaries while keeping runs of capitals (acronyms)
# together: `HTTPServer` -> `HTTP` + `Server`, `JWTHandler` -> `JWT` + `Handler`.
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


class SinglePublicExport(Rule):
    id: str = "single-public-export"
    code: str = "SARJ022"
    description: str = (
        "A generic-named module with exactly one public top-level function/class and no public constants "
        "should be renamed after that export."
    )

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
        if len(public_defs) != 1 or _has_additional_public_export(tree):
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


def _has_additional_public_export(tree: ast.Module) -> bool:
    """Report whether a definition is not the module's only public export."""
    if _has_multiple_static_all_names(tree):
        return True
    targets: list[ast.expr] = []
    for stmt in tree.body:
        match stmt:
            case ast.TypeAlias(name=ast.Name(id=name)) if not name.startswith("_"):
                return True
            case ast.Assign(targets=assigned):
                targets.extend(assigned)
            case ast.AnnAssign(target=target):
                if (
                    isinstance(target, ast.Name)
                    and not target.id.startswith("_")
                    and _annotation_name(stmt.annotation) == "TypeAlias"
                ):
                    return True
                targets.append(target)
            case _:
                pass
    assigned_names = (node for target in targets for node in ast.walk(target) if isinstance(node, ast.Name))
    return any(
        not name.id.startswith("_") and name.id == name.id.upper() and any(c.isalpha() for c in name.id)
        for name in assigned_names
    )


def _has_multiple_static_all_names(tree: ast.Module) -> bool:
    """Report a literal ``__all__`` that exposes more than one name."""
    for stmt in tree.body:
        value: ast.expr | None = None
        match stmt:
            case ast.Assign(targets=targets, value=assigned) if any(
                isinstance(target, ast.Name) and target.id == "__all__" for target in targets
            ):
                value = assigned
            case ast.AnnAssign(target=ast.Name(id="__all__"), value=assigned):
                value = assigned
            case _:
                continue
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            names = [elt.value for elt in value.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)]
            if len(names) == len(value.elts) and len(names) > 1:
                return True
    return False


def _annotation_name(node: ast.expr) -> str:
    """Return the final component of an annotation name."""
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return ""


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

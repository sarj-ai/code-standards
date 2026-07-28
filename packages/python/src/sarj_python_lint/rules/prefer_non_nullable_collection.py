"""SARJ074: prefer non-null list fields in declared data shapes.

Nullable list fields create two representations of an empty collection: ``None``
and ``[]``. When the project convention is that absence means empty, every
consumer inherits an unnecessary nullable type and null guard.

    # flagged
    class CallSettings(BaseModel):
        organization_ids: list[OrganizationId] | None = None

    # preferred when omission means "empty"
    class CallSettings(BaseModel):
        organization_ids: list[OrganizationId] = Field(default_factory=list)

The rule applies to annotated fields on every class data shape, including
Pydantic models, dataclasses, attrs classes, and ordinary typed classes. It does
not inspect function defaults: ``None`` is the safe Python idiom there because
``[]`` would be shared mutable state. Tests and generated sources are exempt.
``Optional[list[T]]`` and ``Union[list[T], None]`` are recognized alongside PEP
604 unions. A field is reported whether it defaults to ``None``, uses
``Field(default=None)``, or has no default at all.

This is an opinionated application convention, not a Python type-system fact.
When ``None`` is a meaningful third state (for example, "inherit this
constraint" rather than "allow no values"), keep the union and suppress the
line with ``# sarj-noqa: SARJ074 — None means ...``.

Corpus sweep (2026-07-27): FastAPI, Pydantic, SQLModel, Zod, and React Router;
2,901 Python/TypeScript files total. The final rule reported 30 explicit Python
nullable-list fields. Every match had the advertised AST shape; the sweep also
confirmed the meaningful-third-state suppression boundary on public framework
contracts such as Pydantic's ``UrlConstraints.allowed_schemes``.

"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_generated_source, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_UNION_NAMES = frozenset({"Optional", "Union"})


class PreferNonNullableCollection(Rule):
    """Nullable list field -- use a non-null list with an empty default."""

    id: str = "prefer-non-nullable-collection"
    code: str = "SARJ074"
    description: str = (
        "List fields should use a non-null list and an empty default instead of two equivalent empty states."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path) or _is_generated_or_vendored_path(path) or is_generated_source(source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags: list[Diagnostic] = []
        for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            for statement in cls.body:
                if not isinstance(statement, ast.AnnAssign):
                    continue
                if not isinstance(statement.target, ast.Name):
                    continue
                if not _is_nullable_list(statement.annotation):
                    continue
                name = statement.target.id
                diags.append(
                    Diagnostic(
                        path=path,
                        line=statement.lineno,
                        col=statement.col_offset + 1,
                        code=self.code,
                        message=(
                            f"`{name}` is a nullable list field, so `None` and `[]` "
                            "represent the same empty collection; use a non-null list "
                            "with `Field(default_factory=list)` / "
                            "`field(default_factory=list)` (or make it required)."
                        ),
                    )
                )
        return diags


def _is_generated_or_vendored_path(path: Path) -> bool:
    return any(part.lower() in {"generated", "vendor", "vendored"} for part in path.parts)


def _qualified_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Subscript):
        return _qualified_name(node.value)
    return ""


def _is_nullable_list(annotation: ast.expr) -> bool:
    members = _union_members(annotation)
    if members is None:
        return False
    non_none = [member for member in members if not _is_none_type(member)]
    return len(non_none) > 0 and len(non_none) < len(members) and all(_is_list_type(member) for member in non_none)


def _union_members(annotation: ast.expr) -> list[ast.expr] | None:
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        left = _union_members(annotation.left) or [annotation.left]
        right = _union_members(annotation.right) or [annotation.right]
        return [*left, *right]
    if isinstance(annotation, ast.Subscript) and _qualified_name(annotation.value).split(".")[-1] in _UNION_NAMES:
        if _qualified_name(annotation.value).endswith("Optional"):
            return [annotation.slice, ast.Constant(value=None)]
        if isinstance(annotation.slice, ast.Tuple):
            return list(annotation.slice.elts)
        return [annotation.slice]
    return None


def _is_none_type(node: ast.expr) -> bool:
    return (isinstance(node, ast.Constant) and node.value is None) or (isinstance(node, ast.Name) and node.id == "None")


def _is_list_type(node: ast.expr) -> bool:
    return isinstance(node, ast.Subscript) and _qualified_name(node.value).split(".")[-1] in {
        "List",
        "list",
    }

from __future__ import annotations

import ast
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from sarj_python_lint.rules._imports import ImportIndex


def stdlib_enum_base(base: ast.expr, imports: ImportIndex) -> str | None:
    return imports.resolved_symbol(base, sources=frozenset({"enum"}))


def class_enum_members(declaration: ast.ClassDef) -> frozenset[str]:
    return frozenset(
        target.id
        for statement in declaration.body
        if isinstance(statement, ast.Assign | ast.AnnAssign)
        and (not isinstance(statement, ast.AnnAssign) or statement.value is not None)
        for target in (statement.targets if isinstance(statement, ast.Assign) else (statement.target,))
        if isinstance(target, ast.Name) and not target.id.startswith("_")
    )

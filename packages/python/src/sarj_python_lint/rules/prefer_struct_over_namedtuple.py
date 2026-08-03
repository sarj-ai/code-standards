"""SARJ015 — `collections.namedtuple` — prefer `typing.NamedTuple` or a model

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_struct_over_namedtuple.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MSG = (
    "collections.namedtuple is untyped and positionally constructed — prefer "
    "typing.NamedTuple, or a frozen pydantic BaseModel for boundary values."
)


class PreferStructOverNamedtuple(Rule):
    id: str = "prefer-struct-over-namedtuple"
    code: str = "SARJ015"
    description: str = (
        "collections.namedtuple is untyped/positional — prefer typing.NamedTuple or a frozen pydantic model."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        collections_names = {"collections"}
        candidates: list[tuple[ast.AST, str | None]] = []
        for node in nodes(tree, ast.ImportFrom, ast.Import, ast.Call):
            if isinstance(node, ast.ImportFrom):
                if node.module == "collections":
                    candidates.extend((node, None) for alias in node.names if alias.name == "namedtuple")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "collections":
                        collections_names.add(alias.asname or "collections")
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "namedtuple"
                and isinstance(node.func.value, ast.Name)
            ):
                candidates.append((node, node.func.value.id))
        return [self._diag(path, node) for node, name in candidates if name is None or name in collections_names]

    def _diag(self, path: Path, node: ast.AST) -> Diagnostic:
        return Diagnostic(
            path=path,
            line=getattr(node, "lineno", 1),
            col=getattr(node, "col_offset", 0) + 1,
            code=self.code,
            message=_MSG,
        )

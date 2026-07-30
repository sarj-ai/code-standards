"""SARJ083: Forbid implicit dictionary accesses using string literals.

The anti-pattern:
    price = foo.get("price")
    user_id = event["user_id"]

Accessing dictionaries with hardcoded string literals implies the object has a known schema.
This should be parsed declaratively with Pydantic instead of plucked manually.

Define a Pydantic model and parse the payload at the boundary instead:
    class Payload(BaseModel):
        price: int
        user_id: str

    data = Payload.model_validate(foo)
    price = data.price
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none


if TYPE_CHECKING:
    from pathlib import Path

_EXCLUDED_BASES = {
    "environ",
    "headers",
    "cookies",
    "session",
    "redis",
    "cache",
    "state",
    "config",
    "kwargs",
    "env",
    "os",
    "sys",
}


def _get_base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _get_literal_get_key(node: ast.Call) -> str | None:
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "get" or not node.args:
        return None
    first_arg = node.args[0]
    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        return first_arg.value
    return None


class NoImplicitAttributeAccess(Rule):
    """Implicit dictionary access with string literals — use declarative parsing."""

    id: str = "no-implicit-attribute-access"
    code: str = "SARJ083"
    description: str = "Implicit dictionary access with string literals — parse declaratively with Pydantic."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if _is_test_path(path) or _is_excluded_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags: list[Diagnostic] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                key = _get_literal_get_key(node)
                if key is not None and isinstance(node.func, ast.Attribute):
                    base_name = _get_base_name(node.func.value)
                    if base_name in _EXCLUDED_BASES:
                        continue
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=node.lineno,
                            col=node.col_offset + 1,
                            code=self.code,
                            message=f"Imperative `.get('{key}')` lookup — use a declarative Pydantic model instead.",
                        )
                    )
            elif (
                isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                base_name = _get_base_name(node.value)
                if base_name not in _EXCLUDED_BASES:
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=node.lineno,
                            col=node.col_offset + 1,
                            code=self.code,
                            message=f"Imperative `['{node.slice.value}']` lookup — use a declarative Pydantic model instead.",
                        )
                    )

        return diags


def _is_test_path(path: Path) -> bool:
    return path.name.startswith("test_") or "tests" in path.parts


def _is_excluded_path(path: Path) -> bool:
    excluded = {".uv-cache", ".venv", "venv", "node_modules", "site-packages"}
    return bool(excluded.intersection(path.parts))

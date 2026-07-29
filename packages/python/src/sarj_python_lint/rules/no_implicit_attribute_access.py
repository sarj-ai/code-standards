"""SARJ110: Forbid implicit dictionary accesses using string literals.

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


class NoImplicitAttributeAccess(Rule):
    """Implicit dictionary access with string literals — use declarative parsing."""

    id: str = "no-implicit-attribute-access"
    code: str = "SARJ110"
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
            value: str | None = None
            base: ast.expr | None = None
            match node:
                case ast.Call(
                    func=ast.Attribute(attr="get", value=call_base),
                    args=[ast.Constant(value=str() as call_value), *_],
                ):
                    value = call_value
                    base = call_base
                case ast.Subscript(
                    value=subscript_base,
                    slice=ast.Constant(value=str() as subscript_value),
                ):
                    value = subscript_value
                    base = subscript_base
                case _:
                    continue
            if _get_base_name(base) not in _EXCLUDED_BASES:
                diags.append(
                    Diagnostic(
                        path=path,
                        line=node.lineno,
                        col=node.col_offset + 1,
                        code=self.code,
                        message=f"Imperative string-key lookup for {value!r} — use a declarative Pydantic model instead.",
                    )
                )

        return diags


def _is_test_path(path: Path) -> bool:
    return path.name.startswith("test_") or "tests" in path.parts


def _is_excluded_path(path: Path) -> bool:
    excluded = {".uv-cache", ".venv", "venv", "node_modules", "site-packages"}
    return bool(excluded.intersection(path.parts))

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
from sarj_python_lint.rules._ast_index import nodes


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


# Typing constructs subscripted with string literals. `Literal["x"]` is a type,
# not a lookup, so the rule's advice ("parse declaratively with Pydantic") is
# nonsensical there -- the annotation already IS the declarative schema.
_TYPE_SUBSCRIPTS = frozenset(
    {
        "Literal",
        "Annotated",
        "TypedDict",
        "NamedTuple",
        "Field",
        "Doc",
        "Required",
        "NotRequired",
        "ReadOnly",
    }
)


def _looks_like_route_or_url(value: str) -> bool:
    """Report whether a `.get()` argument is a route path or URL rather than a key.

    Returns:
        True for `"/users/{id}"`-shaped paths and anything carrying a scheme.

    """
    return value.startswith("/") or "://" in value


def _get_base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
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
        for node in nodes(tree, ast.Call, ast.Subscript):
            key = _get_key(node) if isinstance(node, ast.Call) else _subscript_key(node)
            if key is None:
                continue
            lookup = f".get('{key}')" if isinstance(node, ast.Call) else f"['{key}']"
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=f"Imperative `{lookup}` lookup — use a declarative Pydantic model instead.",
                )
            )

        return diags


def _get_key(node: ast.Call) -> str | None:
    """Read the string key of a `<base>.get("literal")` lookup worth reporting.

    Returns:
        The literal key, or None when this is not such a lookup or the base is
        one of the excluded receivers.

    """
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "get" or not node.args:
        return None
    first = node.args[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return None
    # `.get()` is also the HTTP verb and the route-registration decorator, and
    # both take a string first argument, so the method name alone cannot tell
    # them from a mapping lookup. The ARGUMENT can: a URL or a route path is not
    # a dictionary key. Measured on bulbul + noura-be, this shape was 168 of the
    # rule's 1,756 findings (9.6%) -- `@router.get("/available-events")` and
    # `await self.http_client.get(url)` were reported as implicit schema access.
    if _looks_like_route_or_url(first.value):
        return None
    return None if _get_base_name(func.value) in _EXCLUDED_BASES else first.value


def _subscript_key(node: ast.Subscript) -> str | None:
    """Read the string key of a `<base>["literal"]` lookup worth reporting.

    Returns:
        The literal key, or None when the subscript is not a string literal or
        the base is one of the excluded receivers.

    """
    # Writing to a mapping is the opposite of the defect. This rule is about
    # PLUCKING fields out of a payload whose schema is already known -- building
    # a dict up key by key (`field_dict["x"] = x`, `params["status"] = ...`) is
    # ordinary construction, and a Pydantic model does not replace it. Measured
    # on bulbul + noura-be this was 503 of 1,756 findings (28.6%), the single
    # largest source, and every sampled instance was an assignment target.
    if isinstance(node.ctx, (ast.Store, ast.Del)):
        return None
    # `Literal["a"]`, `Annotated[T, "..."]` and friends are type expressions that
    # merely LOOK like subscripts. They are not dictionary access at all, and no
    # Pydantic model can replace them -- `Literal["user"]` IS the schema. 470 of
    # 1,756 findings (26.8%) were this, second only to assignment targets.
    base_name = _get_base_name(node.value)
    if base_name in _TYPE_SUBSCRIPTS:
        return None
    index = node.slice
    if not isinstance(index, ast.Constant) or not isinstance(index.value, str):
        return None
    return None if base_name in _EXCLUDED_BASES else index.value


def _is_test_path(path: Path) -> bool:
    return path.name.startswith("test_") or "tests" in path.parts


def _is_excluded_path(path: Path) -> bool:
    excluded = {".uv-cache", ".venv", "venv", "node_modules", "site-packages"}
    return bool(excluded.intersection(path.parts))

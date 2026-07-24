"""SARJ034: >=2 positional parameters with the same primitive annotation — swap-prone.

`def transfer(source_id: str, target_id: str)` accepts `transfer(target, source)`
without a whisper from the type checker: two positional parameters with the same
primitive type are indistinguishable at the call site, and the resulting swap
bugs pass typecheck, pass review, and fail in production. Reviewers asked for a
keyword-only marker (`*`) in ~11 PRs, always with the same suggestion block:

    # flagged
    def transfer(source_id: str, target_id: str) -> None: ...

    # preferred — call sites must name the arguments
    def transfer(*, source_id: str, target_id: str) -> None: ...

Fires only when EVERY narrowing gate holds:

* the function has >= 2 positional parameters (excluding a leading `self`/`cls`)
  whose annotations are IDENTICAL and are a bare primitive (`str`, `int`,
  `float`, `bool`) — primitives carry no domain meaning, so the call site has
  nothing to disambiguate with. Same-typed domain objects
  (`a: Money, b: Money`) are left to review: arithmetic/comparison helpers over
  a domain type are often legitimately symmetric.

Never flags — these signatures cannot or should not change:

* dunder methods (`__init__`, `__eq__`, ... — protocol-pinned or pervasively
  called positionally),
* `visit_*` / `test_*` functions (visitor dispatch and pytest fixtures are
  framework-called with positional conventions),
* functions decorated `@override` / `@overload` / `@abstractmethod` (an
  override cannot unilaterally change the parent's signature; overload/abstract
  signatures are contracts),
* functions that already have a keyword-only section or a `*args` variadic
  (the author has already made a positional/keyword decision),
* functions with positional-only parameters (`/`) — an explicit, deliberate
  positional API.

Symmetric functions (`def add(x: int, y: int)`) where order genuinely does not
matter are suppressed with `# sarj-noqa: SARJ034 — <reason>`.
"""

from __future__ import annotations

import ast
from collections import Counter
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none


if TYPE_CHECKING:
    from pathlib import Path


_MIN_SAME_TYPE = 2

_PRIMITIVES = frozenset({"str", "int", "float", "bool"})

_EXEMPT_DECORATORS = frozenset({"override", "overload", "abstractmethod"})

_EXEMPT_NAME_PREFIXES = ("visit_", "test_")


class KwonlySameTypeParams(Rule):
    """>=2 positional params sharing one primitive annotation — insert `*`."""

    id: str = "kwonly-same-type-params"
    code: str = "SARJ034"
    description: str = (
        "two or more positional parameters with the same primitive annotation "
        "are swap-prone — make them keyword-only by inserting `*`."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if _is_exempt(node):
                continue
            offending = _swap_prone_annotation(node.args)
            if offending is None:
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        f"`{node.name}` takes multiple positional `{offending}` "
                        "parameters — swap-prone at call sites; insert `*` to "
                        "make them keyword-only."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_exempt(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    name = node.name
    if name.startswith("__") and name.endswith("__"):
        return True
    if name.startswith(_EXEMPT_NAME_PREFIXES):
        return True
    if any(_is_exempt_decorator(dec) for dec in node.decorator_list):
        return True
    args = node.args
    # An existing kwonly section / *args variadic means the positional-vs-keyword
    # decision was already made; positional-only params (`/`) are a deliberate API.
    return bool(args.kwonlyargs) or args.vararg is not None or bool(args.posonlyargs)


def _is_exempt_decorator(dec: ast.expr) -> bool:
    match dec:
        case ast.Name(id=name) if name in _EXEMPT_DECORATORS:
            return True
        case ast.Attribute(attr=name) if name in _EXEMPT_DECORATORS:
            return True
        case _:
            return False


def _swap_prone_annotation(args: ast.arguments) -> str | None:
    """Find a primitive annotation shared by >= 2 positional parameters.

    A leading `self`/`cls` is excluded. Only bare-`Name` primitive annotations
    participate — `str | None`, `Literal[...]`, and domain types never group.

    Returns:
        The offending primitive name, or None when the signature is fine.

    """
    params = list(args.args)
    if params and params[0].arg in {"self", "cls"}:
        params = params[1:]
    counts = Counter(
        ann.id
        for p in params
        if isinstance(ann := p.annotation, ast.Name) and ann.id in _PRIMITIVES
    )
    for name, count in counts.most_common():
        if count >= _MIN_SAME_TYPE:
            return name
    return None

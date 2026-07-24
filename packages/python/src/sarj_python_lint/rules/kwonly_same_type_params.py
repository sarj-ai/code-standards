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
* HTTP route handlers — any decorator of the shape
  `@<name>.get/post/put/patch/delete/head/options/websocket(...)` (`router`,
  `app`, `api`, ...): FastAPI binds handler parameters by NAME (path/query
  keys), so the positional shape is never called swap-prone by a human,
* test files (`_paths.is_test_path`) — test fakes and helpers mirror the
  signatures of the code under test and cannot unilaterally change them,
* parameters that are already keyword-only (behind `*`) or positional-only
  (before `/`, a deliberate positional API). Note this is per-parameter, not
  per-signature: `def f(a: str, b: str, *, c: int)` is still flagged, because
  `a`/`b` sit BEFORE the marker and remain swap-prone. A `*args` variadic
  likewise does not shield same-type params in front of it.

Parameters with defaults still count (documented judgment call: a default does
not make the call site any less swappable).

Symmetric functions (`def add(x: int, y: int)`) where order genuinely does not
matter are suppressed with `# sarj-noqa: SARJ034 — <reason>`.
"""

from __future__ import annotations

import ast
from collections import Counter
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MIN_SAME_TYPE = 2

_PRIMITIVES = frozenset({"str", "int", "float", "bool"})

_EXEMPT_DECORATORS = frozenset({"override", "overload", "abstractmethod"})

_HTTP_ROUTE_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "websocket"}
)

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
        if is_test_path(path):
            return []
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
    return any(
        _is_exempt_decorator(dec) or _is_route_decorator(dec) for dec in node.decorator_list
    )


def _is_exempt_decorator(dec: ast.expr) -> bool:
    match dec:
        case ast.Name(id=name) if name in _EXEMPT_DECORATORS:
            return True
        case ast.Attribute(attr=name) if name in _EXEMPT_DECORATORS:
            return True
        case _:
            return False


def _is_route_decorator(dec: ast.expr) -> bool:
    """Report whether `dec` is an HTTP-route decorator like `@router.get(...)`.

    Matches `<Name>.<http method>` — optionally called — for any receiver name
    (`router`, `app`, `api`, ...). FastAPI binds handler parameters by name, so
    a route handler's positional shape is not swap-prone at any call site.

    Returns:
        True when the decorator is an HTTP-route registration.

    """
    target = dec.func if isinstance(dec, ast.Call) else dec
    match target:
        case ast.Attribute(value=ast.Name(), attr=attr) if attr in _HTTP_ROUTE_METHODS:
            return True
        case _:
            return False


def _swap_prone_annotation(args: ast.arguments) -> str | None:
    """Find a primitive annotation shared by >= 2 swap-prone positional parameters.

    A leading `self`/`cls` is excluded. Only bare-`Name` primitive annotations
    participate — `str | None`, `Literal[...]`, and domain types never group.
    Only `args.args` (positional-or-keyword) parameters count: keyword-only
    parameters (behind `*`) cannot be swapped positionally, and positional-only
    parameters (before `/`) are a deliberate positional API. A `*`/`*args`/`/`
    marker therefore exempts exactly the parameters it protects — never the
    same-type pair sitting in front of it.

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

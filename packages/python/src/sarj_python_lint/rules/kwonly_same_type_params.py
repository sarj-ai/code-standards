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
* generated files (`_paths.is_generated_source`) — the signature mirrors
  whatever the generator emits (found via trio's `_generated_io_kqueue.py`),
* functions whose name is referenced as a VALUE anywhere in the module
  (passed to a registry, returned, stored) — the signature is a callback
  protocol shared with other implementations and cannot change unilaterally
  (found via attrs' `fmt_setter` family and sphinx `app.connect` handlers),
* the implementation of `@overload`-decorated stubs — a same-named sibling
  in the same scope carries `@overload`, so the impl's positional shape is
  pinned by the declared overloads (found via trio's `getsockopt`),
* signatures whose same-typed params differ only by a numeric suffix
  (`value_1: float, value_2: float`) — the numbering declares the function
  symmetric, so argument order genuinely does not matter (found via
  pydantic's `almost_equal_floats`),
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
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_generated_source, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MIN_SAME_TYPE = 2

_PRIMITIVES = frozenset({"str", "int", "float", "bool"})

_EXEMPT_DECORATORS = frozenset({"override", "overload", "abstractmethod"})

_HTTP_ROUTE_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "websocket"})

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
        if is_test_path(path) or is_generated_source(source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        value_referenced = _value_referenced_names(tree)
        overload_names = _overload_stub_names(tree)
        diags: list[Diagnostic] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if _is_exempt(node):
                continue
            if node.name in value_referenced or node.name in overload_names:
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
        (isinstance(dec, ast.Name) and dec.id in _EXEMPT_DECORATORS)
        or (isinstance(dec, ast.Attribute) and dec.attr in _EXEMPT_DECORATORS)
        or _is_route_decorator(dec)
        for dec in node.decorator_list
    )


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

    A group whose parameter names differ only by a numeric suffix
    (`value_1`/`value_2`) is a declared-symmetric signature and never groups.

    Returns:
        The offending primitive name, or None when the signature is fine.

    """
    params = list(args.args)
    if params and params[0].arg in {"self", "cls"}:
        params = params[1:]
    groups: dict[str, list[str]] = {}
    for p in params:
        if isinstance(ann := p.annotation, ast.Name) and ann.id in _PRIMITIVES:
            groups.setdefault(ann.id, []).append(p.arg)
    for name, arg_names in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(arg_names) >= _MIN_SAME_TYPE and not _is_symmetric_numbering(arg_names):
            return name
    return None


_NUMERIC_SUFFIX_RE = re.compile(r"_?\d+$")


def _is_symmetric_numbering(arg_names: list[str]) -> bool:
    """Report whether every name in the group is one stem plus a numeric suffix.

    `value_1`/`value_2` (or `x1`/`x2`) declare a symmetric function — argument
    order genuinely does not matter, so the group is not swap-prone.

    Returns:
        True when all names share one stem and differ only by a number.

    """
    stems = {_NUMERIC_SUFFIX_RE.sub("", name) for name in arg_names}
    return len(stems) == 1 and all(_NUMERIC_SUFFIX_RE.search(name) for name in arg_names)


def _value_referenced_names(tree: ast.AST) -> frozenset[str]:
    """Names referenced as a VALUE (loaded but not called) anywhere in the module.

    A function whose name appears as a bare value — passed to a registry,
    returned, stored in a collection — implements a callback protocol whose
    positional shape is shared with other implementations; it cannot go
    keyword-only unilaterally.

    Returns:
        The set of names loaded outside call position.

    """
    call_funcs = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    return frozenset(
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and id(node) not in call_funcs
    )


def _overload_stub_names(tree: ast.AST) -> frozenset[str]:
    """Names carrying an `@overload` decorator anywhere in the module.

    The undecorated implementation of an overloaded function shares its name
    with the stubs; its positional shape is pinned by the declared overloads.

    Returns:
        The set of `@overload`-decorated function names.

    """
    return frozenset(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            (isinstance(dec, ast.Name) and dec.id == "overload")
            or (isinstance(dec, ast.Attribute) and dec.attr == "overload")
            for dec in node.decorator_list
        )
    )

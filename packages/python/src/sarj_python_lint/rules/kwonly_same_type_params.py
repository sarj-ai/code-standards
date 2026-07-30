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
* CLI command handlers — `@click.*` / `@typer.*`, or `@<name>.command(...)` /
  `@<name>.group(...)`: click and typer bind handler parameters by NAME from
  the declared options/arguments and the human call site is a shell command
  line, not a Python call (3 corpus hits: `httpx/_main.py:452`,
  `black/src/blackd/__init__.py:96`,
  `black/scripts/diff_shades_gha_helper.py:167`),
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
* methods that provably override a base-class method — the body calls
  `super().<same name>(...)`. An override cannot narrow the inherited calling
  convention without breaking every caller that holds the base type
  (`httpx/_models.py:1257`, `_CookieCompatRequest.add_unredirected_header`),
* methods implementing a duck-typed stdlib protocol (`seek`, `read`, `write`,
  `add_unredirected_header`, `recv`, `setsockopt`, ...). The stdlib itself is
  the caller and calls them POSITIONALLY — `io` calls `f.seek(0, 2)`,
  `http.cookiejar` calls `req.add_unredirected_header("Cookie", v)` — so
  inserting `*` is not a style change, it is a `TypeError` at runtime (5
  corpus hits: `requests/cookies.py:89` and `:95`, `httpx/_models.py:1257`,
  `anyio/streams/file.py:97`, `rich/progress.py:270`),
* parameters named `__x` (leading double underscore, no trailing) — PEP 484
  spells positional-only parameters that way, so they cannot be made
  keyword-only at all (`rich/_null_file.py:24`, `NullFile.seek`),
* same-typed groups drawn entirely from a conventional ordered vocabulary —
  `x`/`y`/`z`, `width`/`height`, `red`/`green`/`blue`, `start`/`stop`/`step`,
  `row`/`column`, `top`/`right`/`bottom`/`left`, `year`/`month`/`day`,
  `hour`/`minute`/`second`. Position IS the notation for these: nobody reads
  `Control.move(2, 5)` as ambiguous, and `move(*, x=2, y=5)` is worse (11
  corpus hits, e.g. `rich/control.py:79`, `rich/segment.py:462`,
  `rich/color.py:409` `from_rgb`, `anyio/itertools.py:271` `count`),
  The vocabularies are closed sets of domain notation, NOT a general
  short-name escape: single-letter placeholders stay flagged
  (`def _newer(a: str, b: str)`, `blib2to3/pgen2/driver.py:287`), because
  there the call site genuinely cannot tell the two apart.
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
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._paths import is_generated_source, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MIN_SAME_TYPE = 2

_PRIMITIVES = frozenset({"str", "int", "float", "bool"})

_EXEMPT_DECORATORS = frozenset({"override", "overload", "abstractmethod"})

_HTTP_ROUTE_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "websocket"})

#: Decorator receivers whose attribute access marks a CLI command handler.
_CLI_DECORATOR_MODULES = frozenset({"click", "typer"})

#: `@<name>.command(...)` / `@<name>.group(...)` — click groups and typer apps.
_CLI_DECORATOR_ATTRS = frozenset({"command", "group"})

#: Methods that implement a duck-typed stdlib protocol. The stdlib is the
#: caller and calls them positionally, so `*` here is a runtime TypeError.
_DUCK_PROTOCOL_METHODS = frozenset(
    {
        "read",
        "read1",
        "readinto",
        "readinto1",
        "readline",
        "readlines",
        "seek",
        "truncate",
        "write",
        "writelines",
        "connect",
        "connect_ex",
        "getsockopt",
        "setsockopt",
        "recv",
        "recv_into",
        "recvfrom",
        "recvfrom_into",
        "send",
        "sendall",
        "sendto",
        "add_header",
        "add_unredirected_header",
        "get_header",
        "has_header",
    }
)

#: Parameter-name vocabularies whose ORDER is the notation. A same-typed group
#: drawn entirely from one of these reads unambiguously positionally.
_CONVENTIONAL_ORDER_GROUPS = (
    frozenset({"x", "y", "z"}),
    frozenset({"lat", "lon", "alt"}),
    frozenset({"latitude", "longitude", "altitude"}),
    frozenset({"width", "height", "depth"}),
    frozenset({"red", "green", "blue", "alpha"}),
    frozenset({"row", "column"}),
    frozenset({"top", "right", "bottom", "left"}),
    frozenset({"left", "right"}),
    frozenset({"lo", "hi"}),
    frozenset({"low", "high"}),
    frozenset({"minimum", "maximum"}),
    frozenset({"min_value", "max_value"}),
    frozenset({"begin", "end"}),
    frozenset({"source", "sink"}),
    frozenset({"year", "month", "day"}),
    frozenset({"hour", "minute", "second", "microsecond"}),
    frozenset({"start", "stop", "step"}),
)

_EXEMPT_NAME_PREFIXES = ("visit_", "test_")
_RISKY_NAME_PART_RE = re.compile(
    r"(?:^|_)(?:id|key|token|secret|password|signature|hash|email|url|uri|path|file|"
    r"source|src|target|dst|dest|destination|parent|child|from|to|old|new|"
    r"before|after|previous|next|expected|actual|left_id|right_id)(?:_|$)"
)


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
        # The signature test is a local, allocation-free predicate; the three
        # name/id tables each scan the whole module. Screening on the signature
        # first means a module with no swap-prone signature at all — the common
        # case — never builds a table.
        candidates = [
            (node, offending)
            for node in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef)
            if not _is_exempt(node) and (offending := _swap_prone_annotation(node.args)) is not None
        ]
        if not candidates:
            return []
        value_referenced = _value_referenced_names(tree)
        overload_names = _overload_stub_names(tree)
        method_ids = _method_node_ids(tree)
        diags: list[Diagnostic] = []
        for node, offending in candidates:
            if node.name in value_referenced or node.name in overload_names:
                continue
            # Checked last: `_calls_super_same_name` walks the body, so it runs
            # only for the few signatures that would otherwise be reported.
            if id(node) in method_ids and (node.name in _DUCK_PROTOCOL_METHODS or _calls_super_same_name(node)):
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
        or _is_cli_command_decorator(dec)
        for dec in node.decorator_list
    )


def _is_cli_command_decorator(dec: ast.expr) -> bool:
    """Report whether `dec` registers the function as a click/typer CLI handler.

    Matches `@click.*` / `@typer.*` (any attribute: `command`, `option`,
    `argument`, ...) and `@<name>.command(...)` / `@<name>.group(...)` for a
    click group or typer app. Both frameworks bind handler parameters by NAME
    from the declared options, and the human-facing call site is a shell
    command line — the positional shape is never typed by a caller.

    Returns:
        True when the decorator is a CLI command registration.

    """
    target = dec.func if isinstance(dec, ast.Call) else dec
    match target:
        case ast.Attribute(value=ast.Name(id=receiver)) if receiver in _CLI_DECORATOR_MODULES:
            return True
        case ast.Attribute(value=ast.Name(), attr=attr) if attr in _CLI_DECORATOR_ATTRS:
            return True
        case _:
            return False


def _method_node_ids(tree: ast.AST) -> frozenset[int]:
    """Identify the defs that are methods — direct children of a class body.

    Returns:
        The set of `id(FunctionDef)` for every method in the module.

    """
    return frozenset(
        id(child)
        for node in nodes(tree, ast.ClassDef)
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _calls_super_same_name(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether the body calls `super().<this method's name>(...)`.

    That call is proof the method overrides an inherited one: its calling
    convention belongs to the base class, and narrowing it to keyword-only
    breaks every caller holding the base type.

    Returns:
        True when the method provably overrides a base-class method.

    """
    return any(
        isinstance(func := call.func, ast.Attribute)
        and func.attr == node.name
        and isinstance(inner := func.value, ast.Call)
        and isinstance(inner.func, ast.Name)
        and inner.func.id == "super"
        for call in walk(node)
        if isinstance(call, ast.Call)
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

    A parameter named `__x` is positional-only by the PEP 484 spelling and so
    cannot be made keyword-only at all; it never groups.

    A group whose parameter names differ only by a numeric suffix
    (`value_1`/`value_2`) or are drawn entirely from a conventional ordered
    vocabulary (`x`/`y`, `width`/`height`) is not swap-prone and never groups.

    Returns:
        The offending primitive name, or None when the signature is fine.

    """
    params = list(args.args)
    if params and params[0].arg in {"self", "cls"}:
        params = params[1:]
    groups: dict[str, list[str]] = {}
    for p in params:
        if _is_dunder_prefixed(p.arg):
            continue
        if isinstance(ann := p.annotation, ast.Name) and ann.id in _PRIMITIVES:
            groups.setdefault(ann.id, []).append(p.arg)
    for name, arg_names in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if (
            len(arg_names) >= _MIN_SAME_TYPE
            and not (_is_symmetric_numbering(arg_names) or _is_conventional_order(arg_names))
            and _is_high_value_group(name, arg_names)
        ):
            return name
    return None


def _is_high_value_group(annotation: str, arg_names: list[str]) -> bool:
    """Report whether a same-primitive group is worth enforcing globally.

    Booleans are always high-risk because positional `True, False` carries no
    call-site meaning. Other primitives fire only when the parameter names carry
    production-domain identifiers or directed relationships (`source_id`,
    `target_id`, `old_key`, `new_key`, `input_path`, `output_path`). This keeps
    math / algorithm APIs such as `power(base, exponent)` and `f(a, b)` out of
    the default rule while preserving the bug class the rule was written for.

    Returns:
        True when the group should be reported.

    """
    if annotation == "bool":
        return True
    return sum(1 for name in arg_names if _RISKY_NAME_PART_RE.search(name)) >= _MIN_SAME_TYPE


def _is_dunder_prefixed(arg: str) -> bool:
    """Report whether `arg` uses the PEP 484 positional-only naming convention.

    Returns:
        True for a `__name` parameter (leading dunder, no trailing dunder).

    """
    return arg.startswith("__") and not arg.endswith("__")


def _is_conventional_order(arg_names: list[str]) -> bool:
    """Report whether every name comes from one conventional ordered vocabulary.

    `x`/`y`, `width`/`height`, `red`/`green`/`blue`, `start`/`stop`/`step`:
    position IS the notation, so the call site is not ambiguous and inserting
    `*` makes it noisier, not safer.

    Returns:
        True when the whole group sits inside one ordered vocabulary.

    """
    names = set(arg_names)
    return any(names <= vocabulary for vocabulary in _CONVENTIONAL_ORDER_GROUPS)


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
    call_funcs = {id(node.func) for node in nodes(tree, ast.Call)}
    return frozenset(
        node.id for node in nodes(tree, ast.Name) if isinstance(node.ctx, ast.Load) and id(node) not in call_funcs
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
        for node in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef)
        if any(
            (isinstance(dec, ast.Name) and dec.id == "overload")
            or (isinstance(dec, ast.Attribute) and dec.attr == "overload")
            for dec in node.decorator_list
        )
    )

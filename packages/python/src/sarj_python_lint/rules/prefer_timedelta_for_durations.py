"""SARJ014: flag a duration named in time units but typed as a raw `int`/`float`.

A parameter or field whose name carries a time unit (`timeout_seconds`,
`retry_interval_ms`, `ttl`, `backoff_minutes`, ...) but is annotated `int` or
`float` forces every call site to remember the unit and invites the
`_seconds` / `_ms` / `_minutes` naming-collision class of bugs. `datetime.timedelta`
makes the unit explicit at the call site and lets the type checker catch
mismatches.

    # flagged
    def schedule(self, timeout_seconds: int) -> None: ...
    class Settings(BaseModel):
        retry_interval_ms: float = 250.0
        api_timeout_s: NonNegativeFloat = 30.0   # constrained brands too

    # preferred
    def schedule(self, timeout: timedelta) -> None: ...
    class Settings(BaseModel):
        retry_interval: timedelta = timedelta(milliseconds=250)

Scope is deliberately narrow to keep false positives low: only annotated
function parameters and annotated assignments (`AnnAssign`, i.e. class/module
fields) are inspected, and only when the annotation resolves to a numeric type —
bare `int`/`float`, a pydantic constrained brand (`PositiveInt`,
`NonNegativeFloat`, ...), or any of those under `| None` / `Optional[...]` /
`Annotated[...]`. Plain local assignments are not flagged.

Deliberately NOT flagged:
- count-like names (`*_count`, `num_*`, `n_*`, `*_size`, `*_limit`),
- wall-clock components, which are positions not durations — only plural/abbrev
  unit names match (`*_minutes`, `*_secs`), so a bare `hour`/`minute`/`second` is
  left alone,
- percentages and rates (`*_percentage`, `*_pct`, `*_rate`, `*_ratio`),
- calendar units that `timedelta` cannot express cleanly (`*_months`, `*_years`),
- absolute instants (`*_timestamp`, `*_epoch`, `expires_at`, `*_at`),
- anything already annotated `timedelta`,
- fields declared directly on a pydantic-settings class (any base name ending in
  `Settings`, e.g. `BaseSettings` / `pydantic_settings.BaseSettings` / a
  `...Settings` subclass): these are populated from environment variables, whose
  bare-numeric wire values `timedelta` cannot parse, so a raw `int`/`float` is
  the only workable type at that boundary. Ordinary `BaseModel` domain fields are
  still flagged.
- test files (`_paths.is_test_path`): test fakes and helpers mirror the
  signatures of stdlib/third-party APIs under test (`Lock.acquire(timeout=-1)`,
  seconds-based subprocess helpers) and cannot change them — the trio sweep's
  false positives were all of this shape.
- `@overload` stubs. The overload set restates one implementation's signature N
  times, so reporting each is N-1 duplicates of the same finding; the
  implementation that follows is still flagged. Six of the famous-repo sweep's
  21 hits were this
  (`anyio/src/anyio/_core/_sockets.py:82`, `:97`, `:113`, `:129`, `:141` all
  restating `happy_eyeballs_delay` for `connect_tcp` at `:155`, plus
  `anyio/src/anyio/functools.py:282` restating `ttl` for `:303`).
- **CLI parameters** — a parameter of a function decorated with `click` /
  `typer` (`@click.option`, `@click.argument`, ...). Same boundary argument as
  pydantic-settings: the value is parsed out of `argv` by the framework
  (`type=float`), and `timedelta` is not a shape argv can carry
  (`httpx/httpx/_main.py:464`, `timeout: float` behind `@click.option("--timeout",
  type=float, default=5.0)`).
- **Same-name delegation wrappers** — a body that does nothing but forward the
  parameter to a callee of the same name (`async def sleep(delay: float): await
  trio.sleep(delay)`). The unit belongs to the wrapped API, not to the wrapper:
  `anyio/src/anyio/_backends/_trio.py:1115`,
  `anyio/src/anyio/_backends/_asyncio.py:2532`, and
  `anyio/src/anyio/_core/_eventloop.py:88` all mirror stdlib `sleep`. A body
  that computes with the parameter (`deadline = current_time() + delay`) is not
  a pass-through and still fires.

Suppress an intentional raw-numeric duration with `# sarj-noqa: SARJ014 — <reason>`.

References:
- https://docs.python.org/3/library/datetime.html#timedelta-objects

"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_UNIT_RE = re.compile(
    r"(?:^|_)(?:"
    r"seconds|secs|milliseconds|millis|ms|"
    r"minutes|mins|hours|hrs|days|"
    r"timeout|interval|ttl|delay|backoff|duration|cooldown|expires_in"
    r")(?:_|$)",
    re.IGNORECASE,
)

_EXCLUDE_RE = re.compile(
    r"(?:^|_)(?:count|num|n|size|len|length|limit|offset|index|idx|id|"
    r"version|month|months|year|years|timestamp|epoch|"
    r"percentage|percent|pct|ratio|rate|trend)(?:_|$)|_at$|_ts$",
    re.IGNORECASE,
)

_NUMERIC_NAMES = frozenset({"int", "float"})

#: Roots of the CLI frameworks whose decorators bind a parameter to an argv value.
_CLI_MODULES = frozenset({"click", "typer"})

#: Decorator names that declare a CLI parameter whatever they are imported from
#: (`@option(...)`, `@app.argument(...)`).
_CLI_DECORATORS = frozenset({"argument", "option"})

_CONSTRAINED_NUMERIC = {
    "PositiveInt": "int",
    "NonNegativeInt": "int",
    "NegativeInt": "int",
    "NonPositiveInt": "int",
    "StrictInt": "int",
    "PositiveFloat": "float",
    "NonNegativeFloat": "float",
    "NegativeFloat": "float",
    "NonPositiveFloat": "float",
    "StrictFloat": "float",
}


class PreferTimedeltaForDurations(Rule):
    """Duration named in time units but typed as a raw int/float — prefer timedelta."""

    id: str = "prefer-timedelta-for-durations"
    code: str = "SARJ014"
    description: str = (
        "Duration named in time units (timeout_seconds, ttl, ...) typed as raw "
        "int/float — use datetime.timedelta so the unit is explicit and checked."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        settings_fields = _settings_field_ids(tree)
        diags: list[Diagnostic] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _is_overload(node) or _has_cli_decorator(node):
                    continue
                args = node.args
                for a in (*args.posonlyargs, *args.args, *args.kwonlyargs):
                    if _is_forwarded_to_same_name(node, a.arg):
                        continue
                    self._consider(a.arg, a.annotation, a, diags, path)
            elif isinstance(node, ast.AnnAssign):
                if id(node) in settings_fields:
                    continue
                name = _target_name(node.target)
                if name is not None:
                    self._consider(name, node.annotation, node, diags, path)
        return diags

    def _consider(
        self,
        name: str,
        annotation: ast.expr | None,
        node: ast.AST,
        diags: list[Diagnostic],
        path: Path,
    ) -> None:
        if annotation is None:
            return
        if not _UNIT_RE.search(name) or _EXCLUDE_RE.search(name):
            return
        numeric = _numeric_annotation(annotation)
        if numeric is None:
            return
        diags.append(
            Diagnostic(
                path=path,
                line=getattr(node, "lineno", 1),
                col=getattr(node, "col_offset", 0) + 1,
                code=self.code,
                message=(
                    f"`{name}: {numeric}` is a duration named in time units — use "
                    f"datetime.timedelta instead of a raw {numeric}."
                ),
            )
        )


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether the function is an `@overload` restatement of another signature.

    Returns:
        True when an `overload` decorator is present.

    """
    return any(_trailing_name(dec) == "overload" for dec in node.decorator_list)


def _has_cli_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether the function is a `click` / `typer` command entry point.

    Its parameters are parsed out of `argv` by the framework, which knows how to
    build an `int`/`float` and not a `timedelta`.

    Returns:
        True when any decorator comes from a CLI framework.

    """
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        dotted = _dotted_name(target)
        if dotted is None:
            continue
        parts = dotted.split(".")
        if parts[0] in _CLI_MODULES or parts[-1] in _CLI_DECORATORS:
            return True
    return False


def _is_forwarded_to_same_name(node: ast.FunctionDef | ast.AsyncFunctionDef, param: str) -> bool:
    """Report whether the body only forwards `param` to a callee of the function's own name.

    `async def sleep(delay: float) -> None: await trio.sleep(delay)` is a
    pass-through: the unit is the wrapped API's, and this signature exists to
    mirror it.

    Returns:
        True when the body is a single same-name call that receives `param`.

    """
    body = [stmt for stmt in node.body if not _is_docstring(stmt)]
    if len(body) != 1:
        return False
    match body[0]:
        case ast.Return(value=ast.expr() as value) | ast.Expr(value=value):
            call = value.value if isinstance(value, ast.Await) else value
        case _:
            return False
    if not isinstance(call, ast.Call) or _trailing_name(call.func) != node.name:
        return False
    passed = [*call.args, *(kw.value for kw in call.keywords)]
    return any(isinstance(arg, ast.Name) and arg.id == param for arg in passed)


def _is_docstring(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)


def _dotted_name(node: ast.expr) -> str | None:
    """Render a `Name` / `Attribute` chain as a dotted string.

    Returns:
        The dotted name, or None when the expression is not a plain chain.

    """
    match node:
        case ast.Name(id=ident):
            return ident
        case ast.Attribute(value=value, attr=attr):
            base = _dotted_name(value)
            return None if base is None else f"{base}.{attr}"
        case _:
            return None


def _settings_field_ids(tree: ast.Module) -> frozenset[int]:
    """`id()` of every `AnnAssign` declared directly on a pydantic-settings class.

    A class is treated as pydantic-settings when it derives from a `...Settings`
    base — either directly (`BaseSettings`, `pydantic_settings.BaseSettings`, a
    project `...Settings` class) or transitively through an intermediate base
    defined in the same module (e.g. `class _Base(BaseSettings)` →
    `class Foo(_Base)`). Such fields come from environment variables, whose
    bare-numeric wire form `timedelta` cannot parse, so they are exempt.

    Returns:
        The `id()`s of the exempt settings-field `AnnAssign` nodes.

    """
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    settings_classes = _resolve_settings_classes(classes)
    exempt: set[int] = set()
    for node in settings_classes:
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign):
                exempt.add(id(stmt))
    return frozenset(exempt)


def _resolve_settings_classes(
    classes: list[ast.ClassDef],
) -> set[ast.ClassDef]:
    by_name: dict[str, ast.ClassDef] = {}
    for node in classes:
        by_name.setdefault(node.name, node)
    resolved: dict[int, bool] = {}

    def is_settings(node: ast.ClassDef, seen: frozenset[int]) -> bool:
        if id(node) in resolved:
            return resolved[id(node)]
        if id(node) in seen:
            return False
        result = False
        for base in node.bases:
            base_name = _trailing_name(base)
            if base_name is None:
                continue
            if base_name.endswith("Settings"):
                result = True
                break
            parent = by_name.get(base_name)
            if parent is not None and is_settings(parent, seen | {id(node)}):
                result = True
                break
        resolved[id(node)] = result
        return result

    return {node for node in classes if is_settings(node, frozenset())}


def _target_name(target: ast.expr) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _numeric_annotation(node: ast.expr) -> str | None:
    """Return 'int'/'float' if the annotation resolves to a numeric duration type.

    Handles bare `int`/`float`, pydantic constrained brands (`PositiveInt`,
    `NonNegativeFloat`, ...), `x | None`, `Optional[x]`, and `Annotated[x, ...]`.

    Returns:
        'int'/'float' for a numeric annotation, or None otherwise.

    """
    direct = _bare_numeric(node)
    if direct is not None:
        return direct
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        for side in (node.left, node.right):
            inner = _numeric_annotation(side)
            if inner is not None:
                return inner
        return None
    if isinstance(node, ast.Subscript):
        if _is_named(node.value, "Optional"):
            return _numeric_annotation(node.slice)
        if _is_named(node.value, "Annotated"):
            inner = node.slice
            if isinstance(inner, ast.Tuple) and inner.elts:
                inner = inner.elts[0]
            return _numeric_annotation(inner)
    return None


def _bare_numeric(node: ast.expr) -> str | None:
    name = _trailing_name(node)
    if name in _NUMERIC_NAMES:
        return name
    return _CONSTRAINED_NUMERIC.get(name or "")


def _trailing_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _trailing_name(node.value)
    return None


def _is_named(node: ast.expr, name: str) -> bool:
    return _trailing_name(node) == name

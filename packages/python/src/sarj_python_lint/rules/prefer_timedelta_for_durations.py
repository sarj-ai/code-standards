"""SARJ014 — Duration named in time units but typed as a raw `int`/`float`.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_timedelta_for_durations.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._paths import is_generated, is_test_path


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
_BARE_UNIT_NAMES = frozenset(
    {
        "day",
        "days",
        "hour",
        "hours",
        "minute",
        "minutes",
        "min",
        "mins",
        "second",
        "seconds",
        "sec",
        "secs",
        "millisecond",
        "milliseconds",
        "ms",
    }
)

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
    id: str = "prefer-timedelta-for-durations"
    code: str = "SARJ014"
    description: str = (
        "Duration named in time units (timeout_seconds, ttl, ...) typed as raw "
        "int/float — use datetime.timedelta so the unit is explicit and checked."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        if is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        settings_fields = _settings_field_ids(tree)
        diags: list[Diagnostic] = []
        for node in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef, ast.AnnAssign):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _is_overload(node) or _has_cli_decorator(node):
                    continue
                args = node.args
                forwarded = _same_name_forwarded_params(node, _duration_named_params(args))
                for a in (*args.posonlyargs, *args.args, *args.kwonlyargs):
                    if a.arg in forwarded or _is_forwarded_to_same_name(node, a.arg):
                        continue
                    self._consider(a.arg, a.annotation, a, diags, path)
            else:
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
        if name.lower() in _BARE_UNIT_NAMES or name.lower().endswith(("_worked", "_elapsed")):
            return
        if not _UNIT_RE.search(name) or _EXCLUDE_RE.search(name):
            return
        if _admits_timedelta(annotation):
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
    """Report whether the function is an `@overload` restatement of another signature."""
    return any(_trailing_name(dec) == "overload" for dec in node.decorator_list)


def _has_cli_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether the function is a `click` / `typer` command entry point."""
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
    """Report whether the body only forwards `param` to a callee of the function's own name."""
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


def _duration_named_params(args: ast.arguments) -> frozenset[str]:
    """Collect the annotated parameters whose names read as durations.

    The forwarding walk below costs an `ast.walk` of the whole function, so it
    only runs when some parameter could be reported in the first place.

    Returns:
        The candidate parameter names.

    """
    return frozenset(
        a.arg
        for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
        if a.annotation is not None and _UNIT_RE.search(a.arg) and not _EXCLUDE_RE.search(a.arg)
    )


def _same_name_forwarded_params(node: ast.FunctionDef | ast.AsyncFunctionDef, params: frozenset[str]) -> frozenset[str]:
    """Collect the parameters this function only ever forwards under their own name.

    A parameter qualifies when it is used at least once and *every* one of its
    loads sits directly in a same-name sink — a keyword argument whose keyword is
    the parameter's own name, or an attribute store to the same name. Requiring
    the load to be the sink's direct value is what excludes arithmetic,
    comparisons and subscripts: in `client.call(timeout=timeout * 2)` the
    keyword's value is the `BinOp`, not the parameter, so the parameter is
    disqualified and the finding stands.

    An unused parameter never qualifies — `def schedule(timeout_seconds: int)
    -> None: ...` has no loads at all and is the rule's core finding.

    Returns:
        The names of the parameters whose every use is a same-name forward.

    """
    if not params:
        return frozenset()
    used: set[str] = set()
    computed: set[str] = set()
    for parent in ast.walk(node):
        for child in ast.iter_child_nodes(parent):
            if not isinstance(child, ast.Name) or not isinstance(child.ctx, ast.Load):
                continue
            if child.id not in params:
                continue
            used.add(child.id)
            if not _is_same_name_sink(parent, child.id):
                computed.add(child.id)
    return frozenset(used - computed)


def _is_same_name_sink(parent: ast.AST, name: str) -> bool:
    """Report whether `parent` consumes a load of `name` under that same name.

    Returns:
        True for `f(<name>=<name>)` and `self.<name> = <name>`.

    """
    match parent:
        case ast.keyword(arg=str(keyword)):
            return keyword == name
        case ast.Assign(targets=[ast.Attribute(attr=attribute)]) | ast.AnnAssign(target=ast.Attribute(attr=attribute)):
            return attribute == name
        case _:
            return False


def _admits_timedelta(node: ast.expr) -> bool:
    """Report whether the annotation already accepts a `timedelta`.

    Walks the same shapes `_numeric_annotation` does — `|` unions,
    `Optional[...]`, `Annotated[...]` — so that `float | timedelta | None` is
    recognised as a signature that already takes what the rule asks for.

    Returns:
        True when any member of the annotation is `timedelta`.

    """
    if _trailing_name(node) == "timedelta":
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _admits_timedelta(node.left) or _admits_timedelta(node.right)
    if isinstance(node, ast.Subscript) and (_is_named(node.value, "Optional") or _is_named(node.value, "Annotated")):
        inner = node.slice
        if isinstance(inner, ast.Tuple) and inner.elts:
            inner = inner.elts[0]
        return _admits_timedelta(inner)
    return False


def _is_docstring(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)


def _dotted_name(node: ast.expr) -> str | None:
    """Render a `Name` / `Attribute` chain as a dotted string."""
    match node:
        case ast.Name(id=ident):
            return ident
        case ast.Attribute(value=value, attr=attr):
            base = _dotted_name(value)
            return None if base is None else f"{base}.{attr}"
        case _:
            return None


def _settings_field_ids(tree: ast.Module) -> frozenset[int]:
    """`id()` of every `AnnAssign` declared directly on a pydantic-settings class."""
    classes = nodes(tree, ast.ClassDef)
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
    """Return 'int'/'float' if the annotation resolves to a numeric duration type."""
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

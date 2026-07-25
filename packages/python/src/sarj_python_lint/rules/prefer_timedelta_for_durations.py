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
                args = node.args
                for a in (*args.posonlyargs, *args.args, *args.kwonlyargs):
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

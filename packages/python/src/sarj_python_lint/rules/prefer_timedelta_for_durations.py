"""SARJ014 — Duration named in time units but typed as a raw `int`/`float`.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_timedelta_for_durations.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._imports import ImportIndex
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
    r"percentage|percent|pct|ratio|rate|trend|factor|multiplier|confidence|probability)(?:_|$)|_at$|_ts$",
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

_CONSTRAINED_NUMERIC = MappingProxyType(
    {
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
)


class PreferTimedeltaForDurations(Rule):
    id: str = "prefer-timedelta-for-durations"
    code: str = "SARJ014"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Duration-bearing name is typed as a raw integer or float.",
        rationale="A `timedelta` makes the unit explicit and prevents incompatible duration values from mixing silently.",
        remediation="Use `datetime.timedelta` at the typed boundary and convert only at external interfaces.",
        category=RuleCategory.CORRECTNESS,
        limitations=(
            "Detection relies on duration-shaped names and numeric type annotations.",
            "Tests, generated files, CLI parameters, settings/model/wire fields, observability boundaries, counts, rates, calendar units, and timestamps are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="numeric-duration-parameter",
                title="Seconds represented as an integer",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("scheduler.py", "def schedule(timeout_seconds: int) -> None: ...\n"),),
                focus_path=PurePosixPath("scheduler.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="timedelta-duration-parameter",
                title="Duration represented as timedelta",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "scheduler.py",
                        "from datetime import timedelta\n\ndef schedule(timeout: timedelta) -> None: ...\n",
                    ),
                ),
                focus_path=PurePosixPath("scheduler.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        if is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree)
        exempt_fields = (
            _settings_field_ids(tree) | _pydantic_model_field_ids(tree, imports) | _typed_dict_field_ids(tree, imports)
        )
        serialized_constants = _exclusively_serialized_duration_constants(tree, imports)
        diags: list[Diagnostic] = []
        for node in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef, ast.AnnAssign):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _is_overload(node) or _has_cli_decorator(node) or _is_observability_boundary(path, node):
                    continue
                args = node.args
                forwarded = _same_name_forwarded_params(node, _duration_named_params(args))
                for a in (*args.posonlyargs, *args.args, *args.kwonlyargs):
                    if a.arg in forwarded or _is_forwarded_to_same_name(node, a.arg):
                        continue
                    self._consider(a.arg, a.annotation, a, diags, path)
            else:
                if id(node) in exempt_fields:
                    continue
                name = _target_name(node.target)
                if name is not None:
                    self._consider(name, node.annotation, node, diags, path)
        for statement in tree.body:
            match statement:
                case ast.Assign(targets=[ast.Name(id=name)], value=value) if _is_numeric_expression(value):
                    if _is_constant_reference(name) and name not in serialized_constants:
                        numeric = "float" if _contains_float(value) else "int"
                        self._consider(name, ast.Name(id=numeric), statement, diags, path)
                case _:
                    pass
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


def _is_observability_boundary(path: Path, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Keep raw numeric units at logging/metrics serialization boundaries."""
    name = node.name.lstrip("_")
    return (
        "logger" in path.stem.lower()
        or name.startswith(("log_", "record_", "emit_"))
        or name.endswith(("_metric", "_metrics"))
    )


def _is_constant_reference(identifier: str) -> bool:
    return identifier.isupper() and any(character.isalpha() for character in identifier)


def _is_numeric_expression(node: ast.expr) -> bool:
    match node:
        case ast.Constant(value=value):
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        case ast.UnaryOp(op=ast.UAdd() | ast.USub(), operand=operand):
            return _is_numeric_expression(operand)
        case ast.BinOp(left=left, right=right):
            return _is_numeric_expression(left) and _is_numeric_expression(right)
        case _:
            return False


def _contains_float(node: ast.AST) -> bool:
    return any(isinstance(child, ast.Constant) and isinstance(child.value, float) for child in ast.walk(node))


def _exclusively_serialized_duration_constants(tree: ast.Module, imports: ImportIndex) -> frozenset[str]:
    """Find numeric constants whose reads are proven wire-model construction only."""
    definitions = {
        statement.targets[0].id: statement.targets[0]
        for statement in tree.body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and _is_numeric_expression(statement.value)
        and _is_constant_reference(statement.targets[0].id)
    }
    if not definitions:
        return frozenset()
    wire_models = _wire_model_class_names(tree, imports)
    if not wire_models:
        return frozenset()
    parent = {id(child): owner for owner in ast.walk(tree) for child in ast.iter_child_nodes(owner)}
    serialized: set[str] = set()
    for name, target in definitions.items():
        if _has_competing_binding(tree, name, target):
            continue
        loads = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == name
        ]
        if loads and all(_is_wire_model_value(load, parent, wire_models) for load in loads):
            serialized.add(name)
    return frozenset(serialized)


def _has_competing_binding(tree: ast.Module, name: str, definition: ast.Name) -> bool:
    """Reject lexical ambiguity rather than attributing shadowed reads to a constant."""
    for node in ast.walk(tree):
        match node:
            case ast.Name(id=identifier, ctx=ast.Store()) if identifier == name and node is not definition:
                return True
            case ast.arg(arg=identifier) if identifier == name:
                return True
            case (
                ast.FunctionDef(name=identifier) | ast.AsyncFunctionDef(name=identifier) | ast.ClassDef(name=identifier)
            ) if identifier == name:
                return True
            case ast.alias(name=imported, asname=alias) if (alias or imported.split(".")[0]) == name:
                return True
            case ast.ExceptHandler(name=identifier) if identifier == name:
                return True
            case ast.MatchAs(name=identifier) | ast.MatchStar(name=identifier) if identifier == name:
                return True
            case ast.MatchMapping(rest=identifier) if identifier == name:
                return True
            case _:
                pass
    return False


def _is_wire_model_value(
    load: ast.Name,
    parents: dict[int, ast.AST],
    wire_models: frozenset[str],
) -> bool:
    parent = parents.get(id(load))
    if isinstance(parent, ast.keyword) and parent.value is load:
        call = parents.get(id(parent))
        return isinstance(call, ast.Call) and _trailing_name(call.func) in wire_models
    if not (isinstance(parent, ast.Dict) and any(value is load for value in parent.values)):
        return False
    returned = parents.get(id(parent))
    if not (isinstance(returned, ast.Return) and returned.value is parent):
        return False
    owner = parents.get(id(returned))
    while owner is not None and not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
        owner = parents.get(id(owner))
    return owner is not None and bool(_annotation_names(owner.returns) & wire_models)


def _annotation_names(node: ast.expr | None) -> frozenset[str]:
    if node is None:
        return frozenset()
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value.strip(), mode="eval").body
        except SyntaxError:
            return frozenset()
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _annotation_names(node.left) | _annotation_names(node.right)
    if isinstance(node, ast.Subscript) and _trailing_name(node.value) in {"Annotated", "Optional"}:
        inner = node.slice.elts[0] if isinstance(node.slice, ast.Tuple) and node.slice.elts else node.slice
        return _annotation_names(inner)
    name = _trailing_name(node)
    return frozenset({name}) if name is not None else frozenset()


def _wire_model_class_names(tree: ast.Module, imports: ImportIndex) -> frozenset[str]:
    """Resolve locally declared Pydantic and TypedDict wire models."""
    classes = nodes(tree, ast.ClassDef)
    by_name: dict[str, list[ast.ClassDef]] = {}
    for node in classes:
        by_name.setdefault(node.name, []).append(node)
    resolved: dict[int, bool] = {}

    def is_wire_model(node: ast.ClassDef, seen: frozenset[int]) -> bool:
        cached = resolved.get(id(node))
        if cached is not None:
            return cached
        if id(node) in seen:
            return False
        result = any(
            imports.resolves(
                base,
                sources=frozenset(
                    {
                        "pydantic",
                        "pydantic.main",
                        "pydantic.v1",
                        "pydantic.v1.main",
                    }
                ),
                symbol="BaseModel",
            )
            or imports.resolves(
                base,
                sources=frozenset({"typing", "typing_extensions"}),
                symbol="TypedDict",
            )
            or (
                (base_name := _trailing_name(base)) is not None
                and len(parents := by_name.get(base_name, ())) == 1
                and is_wire_model(parents[0], seen | {id(node)})
            )
            for base in node.bases
        )
        resolved[id(node)] = result
        return result

    return frozenset(
        name
        for name, definitions in by_name.items()
        if len(definitions) == 1 and is_wire_model(definitions[0], frozenset())
    )


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
    """Collect the annotated parameters whose names read as durations."""
    return frozenset(
        a.arg
        for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
        if a.annotation is not None and _UNIT_RE.search(a.arg) and not _EXCLUDE_RE.search(a.arg)
    )


def _same_name_forwarded_params(node: ast.FunctionDef | ast.AsyncFunctionDef, params: frozenset[str]) -> frozenset[str]:
    """Collect parameters used only as same-named sinks, never in duration arithmetic."""
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
    """Report whether `parent` consumes a load of `name` under that same name."""
    match parent:
        case ast.keyword(arg=str(keyword)):
            return keyword == name
        case ast.Assign(targets=[ast.Attribute(attr=attribute)]) | ast.AnnAssign(target=ast.Attribute(attr=attribute)):
            return attribute == name
        case _:
            return False


def _admits_timedelta(node: ast.expr) -> bool:
    """Report whether the annotation already accepts a `timedelta`."""
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


def _pydantic_model_field_ids(tree: ast.Module, imports: ImportIndex) -> frozenset[int]:
    """Exclude import-proven Pydantic schema fields whose numeric unit is their wire contract."""
    classes = nodes(tree, ast.ClassDef)
    by_name: dict[str, list[ast.ClassDef]] = {}
    for node in classes:
        by_name.setdefault(node.name, []).append(node)
    resolved: dict[int, bool] = {}

    def is_model(node: ast.ClassDef, seen: frozenset[int]) -> bool:
        cached = resolved.get(id(node))
        if cached is not None:
            return cached
        if id(node) in seen:
            return False
        result = any(
            imports.resolves(
                base,
                sources=frozenset({"pydantic", "pydantic.main", "pydantic.v1", "pydantic.v1.main"}),
                symbol="BaseModel",
            )
            or (
                (base_name := _trailing_name(base)) is not None
                and len(parents := by_name.get(base_name, ())) == 1
                and is_model(parents[0], seen | {id(node)})
            )
            for base in node.bases
        )
        resolved[id(node)] = result
        return result

    return frozenset(
        id(statement)
        for node in classes
        if is_model(node, frozenset())
        for statement in node.body
        if isinstance(statement, ast.AnnAssign)
    )


def _typed_dict_field_ids(tree: ast.Module, imports: ImportIndex) -> frozenset[int]:
    """Exclude import-proven TypedDict fields whose numeric unit is a wire contract."""
    classes = nodes(tree, ast.ClassDef)
    by_name = {node.name: node for node in classes}
    resolved: dict[int, bool] = {}

    def is_typed_dict(node: ast.ClassDef, seen: frozenset[int]) -> bool:
        cached = resolved.get(id(node))
        if cached is not None:
            return cached
        if id(node) in seen:
            return False
        result = any(
            imports.resolves(
                base,
                sources=frozenset({"typing", "typing_extensions"}),
                symbol="TypedDict",
            )
            or (
                (name := _trailing_name(base)) is not None
                and (parent := by_name.get(name)) is not None
                and is_typed_dict(parent, seen | {id(node)})
            )
            for base in node.bases
        )
        resolved[id(node)] = result
        return result

    return frozenset(
        id(statement)
        for node in classes
        if is_typed_dict(node, frozenset())
        for statement in node.body
        if isinstance(statement, ast.AnnAssign)
    )


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
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(attr=attr):
            return attr
        case ast.Subscript(value=value):
            return _trailing_name(value)
        case _:
            return None


def _is_named(node: ast.expr, name: str) -> bool:
    return _trailing_name(node) == name

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum
from io import StringIO
from itertools import pairwise
from pathlib import PurePosixPath
import tokenize
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    is_suppressed,
)
from sarj_python_lint.rules._ast_index import walk as walk_ast


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._ast_index import NodeIndex


_Callable = ast.FunctionDef | ast.AsyncFunctionDef
_Init = ast.Assign | ast.AnnAssign
_PROHIBITED_EXPRESSION_NODES = (
    ast.Await,
    ast.DictComp,
    ast.GeneratorExp,
    ast.Lambda,
    ast.ListComp,
    ast.NamedExpr,
    ast.SetComp,
    ast.Yield,
    ast.YieldFrom,
)
_MAX_REPLACEMENT_WIDTH = 120


class _CollectionKind(StrEnum):
    DICT = "dict"
    LIST = "list"
    SET = "set"


@dataclass(frozen=True)
class _InitializedCollection:
    name: str
    kind: _CollectionKind


@dataclass(frozen=True)
class _Candidate:
    kind: _CollectionKind
    name: str
    action: str = "populates"


@dataclass(frozen=True)
class _LoopReplacement:
    kind: _CollectionKind
    expression: str
    action: str = "populates"
    allow_multiline: bool = False


@final
class PreferCollectionComprehension(Rule):
    id = "prefer-collection-comprehension"
    code = "SARJ430"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Single-purpose fresh collection builder loop — prefer a direct comprehension.",
        rationale=(
            "An empty collection followed by a loop whose only behavior is one projection or filtered insertion "
            "spreads a declarative map/filter across mutable scaffolding."
        ),
        remediation=(
            "Build the fresh collection with one dict, list, or set comprehension. When a list candidate must be "
            "computed once and reused in the element, bind it in the filter with :=. Keep the loop when mutation "
            "is incremental, evaluation order is observable, or the imperative form carries additional behavior."
        ),
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only function-local, adjacent empty initializers and one synchronous single-purpose loop are checked.",
            (
                "The rule fills gaps left by Ruff PERF401, PERF403, and FURB142: derived dict projections, "
                "destructured list projections, narrowly filtered computed list candidates, and filtered set "
                "builders."
            ),
            (
                "Comments, loop-target leakage, try blocks, aliases, complex projections, and replacements that "
                "do not fit a 120-column line or a simple formatter-style multiline comprehension are excluded. "
                "No autofix is offered because dict key/value evaluation order can differ."
            ),
            (
                "Attribute projections can invoke properties or descriptors, so reviewers should keep the loop "
                "when the relative order of those reads is observable."
            ),
            (
                "Computed list candidates are limited to one local assignment, a truthiness or None filter, and "
                "one bounded projection. Validation, logging, exceptions, multiple guards, and secondary mutation "
                "remain imperative."
            ),
        ),
        examples=(
            RuleExample(
                example_id="derived-dict-projection-loop",
                title="Build a projected dictionary directly",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/capacity.py",
                        "def organization_caps(rows):\n"
                        "    caps: dict[str, int] = {}\n"
                        "    for row in rows:\n"
                        "        caps[row.organization_id] = row.organization_cap\n"
                        "    return caps\n",
                    ),
                ),
                focus_path=PurePosixPath("app/capacity.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="computed-filtered-list-loop",
                title="Compute and filter a list candidate directly",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/intervals.py",
                        "def clipped(items, bounds):\n"
                        "    result: list[Interval] = []\n"
                        "    for item in items:\n"
                        "        value = item.clipped(bounds)\n"
                        "        if value is not None:\n"
                        "            result.append(value)\n"
                        "    return result\n",
                    ),
                ),
                focus_path=PurePosixPath("app/intervals.py"),
                expected_count=1,
                public=True,
                scenario="computed-filter",
            ),
            RuleExample(
                example_id="computed-filtered-list-comprehension",
                title="Keep a computed filtered list declarative",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/intervals.py",
                        "def clipped(items, bounds):\n"
                        "    return [\n"
                        "        value\n"
                        "        for item in items\n"
                        "        if (value := item.clipped(bounds)) is not None\n"
                        "    ]\n",
                    ),
                ),
                focus_path=PurePosixPath("app/intervals.py"),
                expected_count=0,
                public=True,
                scenario="computed-filter",
            ),
            RuleExample(
                example_id="direct-dict-comprehension",
                title="Keep the collection projection declarative",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/capacity.py",
                        "def organization_caps(rows):\n"
                        "    return {row.organization_id: row.organization_cap for row in rows}\n",
                    ),
                ),
                focus_path=PurePosixPath("app/capacity.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        source = context.source
        if context.generated:
            return []
        tree = context.tree
        if tree is None:
            return []

        source_lines = context.source_lines
        comments = _comment_lines(source)
        diagnostics: list[Diagnostic] = []
        for owner in (node for node in context.nodes(ast.AST) if isinstance(node, _Callable)):
            for block in _statement_blocks(owner.body):
                for init, loop in pairwise(block):
                    finding = _candidate(
                        tree,
                        owner,
                        init=init,
                        loop=loop,
                        source_lines=source_lines,
                        comments=comments,
                        node_index=context.node_index,
                    )
                    if finding is None:
                        continue
                    diagnostics.append(
                        Diagnostic(
                            path=path,
                            line=loop.lineno,
                            col=loop.col_offset + 1,
                            code=self.code,
                            message=_message(finding),
                        )
                    )
        return sorted(diagnostics, key=lambda diagnostic: (diagnostic.line, diagnostic.col))


def _statement_blocks(body: list[ast.stmt]) -> Iterator[list[ast.stmt]]:
    yield body
    for statement in body:
        match statement:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() | ast.Try() | ast.TryStar():
                continue
            case ast.If() | ast.For() | ast.While():
                yield from _statement_blocks(statement.body)
                yield from _statement_blocks(statement.orelse)
            case ast.With() | ast.AsyncWith():
                continue
            case ast.Match(cases=cases):
                for case in cases:
                    yield from _statement_blocks(case.body)
            case _:
                continue


def _candidate(
    tree: ast.Module,
    owner: _Callable,
    *,
    init: ast.stmt,
    loop: ast.stmt,
    source_lines: list[str],
    comments: frozenset[int],
    node_index: NodeIndex | None = None,
) -> _Candidate | None:
    if not isinstance(init, _Init) or not isinstance(loop, ast.For) or loop.orelse:
        return None
    initialized = _initialized_collection(init)
    if initialized is None:
        return None
    name = initialized.name
    if initialized.kind is _CollectionKind.SET and _set_is_shadowed(tree, node_index=node_index):
        return None
    if _has_comment(init, loop, comments) or is_suppressed(
        source_lines, loop.lineno, PreferCollectionComprehension.code
    ):
        return None
    bound_names = _bound_names(loop.target)
    if not bound_names or _contains_starred(loop.target) or name in bound_names:
        return None
    if _target_binding_is_observable(owner, bound_names, loop):
        return None
    if (
        _loads_name(loop.iter, name)
        or _contains_prohibited_expression(loop.iter)
        or _declares_external(owner, frozenset({name}))
    ):
        return None

    replacement = _loop_replacement(loop, name, initialized.kind, bound_names, owner)
    if replacement is None or not _replacement_fits(
        init, name, replacement.expression, allow_multiline=replacement.allow_multiline
    ):
        return None
    return _Candidate(kind=replacement.kind, name=name, action=replacement.action)


def _initialized_collection(statement: _Init) -> _InitializedCollection | None:
    match statement:
        case ast.Assign(targets=[ast.Name(id=name)], value=ast.Dict(keys=[], values=[])):
            return _InitializedCollection(name, _CollectionKind.DICT)
        case ast.Assign(targets=[ast.Name(id=name)], value=ast.List(elts=[])):
            return _InitializedCollection(name, _CollectionKind.LIST)
        case ast.Assign(targets=[ast.Name(id=name)], value=ast.Call(func=ast.Name(id="set"), args=[], keywords=[])):
            return _InitializedCollection(name, _CollectionKind.SET)
        case ast.AnnAssign(target=ast.Name(id=name), value=ast.Dict(keys=[], values=[]), simple=1):
            return _InitializedCollection(name, _CollectionKind.DICT)
        case ast.AnnAssign(target=ast.Name(id=name), value=ast.List(elts=[]), simple=1):
            return _InitializedCollection(name, _CollectionKind.LIST)
        case ast.AnnAssign(
            target=ast.Name(id=name),
            value=ast.Call(func=ast.Name(id="set"), args=[], keywords=[]),
            simple=1,
        ):
            return _InitializedCollection(name, _CollectionKind.SET)
        case _:
            return None


def _loop_replacement(
    loop: ast.For,
    name: str,
    initialized_kind: _CollectionKind,
    bound_names: frozenset[str],
    owner: _Callable,
) -> _LoopReplacement | None:
    if initialized_kind is _CollectionKind.DICT and len(loop.body) == 1:
        match loop.body[0]:
            case ast.Assign(targets=[ast.Subscript(value=ast.Name(id=target), slice=key)], value=value) if (
                target == name
            ):
                if _valid_dict_projection(key, value, name, bound_names):
                    return _LoopReplacement(
                        _CollectionKind.DICT,
                        f"{{{ast.unparse(key)}: {ast.unparse(value)} for {ast.unparse(loop.target)} "
                        f"in {ast.unparse(loop.iter)}}}",
                    )
            case _:
                pass
    if initialized_kind is _CollectionKind.LIST:
        replacement = _list_replacement(loop, name, bound_names, owner)
        if replacement is not None:
            return replacement
    if initialized_kind is _CollectionKind.SET and len(loop.body) == 1:
        return _set_replacement(loop, name, bound_names)
    return None


def _list_replacement(
    loop: ast.For, name: str, bound_names: frozenset[str], owner: _Callable
) -> _LoopReplacement | None:
    if len(bound_names) > 1 and len(loop.body) == 1:
        expression = _single_method_argument(loop.body[0], name, "append")
        if expression is not None and not _loads_name(expression, name) and _simple_projection(expression, bound_names):
            return _LoopReplacement(
                _CollectionKind.LIST,
                f"[{ast.unparse(expression)} for {ast.unparse(loop.target)} in {ast.unparse(loop.iter)}]",
            )

    filtered = _filtered_list_parts(loop.body, name)
    if filtered is not None and len(bound_names) > 1:
        expression, test, inverted = filtered
        if (
            not _loads_name(expression, name)
            and not _loads_name(test, name)
            and _simple_projection(expression, bound_names)
            and not _contains_prohibited_expression(test)
        ):
            condition = _condition_source(test, inverted=inverted)
            return _LoopReplacement(
                _CollectionKind.LIST,
                f"[{ast.unparse(expression)} for {ast.unparse(loop.target)} in {ast.unparse(loop.iter)} "
                f"if {condition}]",
                "filters and appends to",
                allow_multiline=True,
            )

    return _computed_list_replacement(loop, name, bound_names, owner)


def _filtered_list_parts(body: list[ast.stmt], name: str) -> tuple[ast.expr, ast.expr, bool] | None:
    match body:
        case [ast.If(test=test, body=[statement], orelse=[])]:
            expression = _single_method_argument(statement, name, "append")
            if expression is not None:
                return expression, test, False
        case [ast.If(test=test, body=[ast.Continue()], orelse=[]), statement]:
            expression = _single_method_argument(statement, name, "append")
            if expression is not None:
                return expression, test, True
        case _:
            pass
    return None


def _computed_list_replacement(
    loop: ast.For, name: str, bound_names: frozenset[str], owner: _Callable
) -> _LoopReplacement | None:
    match loop.body:
        case [ast.Assign(targets=[ast.Name(id=candidate)], value=value), *tail]:
            pass
        case _:
            return None

    if candidate == name or candidate in bound_names:
        return None
    if _target_binding_is_observable(owner, frozenset({candidate}), loop):
        return None
    if _loads_name(value, name) or _contains_prohibited_expression(value):
        return None

    filtered = _filtered_list_parts(tail, name)
    if filtered is None:
        return None
    expression, test, inverted = filtered
    condition_kind = _computed_condition_kind(test, candidate, inverted=inverted)
    if condition_kind is None:
        return None
    if _loads_name(expression, name) or not _loads_name(expression, candidate):
        return None
    projection_names = bound_names | frozenset({candidate})
    if not _bounded_list_projection(expression, projection_names):
        return None

    assignment = f"({candidate} := {ast.unparse(value)})"
    condition = assignment if condition_kind == "truthy" else f"{assignment} is not None"
    return _LoopReplacement(
        _CollectionKind.LIST,
        f"[{ast.unparse(expression)} for {ast.unparse(loop.target)} in {ast.unparse(loop.iter)} if {condition}]",
        "computes, filters, and appends to",
        allow_multiline=True,
    )


def _computed_condition_kind(test: ast.expr, candidate: str, *, inverted: bool) -> str | None:
    if not inverted and isinstance(test, ast.Name) and test.id == candidate:
        return "truthy"
    if (
        inverted
        and isinstance(test, ast.UnaryOp)
        and isinstance(test.op, ast.Not)
        and isinstance(test.operand, ast.Name)
        and test.operand.id == candidate
    ):
        return "truthy"
    match test:
        case ast.Compare(left=ast.Name(id=left), ops=[operator], comparators=[ast.Constant(value=None)]) if (
            left == candidate
            and ((not inverted and isinstance(operator, ast.IsNot)) or (inverted and isinstance(operator, ast.Is)))
        ):
            return "not-none"
        case _:
            return None


def _bounded_list_projection(node: ast.expr, names: frozenset[str]) -> bool:
    if _simple_projection(node, names):
        return True
    match node:
        case ast.Call(func=func, args=args, keywords=keywords):
            if any(isinstance(argument, ast.Starred) for argument in args):
                return False
            if any(keyword.arg is None for keyword in keywords):
                return False
            if not _dotted_name(func):
                return False
            values = (*args, *(keyword.value for keyword in keywords))
            return all(
                not any(isinstance(item, ast.Call) for item in walk_ast(value))
                and not _contains_prohibited_expression(value)
                for value in values
            )
        case _:
            return False


def _dotted_name(node: ast.expr) -> bool:
    match node:
        case ast.Name():
            return True
        case ast.Attribute(value=value):
            return _dotted_name(value)
        case _:
            return False


def _condition_source(test: ast.expr, *, inverted: bool) -> str:
    if not inverted:
        return ast.unparse(test)
    return ast.unparse(ast.UnaryOp(op=ast.Not(), operand=test))


def _single_method_argument(statement: ast.stmt, name: str, method: str) -> ast.expr | None:
    match statement:
        case ast.Expr(
            value=ast.Call(
                func=ast.Attribute(value=ast.Name(id=receiver), attr=called),
                args=[argument],
                keywords=[],
            )
        ) if receiver == name and called == method:
            return argument
        case _:
            return None


def _simple_projection(node: ast.AST, bound_names: frozenset[str]) -> bool:
    match node:
        case ast.Name(id=name):
            return name in bound_names
        case ast.Constant():
            return True
        case ast.Attribute(value=value):
            return _simple_projection(value, bound_names)
        case ast.Tuple() | ast.List():
            return bool(node.elts) and all(_simple_projection(element, bound_names) for element in node.elts)
        case _:
            return False


def _valid_dict_projection(key: ast.expr, value: ast.expr, name: str, bound_names: frozenset[str]) -> bool:
    if _loads_name(key, name) or _loads_name(value, name):
        return False
    return (
        _simple_projection(key, bound_names)
        and _simple_projection(value, bound_names)
        and (_is_derived(key) or _is_derived(value))
    )


def _is_derived(node: ast.AST) -> bool:
    return isinstance(node, (ast.Attribute, ast.Tuple, ast.List))


def _bound_names(target: ast.expr) -> frozenset[str]:
    return frozenset(
        node.id for node in walk_ast(target) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    )


def _contains_starred(target: ast.expr) -> bool:
    return any(isinstance(node, ast.Starred) for node in walk_ast(target))


def _loads_name(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load) and item.id == name for item in walk_ast(node)
    )


def _contains_prohibited_expression(node: ast.AST) -> bool:
    return any(isinstance(item, _PROHIBITED_EXPRESSION_NODES) for item in walk_ast(node))


def _target_binding_is_observable(owner: _Callable, names: frozenset[str], loop: ast.For) -> bool:
    if _declares_external(owner, names) or any(_loads_name(loop.iter, name) for name in names):
        return True
    end_line = loop.end_lineno or loop.lineno
    for node in walk_ast(owner):
        if isinstance(node, ast.arg) and node.arg in names:
            return True
        if (
            isinstance(node, ast.Name)
            and node.id in names
            and (
                getattr(node, "lineno", loop.lineno) < loop.lineno
                or (getattr(node, "lineno", 0) > end_line and isinstance(node.ctx, (ast.Load, ast.Del)))
            )
        ):
            return True
    return False


def _declares_external(owner: _Callable, names: frozenset[str]) -> bool:
    return any(
        isinstance(node, (ast.Global, ast.Nonlocal)) and not names.isdisjoint(node.names) for node in walk_ast(owner)
    )


def _set_is_shadowed(tree: ast.Module, *, node_index: NodeIndex | None = None) -> bool:
    for node in walk_ast(tree, index=node_index):
        match node:
            case (
                ast.arg(arg="set")
                | ast.Name(id="set", ctx=ast.Store())
                | ast.ExceptHandler(name="set")
                | ast.MatchAs(name="set")
                | ast.MatchStar(name="set")
                | ast.MatchMapping(rest="set")
                | ast.FunctionDef(name="set")
                | ast.AsyncFunctionDef(name="set")
                | ast.ClassDef(name="set")
            ):
                return True
            case ast.Import(names=names) | ast.ImportFrom(names=names) if any(
                (alias.asname or alias.name) == "set" for alias in names
            ):
                return True
            case _:
                continue
    return False


def _replacement_fits(init: _Init, name: str, expression: str, *, allow_multiline: bool = False) -> bool:
    prefix = f"{name} = "
    if isinstance(init, ast.AnnAssign):
        prefix = f"{name}: {ast.unparse(init.annotation)} = "
    if init.col_offset + len(prefix) + len(expression) <= _MAX_REPLACEMENT_WIDTH:
        return True
    if not allow_multiline or not (expression.startswith("[") and expression.endswith("]")):
        return False
    content = expression[1:-1]
    return (
        init.col_offset + len(prefix) + 1 <= _MAX_REPLACEMENT_WIDTH
        and init.col_offset + 4 + len(content) <= _MAX_REPLACEMENT_WIDTH
    )


def _comment_lines(source: str) -> frozenset[int]:
    try:
        tokens = tokenize.generate_tokens(StringIO(source).readline)
        return frozenset(token.start[0] for token in tokens if token.type == tokenize.COMMENT)
    except IndentationError, tokenize.TokenError:
        return frozenset()


def _has_comment(init: _Init, loop: ast.For, comments: frozenset[int]) -> bool:
    end_line = loop.end_lineno or loop.lineno
    return any(init.lineno <= line <= end_line for line in comments)


def _set_replacement(loop: ast.For, name: str, bound_names: frozenset[str]) -> _LoopReplacement | None:
    match loop.body[0]:
        case ast.If(test=test, body=[body], orelse=[]):
            expression = _single_method_argument(body, name, "add")
            if (
                expression is not None
                and not _loads_name(test, name)
                and not _loads_name(expression, name)
                and _simple_projection(expression, bound_names)
                and not _contains_prohibited_expression(test)
            ):
                return _LoopReplacement(
                    _CollectionKind.SET,
                    f"{{{ast.unparse(expression)} for {ast.unparse(loop.target)} in {ast.unparse(loop.iter)} "
                    f"if {ast.unparse(test)}}}",
                )
        case _:
            pass
    return None


def _message(finding: _Candidate) -> str:
    qualifier = "filtered " if finding.action != "populates" else ""
    return (
        f"This loop only {finding.action} fresh {finding.kind} {finding.name!r} — prefer a "
        f"{qualifier}{finding.kind} comprehension."
    )

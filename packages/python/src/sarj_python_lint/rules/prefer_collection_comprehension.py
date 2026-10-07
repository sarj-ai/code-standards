from __future__ import annotations

import ast
from collections import defaultdict
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
from sarj_python_lint.rules._ast_index import children, walk as walk_ast


if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

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


@dataclass(frozen=True)
class _OwnerBindings:
    names: dict[str, list[ast.Name | ast.arg]]
    external: frozenset[str]
    local_nodes: frozenset[int]
    captured: frozenset[str]
    observes_namespace: bool


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
                "constructor-valued and filtered dict projections, destructured list projections, narrowly filtered computed list candidates, and filtered set "
                "builders."
            ),
            (
                "Comments, loop-target leakage, try blocks, aliases, complex projections, and replacements that "
                "do not fit a 120-column line or a simple formatter-style multiline comprehension are excluded. "
                "Namespace observers, explicit inspect/sys frame access, and collections referenced by nested functions "
                "are excluded. No autofix is offered because dict key/value evaluation order can differ."
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
                example_id="constructor-dict-projection-loop",
                title="Build constructor-valued dictionaries directly",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/views.py",
                        "def views(rows, labels):\n"
                        "    result = {}\n"
                        "    for row in rows:\n"
                        "        result[row.id] = EntryView(id=row.id, label=labels.get(row.id))\n"
                        "    return result\n",
                    ),
                ),
                focus_path=PurePosixPath("app/views.py"),
                expected_count=1,
                public=True,
                scenario="constructor-dict",
            ),
            RuleExample(
                example_id="constructor-dict-comprehension",
                title="Keep constructor-valued dictionaries declarative",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/views.py",
                        "def views(rows, labels):\n"
                        "    return {row.id: EntryView(id=row.id, label=labels.get(row.id)) for row in rows}\n",
                    ),
                ),
                focus_path=PurePosixPath("app/views.py"),
                expected_count=0,
                public=True,
                scenario="constructor-dict",
            ),
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
        set_shadowed = _set_is_shadowed(tree, node_index=context.node_index)
        namespace_observers = _namespace_observer_calls(context)
        for owner in (node for node in context.nodes(ast.AST) if isinstance(node, _Callable)):
            for finding, loop in _owner_candidates(
                owner, source_lines, comments, namespace_observers, set_shadowed=set_shadowed
            ):
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


def _owner_candidates(
    owner: _Callable,
    source_lines: list[str],
    comments: frozenset[int],
    namespace_observers: frozenset[int],
    *,
    set_shadowed: bool,
) -> Iterator[tuple[_Candidate, ast.For]]:
    bindings = None
    for block in _statement_blocks(owner.body):
        for init, loop in pairwise(block):
            if not isinstance(init, _Init) or not isinstance(loop, ast.For) or _initialized_collection(init) is None:
                continue
            if bindings is None:
                bindings = _owner_bindings(owner, namespace_observers)
            finding = _candidate(
                bindings,
                init=init,
                loop=loop,
                source_lines=source_lines,
                comments=comments,
                set_shadowed=set_shadowed,
            )
            if finding is not None:
                yield finding, loop


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
    bindings: _OwnerBindings,
    *,
    init: ast.stmt,
    loop: ast.stmt,
    source_lines: list[str],
    comments: frozenset[int],
    set_shadowed: bool,
) -> _Candidate | None:
    if not isinstance(init, _Init) or not isinstance(loop, ast.For) or loop.orelse:
        return None
    initialized = _initialized_collection(init)
    if initialized is None:
        return None
    name = initialized.name
    if bindings.observes_namespace or name in bindings.captured:
        return None
    if initialized.kind is _CollectionKind.SET and set_shadowed:
        return None
    if _has_comment(init, loop, comments) or is_suppressed(
        source_lines, loop.lineno, PreferCollectionComprehension.code
    ):
        return None
    bound_names = _bound_names(loop.target)
    if not bound_names or _contains_starred(loop.target) or name in bound_names:
        return None
    if _target_binding_is_observable(bindings, bound_names, loop):
        return None
    if _loads_name(loop.iter, name) or _contains_prohibited_expression(loop.iter) or name in bindings.external:
        return None

    try:
        replacement = _loop_replacement(loop, name, initialized.kind, bound_names, bindings)
        fits = replacement is not None and _replacement_fits(
            init, name, replacement.expression, allow_multiline=replacement.allow_multiline
        )
    except RecursionError, SyntaxError:
        return None
    if replacement is None or not fits:
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
    bindings: _OwnerBindings,
) -> _LoopReplacement | None:
    if initialized_kind is _CollectionKind.DICT:
        return _dict_replacement(loop, name, bound_names)
    if initialized_kind is _CollectionKind.LIST:
        replacement = _list_replacement(loop, name, bound_names, bindings)
        if replacement is not None:
            return replacement
    if initialized_kind is _CollectionKind.SET:
        return _set_replacement(loop, name, bound_names)
    return None


def _dict_replacement(loop: ast.For, name: str, bound_names: frozenset[str]) -> _LoopReplacement | None:
    condition = ""
    filtered = _filtered_statement_parts(loop.body)
    if filtered is not None:
        statement, test, inverted = filtered
        if _loads_name(test, name) or _contains_prohibited_expression(test):
            return None
        condition = f" if {_condition_source(test, inverted=inverted)}"
    elif len(loop.body) == 1:
        statement = loop.body[0]
    else:
        return None
    match statement:
        case ast.Assign(targets=[ast.Subscript(value=ast.Name(id=target), slice=key)], value=value) if target == name:
            pass
        case _:
            return None
    if not _valid_dict_projection(key, value, name, bound_names):
        return None
    return _LoopReplacement(
        _CollectionKind.DICT,
        f"{{{ast.unparse(key)}: {ast.unparse(value)} for {ast.unparse(loop.target)} "
        f"in {_comprehension_expression_source(loop.iter)}{condition}}}",
        "filters and populates" if filtered is not None else "populates",
        allow_multiline=isinstance(value, ast.Call),
    )


def _list_replacement(
    loop: ast.For, name: str, bound_names: frozenset[str], bindings: _OwnerBindings
) -> _LoopReplacement | None:
    if len(bound_names) > 1 and len(loop.body) == 1:
        expression = _single_method_argument(loop.body[0], name, "append")
        if expression is not None and not _loads_name(expression, name) and _simple_projection(expression, bound_names):
            return _LoopReplacement(
                _CollectionKind.LIST,
                f"[{ast.unparse(expression)} for {ast.unparse(loop.target)} in {_comprehension_expression_source(loop.iter)}]",
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
                f"[{ast.unparse(expression)} for {ast.unparse(loop.target)} in {_comprehension_expression_source(loop.iter)} "
                f"if {condition}]",
                "filters and appends to",
                allow_multiline=True,
            )

    return _computed_list_replacement(loop, name, bound_names, bindings)


def _filtered_statement_parts(body: list[ast.stmt]) -> tuple[ast.stmt, ast.expr, bool] | None:
    match body:
        case [ast.If(test=test, body=[statement], orelse=[])]:
            return statement, test, False
        case [ast.If(test=test, body=[ast.Continue()], orelse=[]), statement]:
            return statement, test, True
        case _:
            return None


def _filtered_list_parts(body: list[ast.stmt], name: str) -> tuple[ast.expr, ast.expr, bool] | None:
    parts = _filtered_statement_parts(body)
    if parts is None:
        return None
    statement, test, inverted = parts
    expression = _single_method_argument(statement, name, "append")
    return (expression, test, inverted) if expression is not None else None


def _computed_list_replacement(
    loop: ast.For, name: str, bound_names: frozenset[str], bindings: _OwnerBindings
) -> _LoopReplacement | None:
    match loop.body:
        case [ast.Assign(targets=[ast.Name(id=candidate)], value=value), *tail]:
            pass
        case _:
            return None

    if candidate == name or candidate in bound_names:
        return None
    if _target_binding_is_observable(bindings, frozenset({candidate}), loop):
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
        f"[{ast.unparse(expression)} for {ast.unparse(loop.target)} in {_comprehension_expression_source(loop.iter)} if {condition}]",
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


def _comprehension_expression_source(iterable: ast.expr) -> str:
    source = ast.unparse(iterable)
    return f"({source})" if isinstance(iterable, ast.IfExp) else source


def _condition_source(test: ast.expr, *, inverted: bool) -> str:
    if not inverted:
        return _comprehension_expression_source(test)
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
        and (_simple_projection(value, bound_names) or _constructor_projection(value))
        and (_is_derived(key) or _is_derived(value) or isinstance(value, ast.Call))
    )


def _constructor_projection(node: ast.expr) -> bool:
    if not isinstance(node, ast.Call) or _contains_prohibited_expression(node):
        return False
    return all(
        _dotted_name(call.func)
        and not any(isinstance(argument, ast.Starred) for argument in call.args)
        and all(keyword.arg is not None for keyword in call.keywords)
        for call in walk_ast(node)
        if isinstance(call, ast.Call)
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


def _owner_bindings(owner: _Callable, namespace_observers: frozenset[int]) -> _OwnerBindings:
    nodes = tuple(walk_ast(owner))
    names: defaultdict[str, list[ast.Name | ast.arg]] = defaultdict(list)
    for node in nodes:
        if isinstance(node, ast.Name):
            names[node.id].append(node)
        elif isinstance(node, ast.arg):
            names[node.arg].append(node)
    return _OwnerBindings(
        names=dict(names),
        external=frozenset(
            name for node in nodes if isinstance(node, (ast.Global, ast.Nonlocal)) for name in node.names
        ),
        local_nodes=frozenset(_comprehension_local_nodes(nodes, frozenset(names))),
        captured=_captured_names(owner),
        observes_namespace=any(id(node) in namespace_observers for node in nodes),
    )


def _namespace_observer_calls(context: PythonFileContext) -> frozenset[int]:
    observers = {
        "builtins": {"locals", "vars", "eval", "exec"},
        "inspect": {"currentframe"},
        "sys": {"_getframe"},
    }
    # Explicit aliases remain conservative exclusions even when another scope shadows them.
    modules: defaultdict[str, set[str]] = defaultdict(set)
    symbols = observers["builtins"].copy()
    for node in context.nodes(ast.Import):
        for alias in node.names:
            if alias.name in observers:
                modules[alias.asname or alias.name].update(observers[alias.name])
    for node in context.nodes(ast.ImportFrom):
        if node.module not in observers:
            continue
        symbols.update(alias.asname or alias.name for alias in node.names if alias.name in observers[node.module])
    return frozenset(
        id(call) for call in context.nodes(ast.Call) if _is_namespace_observer(call.func, symbols, modules)
    )


def _is_namespace_observer(function: ast.expr, symbols: set[str], modules: dict[str, set[str]]) -> bool:
    match function:
        case ast.Name(id=name):
            return name in symbols
        case ast.Attribute(value=ast.Name(id=module), attr=symbol):
            return module in modules and symbol in modules[module]
        case _:
            return False


def _captured_names(owner: _Callable) -> frozenset[str]:
    captured: set[str] = set()
    pending: list[tuple[ast.AST, bool]] = [(owner, False)]
    while pending:
        node, nested = pending.pop()
        nested = nested or (node is not owner and isinstance(node, (_Callable, ast.Lambda, ast.ClassDef)))
        if nested and isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            captured.add(node.id)
        pending.extend((child, nested) for child in children(node))
    return frozenset(captured)


def _target_binding_is_observable(bindings: _OwnerBindings, names: frozenset[str], loop: ast.For) -> bool:
    if not bindings.external.isdisjoint(names) or any(_loads_name(loop.iter, name) for name in names):
        return True
    end_line = loop.end_lineno or loop.lineno
    for name in names:
        for node in bindings.names.get(name, []):
            if isinstance(node, ast.arg):
                return True
            if id(node) in bindings.local_nodes:
                continue
            if node.lineno < loop.lineno or (node.lineno > end_line and isinstance(node.ctx, (ast.Load, ast.Del))):
                return True
    return False


def _comprehension_local_nodes(nodes: Iterable[ast.AST], names: frozenset[str]) -> set[int]:
    local_nodes: set[int] = set()
    for node in nodes:
        if not isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            continue
        # Only first-generator bindings are local before every later generator expression.
        bound = _bound_names(node.generators[0].target) & names
        if not bound:
            continue
        # The first iterable runs in the surrounding scope; targets and remaining expressions are local.
        scoped: list[ast.AST] = [node.generators[0].target, *node.generators[0].ifs, *node.generators[1:]]
        scoped.extend((node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,))
        local_nodes.update(
            id(child)
            for expression in scoped
            for child in walk_ast(expression)
            if isinstance(child, ast.Name) and child.id in bound
        )
    return local_nodes


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
    comprehension = ast.parse(expression, mode="eval").body
    prefix = f"{name} = "
    if isinstance(init, ast.AnnAssign):
        prefix = f"{name}: {ast.unparse(init.annotation)} = "
    if init.col_offset + len(prefix) + len(expression) <= _MAX_REPLACEMENT_WIDTH:
        return True
    if not allow_multiline:
        return False
    if expression.startswith("{"):
        if not isinstance(comprehension, ast.DictComp) or not isinstance(comprehension.value, ast.Call):
            return False
        call = comprehension.value
        generator = comprehension.generators[0]
        lines = (
            f"{ast.unparse(comprehension.key)}: {ast.unparse(call.func)}(",
            *(f"    {ast.unparse(argument)}," for argument in call.args),
            *(f"    {keyword.arg}={ast.unparse(keyword.value)}," for keyword in call.keywords),
            f"for {ast.unparse(generator.target)} in {_comprehension_expression_source(generator.iter)}",
            *(f"if {_comprehension_expression_source(test)}" for test in generator.ifs),
        )
        return init.col_offset + len(prefix) + 1 <= _MAX_REPLACEMENT_WIDTH and all(
            init.col_offset + 4 + len(line) <= _MAX_REPLACEMENT_WIDTH for line in lines
        )
    if not (expression.startswith("[") and expression.endswith("]")):
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
    parts = _filtered_statement_parts(loop.body)
    if parts is None:
        return None
    statement, test, inverted = parts
    expression = _single_method_argument(statement, name, "add")
    if (
        expression is None
        or _loads_name(test, name)
        or _loads_name(expression, name)
        or not _simple_projection(expression, bound_names)
        or _contains_prohibited_expression(test)
    ):
        return None
    return _LoopReplacement(
        _CollectionKind.SET,
        f"{{{ast.unparse(expression)} for {ast.unparse(loop.target)} "
        f"in {_comprehension_expression_source(loop.iter)} if {_condition_source(test, inverted=inverted)}}}",
    )


def _message(finding: _Candidate) -> str:
    qualifier = "filtered " if finding.action != "populates" else ""
    return (
        f"This loop only {finding.action} fresh {finding.kind} {finding.name!r} — prefer a "
        f"{qualifier}{finding.kind} comprehension."
    )

from __future__ import annotations

import ast
from enum import Flag, auto
from itertools import chain
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._annotation_semantics import module_rebindings, union_members
from sarj_python_lint.rules._ast_index import has_own_yield
from sarj_python_lint.rules._ast_names import root_name
from sarj_python_lint.rules._imports import TYPING_SOURCES
from sarj_python_lint.rules._inherited_contract import inherited_contract
from sarj_python_lint.rules._logging import LOG_METHODS, is_logger_expr
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path
from sarj_python_lint.rules._project_index import SymbolRef
from sarj_python_lint.rules._resource_provenance import import_name_for_binding
from sarj_python_lint.rules._suite_flow import literal_truth, reachable_branch
from sarj_python_lint.rules.no_swallowed_exception import BUILTIN_EXCEPTIONS, LOOKUP_EXCEPTIONS


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_OS_FAILURES = frozenset(
    {
        "OSError",
        "BrokenPipeError",
        "ConnectionError",
        "ConnectionAbortedError",
        "ConnectionRefusedError",
        "ConnectionResetError",
        "PermissionError",
        "TimeoutError",
    }
)
_TRANSPORT_FAILURES = frozenset(f"builtins.{name}" for name in _OS_FAILURES) | {
    "asyncio.TimeoutError",
    "asyncio.exceptions.TimeoutError",
    "google.auth.exceptions.TransportError",
}
_GOOGLE_AUTH_FAILURE = "google.auth.exceptions.GoogleAuthError"
_GOOGLE_TOKEN_VERIFIERS = ("google.oauth2.id_token.verify_oauth2_token", "google.oauth2.id_token.verify_token")
_OTHER_OWNERS = frozenset(
    {"builtins.Exception", "builtins.BaseException", "asyncio.CancelledError", "asyncio.exceptions.CancelledError"}
)
_EXAMPLE_PATH = PurePosixPath("app/scores.py")
_BAD = """\
from pathlib import Path


def read_score(path: Path, enabled: bool) -> int | None:
    if not enabled:
        return None
    try:
        return int(path.read_text())
    except (OSError, ValueError):
        return None
"""
_GOOD = """\
from pathlib import Path

from app.outcomes import MissingScore, ReadFailure, Score


def read_score(path: Path, enabled: bool) -> Score | MissingScore | ReadFailure:
    if not enabled:
        return MissingScore()
    try:
        return Score(int(path.read_text()))
    except (OSError, ValueError) as error:
        return ReadFailure(error)
"""


@final
class NoFailureConflatedWithAbsence(ProjectRule):
    id = "no-failure-conflated-with-absence"
    code = "SARJ601"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Distinguish a caught failure from a missing result.",
        rationale="Callers cannot distinguish an operation that failed from a successful lookup with no result when both paths return None.",
        remediation="Let the failure propagate, or return a typed outcome with separate variants for a missing result and a failed operation.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Requires an outer nullable return annotation and a handler that returns None, with optional logging. "
                "A separate normal path must return None, return without a value, or fall off the end."
            ),
            (
                "Broad catches, asyncio cancellation, lookup-only catches, inherited method contracts, generators, "
                "tests and generated files are excluded. Ambiguous exception bindings and complex finalizers abstain."
            ),
            (
                "Requires a known I/O or transport failure, a Google ID-token verification that can fail fetching "
                "certificates, or a Pydantic validation failure from an awaited read whose result is explicitly "
                "tested for None. Input parsing, expected misses and unclassified domain exceptions abstain."
            ),
        ),
        examples=(
            RuleExample(
                example_id="failure-as-absence",
                title="A failed read looks like a missing score",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python(_EXAMPLE_PATH, _BAD),),
                focus_path=_EXAMPLE_PATH,
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="distinct-read-outcomes",
                title="Missing scores and failed reads have distinct outcomes",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python(_EXAMPLE_PATH, _GOOD),),
                focus_path=_EXAMPLE_PATH,
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if "except" not in context.symbol_source or context.tree is None or context.has_wildcard_import:
            return []
        if context.generated or is_test_path(path) or is_test_support_path(path):
            return []
        diagnostics: list[Diagnostic] = []
        for handler in context.nodes(ast.ExceptHandler):
            if (
                handler.type is None
                or (returned := _handler_return(handler)) is None
                or (function := _reachable_function(handler, context)) is None
                or not _has_normal_absence(function, context)
                or not _proven_failure(handler, context)
            ):
                continue
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=returned.lineno,
                    col=returned.col_offset + 1,
                    code=self.code,
                    message=(
                        f"`{function.name}` returns None for both a caught failure and a normal path. "
                        "Propagate the failure or return distinct typed outcomes."
                    ),
                    severity=Severity.WARNING,
                )
            )
        return sorted(diagnostics, key=lambda finding: (finding.line, finding.col))


def _has_normal_absence(function: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext) -> bool:
    if function.returns is None or (function.name.startswith("__") and function.name.endswith("__")):
        return False
    if not function.name.startswith("_") and inherited_contract(context.parents.get(function)):
        return False
    return (
        not any(
            context.imports.resolves(decorator, sources=TYPING_SOURCES, symbol="override")
            for decorator in function.decorator_list
        )
        and _nullable(function.returns, function, context)
        and bool(_normal_flow(function.body))
        and not has_own_yield(function)
    )


def _nullable(annotation: ast.expr, function: ast.AST, context: PythonFileContext) -> bool:
    semantics = context.annotation_semantics
    pending = [annotation]
    seen: set[ast.expr] = set()
    absent = present = False
    while pending:
        expression = pending.pop()
        if expression in seen or (node := semantics.parse(expression)) is None:
            continue
        seen.add(expression)
        match node:
            case ast.Name(id=name) if name in semantics.aliases and _from_module_scope(name, function, context):
                pending.append(semantics.aliases[name])
            case ast.Constant(value=None):
                absent = True
            case ast.BinOp() if (members := union_members(node, context.module_imports)) is not None:
                pending.extend(members)
            case ast.Subscript(value=ast.Name(id=name) | ast.Attribute(value=ast.Name(id=name))) if (
                members := union_members(node, context.module_imports)
            ) is not None and _from_module_scope(name, function, context):
                pending.extend(members)
            case _:
                present = True
    return absent and present


def _from_module_scope(name: str, function: ast.AST, context: PythonFileContext) -> bool:
    provenance = context.resource_provenance
    binding = provenance.binding(name, function)
    return binding is not None and provenance.scope(binding) is context.tree


def _handler_return(handler: ast.ExceptHandler) -> ast.Return | None:
    match [statement for statement in handler.body if not _is_log(statement)]:
        case [ast.Return(value=None | ast.Constant(value=None)) as returned]:
            return returned
        case _:
            return None


def _is_log(statement: ast.stmt) -> bool:
    match statement:
        case ast.Expr(value=ast.Call(func=ast.Attribute(value=receiver, attr=method))):
            return method in LOG_METHODS and is_logger_expr(receiver)
        case _:
            return False


def _proven_failure(handler: ast.ExceptHandler, context: PythonFileContext) -> bool:
    match handler.type, context.parents.get(handler):
        case ast.Tuple(elts=parts), ast.Try() as protected:
            pass
        case ast.expr() as expression, ast.Try() as protected:
            parts = [expression]
        case _:
            return False
    names = {_exception_name(part, context) for part in parts}
    if None in names or not names.isdisjoint(_OTHER_OWNERS):
        return False
    if not names.isdisjoint(_TRANSPORT_FAILURES):
        return True
    if _GOOGLE_AUTH_FAILURE in names and _verifies_google_token(protected, context):
        return True
    return "pydantic.ValidationError" in names and _reads_nullable_record(protected, context)


def _verifies_google_token(protected: ast.Try, context: PythonFileContext) -> bool:
    provenance = context.resource_provenance
    scope = provenance.scope(protected)
    return any(
        isinstance(node, ast.Call)
        and provenance.scope(node) is scope
        and provenance.runtime_import_name(node.func) in _GOOGLE_TOKEN_VERIFIERS
        for node in chain.from_iterable(ast.walk(statement) for statement in protected.body)
    )


def _reads_nullable_record(protected: ast.Try, context: PythonFileContext) -> bool:
    match protected.body:
        case [
            ast.Assign(targets=[ast.Name() as target], value=ast.Await(value=ast.Call()))
            | ast.AnnAssign(target=ast.Name() as target, value=ast.Await(value=ast.Call()))
        ]:
            pass
        case _:
            return False
    function = context.parents.get(protected)
    if not isinstance(function, ast.AsyncFunctionDef) or protected not in function.body:
        return False
    if tuple(context.runtime_bindings.lookup(function, target.id) or ()) != (target,):
        return False
    for statement in function.body[function.body.index(protected) + 1 :]:
        match statement:
            case ast.Assign() | ast.AnnAssign():
                continue
            case ast.If(test=test, body=body):
                match test:
                    case ast.BoolOp(op=ast.Or(), values=conditions):
                        pass
                    case _:
                        conditions = [test]
                return _Flow.RETURNS_NONE in _normal_flow(body) and any(
                    _is_missing_record(condition, target.id) for condition in conditions
                )
            case _:
                return False
    return False


def _is_missing_record(condition: ast.expr, name: str) -> bool:
    match condition:
        case ast.Compare(left=ast.Name(id=record), ops=[ast.Is()], comparators=[ast.Constant(value=None)]):
            return record == name
        case _:
            return False


def _exception_name(expression: ast.expr, context: PythonFileContext) -> str | None:
    inventory = context.binding_inventory
    if (root := root_name(expression)) is None or root in inventory.mutated:
        return None
    bindings = context.runtime_bindings.lookup(inventory.scope(expression), root)
    if bindings is None:
        match expression:
            case ast.Name(id=name) if name in BUILTIN_EXCEPTIONS and all(
                name not in scope for scope in inventory.bindings.values()
            ):
                return f"builtins.{name}"
            case _:
                return None
    match bindings:
        case [ast.alias() as binding]:
            parent = context.parents[binding]
            name = import_name_for_binding(expression, binding, parent)
            if name is None and context.parents.get(parent) is not context.tree:
                return None
            return _project_exception(expression, context, name)
        case [ast.ClassDef() as binding] if (
            isinstance(expression, ast.Name) and context.parents.get(binding) is context.tree
        ):
            return _project_exception(expression, context, None)
        case _:
            return None


def _project_exception(expression: ast.expr, context: PythonFileContext, qualified: str | None) -> str | None:
    project = context.session.project
    if project is None:
        return qualified
    if qualified is None:
        unit = project.unit(context.path)
        symbol = project.resolve(unit, expression) if unit is not None else None
        if symbol is None:
            return None
    else:
        module, _, name = qualified.rpartition(".")
        symbol = SymbolRef(module, name)
    owner = project.source_unit(symbol.module)
    if owner is None:
        if qualified is not None and all(unit.module != symbol.module for unit in project.source_units):
            return qualified
        return None
    if owner.tree is None or symbol.name in module_rebindings(owner.tree):
        return None
    if project.symbol_inherits_builtin(symbol, LOOKUP_EXCEPTIONS):
        return "builtins.LookupError"
    if project.symbol_inherits_builtin(symbol, _OS_FAILURES):
        return "builtins.OSError"
    if project.symbol_inherits_builtin(symbol, BUILTIN_EXCEPTIONS):
        return f"{symbol.module}.{symbol.name}"
    return None


def _reachable_function(
    handler: ast.ExceptHandler, context: PythonFileContext
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    node: ast.AST = handler
    while (parent := context.parents.get(node)) is not None:
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                return node
            case ast.ClassDef():
                return None
            case ast.ExceptHandler() if isinstance(parent, ast.TryStar):
                return None
            case ast.Try() | ast.TryStar() if not _simple_finalizer(node.finalbody):
                return None
            case _:
                pass
        if not reachable_branch(node, parent):
            return None
        node = parent
    return None


def _simple_finalizer(statements: list[ast.stmt]) -> bool:
    return all(
        isinstance(node, ast.Expr | ast.Assign | ast.AnnAssign | ast.AugAssign | ast.Delete | ast.Pass)
        for node in statements
    )


class _Flow(Flag):
    STOPS = 0
    CONTINUES = auto()
    RETURNS_NONE = auto()


def _normal_flow(statements: list[ast.stmt]) -> _Flow:
    exits = _Flow.CONTINUES
    for statement in statements:
        if _Flow.CONTINUES not in exits:
            break
        exits = (exits & ~_Flow.CONTINUES) | _statement_flow(statement)
    return exits


def _statement_flow(node: ast.stmt) -> _Flow:
    match node:
        case ast.Return(value=None | ast.Constant(value=None)):
            return _Flow.RETURNS_NONE
        case ast.Return() | ast.Raise() | ast.Break() | ast.Continue():
            return _Flow.STOPS
        case ast.Assert(test=test) if literal_truth(test) is False:
            return _Flow.STOPS
        case ast.If(test=test, body=body, orelse=orelse):
            match literal_truth(test):
                case True:
                    return _normal_flow(body)
                case False:
                    return _normal_flow(orelse)
                case None:
                    return _normal_flow(body) | _normal_flow(orelse)
        case ast.Try() | ast.TryStar():
            if not _simple_finalizer(node.finalbody):
                return _Flow.STOPS
            exits = _normal_flow(node.body)
            if _Flow.CONTINUES in exits:
                return (exits & ~_Flow.CONTINUES) | _normal_flow(node.orelse)
            return exits
        case ast.With(body=body) | ast.AsyncWith(body=body):
            return _normal_flow(body)
        case ast.For() | ast.AsyncFor() | ast.While():
            return _loop_flow(node)
        case ast.Match(cases=cases):
            exits = _Flow.STOPS
            for case in cases:
                if case.guard is None or literal_truth(case.guard) is not False:
                    exits |= _normal_flow(case.body)
            return exits
        case _:
            return _Flow.CONTINUES


def _loop_flow(node: ast.For | ast.AsyncFor | ast.While) -> _Flow:
    match node:
        case ast.While(test=test) | ast.For(iter=test):
            truth = literal_truth(test)
        case _:
            truth = None
    if truth is False:
        return _normal_flow(node.orelse)
    exits = _normal_flow(node.body)
    returns = exits & _Flow.RETURNS_NONE
    if truth is True and (isinstance(node, ast.While) or _Flow.CONTINUES not in exits):
        return returns
    return returns | _normal_flow(node.orelse)

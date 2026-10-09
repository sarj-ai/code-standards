from __future__ import annotations

import ast
from collections import Counter
from pathlib import PurePosixPath
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
from sarj_python_lint.rules._ast_index import walk
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sarj_python_lint._file_context import PythonFileContext


_MOCK_SOURCES = frozenset({"unittest.mock"})
_CONSTRUCTORS = frozenset({"Mock", "MagicMock", "AsyncMock"})
_CONSTRUCTOR_OPTIONS = frozenset({"spec", "spec_set", "return_value", "name", "unsafe", "autospec"})
_SAFE_ATTRIBUTES = frozenset(
    {
        "assert_called",
        "assert_called_once",
        "assert_called_with",
        "assert_called_once_with",
        "assert_any_call",
        "assert_has_calls",
        "assert_not_called",
        "assert_awaited",
        "assert_awaited_once",
        "assert_awaited_with",
        "assert_awaited_once_with",
        "assert_any_await",
        "assert_has_awaits",
        "assert_not_awaited",
        "called",
        "call_count",
        "call_args",
        "call_args_list",
        "mock_calls",
        "await_count",
        "await_args",
        "await_args_list",
        "return_value",
    }
)
_REFLECTION = frozenset({"globals", "locals", "vars", "eval", "exec", "setattr", "delattr"})
_REFLECTION_TARGETS = frozenset(f"builtins.{name}" for name in _REFLECTION)
_SCOPES = (
    ast.Module,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)
_BAD = (
    "from unittest.mock import Mock\n"
    "def send(*, recipient: str) -> None:\n    pass\n"
    "def test_send():\n    double = Mock(spec=send)\n    double(recipient='sample')\n"
)
_GOOD = _BAD.replace("Mock", "create_autospec").replace("spec=send", "send, spec_set=True")


@final
class PreferAutospecForCallableMock(Rule):
    id = "prefer-autospec-for-callable-mock"
    code = "SARJ474"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Prefer autospec for specced function mocks called with explicit keywords.",
        rationale=(
            "Mock, MagicMock and AsyncMock with spec or spec_set allow incompatible arguments during invocation. "
            "Tests that assert only results or call counts can therefore accept a misspelled keyword or stale call shape."
        ),
        remediation=(
            "Use create_autospec(function, spec_set=True), preserving configured results. "
            "An async function produces an awaitable mock whose signature is checked when awaited. "
            "Retain a reasoned local exception for a deliberately permissive double."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only authored test files, proven unittest.mock constructors, earlier undecorated non-generic module-local function specs without **kwargs, and unconditional simple mock assignments are analyzed.",
            "Requires a stable binding and at least one direct call with explicit keywords in the same scope. Escapes, aliases, rebinding, dynamic argument unpacking, wildcard imports and reflective namespace mutation are excluded.",
            "Imported functions, class or descriptor specs, wrapping, side effects and uncertain configuration are excluded. AsyncMock requires an async function spec so autospec preserves awaiting. Import and function shadow checks, including exception/pattern captures and importer-root walrus/global writes, are conservative across the file. Proven builtins reflection aliases are excluded.",
            "Exact call-shape assertions such as assert_called_once_with can already validate a spec's signature; this advisory warning asks for validation during invocation. Autospec does not enforce argument value types.",
            "Passing autospec=True to a Mock constructor merely configures an attribute; it does not activate autospeccing. Use create_autospec instead.",
            "The initial bounded private-platform survey found zero direct matches within this scope; this is a preventive contract warning, not evidence of a current platform incident. No autofix or blocking promotion is proposed.",
        ),
        examples=(
            RuleExample(
                example_id="specced-function-direct-call",
                title="A function spec leaves invocation permissive",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("tests/test_delivery.py", _BAD),),
                focus_path=PurePosixPath("tests/test_delivery.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="autospecced-function-direct-call",
                title="Autospec checks the function call shape",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("tests/test_delivery.py", _GOOD),),
                focus_path=PurePosixPath("tests/test_delivery.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if not is_test_path(context.path) or context.generated or "Mock" not in context.source:
            return []
        tree = context.tree
        if tree is None or _ambiguous_namespace(context):
            return []
        specs = _stable_specs(tree)
        if not specs:
            return []
        findings: list[Diagnostic] = []
        scopes = [tree, *context.nodes(ast.FunctionDef, ast.AsyncFunctionDef)]
        for scope in scopes:
            scope_nodes = tuple(walk(scope))
            bindings = _binding_counts(scope_nodes)
            for statement in scope.body:
                candidate = _mock_binding(statement, specs, context)
                if candidate is None:
                    continue
                name, call = candidate
                if bindings[name] != 1 or not _closed_fixed_calls(name, call, scope, scope_nodes, context.parents):
                    continue
                if is_suppressed(context.source_lines, call.lineno, self.code):
                    continue
                findings.append(
                    Diagnostic(
                        path=context.path,
                        line=call.lineno,
                        col=call.col_offset + 1,
                        code=self.code,
                        message="A function spec does not check arguments during invocation; use create_autospec(function, spec_set=True) for this callable mock.",
                        severity=Severity.WARNING,
                    )
                )
        return findings


def _stable_specs(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    bindings = _binding_counts(walk(tree))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.decorator_list
        and not node.type_params
        and node.args.kwarg is None
        and bindings[node.name] == 1
    }


def _binding_counts(nodes: Iterable[ast.AST]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for node in nodes:
        match node:
            case (
                ast.Name(id=name, ctx=(ast.Store() | ast.Del()))
                | ast.arg(arg=name)
                | ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
                | ast.ExceptHandler(name=str(name))
                | ast.MatchAs(name=str(name))
                | ast.MatchStar(name=str(name))
                | ast.MatchMapping(rest=str(name))
            ):
                counts[name] += 1
            case ast.alias(name=name, asname=alias):
                counts[alias or name.partition(".")[0]] += 1
            case ast.Global(names=names) | ast.Nonlocal(names=names):
                counts.update(names)
            case _:
                pass
    return counts


def _mock_binding(
    statement: ast.stmt, specs: Mapping[str, ast.FunctionDef | ast.AsyncFunctionDef], context: PythonFileContext
) -> tuple[str, ast.Call] | None:
    match statement:
        case (
            ast.Assign(targets=[ast.Name(id=name)], value=ast.Call() as call)
            | ast.AnnAssign(target=ast.Name(id=name), value=ast.Call() as call)
        ):
            pass
        case _:
            return None
    constructor = context.imports.resolved_symbol(call.func, sources=_MOCK_SOURCES)
    if call.args or constructor not in _CONSTRUCTORS:
        return None
    if any(keyword.arg not in _CONSTRUCTOR_OPTIONS for keyword in call.keywords):
        return None
    contracts = [keyword.value for keyword in call.keywords if keyword.arg in {"spec", "spec_set"}]
    if len(contracts) != 1 or not isinstance(contracts[0], ast.Name) or contracts[0].id not in specs:
        return None
    spec = specs[contracts[0].id]
    if spec.lineno >= call.lineno or (constructor == "AsyncMock" and not isinstance(spec, ast.AsyncFunctionDef)):
        return None
    return name, call


def _closed_fixed_calls(
    name: str,
    constructor: ast.Call,
    scope: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef,
    nodes: tuple[ast.AST, ...],
    parents: Mapping[ast.AST, ast.AST],
) -> bool:
    called = False
    for node in nodes:
        if not isinstance(node, ast.Name) or node.id != name or not isinstance(node.ctx, ast.Load):
            continue
        if node.lineno <= constructor.lineno or _scope_of(node, parents) is not scope:
            return False
        parent = parents[node]
        if isinstance(parent, ast.Call) and parent.func is node:
            if not _fixed_arguments(parent):
                return False
            called = called or bool(parent.keywords)
        elif _safe_mock_attribute(parent):
            continue
        else:
            return False
    return called


def _fixed_arguments(call: ast.Call) -> bool:
    return not any(isinstance(argument, ast.Starred) for argument in call.args) and all(
        keyword.arg is not None for keyword in call.keywords
    )


def _safe_mock_attribute(node: ast.AST) -> bool:
    if not isinstance(node, ast.Attribute) or node.attr not in _SAFE_ATTRIBUTES:
        return False
    return isinstance(node.ctx, ast.Load) or (node.attr == "return_value" and isinstance(node.ctx, ast.Store))


def _scope_of(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> ast.AST:
    while node in parents:
        node = parents[node]
        if isinstance(node, _SCOPES):
            return node
    return node


def _ambiguous_namespace(context: PythonFileContext) -> bool:
    if _ambiguous_constructor_bindings(context):
        return True
    for node in context.nodes(ast.ImportFrom, ast.Call, ast.Attribute):
        if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
            return True
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _REFLECTION:
                return True
            if context.imports.resolved_qualified_name(node.func) in _REFLECTION_TARGETS:
                return True
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, (ast.Store, ast.Del))
            and context.imports.resolved_symbol(node, sources=_MOCK_SOURCES) in _CONSTRUCTORS
        ):
            return True
    return False


def _ambiguous_constructor_bindings(context: PythonFileContext) -> bool:
    constructor_roots = _constructor_roots(context)
    for node in context.nodes(
        ast.ExceptHandler, ast.MatchAs, ast.MatchStar, ast.MatchMapping, ast.NamedExpr, ast.Global
    ):
        match node:
            case (
                ast.ExceptHandler(name=name)
                | ast.MatchAs(name=name)
                | ast.MatchStar(name=name)
                | ast.MatchMapping(rest=name)
                | ast.NamedExpr(target=ast.Name(id=name))
            ):
                if name in constructor_roots:
                    return True
            case ast.Global(names=names):
                if constructor_roots.intersection(names):
                    return True
    return False


def _constructor_roots(context: PythonFileContext) -> set[str]:
    constructor_roots: set[str] = set()
    for call in context.nodes(ast.Call):
        if context.imports.resolved_symbol(call.func, sources=_MOCK_SOURCES) not in _CONSTRUCTORS:
            continue
        root = call.func
        while isinstance(root, ast.Attribute):
            root = root.value
        if isinstance(root, ast.Name):
            constructor_roots.add(root.id)
    return constructor_roots

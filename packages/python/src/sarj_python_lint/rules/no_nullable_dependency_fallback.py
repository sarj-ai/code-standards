from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
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
)
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path
from sarj_python_lint.rules.no_hidden_constructor_fallback import (
    LocalBindingCollector,
    RuntimeConfigFacts,
    RuntimeConfigResolver,
    scope_bindings,
)


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._analysis_session import AnalysisSession
    from sarj_python_lint._file_context import PythonFileContext


_SCOPES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)
_FALLBACK_VALUES = 2


@dataclass(frozen=True, slots=True)
class _ScopeUsage:
    parents: dict[ast.AST, ast.AST]
    calls: dict[str, list[ast.Call]]


@final
class NoNullableDependencyFallback(Rule):
    _facts: RuntimeConfigFacts | None = None
    id = "no-nullable-dependency-fallback"
    code = "SARJ469"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Require concrete function dependencies instead of resolving a None default inside the function.",
        rationale="A None dependency silently selects another implementation or ambient configuration, hiding wiring mistakes and adding unnecessary branches.",
        remediation="Resolve the dependency at the call site and pass it explicitly; a concrete callable default is also valid when its lifetime is appropriate.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Warns for None-defaulted function parameters with a fallback used as a callable or a proven application-settings fallback; genuine absent state is allowed.",
            "Constructors remain owned by SARJ095 and SARJ468. Decorated functions, tests, generated code, nested scope captures, non-callable object fallbacks, and interprocedural forwarding are excluded.",
            "Callable use through a local assignment, annotation or None guard requires at most one body binding for that name and a call after the binding statement completes. Rebinding, deletion, imports, definitions, pattern or exception captures, global/nonlocal declarations and nested-scope bindings conservatively exclude that inference; direct inline calls and proven settings fallbacks remain independent.",
            "No autofix: removing explicit None acceptance changes the callable contract, and moving a fallback can change initialization timing or error handling.",
        ),
        examples=(
            RuleExample(
                example_id="nullable-factory",
                title="Omission silently selects an implementation",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "def run(factory: Factory | None = None):\n    return (factory or DefaultFactory)()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="concrete-factory",
                title="Caller supplies a concrete dependency",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/service.py", "def run(factory: Factory):\n    return factory()\n"),),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def prepare_session(self, session: AnalysisSession) -> None:
        super().prepare_session(session)
        self._facts = RuntimeConfigFacts()

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            context.tree is None
            or context.generated
            or is_test_path(context.path)
            or is_test_support_path(context.path)
        ):
            return []
        facts = self._facts if self._analysis_session is context.session else None
        resolver = RuntimeConfigResolver(
            context.path, context.tree, context.session.first_party, facts or RuntimeConfigFacts()
        )
        findings: list[Diagnostic] = []
        for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
            if function.name == "__init__" or function.decorator_list:
                continue
            parameters = _none_default_parameters(function.args)
            if not parameters:
                continue
            hidden = _hidden_dependencies(function, parameters, resolver)
            findings.extend(
                Diagnostic(
                    path=context.path,
                    line=argument.lineno,
                    col=argument.col_offset + 1,
                    code=self.code,
                    message=f"Dependency `{argument.arg}` defaults to None and selects a fallback; pass a concrete dependency from the caller or use a concrete callable default.",
                    severity=Severity.WARNING,
                )
                for argument in parameters.values()
                if argument.arg in hidden
            )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _none_default_parameters(arguments: ast.arguments) -> dict[str, ast.arg]:
    positional = (*arguments.posonlyargs, *arguments.args)
    defaulted = positional[-len(arguments.defaults) :] if arguments.defaults else ()
    return {
        argument.arg: argument
        for argument, default in (
            *zip(defaulted, arguments.defaults, strict=True),
            *zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True),
        )
        if _is_none(default)
    }


def _hidden_dependencies(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    parameters: dict[str, ast.arg],
    resolver: RuntimeConfigResolver,
) -> set[str]:
    usage = _scope_usage(function)
    candidates = set(parameters)
    hidden: set[str] = set()
    shadowed = set(scope_bindings(function))
    for statement in function.body:
        guard = _guarded_fallback(statement, candidates)
        bindings = LocalBindingCollector()
        bindings.visit(statement)
        bindings.names.update(name for node in _scope_nodes(statement) for name in _binding_names(node))
        bindings.names.update(node.target.id for node in ast.walk(statement) if isinstance(node, ast.NamedExpr))
        # Branch/loop bindings are conservatively local; do not infer data flow.
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)) and guard is None:
            candidates.difference_update(bindings.names)
        hidden.update(
            _expression_dependencies(
                statement,
                candidates=candidates,
                resolver=resolver,
                shadowed=shadowed,
                usage=usage,
            )
        )
        if guard is not None:
            name, value = guard
            if _called_after(name, statement, usage) or _is_settings_fallback(value, resolver, shadowed):
                hidden.add(name)
        candidates.difference_update(bindings.names)
    return hidden


def _scope_usage(function: ast.FunctionDef | ast.AsyncFunctionDef) -> _ScopeUsage:
    nodes = [node for statement in function.body for node in _scope_nodes(statement)]
    parents = {child: node for node in nodes for child in ast.iter_child_nodes(node)}
    bindings = Counter(
        name for statement in function.body for node in ast.walk(statement) for name in _binding_names(node)
    )
    calls: dict[str, list[ast.Call]] = {}
    for node in nodes:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and bindings[node.func.id] <= 1:
            calls.setdefault(node.func.id, []).append(node)
    return _ScopeUsage(parents=parents, calls=calls)


def _called_after(name: str, binding: ast.stmt, usage: _ScopeUsage) -> bool:
    end = (binding.end_lineno or binding.lineno, binding.end_col_offset or binding.col_offset)
    return any((call.lineno, call.col_offset) > end for call in usage.calls.get(name, ()))


def _binding_names(node: ast.AST) -> Iterator[str]:
    match node:
        case (
            ast.Name(id=name, ctx=(ast.Store() | ast.Del()))
            | ast.arg(arg=name)
            | ast.FunctionDef(name=name)
            | ast.AsyncFunctionDef(name=name)
            | ast.ClassDef(name=name)
            | ast.ExceptHandler(name=str() as name)
            | ast.MatchAs(name=str() as name)
            | ast.MatchStar(name=str() as name)
            | ast.MatchMapping(rest=str() as name)
        ):
            yield name
        case ast.alias(name=imported, asname=alias):
            yield alias or imported.partition(".")[0]
        case ast.Global(names=names) | ast.Nonlocal(names=names):
            yield from names
        case _:
            return


def _expression_dependencies(
    statement: ast.stmt,
    *,
    candidates: set[str],
    resolver: RuntimeConfigResolver,
    shadowed: set[str],
    usage: _ScopeUsage,
) -> set[str]:
    hidden: set[str] = set()
    for node in _scope_nodes(statement):
        fallback = _fallback(node, candidates)
        if fallback is None:
            continue
        name, value = fallback
        if _is_settings_fallback(value, resolver, shadowed) or _used_as_dependency(node, usage):
            hidden.add(name)
    return hidden


def _is_settings_fallback(value: ast.expr, resolver: RuntimeConfigResolver, shadowed: set[str]) -> bool:
    target = value.func if isinstance(value, ast.Call) else value
    return resolver.is_runtime_config(target, shadowed)


def _scope_nodes(statement: ast.AST) -> Iterator[ast.AST]:
    if isinstance(statement, _SCOPES):
        return
    yield statement
    for child in ast.iter_child_nodes(statement):
        yield from _scope_nodes(child)


def _guarded_fallback(statement: ast.stmt, candidates: set[str]) -> tuple[str, ast.expr] | None:
    if not isinstance(statement, ast.If) or statement.orelse or len(statement.body) != 1:
        return None
    name = _none_guard(statement.test)
    assignment = statement.body[0]
    if name not in candidates or not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1:
        return None
    target = assignment.targets[0]
    if isinstance(target, ast.Name) and target.id == name:
        return name, assignment.value
    return None


def _fallback(node: ast.AST, candidates: set[str]) -> tuple[str, ast.expr] | None:
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or) and len(node.values) == _FALLBACK_VALUES:
        value, fallback = node.values
        if isinstance(value, ast.Name) and value.id in candidates:
            return value.id, fallback
    if isinstance(node, ast.IfExp):
        name = _none_guard(node.test)
        value, fallback = node.orelse, node.body
        if name is None:
            name = _none_guard(node.test, inverse=True)
            value, fallback = node.body, node.orelse
        if name in candidates and isinstance(value, ast.Name) and value.id == name:
            return name, fallback
    return None


def _none_guard(node: ast.AST, *, inverse: bool = False) -> str | None:
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
        return None
    if not isinstance(node.ops[0], ast.IsNot if inverse else ast.Is):
        return None
    for value, other in ((node.left, node.comparators[0]), (node.comparators[0], node.left)):
        if isinstance(value, ast.Name) and _is_none(other):
            return value.id
    return None


def _is_none(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _used_as_dependency(node: ast.AST, usage: _ScopeUsage) -> bool:
    parent = usage.parents.get(node)
    if isinstance(parent, ast.Call) and parent.func is node:
        return True
    match parent:
        case (
            ast.Assign(targets=[ast.Name(id=name)], value=value) | ast.AnnAssign(target=ast.Name(id=name), value=value)
        ) if value is node:
            return _called_after(name, parent, usage)
        case _:
            return False

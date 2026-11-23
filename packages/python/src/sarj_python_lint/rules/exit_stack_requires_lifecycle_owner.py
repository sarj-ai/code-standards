from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
from sarj_python_lint.rules._ast_index import walk as walk_ast
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


type _Function = ast.FunctionDef | ast.AsyncFunctionDef

_CONTEXTLIB = frozenset({"contextlib"})
_STACKS = ("ExitStack", "AsyncExitStack")
_RUNNERS = frozenset({"asyncio.run", "anyio.run", "trio.run", "uvloop.run"})
_OWNER_SETUP = frozenset({"__init__", "__enter__", "__aenter__"})
_OWNER_RELEASE = frozenset({"__exit__", "__aexit__", "close", "aclose"})
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

_BAD = (
    "from contextlib import AsyncExitStack\n\n"
    "class Uploader:\n"
    "    def __init__(self, client):\n"
    "        self._client = client\n\n"
    "    async def upload(self, items):\n"
    "        async with AsyncExitStack() as cleanup:\n"
    "            cleanup.push_async_callback(self._client.discard, items)\n"
    "            await self._client.publish(items)\n"
    "            cleanup.pop_all()\n"
)
_GOOD = (
    "from collections.abc import AsyncIterator\n"
    "from contextlib import AsyncExitStack, asynccontextmanager\n\n"
    "@asynccontextmanager\n"
    "async def lifespan(app) -> AsyncIterator[None]:\n"
    "    async with AsyncExitStack() as resources:\n"
    "        app.state.client = await resources.enter_async_context(open_client())\n"
    "        yield\n"
)


@final
class ExitStackRequiresLifecycleOwner(Rule):
    id = "exit-stack-requires-lifecycle-owner"
    code = "SARJ588"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Own exit stacks only where resource lifetime is handed to the caller or the process root.",
        rationale=(
            "An ExitStack inside ordinary application code hides resource ownership in a dynamic callback list: "
            "readers must replay registrations, conditional entries and `pop_all()` transfers to learn what is "
            "closed and when. Clients and cleanups are easier to reason about when the composition root "
            "(lifespan, entry point or context manager) opens them once and closes them in one place."
        ),
        remediation=(
            "Inject already-open clients and let the lifespan, `main` or an `@asynccontextmanager` own closing. "
            "For a fixed set of resources use one multi-item `async with`. To transfer ownership, return a "
            "context manager to the caller instead of guarding with `pop_all()`; for rollback on failure use "
            "`try`/`except` that performs the compensating action and re-raises."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only import-proven contextlib ExitStack or AsyncExitStack constructions inside a function are checked; module-level stacks, tests, test support, generated files, stubs and wildcard-import modules are excluded.",
            "Lifecycle owners are generator functions that yield (context-manager bodies, lifespans, yield dependencies, fixtures), module functions reachable through same-module calls from an `if __name__ == '__main__':` block or an asyncio/anyio/trio run call, and `__init__`/`__enter__`/`__aenter__` of a class that also defines `__exit__`, `__aexit__`, `close` or `aclose`.",
            "A nested non-generator function inside an owner is not itself an owner. Cross-module entry points, framework command registration and decorator-provided lifecycles are not inferred.",
        ),
        examples=(
            RuleExample(
                example_id="service-ownership-guard",
                title="A service method hides cleanup in an exit stack with pop_all",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/uploader.py", _BAD),),
                focus_path=PurePosixPath("app/uploader.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="lifespan-owns-resources",
                title="The application lifespan owns resource closing",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/lifespan.py", _GOOD),),
                focus_path=PurePosixPath("app/lifespan.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if not _in_scope(context) or (tree := context.tree) is None:
            return []
        imports = context.imports
        parents = context.parents
        entry_points: frozenset[str] | None = None
        findings: list[Diagnostic] = []
        for call in context.nodes(ast.Call):
            if not any(imports.resolves(call.func, sources=_CONTEXTLIB, symbol=name) for name in _STACKS):
                continue
            function = _enclosing_function(call, parents)
            if function is None or _yields(function) or _resource_owner_setup(function, parents):
                continue
            if entry_points is None:
                entry_points = _entry_points(tree, imports)
            if parents.get(function) is tree and function.name in entry_points:
                continue
            if context.suppressions.is_suppressed(call.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    path=path,
                    line=call.lineno,
                    col=call.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=_message(function),
                )
            )
        return findings


def _in_scope(context: PythonFileContext) -> bool:
    path = context.path
    if "ExitStack" not in context.symbol_source or path.suffix == ".pyi" or context.generated:
        return False
    if is_test_path(path) or is_test_support_path(path):
        return False
    return not context.has_wildcard_import


def _message(function: _Function) -> str:
    base = (
        f"`{function.name}` owns an exit stack outside a lifecycle owner; inject already-open clients and let the "
        "composition root (lifespan, main or a context manager) close them, or use one multi-item `async with` "
        "for a fixed set of resources"
    )
    if any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "pop_all"
        for node in _own_scope(function)
    ):
        return f"{base}; return a context manager to transfer ownership instead of a `pop_all()` guard."
    return f"{base}."


def _enclosing_function(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> _Function | None:
    current = parents.get(node)
    while current is not None and not isinstance(current, _SCOPES):
        current = parents.get(current)
    return current if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)) else None


def _own_scope(function: _Function) -> Iterator[ast.AST]:
    pending: list[ast.AST] = list(function.body)
    while pending:
        node = pending.pop()
        yield node
        if not isinstance(node, _SCOPES):
            pending.extend(ast.iter_child_nodes(node))


def _yields(function: _Function) -> bool:
    return any(isinstance(node, (ast.Yield, ast.YieldFrom)) for node in _own_scope(function))


def _resource_owner_setup(function: _Function, parents: Mapping[ast.AST, ast.AST]) -> bool:
    owner = parents.get(function)
    if function.name not in _OWNER_SETUP or not isinstance(owner, ast.ClassDef):
        return False
    return any(
        isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name in _OWNER_RELEASE
        for member in owner.body
    )


def _entry_points(tree: ast.Module, imports: ImportIndex) -> frozenset[str]:
    functions = {
        statement.name: statement
        for statement in tree.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    reachable: set[str] = set()
    pending = list(_entry_roots(tree, imports))
    while pending:
        name = pending.pop()
        if name in reachable or (function := functions.get(name)) is None:
            continue
        reachable.add(name)
        pending.extend(_called_names(function.body))
    return frozenset(reachable)


def _entry_roots(tree: ast.Module, imports: ImportIndex) -> set[str]:
    roots: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.If) and _is_main_guard(statement.test):
            roots.update(_called_names(statement.body))
    for node in walk_ast(tree):
        if isinstance(node, ast.Call) and imports.resolved_qualified_name(node.func) in _RUNNERS:
            roots.update(_referenced_names(node.args))
    return roots


def _is_main_guard(test: ast.expr) -> bool:
    match test:
        case (
            ast.Compare(left=ast.Name(id="__name__"), ops=[ast.Eq()], comparators=[ast.Constant(value="__main__")])
            | ast.Compare(left=ast.Constant(value="__main__"), ops=[ast.Eq()], comparators=[ast.Name(id="__name__")])
        ):
            return True
        case _:
            return False


def _called_names(body: list[ast.stmt]) -> set[str]:
    names: set[str] = set()
    for statement in body:
        for node in walk_ast(statement):
            if isinstance(node, ast.Call):
                names.update(_referenced_names([node.func, *node.args]))
    return names


def _referenced_names(expressions: list[ast.expr]) -> set[str]:
    names: set[str] = set()
    for expression in expressions:
        match expression:
            case ast.Name(id=name):
                names.add(name)
            case ast.Call(func=ast.Name(id=name)):
                names.add(name)
            case _:
                pass
    return names

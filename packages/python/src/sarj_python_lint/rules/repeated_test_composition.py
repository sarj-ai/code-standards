from __future__ import annotations

import ast
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules._test_composition import (
    Function,
    WiringScope,
    bindings,
    changed_before,
    constructor,
    direct_nodes,
    local_names,
    shadowed,
    unalias,
    wiring,
)


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


_MIN_TESTS = 3
_HTTPX = frozenset({"httpx"})
_PYTEST = frozenset({"pytest", "pytest_asyncio"})
_CLIENT_EXAMPLE = "from httpx import AsyncClient, ASGITransport\n" + "\n".join(
    f"async def test_case_{number}(app):\n"
    "    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:\n"
    "        assert await client.get('/')\n"
    for number in range(_MIN_TESTS)
)


class RepeatedTestComposition(ProjectRule):
    id: str = "repeated-test-composition"
    code: str = "SARJ457"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Sibling tests repeat service collaborator wiring or managed ASGI HTTP clients.",
        rationale="Repeated assembly hides scenario differences and spreads dependency signature changes across tests.",
        remediation="Move shared assembly into a function-scoped fixture or typed factory fixture; keep scenario values explicit.",
        category=RuleCategory.TESTING,
        limitations=(
            "Requires three sibling tests with equivalent wiring of at least two stored and invoked first-party ABC/Protocol dependencies.",
            "Collaborators must resolve to equivalent fixture parameters or first-party constructor expressions, optionally through unambiguous local aliases.",
            "Requires an unconditional construction followed by a subject method call; dynamic arguments, parametrized tests, constructor validation, multiple instances, mutated dependencies, fixtures, helpers, generated files, and inherited test classes are excluded.",
            "HTTPX detection requires a managed AsyncClient with an inline ASGITransport and equivalent options except its app.",
        ),
        examples=(
            RuleExample(
                example_id="repeated-managed-clients",
                title="Share managed test-client assembly",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("tests/test_client.py", _CLIENT_EXAMPLE),),
                focus_path=PurePosixPath("tests/test_client.py"),
                expected_count=3,
                public=True,
            ),
            RuleExample(
                example_id="fixture-client",
                title="Request a managed test client fixture",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_client.py", "async def test_response(client):\n    assert await client.get('/')\n"
                    ),
                ),
                focus_path=PurePosixPath("tests/test_client.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if not is_test_path(context.path) or context.generated or context.tree is None:
            return []
        project = context.session.project or ProjectIndexSet.single(context.path, context.source)
        hits: list[ast.Call] = []
        for siblings in _groups(context.tree):
            repeated: dict[str, list[ast.Call]] = defaultdict(list)
            for function in siblings:
                for key, call in _function_hits(context, project, function):
                    repeated[key].append(call)
            hits.extend(call for calls in repeated.values() if len(calls) >= _MIN_TESTS for call in calls)
        return [
            Diagnostic(
                path=context.path,
                line=call.lineno,
                col=call.col_offset + 1,
                code=self.code,
                message="sibling tests repeat dependency composition; use a function-scoped fixture or typed factory fixture and keep scenario inputs explicit.",
                severity=Severity.ERROR,
            )
            for call in sorted(hits, key=lambda node: (node.lineno, node.col_offset))
        ]


def _groups(tree: ast.Module) -> Iterator[list[Function]]:
    yield [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for node in tree.body:
        if (
            isinstance(node, ast.ClassDef)
            and node.name.startswith("Test")
            and not node.bases
            and not node.decorator_list
        ):
            yield [method for method in node.body if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _function_hits(
    context: PythonFileContext, project: ProjectIndexSet, function: Function
) -> list[tuple[str, ast.Call]]:
    if not function.name.startswith("test_") or _excluded_decorators(context, function):
        return []
    available = WiringScope(
        frozenset(arg.arg for arg in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)),
        bindings(function),
        frozenset(local_names(function)),
    )
    hits: list[tuple[str, str, ast.Call]] = []
    counts: Counter[str] = Counter()
    for node in direct_nodes(function):
        if not isinstance(node, ast.Call):
            continue
        candidate = _candidate(context, project, function, node, available)
        if candidate is None:
            continue
        identity, key = candidate
        counts[identity] += 1
        if key is not None:
            hits.append((identity, key, node))
    return [(key, node) for identity, key, node in hits if counts[identity] == 1]


def _candidate(
    context: PythonFileContext, project: ProjectIndexSet, function: Function, node: ast.Call, available: WiringScope
) -> tuple[str, str | None] | None:
    aliases = {name: value for name, value in available.aliases.items() if value.lineno < node.lineno}
    callee = unalias(node.func, aliases)
    if shadowed(callee, available.parameters | available.blocked):
        return None
    if context.imports.resolves(node.func, sources=_HTTPX, symbol="AsyncClient"):
        key = _client_key(context, node) if _unconditional(context, node, function) else None
        return "httpx.AsyncClient", key
    spec = constructor(context, callee, project)
    if spec is None:
        return None
    identity = f"{spec.symbol.module}.{spec.symbol.name}"
    if not _unconditional(context, node, function) or not _subject_called(context, function, node):
        return identity, None
    blocked = (available.blocked - aliases.keys()) | changed_before(function, node, aliases)
    scope = WiringScope(available.parameters, aliases, frozenset(blocked))
    arguments = wiring(context, project, node, spec, scope)
    return identity, f"{identity}:{arguments!r}" if arguments is not None else None


def _excluded_decorators(context: PythonFileContext, function: Function) -> bool:
    for decorator in function.decorator_list:
        expression = decorator.func if isinstance(decorator, ast.Call) else decorator
        qualified = context.imports.resolved_qualified_name(expression)
        if qualified is None or not qualified.startswith("pytest.mark.") or qualified == "pytest.mark.parametrize":
            return True
    return False


def _unconditional(context: PythonFileContext, node: ast.AST, function: Function) -> bool:
    parent = context.parents.get(node)
    while parent is not None and parent is not function:
        if isinstance(
            parent,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.Try,
                ast.TryStar,
                ast.Match,
                ast.IfExp,
                ast.ListComp,
                ast.DictComp,
                ast.SetComp,
                ast.GeneratorExp,
                ast.BoolOp,
            ),
        ):
            return False
        if isinstance(parent, (ast.With, ast.AsyncWith)) and not any(
            item.context_expr is node for item in parent.items
        ):
            return False
        parent = context.parents.get(parent)
    return True


def _subject_called(context: PythonFileContext, function: Function, call: ast.Call) -> bool:
    parent = context.parents.get(call)
    if isinstance(parent, ast.Attribute):
        invocation = context.parents.get(parent)
        return isinstance(invocation, ast.Call) and invocation.func is parent
    if isinstance(parent, ast.Assign) and len(parent.targets) == 1:
        target = parent.targets[0]
    elif isinstance(parent, ast.AnnAssign):
        target = parent.target
    else:
        return False
    if not isinstance(target, ast.Name):
        return False
    if target.id not in bindings(function):
        return False
    return any(
        isinstance(node, ast.Call)
        and node.lineno > call.lineno
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == target.id
        for node in direct_nodes(function)
    )


def _client_key(context: PythonFileContext, call: ast.Call) -> str | None:
    if not context.imports.resolves(call.func, sources=_HTTPX, symbol="AsyncClient"):
        return None
    parent = context.parents.get(call)
    if (
        not isinstance(parent, ast.withitem)
        or not isinstance(context.parents.get(parent), ast.AsyncWith)
        or call.args
        or any(keyword.arg is None for keyword in call.keywords)
    ):
        return None
    options: list[tuple[str, str]] = []
    found_transport = False
    for keyword in call.keywords:
        if keyword.arg is None:
            return None
        if keyword.arg != "transport":
            if not isinstance(keyword.value, ast.Constant):
                return None
            options.append((keyword.arg, ast.dump(keyword.value)))
            continue
        transport_options = _transport_options(context, keyword.value)
        if transport_options is None:
            return None
        found_transport = True
        options.extend(transport_options)
    return repr(sorted(options)) if found_transport else None


def _transport_options(context: PythonFileContext, transport: ast.expr) -> list[tuple[str, str]] | None:
    if not isinstance(transport, ast.Call) or not context.imports.resolves(
        transport.func, sources=_HTTPX, symbol="ASGITransport"
    ):
        return None
    if transport.args or any(option.arg is None for option in transport.keywords):
        return None
    if not any(option.arg == "app" for option in transport.keywords):
        return None
    options: list[tuple[str, str]] = []
    for option in transport.keywords:
        if option.arg is None or option.arg == "app":
            continue
        if not isinstance(option.value, ast.Constant):
            return None
        options.append((f"transport.{option.arg}", ast.dump(option.value)))
    return options

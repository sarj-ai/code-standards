from __future__ import annotations

import ast
from collections import Counter
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, override

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
from sarj_python_lint.rules._paths import is_generated, is_test_support_path


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._local_source import LocalModule


type Function = ast.FunctionDef | ast.AsyncFunctionDef
_POOL_CONSTRUCTORS = frozenset({"psycopg_pool.ConnectionPool", "psycopg_pool.AsyncConnectionPool"})
_SETUP_AND_CONSUMER = 2
_SUPPORT_SOURCE = (
    "from psycopg_pool import ConnectionPool\n\n"
    "def pool() -> ConnectionPool[object]:\n"
    "    return ConnectionPool[object](open=False)\n"
)


class _HelperImport(NamedTuple):
    local: str
    symbol: str
    module: str
    level: int


class PreferPytestFixtureInjection(Rule):
    id: str = "prefer-pytest-fixture-injection"
    code: str = "SARJ476"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Request shared database-pool setup through a pytest fixture.",
        rationale=(
            "Calling a shared conftest pool helper during initial test setup bypasses an explicit pytest "
            "fixture dependency, per-test caching, and fixture overrides, even when the helper already "
            "centralizes allocation. This preference does not establish a resource leak."
        ),
        remediation=(
            "Request one function-scoped fixture visible to the test. Declare required setup ordering as "
            "fixture dependencies and preserve initial pool state and cleanup ownership. An unopened "
            "allocation fixture should return the pool without opening or closing it when application "
            "lifespan owns that lifecycle. Use yield teardown only when the fixture owns cleanup; keep "
            "factories for variants or fresh instances."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only directly collected module-level test functions in conventional pytest module names are checked.",
            "Only unshadowed runtime imports from a uniquely resolved conftest in the test's ancestor directories are followed under conventional pytest discovery.",
            "Helpers must be undecorated synchronous functions with no formal inputs and one direct return of an imported psycopg_pool pool constructor.",
            "Async pools require an explicit literal open=False, no unpacked arguments, and no calls inside constructor arguments; opened or dynamically configured async pools need lifecycle-specific fixture design.",
            "Setup must be the first executable statement and immediately feed a plain call, or appear inline as a direct argument of that first call.",
            "Class tests, decorated helpers, unknown test decorators, dynamic imports, re-exports, and ambiguous or out-of-bound source paths are excluded.",
            "Command-line conftest discovery overrides and external pytest plugin registrations are not inferred.",
        ),
        examples=(
            RuleExample(
                example_id="manual-shared-generic-pool",
                title="A test calls shared generic pool setup",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python("tests/conftest.py", _SUPPORT_SOURCE),
                    ExampleFile.python(
                        "tests/test_app.py",
                        "from tests.conftest import pool\n\n"
                        "def test_app():\n    resource = pool()\n    app = Application(resource)\n    assert app\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_app.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="manual-pool-with-application-lifespan",
                scenario="application-lifecycle",
                title="Application-owned lifecycle still uses a fixture dependency",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/conftest.py", _SUPPORT_SOURCE.replace("ConnectionPool", "AsyncConnectionPool")
                    ),
                    ExampleFile.python(
                        "tests/test_app.py",
                        "from tests.conftest import pool\n\n"
                        "async def test_app():\n    resource = pool()\n    app = Application(resource)\n"
                        "    async with lifespan(app):\n        assert not resource.closed\n"
                        "    assert resource.closed\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_app.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="allocation-fixture-keeps-application-lifespan",
                scenario="application-lifecycle",
                title="An unopened fixture leaves open and close ownership with the application",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/conftest.py",
                        "import pytest\nfrom psycopg_pool import AsyncConnectionPool\n\n"
                        "@pytest.fixture\ndef pool() -> AsyncConnectionPool[object]:\n"
                        "    return AsyncConnectionPool[object](open=False)\n",
                    ),
                    ExampleFile.python(
                        "tests/test_app.py",
                        "async def test_app(pool):\n    app = Application(pool)\n    assert pool.closed\n"
                        "    async with lifespan(app):\n        assert not pool.closed\n"
                        "    assert pool.closed\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_app.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="injected-generic-pool",
                title="A test requests its shared resource",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/conftest.py",
                        "import pytest\nfrom psycopg_pool import ConnectionPool\n\n"
                        "@pytest.fixture\ndef pool() -> ConnectionPool[object]:\n"
                        "    return ConnectionPool[object](open=False)\n",
                    ),
                    ExampleFile.python(
                        "tests/test_app.py", "def test_app(pool):\n    app = Application(pool)\n    assert app\n"
                    ),
                ),
                focus_path=PurePosixPath("tests/test_app.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            context.path.suffix != ".py"
            or not (context.path.name.startswith("test_") or context.path.name.endswith("_test.py"))
            or is_test_support_path(context.path)
            or context.generated
            or context.tree is None
        ):
            return []
        tree = context.tree
        helpers = _resource_helpers(context)
        if not helpers:
            return []
        module_bindings = _scope_bindings(tree)
        if "__test__" in module_bindings or any(
            isinstance(node, ast.Attribute) and node.attr == "__test__" and isinstance(node.ctx, (ast.Store, ast.Del))
            for node in ast.walk(tree)
        ):
            return []
        diagnostics: list[Diagnostic] = []
        for statement in tree.body:
            if (
                not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                or module_bindings[statement.name] != 1
                or _module_reference(tree, statement.name)
            ):
                continue
            call = _setup_call(context, statement, helpers)
            if call is not None:
                diagnostics.append(
                    Diagnostic(
                        path=context.path,
                        line=call.lineno,
                        col=call.col_offset + 1,
                        code=self.code,
                        message=(
                            "test calls a shared conftest pool helper during initial setup; request one visible "
                            "function-scoped fixture by parameter for caching and overrides; declare required "
                            "setup dependencies and preserve initial pool state and cleanup ownership; leave "
                            "open/close with application lifespan when it owns them; keep factories for variants "
                            "or fresh instances."
                        ),
                        severity=Severity.WARNING,
                    )
                )
        return diagnostics


def _resource_helpers(context: PythonFileContext) -> frozenset[str]:
    tree = context.tree
    if tree is None:
        return frozenset()
    references = tuple(_helper_imports(tree))
    if not references:
        return frozenset()
    bindings = _scope_bindings(tree)
    helpers: set[str] = set()
    for reference in references:
        if bindings[reference.local] != 1 or _root_mutated(tree, reference.local):
            continue
        target = context.session.local_source.resolve_module(
            context.path, reference.module, reference.level, facts=context.session.first_party
        )
        module = (
            context.session.local_source.read_module(target)
            if (
                target is not None and target.name == "conftest.py" and target.parent in context.path.absolute().parents
            )
            else None
        )
        if module is not None and _is_resource_helper(module, reference.symbol):
            helpers.add(reference.local)
    return frozenset(helpers)


def _helper_imports(tree: ast.Module) -> Iterator[_HelperImport]:
    candidates: list[_HelperImport] = []
    for statement in tree.body:
        if not isinstance(statement, ast.ImportFrom):
            continue
        module = statement.module
        if module is None or module.rsplit(".", 1)[-1] != "conftest":
            continue
        candidates.extend(
            _HelperImport(alias.asname or alias.name, alias.name, module, statement.level) for alias in statement.names
        )
    if not candidates or _has_wildcard(tree):
        return
    yield from candidates


def _is_resource_helper(module: LocalModule, symbol: str) -> bool:
    if (
        is_generated(module.path, module.source)
        or _scope_bindings(module.tree)[symbol] != 1
        or _has_wildcard(module.tree)
        or _root_mutated(module.tree, symbol)
    ):
        return False
    helper = next(
        (node for node in module.tree.body if isinstance(node, ast.FunctionDef) and node.name == symbol), None
    )
    if helper is None or helper.decorator_list:
        return False
    arguments = helper.args
    if arguments.posonlyargs or arguments.args or arguments.kwonlyargs or arguments.vararg or arguments.kwarg:
        return False
    body = _executable_body(helper)
    if len(body) != 1 or not isinstance(body[0], ast.Return) or not isinstance(body[0].value, ast.Call):
        return False
    allocation = body[0].value
    constructor = allocation.func
    if isinstance(constructor, ast.Subscript):
        constructor = constructor.value
    root = _root_name(constructor)
    qualified = module.runtime_imports.resolved_qualified_name(constructor)
    return (
        root is not None
        and _scope_bindings(module.tree)[root] == 1
        and not _root_mutated(module.tree, root)
        and qualified in _POOL_CONSTRUCTORS
        and (qualified != "psycopg_pool.AsyncConnectionPool" or _unopened_async_allocation(allocation))
    )


def _unopened_async_allocation(allocation: ast.Call) -> bool:
    return (
        not any(isinstance(argument, ast.Starred) for argument in allocation.args)
        and all(keyword.arg is not None for keyword in allocation.keywords)
        and any(
            keyword.arg == "open" and isinstance(keyword.value, ast.Constant) and keyword.value.value is False
            for keyword in allocation.keywords
        )
        and not any(isinstance(node, ast.Call) for argument in _arguments(allocation) for node in ast.walk(argument))
    )


def _setup_call(context: PythonFileContext, function: Function, helpers: frozenset[str]) -> ast.Call | None:
    if not function.name.startswith("test_") or any(
        not _pytest_mark(context, decorator) for decorator in function.decorator_list
    ):
        return None
    bindings = _scope_bindings(function)
    available = helpers - bindings.keys()
    # Looking through nested scopes here conservatively excludes captures and callable escapes.
    uses = [node for node in ast.walk(function) if isinstance(node, ast.Name) and node.id in available]
    if len(uses) != 1:
        return None
    body = _executable_body(function)
    if not body:
        return None
    first = body[0]
    setup = _plain_call(first)
    if setup is None:
        return None
    if _helper_call(setup, available):
        return _assigned_dependency_call(context, body, bindings, setup)
    if not _unshadowed_consumer(context, setup, bindings):
        return None
    inline = [arg for arg in _arguments(setup) if isinstance(arg, ast.Call) and _helper_call(arg, available)]
    return inline[0] if len(inline) == 1 else None


def _assigned_dependency_call(
    context: PythonFileContext, body: list[ast.stmt], bindings: Counter[str], setup: ast.Call
) -> ast.Call | None:
    resource = _assignment_name(body[0])
    if resource is None or bindings[resource] != 1 or len(body) < _SETUP_AND_CONSUMER:
        return None
    consumer = _plain_call(body[1])
    if consumer is None or not _unshadowed_consumer(context, consumer, bindings):
        return None
    for argument in _arguments(consumer):
        if isinstance(argument, ast.Name) and argument.id == resource:
            return setup
    return None


def _pytest_mark(context: PythonFileContext, decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    qualified = context.module_imports.resolved_qualified_name(target)
    tree = context.tree
    root = _root_name(target)
    if (
        qualified is None
        or not qualified.startswith("pytest.mark.")
        or tree is None
        or root is None
        or _scope_bindings(tree)[root] != 1
    ):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Attribute, ast.Subscript)) or not isinstance(node.ctx, (ast.Store, ast.Del)):
            continue
        if isinstance(node, ast.Subscript) and _root_name(node.value) == root:
            return False
        changed = context.module_imports.resolved_qualified_name(node)
        if changed is not None and (qualified == changed or qualified.startswith(f"{changed}.")):
            return False
    return True


def _unshadowed_consumer(context: PythonFileContext, call: ast.Call, bindings: Counter[str]) -> bool:
    root = _root_name(call.func)
    tree = context.tree
    return (
        root is not None
        and root not in bindings
        and tree is not None
        and _scope_bindings(tree)[root] <= 1
        and not _root_mutated(tree, root)
    )


def _module_reference(tree: ast.Module, name: str) -> bool:
    return any(
        isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load)
        for statement in tree.body
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        for node in ast.walk(statement)
    )


def _helper_call(call: ast.Call, helpers: frozenset[str] | set[str]) -> bool:
    return isinstance(call.func, ast.Name) and call.func.id in helpers and not call.args and not call.keywords


def _arguments(call: ast.Call) -> Iterator[ast.expr]:
    yield from call.args
    yield from (keyword.value for keyword in call.keywords if keyword.arg is not None)


def _plain_call(statement: ast.stmt) -> ast.Call | None:
    if (
        isinstance(statement, (ast.Expr, ast.Assign, ast.AnnAssign))
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, (ast.Name, ast.Attribute))
    ):
        return statement.value
    return None


def _assignment_name(statement: ast.stmt) -> str | None:
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
        return statement.targets[0].id
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        return statement.target.id
    return None


def _root_name(expression: ast.expr) -> str | None:
    while isinstance(expression, ast.Attribute):
        expression = expression.value
    return expression.id if isinstance(expression, ast.Name) else None


def _executable_body(function: Function) -> list[ast.stmt]:
    body = function.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _scope_bindings(scope: ast.Module | Function) -> Counter[str]:
    names: Counter[str] = Counter()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        arguments = scope.args
        names.update(arg.arg for arg in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs))
        names.update(arg.arg for arg in (arguments.vararg, arguments.kwarg) if arg is not None)
    for statement in scope.body:
        _collect_bindings(statement, names)
    if isinstance(scope, ast.Module):
        names.update(_global_writes(scope))
    return names


def _global_writes(tree: ast.Module) -> Counter[str]:
    if not any(isinstance(node, ast.Global) for node in ast.walk(tree)):
        return Counter()
    writes: Counter[str] = Counter()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        names: Counter[str] = Counter()
        declarations: set[str] = set()
        for statement in node.body:
            _collect_bindings(statement, names)
            declarations.update(_global_names(statement))
        writes.update(dict.fromkeys(declarations & names.keys(), 2))
    return writes


def _global_names(node: ast.AST) -> Iterator[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return
    if isinstance(node, ast.Global):
        yield from node.names
    for child in ast.iter_child_nodes(node):
        yield from _global_names(child)


def _collect_bindings(node: ast.AST, names: Counter[str]) -> None:
    match node:
        case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
            names[name] += 1
            for expression in _definition_expressions(node):
                _collect_bindings(expression, names)
            return
        case ast.Lambda():
            for expression in _definition_expressions(node):
                _collect_bindings(expression, names)
            return
        case ast.Import(names=aliases) | ast.ImportFrom(names=aliases):
            names.update(alias.asname or alias.name.partition(".")[0] for alias in aliases)
        case (
            ast.Name(id=name, ctx=(ast.Store() | ast.Del()))
            | ast.ExceptHandler(name=str(name))
            | ast.MatchAs(name=str(name))
            | ast.MatchStar(name=str(name))
            | ast.MatchMapping(rest=str(name))
        ):
            names[name] += 1
        case ast.comprehension():
            _collect_bindings(node.iter, names)
            for condition in node.ifs:
                _collect_bindings(condition, names)
            return
        case _:
            pass
    for child in ast.iter_child_nodes(node):
        _collect_bindings(child, names)


def _definition_expressions(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda) -> list[ast.AST]:
    if isinstance(node, ast.ClassDef):
        return [*node.decorator_list, *node.bases, *node.keywords]
    defaults: list[ast.AST] = [
        *node.args.defaults,
        *(default for default in node.args.kw_defaults if default is not None),
    ]
    return defaults if isinstance(node, ast.Lambda) else [*node.decorator_list, *defaults]


def _has_wildcard(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names) for node in ast.walk(tree)
    )


def _root_mutated(tree: ast.Module, root: str) -> bool:
    return any(
        isinstance(node, (ast.Attribute, ast.Subscript))
        and isinstance(node.ctx, (ast.Store, ast.Del))
        and _root_name(node.value) == root
        for node in ast.walk(tree)
    )

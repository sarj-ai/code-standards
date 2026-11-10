from __future__ import annotations

import ast
from collections import Counter
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint._file_context import PythonFileContext
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
from sarj_python_lint.rules._declared_contracts import (
    SETTINGS_BASES,
    DeclaredClass,
    DeclaredContracts,
    ordinary_pytest_test,
)
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path
from sarj_python_lint.rules._pytest import collected_tests
from sarj_python_lint.rules._pytest_contract_parameters import FixtureContractParameters
from sarj_python_lint.rules._test_composition import bindings, call_arguments, constructor, direct_nodes, unalias
from sarj_python_lint.rules.pytest_fixture_returns_bare_tuple import fixture_declarations


if TYPE_CHECKING:
    from collections.abc import Collection, Iterator, Mapping

    from sarj_python_lint.rules._project_index import SourceUnit
    from sarj_python_lint.rules.pytest_fixture_returns_bare_tuple import FixtureDeclaration


_NATIVE_HTTP_CLIENTS = frozenset({"httpx.Client", "httpx.AsyncClient"})


_EXAMPLE = "from typing import Protocol\nclass Port(Protocol):\n    def read(self): ...\nclass Store:\n    def read(self): return 1\nclass Service:\n    def __init__(self, store: Port):\n        self.store = store\n    def read(self): return self.store.read()\n"


_FACTORY_SOURCE = "import pytest\nfrom typing import Protocol\n\nclass Port(Protocol):\n    def read(self) -> int: ...\n\nclass Store:\n    def read(self) -> int:\n        return 1\n\nclass Service:\n    def __init__(self, store: Port) -> None:\n        self.store = store\n\n    def read(self) -> int:\n        return self.store.read()\n\n@pytest.fixture\ndef store_factory() -> type[Store]:\n    return Store\n\ndef test_read(store_factory: type[Store]) -> None:\n    if store_factory is Store:\n        service = Service(Store())\n        assert service.read() == 1\n"
_FACTORY_FIXED = "import pytest\nfrom typing import Protocol\n\nclass Port(Protocol):\n    def read(self) -> int: ...\n\nclass Store:\n    def read(self) -> int:\n        return 1\n\nclass Service:\n    def __init__(self, store: Port) -> None:\n        self.store = store\n\n    def read(self) -> int:\n        return self.store.read()\n\n@pytest.fixture\ndef store_factory() -> type[Store]:\n    return Store\n\ndef test_read(store_factory: type[Store]) -> None:\n    if store_factory is Store:\n        service = Service(store_factory())\n        assert service.read() == 1\n"

_BORROWED_STORES = "from abc import ABC, abstractmethod\nclass Queue(ABC):\n    @abstractmethod\n    def retry(self) -> bool: ...\nclass QueueStore(Queue):\n    def __init__(self, resource: object) -> None:\n        self.resource = resource\n    def retry(self) -> bool:\n        return True\nclass Owner:\n    def __init__(self, resource: object) -> None:\n        self.resource = resource\n    def read(self) -> bool:\n        return True\n"
_BORROWED_PROVIDER = "import pytest\nfrom app.stores import Owner, QueueStore\n@pytest.fixture\ndef resource() -> object:\n    return object()\n@pytest.fixture\ndef owner(resource: object) -> Owner:\n    return Owner(resource)\n@pytest.fixture\ndef queue_store(resource: object) -> QueueStore:\n    return QueueStore(resource)\n"


@final
class PreferPytestDependencyFixtures(ProjectRule):
    id = "prefer-pytest-dependency-fixtures"
    code = "SARJ526"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Reuse supplied pytest fixtures and pass test collaborators through fixture dependencies.",
        rationale="Constructing collaborators in a test bypasses pytest's dependency graph, caching and overrides even when only one test currently needs the setup.",
        remediation="Request function-scoped store, service and settings fixtures by parameter. Use a typed factory fixture for variants or multiple instances. Keep construction under test explicit and preserve setup ordering and the actual owner's cleanup; do not create global singletons or autouse fixtures.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Source-visible module-level collaborator instances must also enter tests through fixtures. Argument binding must be explicit: starred positional arguments, keyword unpacking and duplicate bindings abstain rather than guessing collaborator ownership.",
            "Safe fixes only reuse an already-requested typed factory inside an authored runtime identity guard over a closed source-owned collaborator graph. They change only its immediate constructor callee; no fixture, signature, guard, setup event or lifecycle is introduced. All other findings require review.",
            "Checks collected pytest functions and plain test classes. A local or inline class construction must feed a proven stored-and-invoked ABC/Protocol collaborator, or a proven BaseSettings instance must be passed to a call. Names alone never identify a service. Constructor failure tests, fixtures, helpers, dynamic/unresolved sources, generated and test-support paths are excluded. No automatic fixture extraction or lifecycle change.",
            "Native HTTPX Client/AsyncClient constructors also enter through fixtures, including managed clients and runtime-import aliases; source definitions are not required. Opaque constructor factories and reassigned or patched providers are excluded. No transport or teardown is synthesized.",
            "Also reports source-resolved constructors whose class matches a supplied fixture annotation or implements its ABC/Protocol. Parametrized values, shadowed constructors and unresolved types are excluded. A different configuration needs a typed factory fixture; the rule never replaces an instance automatically.",
            "Also recognizes an unrequested function-scoped provider in the test module, ancestor conftest or a literal pytest_plugins registration when a source-owned ABC implementation borrows an attribute of a typed requested fixture. Its single assigned instance must perform an operation before a later assertion directly observes the original fixture; constructor-only and direct-subject observations abstain. Only direct one-input providers are supported; factories, variants, broader lifetimes, class-local providers, unexplained overrides and nested/dynamic registration abstain. Parametrized owner data, unresolved marks and visible generation hooks abstain. Ambient marks need direct module/class declarations; imported, read/escaped, augmented or indirectly assigned pytestmark bindings abstain. Provider class matching does not prove resource or lifecycle equivalence; these findings require manual fixture/factory selection and have no automatic fix.",
        ),
        examples=(
            RuleExample(
                example_id="duplicate-supplied-store",
                scenario="supplied-store",
                title="A second store bypasses the supplied fixture",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_store.py",
                        _EXAMPLE
                        + "def test_read(store: Store):\n    replacement = Store()\n    assert replacement.read() == 1\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="reuse-supplied-store",
                scenario="supplied-store",
                title="Use the supplied store fixture",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_store.py", _EXAMPLE + "def test_read(store: Store):\n    assert store.read() == 1\n"
                    ),
                ),
                focus_path=PurePosixPath("tests/test_store.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="constructed-collaborator",
                title="A test constructs its service's store",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_service.py",
                        _EXAMPLE
                        + "def test_read():\n    store = Store()\n    service = Service(store)\n    assert service.read() == 1\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="injected-collaborator",
                title="The store arrives through pytest",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_service.py",
                        _EXAMPLE
                        + "def test_read(store):\n    service = Service(store)\n    assert service.read() == 1\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="existing-factory-identity",
                title="An authored identity guard closes the existing factory",
                outcome=ExampleOutcome.MATCH,
                scenario="existing-factory-identity",
                files=(ExampleFile.python("tests/test_service.py", _FACTORY_SOURCE),),
                fixed_files=(ExampleFile.python("tests/test_service.py", _FACTORY_FIXED),),
                focus_path=PurePosixPath("tests/test_service.py"),
                expected_count=1,
            ),
            RuleExample(
                example_id="existing-factory-used",
                title="The identical existing factory supplies the collaborator",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="existing-factory-identity",
                files=(ExampleFile.python("tests/test_service.py", _FACTORY_FIXED),),
                focus_path=PurePosixPath("tests/test_service.py"),
                expected_count=0,
            ),
            RuleExample(
                example_id="unrequested-plugin-collaborator",
                scenario="borrowed-fixture-resource",
                title="A visible plugin fixture owns the collaborator",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python("app/__init__.py", '"""Example application package."""\n'),
                    ExampleFile.python("app/stores.py", _BORROWED_STORES),
                    ExampleFile.python("tests/__init__.py", '"""Example test package."""\n'),
                    ExampleFile.python("tests/fixtures.py", _BORROWED_PROVIDER),
                    ExampleFile.python("tests/conftest.py", "pytest_plugins = ['tests.fixtures']\n"),
                    ExampleFile.python(
                        "tests/test_retry.py",
                        "from app.stores import Owner, QueueStore\ndef test_retry(owner: Owner):\n    queue = QueueStore(owner.resource)\n    queue.retry()\n    assert owner.read()\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_retry.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="requested-plugin-collaborator",
                scenario="borrowed-fixture-resource",
                title="Request the collaborator through pytest",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python("app/__init__.py", '"""Example application package."""\n'),
                    ExampleFile.python("app/stores.py", _BORROWED_STORES),
                    ExampleFile.python("tests/__init__.py", '"""Example test package."""\n'),
                    ExampleFile.python("tests/fixtures.py", _BORROWED_PROVIDER),
                    ExampleFile.python("tests/conftest.py", "pytest_plugins = ['tests.fixtures']\n"),
                    ExampleFile.python(
                        "tests/test_retry.py", "def test_retry(queue_store):\n    assert queue_store.retry()\n"
                    ),
                ),
                focus_path=PurePosixPath("tests/test_retry.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            context.tree is None
            or context.generated
            or not is_test_path(context.path)
            or is_test_support_path(context.path)
        ):
            return []
        contracts = DeclaredContracts(context)
        hits: set[ast.expr] = set()
        borrowed: dict[ast.Call, DeclaredClass] = {}
        for function in collected_tests(context.tree.body):
            if ordinary_pytest_test(function, context):
                hits.update(_constructed_dependencies(function, context, contracts))
                borrowed.update(_borrowed_fixture_constructors(function, context, contracts))
        hits.update(_borrowed_fixture_hits(borrowed, context, contracts))
        return [
            Diagnostic(
                context.path,
                call.lineno,
                call.col_offset + 1,
                self.code,
                "Request this constructed collaborator or settings value through a function-scoped fixture; use a typed factory fixture for variants and preserve lifecycle ownership.",
                severity=Severity.WARNING,
            )
            for call in sorted(hits, key=lambda item: (item.lineno, item.col_offset))
            if not context.suppressions.is_suppressed(call.lineno, self.code)
        ]


def _borrowed_fixture_hits(
    borrowed: Mapping[ast.Call, DeclaredClass], context: PythonFileContext, contracts: DeclaredContracts
) -> Iterator[ast.Call]:
    if not borrowed:
        return
    available = _visible_fixture_constructors(context, contracts)
    eligible = {call for call, model in borrowed.items() if model.declaration in available}
    if not eligible or not _stable_ambient_marks(context):
        return
    requested = frozenset(
        argument
        for _, arguments in FixtureContractParameters(context, contracts, ()).parameters
        for argument in arguments
    )
    yield from (
        call for call in eligible if _borrowed_fixture_owner(call, context, contracts, requested, set()) is not None
    )


def _stable_ambient_marks(context: PythonFileContext) -> bool:
    inventory = context.binding_inventory
    if "pytestmark" in inventory.reads or "pytestmark" in inventory.external_bindings:
        return False
    for scope, names in inventory.bindings.items():
        if not isinstance(scope, ast.Module | ast.ClassDef):
            continue
        for binding in names.get("pytestmark", ()):
            parent = context.parents.get(binding)
            if not (
                isinstance(binding, ast.Name)
                and isinstance(binding.ctx, ast.Store)
                and isinstance(parent, ast.Assign | ast.AnnAssign)
                and (not isinstance(parent, ast.Assign) or len(parent.targets) == 1)
                and context.parents.get(parent) is scope
            ):
                return False
    return not any(node.attr == "pytestmark" for node in context.nodes(ast.Attribute))


def _borrowed_fixture_constructors(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    context: PythonFileContext,
    contracts: DeclaredContracts,
) -> Iterator[tuple[ast.Call, DeclaredClass]]:
    parametrized = _parametrized_names(function, context)
    if parametrized is None:
        return
    allocated = bindings(function)
    requested = (*function.args.args, *function.args.kwonlyargs)
    for call in (node for node in direct_nodes(function) if isinstance(node, ast.Call)):
        owner = _borrowed_fixture_owner(call, context, contracts, requested, parametrized)
        if owner is None or _inside_raises(context, call, function):
            continue
        receiver = next((name for name, expression in allocated.items() if expression is call), None)
        if receiver is None or not _arranges_observed_fixture(function, context, call, receiver, owner):
            continue
        model = contracts.class_type(call.func)
        if model is not None and contracts.inherits(
            model, frozenset({"abc.ABC", "typing.Protocol", "typing_extensions.Protocol"})
        ):
            yield call, model


def _borrowed_fixture_owner(
    call: ast.Call,
    context: PythonFileContext,
    contracts: DeclaredContracts,
    requested: Collection[ast.arg],
    parametrized: set[str],
) -> ast.arg | None:
    if len(call.args) != 1 or call.keywords:
        return None
    value = call.args[0]
    if not isinstance(value, ast.Attribute) or not isinstance(value.value, ast.Name):
        return None
    owner = context.static_resource_provenance.binding(value.value.id, value.value)
    if not isinstance(owner, ast.arg) or owner.annotation is None:
        return None
    if owner not in requested or owner.arg in parametrized:
        return None
    if owner.arg in context.static_resource_provenance.mutated or contracts.annotation(owner.annotation) is None:
        return None
    return owner


def _arranges_observed_fixture(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    context: PythonFileContext,
    allocation: ast.Call,
    receiver: str,
    owner: ast.arg,
) -> bool:
    statement = context.parents.get(allocation)
    target = (
        statement.targets[0]
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1
        else statement.target
        if isinstance(statement, ast.AnnAssign)
        else None
    )
    if not isinstance(target, ast.Name):
        return False
    operations = [
        node.lineno
        for node in direct_nodes(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == receiver
        and node.lineno > allocation.lineno
        and context.static_resource_provenance.binding(receiver, node.func.value) is target
        and context.static_resource_provenance.scope(node.func.value) is function
    ]
    return any(
        isinstance(assertion, ast.Assert)
        and any(allocation.lineno < line < assertion.lineno for line in operations)
        and any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == owner.arg
            and context.static_resource_provenance.binding(owner.arg, node.func.value) is owner
            and context.static_resource_provenance.scope(node.func.value) is function
            for node in ast.walk(assertion.test)
        )
        for assertion in direct_nodes(function)
    )


def _visible_fixture_constructors(context: PythonFileContext, contracts: DeclaredContracts) -> frozenset[ast.ClassDef]:
    names: Counter[str] = Counter()
    blocked: set[str] = set()
    candidates: list[tuple[str, ast.ClassDef]] = []
    for unit in _visible_fixture_units(context, contracts):
        if unit.tree is None:
            continue
        module_context = PythonFileContext(unit.path, unit.source, context.session)
        facts = module_context.binding_inventory
        if module_context.tree is None:
            continue
        fixtures = tuple(fixture_declarations(module_context.tree))
        blocked.update(_unexplained_fixture_exports(module_context, fixtures))
        if (
            facts.wildcard
            or module_context.dynamic_namespace
            or facts.bindings.get(module_context.tree, {}).get("pytest_generate_tests")
        ):
            return frozenset()
        for fixture in fixtures:
            names[fixture.name] += 1
            if (model := _provider_constructor(module_context, contracts, unit, fixture)) is not None:
                candidates.append((fixture.name, model))
    return frozenset(model for name, model in candidates if names[name] == 1 and name not in blocked)


def _visible_fixture_units(context: PythonFileContext, contracts: DeclaredContracts) -> tuple[SourceUnit, ...]:
    ancestors = frozenset(context.path.absolute().parents)
    units = {
        unit.path: unit
        for unit in contracts.project.source_units
        if unit.path == context.path or (unit.path.name == "conftest.py" and unit.path.absolute().parent in ancestors)
    }
    if contracts.unit is not None:
        units[contracts.unit.path] = contracts.unit
    for unit in tuple(units.values()):
        if unit.tree is None:
            continue
        plugins = _registered_fixture_plugins(PythonFileContext(unit.path, unit.source, context.session), contracts)
        if plugins is None:
            return ()
        units.update((plugin.path, plugin) for plugin in plugins)
    return tuple(units.values())


def _registered_fixture_plugins(
    context: PythonFileContext, contracts: DeclaredContracts
) -> tuple[SourceUnit, ...] | None:
    facts = context.binding_inventory
    plugin_bindings = facts.bindings.get(context.tree, {}).get("pytest_plugins", ())
    if not plugin_bindings:
        return ()
    if (
        len(plugin_bindings) != 1
        or facts.reads.get("pytest_plugins")
        or context.dynamic_namespace
        or context.tree is None
    ):
        return None
    assignment = context.parents.get(plugin_bindings[0])
    if assignment not in context.tree.body:
        return None
    modules = _literal_case_names(assignment.value if isinstance(assignment, ast.Assign | ast.AnnAssign) else None)
    if modules is None:
        return None
    plugins: list[SourceUnit] = []
    for module in modules:
        plugin = contracts.project.source_unit(module)
        if plugin is None or plugin.tree is None:
            return None
        plugin_context = PythonFileContext(plugin.path, plugin.source, context.session)
        if plugin_context.binding_inventory.bindings.get(plugin_context.tree, {}).get("pytest_plugins"):
            return None
        plugins.append(plugin)
    return tuple(plugins)


def _unexplained_fixture_exports(
    context: PythonFileContext, fixtures: tuple[FixtureDeclaration, ...]
) -> frozenset[str]:
    if context.tree is None:
        return frozenset()
    definitions = {fixture.node.name: fixture.node for fixture in fixtures if fixture.node in context.tree.body}
    return frozenset(
        name
        for name, definitions_at_name in context.binding_inventory.bindings.get(context.tree, {}).items()
        if definitions_at_name != (definitions.get(name),)
    )


def _provider_constructor(
    context: PythonFileContext, contracts: DeclaredContracts, unit: SourceUnit, fixture: FixtureDeclaration
) -> ast.ClassDef | None:
    function = fixture.node
    if context.tree is None or context.generated or function not in context.tree.body or function.returns is None:
        return None
    facts = context.binding_inventory
    if (
        facts.bindings.get(context.tree, {}).get(function.name) != (function,)
        or function.name in facts.external_bindings | facts.mutated
        or not _function_scope_provider(function, fixture.decorator)
    ):
        return None
    if len(function.body) != 1 or not isinstance(function.body[0], ast.Return):
        return None
    returned = function.body[0].value
    if not isinstance(returned, ast.Call) or len(returned.args) != 1 or returned.keywords:
        return None
    argument = returned.args[0]
    if not isinstance(argument, ast.Name) or argument.id not in {arg.arg for arg in function.args.args}:
        return None
    root = returned.func
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name) or not isinstance(
        context.static_resource_provenance.binding(root.id, returned.func), ast.alias | ast.ClassDef
    ):
        return None
    model = contracts.class_type(returned.func, unit)
    annotation = contracts.annotation(function.returns, unit)
    return (
        model.declaration
        if model is not None and annotation is not None and _compatible_fixture(model, annotation, contracts)
        else None
    )


def _function_scope_provider(function: ast.FunctionDef | ast.AsyncFunctionDef, decorator: ast.expr) -> bool:
    arguments = function.args
    if (
        len(function.decorator_list) != 1
        or arguments.defaults
        or arguments.kw_defaults
        or arguments.vararg
        or arguments.kwarg
    ):
        return False
    if not isinstance(decorator, ast.Call):
        return True
    return not decorator.args and all(
        (
            keyword.arg in {"scope", "loop_scope"}
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == "function"
        )
        or (keyword.arg == "name" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str))
        for keyword in decorator.keywords
    )


def _constructed_dependencies(
    function: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext, contracts: DeclaredContracts
) -> Iterator[ast.expr]:
    aliases = bindings(function)
    fixture_types = _supplied_types(function, context, contracts)
    for call in (node for node in direct_nodes(function) if isinstance(node, ast.Call)):
        if _inside_raises(context, call, function):
            continue
        if context.resource_provenance.runtime_import_name(call.func) in _NATIVE_HTTP_CLIENTS:
            yield call
        model = contracts.class_type(call.func) if fixture_types else None
        if model is not None and any(_compatible_fixture(model, supplied, contracts) for supplied in fixture_types):
            yield call
        yield from _call_dependencies(call, context, contracts, aliases)


def _supplied_types(
    function: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext, contracts: DeclaredContracts
) -> tuple[DeclaredClass, ...]:
    parametrized = _parametrized_names(function, context)
    if parametrized is None:
        return ()
    arguments = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
    models: list[DeclaredClass] = []
    for argument in arguments:
        if argument.arg in parametrized or argument.annotation is None:
            continue
        model = contracts.annotation(argument.annotation)
        if model is not None:
            models.append(model)
    return tuple(models)


def _parametrized_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext
) -> set[str] | None:
    parametrized: set[str] = set()
    for decorator in function.decorator_list:
        if (
            not isinstance(decorator, ast.Call)
            or context.imports.resolved_qualified_name(decorator.func) != "pytest.mark.parametrize"
        ):
            continue
        names = (
            decorator.args[0]
            if decorator.args
            else next((keyword.value for keyword in decorator.keywords if keyword.arg == "argnames"), None)
        )
        parsed = _literal_case_names(names)
        if parsed is None:
            return None
        parametrized.update(parsed)
    return parametrized


def _literal_case_names(names: ast.expr | None) -> set[str] | None:
    if isinstance(names, ast.Constant) and isinstance(names.value, str):
        return {name.strip() for name in names.value.split(",")}
    if not isinstance(names, ast.Tuple | ast.List):
        return None
    parsed: set[str] = set()
    for item in names.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            return None
        parsed.add(item.value)
    return parsed


def _compatible_fixture(model: DeclaredClass, supplied: DeclaredClass, contracts: DeclaredContracts) -> bool:
    if model.declaration is supplied.declaration:
        return True
    if supplied.unit.module is None or not contracts.inherits(
        supplied, frozenset({"abc.ABC", "typing.Protocol", "typing_extensions.Protocol"})
    ):
        return False
    return contracts.inherits(model, frozenset({f"{supplied.unit.module}.{supplied.declaration.name}"}))


def _call_dependencies(
    call: ast.Call, context: PythonFileContext, contracts: DeclaredContracts, aliases: dict[str, ast.expr]
) -> Iterator[ast.expr]:
    spec = constructor(context, call.func, contracts.project, minimum_collaborators=1)
    visible_aliases = {key: item for key, item in aliases.items() if item.lineno < call.lineno}
    positional = spec.positional if spec is not None else tuple(f"argument-{index}" for index in range(len(call.args)))
    values = call_arguments(call, positional)
    if values is None:
        return
    for name, value in values.items():
        resolved = unalias(value, visible_aliases)
        if _constructed_dependency(resolved, contracts, collaborator=spec is not None and name in spec.collaborators):
            yield resolved


def _constructed_dependency(value: ast.expr, contracts: DeclaredContracts, *, collaborator: bool) -> bool:
    if isinstance(value, ast.Name) and isinstance(
        contracts.context.static_resource_provenance.binding(value.id, value), ast.arg
    ):
        return False
    model = contracts.value(value)
    return model is not None and (collaborator or contracts.inherits(model, SETTINGS_BASES))


def _inside_raises(context: PythonFileContext, node: ast.AST, function: ast.AST) -> bool:
    while (parent := context.parents.get(node)) is not None and parent is not function:
        if isinstance(parent, ast.With | ast.AsyncWith) and any(
            isinstance(item.context_expr, ast.Call)
            and context.imports.resolves(item.context_expr.func, sources=frozenset({"pytest"}), symbol="raises")
            for item in parent.items
        ):
            return True
        node = parent
    return False

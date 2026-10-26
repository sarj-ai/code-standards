from __future__ import annotations

import ast
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
from sarj_python_lint.rules._declared_contracts import SETTINGS_BASES, DeclaredContracts, ordinary_pytest_test
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path
from sarj_python_lint.rules._pytest import collected_tests
from sarj_python_lint.rules._test_composition import bindings, call_arguments, constructor, direct_nodes, unalias


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


_EXAMPLE = "from typing import Protocol\nclass Port(Protocol):\n    def read(self): ...\nclass Store:\n    def read(self): return 1\nclass Service:\n    def __init__(self, store: Port):\n        self.store = store\n    def read(self): return self.store.read()\n"


_FACTORY_SOURCE = "import pytest\nfrom typing import Protocol\n\nclass Port(Protocol):\n    def read(self) -> int: ...\n\nclass Store:\n    def read(self) -> int:\n        return 1\n\nclass Service:\n    def __init__(self, store: Port) -> None:\n        self.store = store\n\n    def read(self) -> int:\n        return self.store.read()\n\n@pytest.fixture\ndef store_factory() -> type[Store]:\n    return Store\n\ndef test_read(store_factory: type[Store]) -> None:\n    if store_factory is Store:\n        service = Service(Store())\n        assert service.read() == 1\n"
_FACTORY_FIXED = "import pytest\nfrom typing import Protocol\n\nclass Port(Protocol):\n    def read(self) -> int: ...\n\nclass Store:\n    def read(self) -> int:\n        return 1\n\nclass Service:\n    def __init__(self, store: Port) -> None:\n        self.store = store\n\n    def read(self) -> int:\n        return self.store.read()\n\n@pytest.fixture\ndef store_factory() -> type[Store]:\n    return Store\n\ndef test_read(store_factory: type[Store]) -> None:\n    if store_factory is Store:\n        service = Service(store_factory())\n        assert service.read() == 1\n"


@final
class PreferPytestDependencyFixtures(ProjectRule):
    id = "prefer-pytest-dependency-fixtures"
    code = "SARJ526"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Pass test collaborators through fixtures instead of constructing dependency graphs inside tests.",
        rationale="Constructing collaborators in a test bypasses pytest's dependency graph, caching and overrides even when only one test currently needs the setup.",
        remediation="Request function-scoped store, service and settings fixtures by parameter. Use a typed factory fixture for variants or multiple instances. Keep construction under test explicit and preserve setup ordering and the actual owner's cleanup; do not create global singletons or autouse fixtures.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Source-visible module-level collaborator instances must also enter tests through fixtures. Argument binding must be explicit: starred positional arguments, keyword unpacking and duplicate bindings abstain rather than guessing collaborator ownership.",
            "Safe fixes only reuse an already-requested typed factory inside an authored runtime identity guard over a closed source-owned collaborator graph. They change only its immediate constructor callee; no fixture, signature, guard, setup event or lifecycle is introduced. All other findings require review.",
            "Checks collected pytest functions and plain test classes. A local or inline class construction must feed a proven stored-and-invoked ABC/Protocol collaborator, or a proven BaseSettings instance must be passed to a call. Names alone never identify a service. Constructor failure tests, fixtures, helpers, dynamic/unresolved sources, generated and test-support paths are excluded. No automatic fixture extraction or lifecycle change.",
        ),
        examples=(
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
        for function in collected_tests(context.tree.body):
            if ordinary_pytest_test(function, context):
                hits.update(_constructed_dependencies(function, context, contracts))
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
        ]


def _constructed_dependencies(
    function: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext, contracts: DeclaredContracts
) -> Iterator[ast.expr]:
    aliases = bindings(function)
    for call in (node for node in direct_nodes(function) if isinstance(node, ast.Call)):
        if _inside_raises(context, call, function):
            continue
        yield from _call_dependencies(call, context, contracts, aliases)


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

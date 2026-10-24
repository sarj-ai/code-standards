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
from sarj_python_lint.rules._test_composition import bindings, constructor, direct_nodes, unalias


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._test_composition import Constructor


_EXAMPLE = "from typing import Protocol\nclass Port(Protocol):\n    def read(self): ...\nclass Store:\n    def read(self): return 1\nclass Service:\n    def __init__(self, store: Port):\n        self.store = store\n    def read(self): return self.store.read()\n"


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
        autofix=AutofixPolicy.NONE,
        limitations=(
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
        spec = constructor(context, call.func, contracts.project, minimum_collaborators=1)
        visible_aliases = {key: item for key, item in aliases.items() if item.lineno < call.lineno}
        for name, value in _call_arguments(call, spec).items():
            resolved = unalias(value, visible_aliases)
            if _constructed_dependency(
                resolved, contracts, collaborator=spec is not None and name in spec.collaborators
            ):
                yield resolved


def _call_arguments(call: ast.Call, spec: Constructor | None) -> dict[str, ast.expr]:
    positional = spec.positional if spec is not None else tuple(f"argument-{index}" for index in range(len(call.args)))
    values = dict(zip(positional, call.args, strict=False))
    values.update({keyword.arg: keyword.value for keyword in call.keywords if keyword.arg is not None})
    return values


def _constructed_dependency(value: ast.expr, contracts: DeclaredContracts, *, collaborator: bool) -> bool:
    if isinstance(value, ast.Name) and isinstance(
        contracts.context.static_resource_provenance.binding(value.id, value), ast.arg
    ):
        return False
    model = contracts.value(value)
    return model is not None and (
        (isinstance(value, ast.Call) and collaborator) or contracts.inherits(model, SETTINGS_BASES)
    )


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

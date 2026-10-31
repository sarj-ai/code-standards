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
    is_suppressed,
)
from sarj_python_lint.rules._declared_contracts import DeclaredContracts
from sarj_python_lint.rules._fixture_contracts import abstract_ancestors, abstract_contract
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._pytest_contract_parameters import FixtureContractParameters
from sarj_python_lint.rules.pytest_fixture_returns_bare_tuple import fixture_declarations, fixture_yields


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_YIELD_WRAPPERS = frozenset(
    {
        f"{module}.{name}"
        for module in ("typing", "collections.abc")
        for name in ("Iterator", "AsyncIterator", "Generator", "AsyncGenerator")
    }
)
_SOURCE = "import pytest\nfrom abc import ABC, abstractmethod\nclass Store(ABC):\n    @abstractmethod\n    def read(self) -> int: ...\nclass SqlStore(Store):\n    def read(self) -> int: return 1\n@pytest.fixture\ndef store() -> SqlStore:\n    return SqlStore()\n"
_PARAMETER_SOURCE = "import pytest\nfrom abc import ABC, abstractmethod\nclass Store(ABC):\n    @abstractmethod\n    def read(self) -> int: ...\nclass SqlStore(Store):\n    def read(self) -> int: return 1\nclass Router:\n    def __init__(self, store: Store) -> None:\n        self.store = store\n@pytest.fixture\ndef router(store: SqlStore) -> Router:\n    return Router(store=store)\n"


@final
class PreferPytestFixtureContract(ProjectRule):
    id = "prefer-pytest-fixture-contract"
    code = "SARJ550"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Expose existing abstract contracts from pytest fixtures and injected parameters.",
        rationale="Concrete fixture exports and injected parameter annotations couple consumers to an implementation even when an existing ABC or Protocol supports the consumed operations.",
        remediation="Keep concrete construction in the fixture and annotate supplied instances and injected parameters with their existing ABC or Protocol. Retain a reviewed concrete annotation for implementation-specific behavior or stronger concrete guarantees.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Proven injected-parameter matches are blocking errors. Fixture export suggestions remain advisory warnings because cross-module consumers are unknown.",
            "Only proven pytest/pytest-asyncio fixtures and source-visible concrete subclasses of an ABC with declared abstract members or a Protocol are checked. No interface is invented or inferred from a class name.",
            "Single-instance annotations and Iterator/AsyncIterator/Generator/AsyncGenerator fixture annotations are supported; factory, union and collection contracts are excluded.",
            "Required fixture and ordinary pytest test parameters support single-instance annotations, compatible direct method calls and source-resolved forwarding to existing contract-typed parameters. Defaults, positional-only arguments, receivers and parametrized values are excluded.",
            "Implementation-only operations, variant operation signatures, owner-relative Self, runtime identity checks, unknown escapes and nested captures retain their concrete annotation. Cross-module fixture consumers remain unknown; exported fixture findings require review.",
            "Generated files, unresolved or opaque decorated classes/functions, generic and ambiguous contracts, dynamic collection, inheritance beyond eight levels and automatic annotation rewrites are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="concrete-store-fixture",
                title="The fixture exposes its storage implementation",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("tests/conftest.py", _SOURCE),),
                focus_path=PurePosixPath("tests/conftest.py"),
                expected_count=1,
                public=False,
            ),
            RuleExample(
                example_id="abstract-store-fixture",
                title="The fixture constructs SQL storage and exposes its contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python("tests/conftest.py", _SOURCE.replace("store() -> SqlStore", "store() -> Store")),
                ),
                focus_path=PurePosixPath("tests/conftest.py"),
                expected_count=0,
                public=False,
            ),
            RuleExample(
                example_id="concrete-injected-collaborator",
                scenario="injected-collaborator",
                title="A composition fixture exposes a concrete collaborator parameter",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("tests/conftest.py", _PARAMETER_SOURCE),),
                focus_path=PurePosixPath("tests/conftest.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="abstract-injected-collaborator",
                scenario="injected-collaborator",
                title="The composition fixture accepts the existing collaborator contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/conftest.py",
                        _PARAMETER_SOURCE.replace("router(store: SqlStore)", "router(store: Store)"),
                    ),
                ),
                focus_path=PurePosixPath("tests/conftest.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated or not is_test_path(context.path):
            return []
        contracts = DeclaredContracts(context)
        fixtures = tuple(fixture_declarations(context.tree))
        parameters = FixtureContractParameters(context, contracts, fixtures)
        hits = parameters.findings(self.code)
        for fixture in fixtures:
            if not parameters.supported_fixture(fixture):
                continue
            function, name = fixture.node, fixture.name
            annotation = _instance_annotation(function.returns, context, has_yield=fixture_yields(function))
            model = contracts.annotation(annotation) if annotation is not None else None
            if (
                model is None
                or model.declaration.type_params
                or any(isinstance(base, ast.Subscript) for base in model.declaration.bases)
                or abstract_contract(model, contracts)
                or is_suppressed(context.source_lines, function.lineno, self.code)
            ):
                continue
            candidates = abstract_ancestors(model, contracts)
            if len(candidates) != 1 or parameters.implementation_consumer(name, model, candidates[0]):
                continue
            hits.append(
                Diagnostic(
                    context.path,
                    function.returns.lineno if function.returns is not None else function.lineno,
                    function.returns.col_offset + 1 if function.returns is not None else function.col_offset + 1,
                    self.code,
                    f"Fixture `{name}` exposes `{model.declaration.name}`; annotate its supplied instance with the existing `{candidates[0].declaration.name}` contract, or retain a reviewed implementation-specific contract.",
                    severity=Severity.WARNING,
                )
            )
        return sorted(hits, key=lambda finding: (finding.line, finding.col))


def _instance_annotation(
    annotation: ast.expr | None, context: PythonFileContext, *, has_yield: bool
) -> ast.expr | None:
    node = context.annotation_semantics.resolve_alias(annotation)
    if isinstance(node, ast.Subscript):
        if not has_yield or context.module_imports.resolved_qualified_name(node.value) not in _YIELD_WRAPPERS:
            return None
        node = node.slice.elts[0] if isinstance(node.slice, ast.Tuple) and node.slice.elts else node.slice
    return node if isinstance(node, ast.Name | ast.Attribute) else None

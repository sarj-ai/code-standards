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
from sarj_python_lint.rules._declared_contracts import DeclaredClass, DeclaredContracts
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._test_composition import direct_nodes
from sarj_python_lint.rules.pytest_fixture_returns_bare_tuple import fixture_declarations


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_PORT_BASES = frozenset({"abc.ABC", "typing.Protocol", "typing_extensions.Protocol"})
_YIELD_WRAPPERS = frozenset(
    {
        f"{module}.{name}"
        for module in ("typing", "collections.abc")
        for name in ("Iterator", "AsyncIterator", "Generator", "AsyncGenerator")
    }
)
_MAX_DEPTH = 8
_SOURCE = "import pytest\nfrom abc import ABC, abstractmethod\nclass Store(ABC):\n    @abstractmethod\n    def read(self) -> int: ...\nclass SqlStore(Store):\n    def read(self) -> int: return 1\n@pytest.fixture\ndef store() -> SqlStore:\n    return SqlStore()\n"


@final
class PreferPytestFixtureContract(ProjectRule):
    id = "prefer-pytest-fixture-contract"
    code = "SARJ550"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Expose an existing abstract service contract from pytest fixtures.",
        rationale="A concrete fixture annotation couples ordinary consumers to a storage or provider implementation even when the class already implements an explicit service contract.",
        remediation="Keep concrete construction in the fixture and annotate the supplied instance with its existing ABC or Protocol. Retain a reviewed concrete annotation when a fixture deliberately exposes implementation-specific behavior.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only proven pytest/pytest-asyncio fixtures and source-visible concrete subclasses of an ABC with declared abstract members or a Protocol are checked. No interface is invented or inferred from a class name.",
            "Single-instance annotations and Iterator/AsyncIterator/Generator/AsyncGenerator fixture annotations are supported; factory, union and collection contracts are excluded.",
            "Direct local consumers that access members absent from every candidate contract retain their concrete annotation. Dynamic consumers and consumers in other modules cannot prove a fixture's intended surface; findings remain warnings requiring review.",
            "Generated files, unresolved or decorated classes, ambiguous multiple contracts, inherited abstract member discovery beyond eight levels and automatic annotation rewrites are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="concrete-store-fixture",
                title="The fixture exposes its storage implementation",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("tests/conftest.py", _SOURCE),),
                focus_path=PurePosixPath("tests/conftest.py"),
                expected_count=1,
                public=True,
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
        hits: list[Diagnostic] = []
        for fixture in fixture_declarations(context.tree):
            function, name = fixture.node, fixture.name
            annotation = _instance_annotation(function.returns, context)
            model = contracts.annotation(annotation) if annotation is not None else None
            if (
                model is None
                or _abstract_contract(model, contracts)
                or is_suppressed(context.source_lines, function.lineno, self.code)
            ):
                continue
            candidates = _abstract_ancestors(model, contracts)
            if len(candidates) != 1 or _implementation_consumer(name, candidates[0], context, contracts):
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
        return hits


def _instance_annotation(annotation: ast.expr | None, context: PythonFileContext) -> ast.expr | None:
    node = context.annotation_semantics.resolve_alias(annotation)
    if isinstance(node, ast.Subscript):
        if context.module_imports.resolved_qualified_name(node.value) not in _YIELD_WRAPPERS:
            return None
        node = node.slice.elts[0] if isinstance(node.slice, ast.Tuple) and node.slice.elts else node.slice
    return node if isinstance(node, ast.Name | ast.Attribute) else None


def _abstract_contract(model: DeclaredClass, contracts: DeclaredContracts) -> bool:
    if model.unit.tree is None:
        return False
    imports = ImportIndex.from_tree(model.unit.tree, module_scope_only=True)
    if any(
        imports.resolved_qualified_name(base) in {"typing.Protocol", "typing_extensions.Protocol"}
        for base in model.declaration.bases
    ):
        return True
    return bool(_abstract_members(model, contracts))


def _abstract_members(
    model: DeclaredClass, contracts: DeclaredContracts, seen: frozenset[ast.ClassDef] = frozenset()
) -> frozenset[str]:
    if model.unit.tree is None or model.declaration in seen or len(seen) >= _MAX_DEPTH:
        return frozenset()
    imports = ImportIndex.from_tree(model.unit.tree, module_scope_only=True)
    pending: set[str] = set()
    for base in model.declaration.bases:
        parent = contracts.class_type(base, model.unit)
        if parent is not None:
            pending.update(_abstract_members(parent, contracts, seen | {model.declaration}))
    for member in model.declaration.body:
        if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
            if any(
                imports.resolves(decorator, sources=frozenset({"abc"}), symbol="abstractmethod")
                for decorator in member.decorator_list
            ):
                pending.add(member.name)
            else:
                pending.discard(member.name)
    return frozenset(pending)


def _abstract_ancestors(model: DeclaredClass, contracts: DeclaredContracts) -> tuple[DeclaredClass, ...]:
    pending = [(model, 0)]
    seen: set[ast.ClassDef] = set()
    found: list[DeclaredClass] = []
    while pending:
        current, depth = pending.pop()
        if current.declaration in seen or depth >= _MAX_DEPTH:
            continue
        seen.add(current.declaration)
        for base in current.declaration.bases:
            owner = contracts.class_type(base, current.unit)
            if owner is None:
                continue
            if _abstract_contract(owner, contracts) and contracts.inherits(owner, _PORT_BASES):
                found.append(owner)
            else:
                pending.append((owner, depth + 1))
    return tuple(found)


def _implementation_consumer(
    fixture_name: str, contract: DeclaredClass, context: PythonFileContext, contracts: DeclaredContracts
) -> bool:
    members = _contract_members(contract, contracts)
    for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
        arguments = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        if not function.name.startswith("test_") or not any(argument.arg == fixture_name for argument in arguments):
            continue
        if any(
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == fixture_name
            and node.attr not in members
            for node in direct_nodes(function)
        ):
            return True
    return False


def _contract_members(model: DeclaredClass, contracts: DeclaredContracts, depth: int = 0) -> frozenset[str]:
    members = {
        member.name for member in model.declaration.body if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    members.update(
        member.target.id
        for member in model.declaration.body
        if isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name)
    )
    if depth < _MAX_DEPTH:
        for base in model.declaration.bases:
            parent = contracts.class_type(base, model.unit)
            if parent is not None:
                members.update(_contract_members(parent, contracts, depth + 1))
    return frozenset(members)

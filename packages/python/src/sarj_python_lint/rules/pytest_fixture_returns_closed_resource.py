from __future__ import annotations

import ast
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
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules.pytest_fixture_returns_bare_tuple import fixture_declarations


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


_SYNC_RESOURCES = frozenset(
    {
        "builtins.open",
        "io.open",
        "io.StringIO",
        "io.BytesIO",
        "tempfile.TemporaryFile",
        "tempfile.NamedTemporaryFile",
        "httpx.Client",
    }
)
_BAD = 'from io import StringIO\nimport pytest\n\n@pytest.fixture\ndef stream():\n    with StringIO("payload") as handle:\n        return handle\n'


@final
class PytestFixtureReturnsClosedResource(Rule):
    id: str = "pytest-fixture-returns-closed-resource"
    code: str = "SARJ525"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Yield a managed fixture resource until its requesting test finishes.",
        rationale=(
            "Returning a context-managed stream or HTTPX client exits its context before pytest receives the value. "
            "The requesting test receives an already closed resource instead of a usable dependency."
        ),
        remediation=(
            "Yield the resource inside its context so teardown follows the requesting test, updating the generator "
            "annotation as needed. If the contract deliberately supplies a closed resource, use an exact SARJ525 "
            "suppression with that reason. Review exception and cleanup behavior; no automatic rewrite is provided."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only proven pytest/pytest-asyncio fixtures in test paths with one decorator and a direct return inside the owning with/async with are analyzed.",
            "Recognizes built-in/io streams, tempfile TemporaryFile/NamedTemporaryFile, HTTPX Client and async-with AsyncClient; arbitrary context managers and TestClient are excluded.",
            "Aliases, escaped/rebound resources, provider mutation, nested helpers, generator fixtures, returned snapshots and returns after the context are not inferred.",
            "Unreachable branches and intentional closed-resource contracts are not inferred; findings are warnings requiring review.",
        ),
        examples=(
            RuleExample(
                example_id="fixture-returns-closed-stream",
                title="Returning exits the stream context before the test runs",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("tests/conftest.py", _BAD),),
                focus_path=PurePosixPath("tests/conftest.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="fixture-yields-live-stream",
                title="Yield keeps the stream open for the requesting test",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("tests/conftest.py", _BAD.replace("return handle", "yield handle")),),
                focus_path=PurePosixPath("tests/conftest.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            not is_test_path(context.path)
            or context.generated
            or "with" not in context.symbol_source
            or context.tree is None
        ):
            return []
        returns = [node for node in context.nodes(ast.Return) if isinstance(node.value, ast.Name)]
        if not returns:
            return []
        fixtures = {
            fixture.node
            for fixture in fixture_declarations(context.tree)
            if len(fixture.node.decorator_list) == 1
            and not (
                isinstance(fixture.decorator, ast.Call)
                and (fixture.decorator.args or any(keyword.arg is None for keyword in fixture.decorator.keywords))
            )
        }
        if not fixtures:
            return []
        provenance = context.static_resource_provenance
        generators = {provenance.scope(node) for node in context.nodes(ast.Yield, ast.YieldFrom)}
        fixtures.difference_update(generators)
        findings: list[Diagnostic] = []
        for returned in returns:
            if (
                provenance.scope(returned) not in fixtures
                or not isinstance(returned.value, ast.Name)
                or not _returns_managed_resource(returned.value, returned, provenance)
                or is_suppressed(context.source_lines, returned.lineno, self.code)
            ):
                continue
            findings.append(
                Diagnostic(
                    path=context.path,
                    line=returned.lineno,
                    col=returned.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        f"fixture returns `{returned.value.id}` after its context closes it; yield inside the context "
                        "until the requesting test finishes, or document an intentional closed-resource contract"
                    ),
                )
            )
        return findings


def _returns_managed_resource(value: ast.Name, returned: ast.Return, provenance: ResourceProvenance) -> bool:
    binding = provenance.binding(value.id, returned)
    item = provenance.parents.get(binding) if binding is not None else None
    if (
        not isinstance(binding, ast.Name)
        or not isinstance(item, ast.withitem)
        or item.optional_vars is not binding
        or not isinstance(item.context_expr, ast.Call)
    ):
        return False
    if (
        not provenance.contains(provenance.parents.get(item), returned)
        or value.id in provenance.mutated
        or not _resource_reads_are_local(value, binding, provenance)
    ):
        return False
    constructor = item.context_expr.func
    qualified = provenance.runtime_import_name(constructor)
    if qualified is None and _builtin_open(constructor, provenance):
        qualified = "builtins.open"
    owner = provenance.parents.get(item)
    return (
        qualified == "httpx.AsyncClient"
        if isinstance(owner, ast.AsyncWith)
        else isinstance(owner, ast.With) and qualified in _SYNC_RESOURCES
    )


def _builtin_open(constructor: ast.expr, provenance: ResourceProvenance) -> bool:
    if not isinstance(constructor, ast.Name) or constructor.id != "open":
        return False
    return (
        "open" not in provenance.mutated
        and not any("open" in names for names in provenance.bindings.values())
        and provenance.builtin_namespace_untouched
        and not provenance.wildcard
        and not provenance.dynamic_namespace
    )


def _resource_reads_are_local(value: ast.Name, binding: ast.AST, provenance: ResourceProvenance) -> bool:
    for read in provenance.reads.get(value.id, ()):
        if provenance.binding(value.id, read) is not binding:
            continue
        parent = provenance.parents.get(read)
        if read is value or (
            isinstance(parent, ast.Attribute) and parent.value is read and isinstance(parent.ctx, ast.Load)
        ):
            continue
        return False
    return True

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MAX_KEYWORDS = 6

# A builder only pays for itself once the same callee is built more than once.
_MIN_CONSTRUCTIONS = 2
_MIN_SHARED_KEYWORDS = 7

# `dict(a=1, b=2, ...)` is a mapping literal, not a domain object.
_DATA_CALLABLES = frozenset({"dict"})

# `<mapping>.update(a=1, b=2, ...)` spreads mapping entries — data again, and no
# object a builder could construct.
_DATA_METHODS = frozenset({"update"})

# `mock.assert_called_once_with(a=1, ...)` builds nothing: it pins the exact call
# the code under test made, so defaulting its keywords away deletes the assertion.
_MOCK_ASSERTION_PREFIX = "assert_"
_PYTEST_SOURCES = frozenset({"pytest"})
_SIMPLE_NAMESPACE_SOURCES = frozenset({"types"})
_MOCK_CALL_SOURCES = frozenset({"unittest.mock"})


class _CallHit(NamedTuple):
    node: ast.Call
    callee: str
    keywords: frozenset[str]


class _ReportableHit(NamedTuple):
    node: ast.Call
    keyword_count: int
    shared_keyword_count: int
    occurrence_count: int


class RepeatedKwargHeavyCallInTest(Rule):
    id: str = "repeated-kwarg-heavy-call-in-test"
    code: str = "SARJ045"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Tests repeat at least seven explicit keyword names across calls to the same callee.",
        rationale=(
            "Large repeated argument lists duplicate incidental setup, bury scenario differences, and make signature "
            "changes noisy within a test file."
        ),
        remediation=(
            "Extract a scenario helper with sensible defaults, or use a parametrized case table, and override only "
            "values relevant to each case. Suppress the finding when every argument intentionally specifies the "
            "contract, an ordered state transition, or a retry."
        ),
        category=RuleCategory.TESTING,
        limitations=(
            "Only calls to the same syntactic callee that share at least seven named arguments directly inside test functions are reported.",
            "Mapping construction, data-record helpers, mock assertions, fixtures, nested closures, generated files, and dynamic callees are allowed.",
        ),
        aliases=("kwarg-heavy-construction-in-test",),
        examples=(
            RuleExample(
                example_id="repeated-wide-construction",
                title="Tests repeat incidental order setup",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_call.py",
                        "def test_pending_order():\n"
                        "    request = CreateOrderRequest(\n"
                        '        organization_id="org-1", actor_id="user-1", currency="SAR",\n'
                        '        locale="ar-SA", channel="web", notify_customer=True, retry_limit=3,\n'
                        '        status="pending",\n'
                        "    )\n"
                        '    assert request.status == "pending"\n\n'
                        "def test_completed_order():\n"
                        "    request = CreateOrderRequest(\n"
                        '        organization_id="org-1", actor_id="user-1", currency="SAR",\n'
                        '        locale="ar-SA", channel="web", notify_customer=True, retry_limit=3,\n'
                        '        status="completed",\n'
                        "    )\n"
                        '    assert request.status == "completed"\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_call.py"),
                expected_count=2,
                public=True,
            ),
            RuleExample(
                example_id="construction-through-builder",
                title="Tests keep incidental order defaults in one helper",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_call.py",
                        "ORDER_DEFAULTS = {\n"
                        '    "organization_id": "org-1", "actor_id": "user-1", "currency": "SAR",\n'
                        '    "locale": "ar-SA", "channel": "web", "notify_customer": True, "retry_limit": 3,\n'
                        "}\n\n"
                        "def make_order(status):\n"
                        "    return CreateOrderRequest(**ORDER_DEFAULTS, status=status)\n\n"
                        "def test_pending_order():\n"
                        '    assert make_order("pending").status == "pending"\n\n'
                        "def test_completed_order():\n"
                        '    assert make_order("completed").status == "completed"\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_call.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        visitor = _KwargHeavyVisitor(ImportIndex.from_tree(tree))
        visitor.visit(tree)
        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    f"this {count}-keyword call shares {shared_count} keyword names across {occurrence_count} calls, "
                    "burying scenario differences in repeated setup. Extract a helper with defaults or a "
                    "parametrized case table; suppress SARJ045 when every argument is intentionally under test."
                ),
                severity=Severity.WARNING,
            )
            for node, count, shared_count, occurrence_count in visitor.reportable_hits()
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


class _KwargHeavyVisitor(ast.NodeVisitor):
    def __init__(self, imports: ImportIndex) -> None:
        super().__init__()
        self._imports: ImportIndex = imports
        self._func_names: list[str | None] = []
        self._class_names: list[str] = []
        self.hits: list[_CallHit] = []

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        name = None if _is_pytest_fixture(node, self._imports) else node.name
        self._func_names.append(name)
        self.generic_visit(node)
        self._func_names.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_names.append(node.name)
        self.generic_visit(node)
        self._class_names.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._func_names.append(None)
        self.generic_visit(node)
        self._func_names.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if (
            self._in_test_function()
            and not _is_data_callable(node.func, self._imports)
            and not _is_mock_assertion(node.func)
        ):
            keywords = frozenset(keyword.arg for keyword in node.keywords if keyword.arg is not None)
            callee = _callee_identity(node.func, tuple(self._class_names))
            if len(keywords) > _MAX_KEYWORDS and callee is not None:
                self.hits.append(_CallHit(node=node, callee=callee, keywords=keywords))
        self.generic_visit(node)

    def reportable_hits(self) -> list[_ReportableHit]:
        reportable: list[_ReportableHit] = []
        for hit in self.hits:
            shared_counts = [
                len(hit.keywords & other.keywords)
                for other in self.hits
                if other is not hit and other.callee == hit.callee
            ]
            repeated = [count for count in shared_counts if count >= _MIN_SHARED_KEYWORDS]
            if len(repeated) + 1 < _MIN_CONSTRUCTIONS:
                continue
            reportable.append(
                _ReportableHit(
                    node=hit.node,
                    keyword_count=len(hit.keywords),
                    shared_keyword_count=max(repeated),
                    occurrence_count=len(repeated) + 1,
                )
            )
        return reportable

    def _in_test_function(self) -> bool:
        nearest = self._func_names[-1] if self._func_names else None
        return nearest is not None and nearest.startswith("test_")


def _is_data_callable(func: ast.expr, imports: ImportIndex) -> bool:
    if isinstance(func, ast.Name) and func.id in _DATA_CALLABLES and imports.builtin_is_unshadowed(func.id):
        return True
    if isinstance(func, ast.Attribute) and func.attr in _DATA_METHODS:
        return True
    return imports.resolves(func, sources=_SIMPLE_NAMESPACE_SOURCES, symbol="SimpleNamespace") or imports.resolves(
        func,
        sources=_MOCK_CALL_SOURCES,
        symbol="call",
    )


def _is_pytest_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex) -> bool:
    return any(
        imports.resolves(
            decorator.func if isinstance(decorator, ast.Call) else decorator,
            sources=_PYTEST_SOURCES,
            symbol="fixture",
        )
        for decorator in node.decorator_list
    )


def _is_mock_assertion(func: ast.expr) -> bool:
    name = _callee_name(func)
    return name is not None and name.rsplit(".", maxsplit=1)[-1].startswith(_MOCK_ASSERTION_PREFIX)


def _callee_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parent = _callee_name(func.value)
        return f"{parent}.{func.attr}" if parent is not None else None
    return None


def _callee_identity(func: ast.expr, class_names: tuple[str, ...]) -> str | None:
    name = _callee_name(func)
    if name is None or not class_names or name.split(".", maxsplit=1)[0] not in {"self", "cls"}:
        return name
    return f"{'.'.join(class_names)}:{name}"

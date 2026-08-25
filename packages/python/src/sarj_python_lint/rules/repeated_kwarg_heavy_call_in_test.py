from __future__ import annotations

import ast
from collections import Counter
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MAX_KEYWORDS = 6

# A builder only pays for itself once the same callee is built more than once.
_MIN_CONSTRUCTIONS = 2

# `dict(a=1, b=2, ...)` is a mapping literal, not a domain object.
_DATA_CALLABLES = frozenset({"dict"})

# `<mapping>.update(a=1, b=2, ...)` spreads mapping entries — data again, and no
# object a builder could construct.
_DATA_METHODS = frozenset({"update"})

# `mock.assert_called_once_with(a=1, ...)` builds nothing: it pins the exact call
# the code under test made, so defaulting its keywords away deletes the assertion.
_MOCK_ASSERTION_PREFIX = "assert_"


class RepeatedKwargHeavyCallInTest(Rule):
    id: str = "repeated-kwarg-heavy-call-in-test"
    code: str = "SARJ045"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Tests repeat calls with seven or more explicit keyword arguments.",
        rationale=(
            "Large repeated argument lists duplicate incidental setup, bury scenario differences, and make signature "
            "changes noisy across the suite."
        ),
        remediation=(
            "Extract a scenario helper with sensible defaults and override only values relevant to each case; "
            "suppress the finding when every argument is intentionally part of the assertion."
        ),
        category=RuleCategory.TESTING,
        limitations=(
            "Only repeated calls to the same stable callee with seven or more named arguments directly inside test functions are reported.",
            "Mapping construction, mock assertions, fixtures, nested closures, and dynamic callees are allowed.",
        ),
        aliases=("kwarg-heavy-construction-in-test",),
        examples=(
            RuleExample(
                example_id="repeated-wide-construction",
                title="Tests repeat every constructor argument",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_call.py",
                        "def test_style():\n"
                        "    style = Style(\n"
                        '        color="red", bgcolor="black", bold=True, dim=True, italic=True,\n'
                        "        underline=True, blink=True, blink2=True, reverse=True,\n"
                        "    )\n"
                        "    assert str(style)\n\n"
                        "def test_style_again():\n"
                        "    other = Style(\n"
                        '        color="blue", bgcolor="white", bold=False, dim=True, italic=True,\n'
                        "        underline=True, blink=True, blink2=True, reverse=True,\n"
                        "    )\n"
                        "    assert str(other)\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_call.py"),
                expected_count=2,
                public=True,
            ),
            RuleExample(
                example_id="construction-through-builder",
                title="Tests override builder defaults",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_call.py",
                        "def build_style(**overrides):\n"
                        "    defaults = dict(\n"
                        '        color="red", bgcolor="black", bold=True,\n'
                        "        dim=True, italic=True, underline=True,\n"
                        "        blink=True, blink2=True, reverse=True,\n"
                        "    )\n"
                        "    return Style(**(defaults | overrides))\n\n"
                        "def test_style():\n"
                        "    style = build_style()\n"
                        "    assert str(style)\n\n"
                        "def test_style_again():\n"
                        '    other = build_style(color="blue", bgcolor="white", bold=False)\n'
                        "    assert str(other)\n",
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
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        visitor = _KwargHeavyVisitor()
        visitor.visit(tree)
        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    f"this test repeats a call with {count} explicit keywords, burying scenario differences "
                    "in duplicated setup. Extract a helper with defaults and override only what this case changes; "
                    "suppress SARJ045 when every argument is intentionally under test."
                ),
            )
            for node, count in visitor.reportable_hits()
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


class _KwargHeavyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        super().__init__()
        self._func_names: list[str | None] = []
        self.hits: list[tuple[ast.Call, int]] = []

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._func_names.append(node.name)
        self.generic_visit(node)
        self._func_names.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._func_names.append(None)
        self.generic_visit(node)
        self._func_names.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if self._in_test_function() and not _is_data_callable(node.func) and not _is_mock_assertion(node.func):
            named = [kw for kw in node.keywords if kw.arg is not None]
            if len(named) > _MAX_KEYWORDS:
                self.hits.append((node, len(named)))
        self.generic_visit(node)

    def reportable_hits(self) -> list[tuple[ast.Call, int]]:
        counts = Counter(name for node, _ in self.hits if (name := _callee_name(node.func)) is not None)
        return [
            (node, count)
            for node, count in self.hits
            # A callee with no stable name (a subscript, a call result) cannot be
            # counted, so it can never clear the repetition bar.
            if (name := _callee_name(node.func)) is not None and counts[name] >= _MIN_CONSTRUCTIONS
        ]

    def _in_test_function(self) -> bool:
        nearest = self._func_names[-1] if self._func_names else None
        return nearest is not None and nearest.startswith("test_")


def _is_data_callable(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id in _DATA_CALLABLES
    return isinstance(func, ast.Attribute) and func.attr in _DATA_METHODS


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

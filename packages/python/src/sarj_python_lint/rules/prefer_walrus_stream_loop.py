from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath
import re
from typing import ClassVar, Literal, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._paths import is_generated, is_test_path


_LOOP_CANDIDATE_RE = re.compile(r"\bwhile\b[^\n:]*\bTrue\b[^\n:]*:")
_MIN_BODY_LEN = 3
_MAX_REWRITE_COLUMNS = 100


class PreferWalrusStreamLoop(Rule):
    id: str = "prefer-walrus-stream-loop"
    code: str = "SARJ077"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Collapse a compact producer assignment and immediate sentinel break into a named-expression loop.",
        rationale="A named-expression loop can state a repeated producer call and its termination condition together.",
        remediation=(
            "For `if not value: break`, use `while (value := read()):`. "
            "For `if value is None: break`, preserve the sentinel with `while (value := read()) is not None:`."
        ),
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only `while True` loops beginning with a single-line call assignment and a physically adjacent falsy or `None` break are analyzed.",
            "Tests, generated files, comments attached to or separating the matched statements, blank lines, type comments, rewrites over 100 columns, loop or guard `else` clauses, and empty rewritten bodies are excluded.",
            "The producer receiver is not resolved; calls and awaited calls are accepted when the surrounding loop shape is otherwise exact.",
        ),
        examples=(
            RuleExample(
                example_id="explicit-stream-break",
                title="Stream loop assigns and then breaks",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/stream.py",
                        "while True:\n"
                        "    chunk = stream.read(8192)\n"
                        "    if not chunk:\n"
                        "        break\n"
                        "    process(chunk)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/stream.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="conditional-stream-binding",
                title="Stream loop binds in its condition",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/stream.py",
                        "while (chunk := stream.read(8192)):\n    process(chunk)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/stream.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="explicit-none-sentinel-break",
                title="Producer loop preserves a None sentinel",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/messages.py",
                        "while True:\n"
                        "    message = receive()\n"
                        "    if message is None:\n"
                        "        break\n"
                        "    consume(message)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/messages.py"),
                expected_count=1,
                scenario="none-sentinel",
                public=True,
            ),
            RuleExample(
                example_id="conditional-none-sentinel-binding",
                title="Named-expression loop keeps accepting falsy messages",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/messages.py",
                        "while (message := receive()) is not None:\n    consume(message)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/messages.py"),
                expected_count=0,
                scenario="none-sentinel",
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            _LOOP_CANDIDATE_RE.search(source) is None
            or "break" not in source
            or is_test_path(path)
            or is_generated(path, source)
        ):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        source_lines = source.splitlines()
        diags: list[Diagnostic] = []

        for node in nodes(tree, ast.While):
            if not (isinstance(node.test, ast.Constant) and node.test.value is True) or node.orelse or len(node.body) < _MIN_BODY_LEN:
                continue

            first_stmt = node.body[0]
            second_stmt = node.body[1]

            if (
                not isinstance(first_stmt, ast.Assign)
                or len(first_stmt.targets) != 1
                or not isinstance(first_stmt.targets[0], ast.Name)
                or first_stmt.type_comment is not None
                or not _is_producer_call(first_stmt.value)
            ):
                continue
            var_name = first_stmt.targets[0].id

            if not isinstance(second_stmt, ast.If):
                continue
            sentinel = _sentinel_kind(second_stmt, var_name)
            if sentinel is not None and _is_compact_physical_pair(
                first_stmt,
                second_stmt,
                var_name,
                source=source,
                source_lines=source_lines,
                sentinel=sentinel,
            ):
                line = first_stmt.lineno
                col = first_stmt.col_offset + 1
                if not is_suppressed(source_lines, line, self.code):
                    value = ast.get_source_segment(source, first_stmt.value)
                    if value is None:  # pragma: no cover - compact source-backed assignment.
                        continue
                    suffix = " is not None" if sentinel == "none" else ""
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=line,
                            col=col,
                            code=self.code,
                            message=(
                                f"Collapse the leading assignment and sentinel break into "
                                f"`while ({var_name} := {value}){suffix}:`."
                            ),
                        )
                    )

        return sorted(diags, key=lambda d: (d.line, d.col))


def _is_producer_call(value: ast.expr) -> bool:
    return isinstance(value, ast.Call) or (isinstance(value, ast.Await) and isinstance(value.value, ast.Call))


def _sentinel_kind(statement: ast.stmt, var_name: str) -> Literal["falsy", "none"] | None:
    if not (
        isinstance(statement, ast.If)
        and not statement.orelse
        and len(statement.body) == 1
        and isinstance(statement.body[0], ast.Break)
    ):
        return None
    test = statement.test
    if (
        isinstance(test, ast.UnaryOp)
        and isinstance(test.op, ast.Not)
        and isinstance(test.operand, ast.Name)
        and test.operand.id == var_name
    ):
        return "falsy"
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Is)):
        return None
    left, right = test.left, test.comparators[0]
    match left, right:
        case ast.Name(id=name), ast.Constant(value=None) if name == var_name:
            return "none"
        case ast.Constant(value=None), ast.Name(id=name) if name == var_name:
            return "none"
        case _:
            pass
    return None


def _is_compact_physical_pair(
    assignment: ast.Assign,
    guard: ast.If,
    var_name: str,
    *,
    source: str,
    source_lines: list[str],
    sentinel: Literal["falsy", "none"],
) -> bool:
    break_statement = guard.body[0]
    if not isinstance(break_statement, ast.Break):  # pragma: no cover - established by _sentinel_kind.
        return False
    if (
        assignment.end_lineno != assignment.lineno
        or guard.test.end_lineno != guard.lineno
        or guard.lineno != assignment.lineno + 1
        or break_statement.lineno != guard.lineno + 1
    ):
        return False
    if any(_has_trailing_comment(node, source_lines) for node in (assignment, guard.test, break_statement)):
        return False
    value = ast.get_source_segment(source, assignment.value)
    if value is None:
        return False
    suffix = " is not None" if sentinel == "none" else ""
    proposed = f"{' ' * guard.col_offset}while ({var_name} := {value}){suffix}:"
    return len(proposed) <= _MAX_REWRITE_COLUMNS


def _has_trailing_comment(node: ast.stmt | ast.expr, source_lines: list[str]) -> bool:
    if node.end_lineno is None or node.end_col_offset is None:
        return True
    return "#" in source_lines[node.end_lineno - 1][node.end_col_offset :]

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, override

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


if TYPE_CHECKING:
    from pathlib import Path

_MIN_BODY_LEN = 2


def _is_constant_true(node: ast.AST) -> bool:
    return (isinstance(node, ast.Constant) and node.value is True) or (isinstance(node, ast.Name) and node.id == "True")


def _is_falsy_break_check(test_node: ast.AST, var_name: str) -> bool:
    if (
        isinstance(test_node, ast.UnaryOp)
        and isinstance(test_node.op, ast.Not)
        and isinstance(test_node.operand, ast.Name)
        and test_node.operand.id == var_name
    ):
        return True
    if (
        isinstance(test_node, ast.Compare)
        and isinstance(test_node.left, ast.Name)
        and test_node.left.id == var_name
        and len(test_node.ops) == 1
        and isinstance(test_node.ops[0], ast.Is)
    ):
        right = test_node.comparators[0]
        if isinstance(right, ast.Constant) and right.value is None:
            return True
    return False


class PreferWalrusStreamLoop(Rule):
    id: str = "prefer-walrus-stream-loop"
    code: str = "SARJ077"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Bind each stream value in the `while` condition instead of using an explicit break.",
        rationale="A named-expression loop states the read, sentinel check, and iteration condition in one place.",
        remediation="Replace the leading assignment and immediate sentinel break with `while (value := read()):`.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only `while True` loops beginning with a simple assignment and an immediate falsy or `None` break are analyzed.",
            "Loops with an `else`, complex assignment targets, or additional work before the sentinel check are excluded.",
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
                        "while chunk := stream.read(8192):\n    process(chunk)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/stream.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        source_lines = source.splitlines()
        diags: list[Diagnostic] = []

        for node in nodes(tree, ast.While):
            if not _is_constant_true(node.test) or node.orelse or len(node.body) < _MIN_BODY_LEN:
                continue

            first_stmt = node.body[0]
            second_stmt = node.body[1]

            if (
                not isinstance(first_stmt, ast.Assign)
                or len(first_stmt.targets) != 1
                or not isinstance(first_stmt.targets[0], ast.Name)
            ):
                continue
            var_name = first_stmt.targets[0].id

            if (
                isinstance(second_stmt, ast.If)
                and len(second_stmt.body) == 1
                and isinstance(second_stmt.body[0], ast.Break)
                and _is_falsy_break_check(second_stmt.test, var_name)
            ):
                line = first_stmt.lineno
                col = first_stmt.col_offset + 1
                if not is_suppressed(source_lines, line, self.code):
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=line,
                            col=col,
                            code=self.code,
                            message=(
                                f"Use `while ({var_name} := ...)` loop condition instead of `while True:` "
                                f"with an explicit `break`."
                            ),
                        )
                    )

        return sorted(diags, key=lambda d: (d.line, d.col))

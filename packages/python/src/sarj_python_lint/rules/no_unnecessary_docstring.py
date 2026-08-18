"""SARJ420 — Docstrings are reserved for machine-consumed documentation.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_unnecessary_docstring.py
"""

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
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._docstrings import (
    docstring_expression,
    is_framework_consumed_docstring,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


_DOCTEST_PROMPT = ">>>"


@final
class NoUnnecessaryDocstring(Rule):
    id: str = "no-unnecessary-docstring"
    code: str = "SARJ420"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Keep docstrings only when a machine or framework consumes them.",
        rationale=(
            "Human-only docstrings duplicate names, signatures, and nearby code while creating a second prose surface "
            "that agents expand and maintainers must review."
        ),
        remediation=(
            "Delete the docstring; move a genuinely hidden local invariant to one concise comment, or suppress SARJ420 "
            "when an external documentation consumer cannot be detected mechanically."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Generated files, doctests, syntax-required stub bodies, schema classes, framework decorators, explicit "
                "__doc__/help/getdoc consumers, and local sarj-noqa suppressions are excluded."
            ),
            (
                "The rule is intentionally default-deny: public API documentation without mechanically visible "
                "consumption needs an auditable SARJ420 suppression."
            ),
        ),
        examples=(
            RuleExample(
                example_id="human-only-docstrings",
                title="Human-only module, class, and function prose",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        '"""Service entry points."""\n\nclass Service:\n    """Coordinates requests."""\n\n    def run(self) -> None:\n        """Run the service."""\n        return None\n',
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=3,
                public=True,
            ),
            RuleExample(
                example_id="framework-docstring",
                title="Framework consumes the function docstring",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/tools.py",
                        '@function_tool\ndef lookup_account(account_id: str) -> str:\n    """Look up an account for the model."""\n    return account_id\n',
                    ),
                ),
                focus_path=PurePosixPath("app/tools.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        explicitly_consumed = _explicit_docstring_consumers(tree)
        source_lines = source.splitlines()
        diagnostics: list[Diagnostic] = []
        for owner in _docstring_owners(tree):
            expression = docstring_expression(owner)
            if expression is None:
                continue
            docstring = ast.get_docstring(owner, clean=False)
            if docstring is None or _DOCTEST_PROMPT in docstring:
                continue
            if _is_syntax_required(owner) or is_framework_consumed_docstring(owner):
                continue
            if _owner_name(owner) in explicitly_consumed:
                continue
            if _suppressed_on_docstring(source_lines, expression, self.code):
                continue
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=expression.lineno,
                    col=expression.col_offset + 1,
                    code=self.code,
                    message=self.description,
                )
            )
        return sorted(diagnostics, key=lambda diagnostic: (diagnostic.line, diagnostic.col))


def _docstring_owners(tree: ast.Module) -> Iterable[ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef]:
    yield tree
    yield from (
        node for node in ast.walk(tree) if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _is_syntax_required(owner: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return not isinstance(owner, ast.Module) and len(owner.body) == 1


def _owner_name(owner: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    return "__doc__" if isinstance(owner, ast.Module) else owner.name


def _suppressed_on_docstring(source_lines: list[str], expression: ast.Expr, code: str) -> bool:
    end_line = expression.end_lineno or expression.lineno
    return any(is_suppressed(source_lines, line, code) for line in range(expression.lineno, end_line + 1))


def _explicit_docstring_consumers(tree: ast.Module) -> frozenset[str]:
    """Collect owners whose docstrings are visibly read by executable code."""
    consumed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == "__doc__":
            consumed.add("__doc__")
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and node.attr == "__doc__":
            if name := _final_name(node.value):
                consumed.add(name)
        elif (
            isinstance(node, ast.Call)
            and _final_name(node.func) in {"getdoc", "help"}
            and node.args
            and (name := _final_name(node.args[0])) is not None
        ):
            consumed.add(name)
    return frozenset(consumed)


def _final_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None

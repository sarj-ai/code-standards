"""SARJ085 — A class docstring that only re-spells the class name.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_redundant_class_docstring.py
"""

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
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._comments import is_protected, split_identifier
from sarj_python_lint.rules._docstrings import (
    VALUE_MARKER_RE,
    base_names,
    identifier_stems,
    is_framework_consumed_docstring,
    restates,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


class RedundantClassDocstring(Rule):
    id: str = "redundant-class-docstring"
    code: str = "SARJ085"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Class docstrings must add information beyond the class name and bases.",
        rationale="Restating a class declaration adds maintenance cost without helping a reader understand its contract.",
        remediation="Delete the redundant docstring or document an invariant, lifetime, exclusion, or other fact absent from the declaration.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Schema-carrying bases and decorators, runtime-consumed prompt decorators, generated files, and docstring-only class bodies are excluded.",
            "The rule compares conservative word stems; a novel term keeps the docstring.",
        ),
        examples=(
            RuleExample(
                example_id="class-name-restatement",
                title="Docstring repeats the class name",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/policy.py", 'class RetryPolicy:\n    """The retry policy."""\n\n    attempts: int = 3\n'
                    ),
                ),
                focus_path=PurePosixPath("app/policy.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="class-invariant",
                title="Docstring records an invariant",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/policy.py",
                        'class RetryPolicy:\n    """Retry policy required because the upstream caps concurrency."""\n\n    attempts: int = 3\n',
                    ),
                ),
                focus_path=PurePosixPath("app/policy.py"),
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
        diags: list[Diagnostic] = []
        for node in nodes(tree, ast.ClassDef):
            if self._is_ceremony(node):
                expr = node.body[0]
                diags.append(
                    Diagnostic(
                        path=path,
                        line=expr.lineno,
                        col=expr.col_offset + 1,
                        code=self.code,
                        message=self.description,
                    )
                )
        return sorted(diags, key=lambda d: d.line)

    @staticmethod
    def _is_ceremony(node: ast.ClassDef) -> bool:
        docstring = ast.get_docstring(node, clean=True)
        if not docstring or VALUE_MARKER_RE.search(docstring) or is_protected(docstring):
            return False
        if len(node.body) == 1:
            return False  # the docstring IS the body; deleting it leaves a syntax error
        bases = base_names(node)
        if is_framework_consumed_docstring(node):
            return False
        known = {*identifier_stems(node.name)}
        for base in bases:
            known |= identifier_stems(base)
        known |= {part for base in bases for part in split_identifier(base)}
        return restates(docstring, known)

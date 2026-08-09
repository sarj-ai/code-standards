"""SARJ098 — Reject duplicate names in a static package ``__all__``.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_duplicate_dunder_all_entry.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


@final
class NoDuplicateDunderAllEntry(Rule):
    """Find later duplicates in a fully static package export declaration."""

    id = "no-duplicate-dunder-all-entry"
    code = "SARJ098"
    documentation = RuleDocumentation(
        summary="static package `__all__` declarations should list each exported name once",
        rationale=(
            "Duplicate exports add noise to a package's public contract and commonly reveal copy-paste mistakes in "
            "generated or maintained facade lists."
        ),
        remediation="Remove each later duplicate while preserving the first declaration of the exported name.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only one fully static list or tuple assigned to module-level `__all__` is analyzed.",
            "Generated, dynamically reassigned, and non-Python declarations are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="duplicate-package-export",
                title="Duplicate name in a package export list",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "diagnostics/__init__.py",
                        '__all__ = ["Diagnostic", "AnalysisReport", "Diagnostic"]\n',
                    ),
                ),
                focus_path=PurePosixPath("diagnostics/__init__.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="unique-package-exports",
                title="Unique names in a package export list",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "diagnostics/__init__.py",
                        '__all__ = ["Diagnostic", "AnalysisReport"]\n',
                    ),
                ),
                focus_path=PurePosixPath("diagnostics/__init__.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix != ".py" or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        declarations = [statement for statement in tree.body if _assigns_dunder_all(statement)]
        if len(declarations) != 1:
            return []
        declaration = declarations[0]
        if _has_other_dunder_all_rebindings(tree, declaration):
            return []
        elements = _literal_elements(declaration)
        if elements is None:
            return []

        first_lines: dict[str, int] = {}
        findings: list[Diagnostic] = []
        for name, line, col in elements:
            first_line = first_lines.get(name)
            if first_line is None:
                first_lines[name] = line
                continue
            findings.append(
                Diagnostic(
                    path=path,
                    line=line,
                    col=col,
                    code=self.code,
                    message=(
                        f"`{name}` duplicates an earlier `__all__` entry on line {first_line}; remove the later entry."
                    ),
                    severity=Severity.WARNING,
                )
            )
        return findings


def _assigns_dunder_all(statement: ast.AST) -> bool:
    match statement:
        case ast.Assign(targets=targets):
            return any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets)
        case ast.AnnAssign(target=ast.Name(id="__all__")) | ast.AugAssign(target=ast.Name(id="__all__")):
            return True
        case _:
            return False


def _has_other_dunder_all_rebindings(tree: ast.Module, declaration: ast.stmt) -> bool:
    """Skip when code outside ``declaration`` can replace ``__all__``."""
    for statement in tree.body:
        if statement is declaration:
            continue
        for node in ast.walk(statement):
            if _assigns_dunder_all(node):
                return True
    return False


def _literal_elements(statement: ast.stmt) -> list[tuple[str, int, int]] | None:
    value: ast.expr | None
    match statement:
        case ast.Assign(targets=[ast.Name(id="__all__")]) | ast.AnnAssign(target=ast.Name(id="__all__"), simple=1):
            value = statement.value
        case _:
            return None
    if not isinstance(value, (ast.List, ast.Tuple)):
        return None
    elements: list[tuple[str, int, int]] = []
    for element in value.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        elements.append((element.value, element.lineno, element.col_offset + 1))
    return elements

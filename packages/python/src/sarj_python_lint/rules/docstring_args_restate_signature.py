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
from sarj_python_lint.rules._ast_index import children
from sarj_python_lint.rules._comments import is_protected
from sarj_python_lint.rules._docstrings import (
    PROMPT_DECORATOR_MARKERS,
    VALUE_MARKER_RE,
    arg_entries,
    arg_section,
    decorator_markers,
    identifier_stems,
    restates,
    signature_stems,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


class DocstringArgsRestateSignature(Rule):
    id: str = "docstring-args-restate-signature"
    code: str = "SARJ086"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Argument documentation must add facts beyond the function signature.",
        rationale="Repeating parameter names and types obscures useful behavioral contracts and drifts when signatures change.",
        remediation=(
            "Delete the human-only docstring or redundant argument section. Express author-controlled semantics with "
            "names and types; keep hidden constraints or units as a concise local comment."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The rule reads Google-style argument sections and requires every documented entry to be a restatement before reporting.",
            "Generated files, runtime-consumed prompt, CLI, and route docstrings, protected facts, and empty machine-generated stubs are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="argument-restates-signature",
                title="Argument description repeats its name",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/widgets.py",
                        'def count_widgets(tenant_id: str) -> int:\n    """Count active widgets.\n\n    Args:\n        tenant_id: Tenant ID\n    """\n    return 0\n',
                    ),
                ),
                focus_path=PurePosixPath("app/widgets.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="argument-documents-unit",
                title="Redundant argument section removed",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/widgets.py",
                        'def count_widgets(tenant_id: str) -> int:\n    """Count active widgets."""\n    return 0\n',
                    ),
                ),
                focus_path=PurePosixPath("app/widgets.py"),
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
        self._walk(tree, None, path, diags)
        return sorted(diags, key=lambda d: d.line)

    def _walk(self, node: ast.AST, class_name: str | None, path: Path, diags: list[Diagnostic]) -> None:
        for child in children(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._check_function(child, class_name, path, diags)
                self._walk(child, class_name, path, diags)
            elif isinstance(child, ast.ClassDef):
                self._walk(child, child.name, path, diags)
            else:
                self._walk(child, class_name, path, diags)

    def _check_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        class_name: str | None,
        path: Path,
        diags: list[Diagnostic],
    ) -> None:
        docstring = ast.get_docstring(node, clean=True)
        if not docstring:
            return
        block = arg_section(docstring)
        if block is None or VALUE_MARKER_RE.search(block) or is_protected(block):
            return
        if decorator_markers(node) & PROMPT_DECORATOR_MARKERS:
            return
        entries = arg_entries(block)
        if not entries:
            return
        known = signature_stems(node, class_name)
        for name, annotation, description in entries:
            if not description:
                return  # a machine-emitted `name (type):` stub — see the module docstring
            if not restates(description, known | identifier_stems(name) | identifier_stems(annotation)):
                return
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

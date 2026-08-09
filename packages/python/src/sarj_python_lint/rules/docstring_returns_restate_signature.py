"""SARJ087 — A `Returns:` block that only re-spells the name and the return annotation.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_docstring_returns_restate_signature.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
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
    decorator_markers,
    restates,
    sections,
    signature_stems,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_RETURN_SECTIONS = ("Returns", "Return", "Yields", "Yield")

# Identity semantics: whether the value handed back is a FRESH object or the
# receiver itself is the one fact `-> Self` and `-> Foo` cannot carry, and the
# words that state it (`new`, `copy`, `same`) are stopwords for the restatement
# tokenizer, so the block reads as pure ceremony without this.
_IDENTITY_RE = re.compile(
    r"\b(?:new|copy|copies|copied|clone[ds]?|fresh|same|itself|self|shallow|deep|"
    r"in[- ]place|unchanged|original)\b",
    re.IGNORECASE,
)


def _return_block(docstring: str) -> str | None:
    found = sections(docstring)
    for name in _RETURN_SECTIONS:
        if name in found:
            return found[name]
    return None


class DocstringReturnsRestateSignature(Rule):
    id: str = "docstring-returns-restate-signature"
    code: str = "SARJ087"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Return documentation must add facts beyond the function name and annotation.",
        rationale="Repeating the return type or function name adds noise and can become stale without explaining the result's semantics.",
        remediation="Remove the redundant return section, or document identity, units, constraints, or other behavior absent from the signature.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The rule reads Google-style return and yield sections and uses conservative signature-word matching.",
            "Generated files, runtime-consumed docstrings, protected facts, identity semantics, and whole-docstring restatements owned by SARJ050 are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="return-restates-signature",
                title="Return description repeats the signature",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/lines.py",
                        'def get_line_length(line: list[str]) -> int:\n    """Measure a rendered line.\n\n    Returns:\n        int: The length of the line.\n    """\n    return len(line)\n',
                    ),
                ),
                focus_path=PurePosixPath("app/lines.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="return-documents-semantics",
                title="Return description records semantics",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/lines.py",
                        'def get_line_length(line: list[str]) -> int:\n    """Measure a rendered line.\n\n    Returns:\n        The width in terminal cells, which is not the character count.\n    """\n    return len(line)\n',
                    ),
                ),
                focus_path=PurePosixPath("app/lines.py"),
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
        return sorted(diags, key=lambda diag: diag.line)

    def _walk(self, node: ast.AST, class_name: str | None, path: Path, diags: list[Diagnostic]) -> None:
        for child in children(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
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
        block = _return_block(docstring)
        if block is None:
            return
        if VALUE_MARKER_RE.search(block) or is_protected(block) or _IDENTITY_RE.search(block):
            return
        if decorator_markers(node) & PROMPT_DECORATOR_MARKERS:
            return
        stems = signature_stems(node, class_name)
        # The whole-docstring case is SARJ050's; reporting it here too would
        # make one deletion look like two findings.
        if restates(docstring, stems):
            return
        if not restates(block, stems):
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

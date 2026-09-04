from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
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
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._comments import is_protected, split_identifier, stem
from sarj_python_lint.rules._docstrings import VALUE_MARKER_RE, sections
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_SPECIAL_MODULES = frozenset({"__init__.py", "__main__.py"})
_SUMMARY_ONLY = frozenset({"summary"})
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")
_DOCSTRING_TOKEN_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?|\d+")
_GRAMMATICAL_FILLER = frozenset({"a", "an", "the"})
_MIN_DOUBLED_STEM_LENGTH = 2

# These words describe existence rather than purpose; unknown words are evidence
# that the docstring may say something the path cannot.
_MODULE_FILLER_STEMS = frozenset(
    stem(word)
    for word in (
        "class",
        "function",
        "helper",
        "implementation",
        "module",
        "operation",
        "utility",
        "utils",
    )
)


@final
class RedundantModuleDocstring(Rule):
    id: str = "redundant-module-docstring"
    code: str = "SARJ099"
    documentation = RuleDocumentation(
        summary=("Module docstring only repeats the filename and, optionally, its immediate parent package."),
        rationale="A one-line restatement of a module path duplicates information already visible to readers and search tools.",
        remediation=(
            "Remove the restatement after confirming module `__doc__` is not an external documentation or runtime "
            "contract. Clarify author-controlled names or exports, and keep durable constraints."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        aliases=("module-docstring-restates-path",),
        limitations=(
            "Only single-line summaries are compared, after generic module vocabulary is removed, with the complete normalized filename and optionally the complete immediate parent package.",
            "Shebang and main-guard modules, visible `__doc__` reads or publication, special modules, stubs, generated files, multiline documentation, and protected technical facts are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="module-path-restatement",
                title="Docstring repeats the module path",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("celery/utils/log.py", '"""Logging utilities."""\n\nVALUE = 1\n'),),
                focus_path=PurePosixPath("celery/utils/log.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="module-contract",
                title="Docstring records a module contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "celery/utils/log.py", '"""Logging utilities redact credentials."""\n\nVALUE = 1\n'
                    ),
                ),
                focus_path=PurePosixPath("celery/utils/log.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if self._excluded_path(path) or is_generated(path, source) or source.startswith("#!"):
            return []
        tree = parse_or_none(path, source)
        if tree is None or len(tree.body) <= 1:
            return []
        if _is_executable_module(tree) or _uses_module_docstring(tree):
            return []
        expression = tree.body[0]
        if (
            not isinstance(expression, ast.Expr)
            or not isinstance(expression.value, ast.Constant)
            or not isinstance(expression.value.value, str)
        ):
            return []
        docstring = ast.get_docstring(tree, clean=True)
        if not docstring or not self._is_plain_summary(expression, docstring):
            return []
        if not _restates_path(docstring, path):
            return []
        if is_suppressed(source.splitlines(), expression.lineno, self.code):
            return []
        return [
            Diagnostic(
                path=path,
                line=expression.lineno,
                col=expression.col_offset + 1,
                code=self.code,
                message=self.description,
                severity=Severity.WARNING,
            )
        ]

    @staticmethod
    def _excluded_path(path: Path) -> bool:
        return path.name in _SPECIAL_MODULES or path.suffix == ".pyi" or is_test_path(path)

    @staticmethod
    def _is_plain_summary(expression: ast.Expr, docstring: str) -> bool:
        if expression.end_lineno != expression.lineno or "\n" in docstring:
            return False
        if frozenset(sections(docstring)) != _SUMMARY_ONLY:
            return False
        if len(_SENTENCE_END_RE.findall(docstring)) > 1:
            return False
        return not VALUE_MARKER_RE.search(docstring) and not is_protected(docstring)


def _restates_path(docstring: str, path: Path) -> bool:
    content_words = [
        word
        for match in _DOCSTRING_TOKEN_RE.finditer(docstring)
        if (word := match.group(0).lower()) not in _GRAMMATICAL_FILLER
        and _module_stem(word) not in _MODULE_FILLER_STEMS
    ]
    if not content_words:
        return False
    filename = _component_tokens(path.stem)
    parent = _component_tokens(path.parent.name)
    filename_stems = _component_stems(filename)
    parent_stems = _component_stems(parent)
    for split_at in range(len(content_words) + 1):
        filename_words = content_words[:split_at]
        parent_words = content_words[split_at:]
        if not _matches_component(filename_words, filename, filename_stems):
            continue
        if not parent_words or _matches_component(parent_words, parent, parent_stems):
            return True
    return False


def _component_tokens(component: str) -> list[str]:
    tokens: list[str] = []
    for chunk in component.split("_"):
        if chunk.isascii():
            tokens.extend(split_identifier(chunk))
        else:
            tokens.extend(match.group(0).lower() for match in _DOCSTRING_TOKEN_RE.finditer(chunk))
    return tokens


def _component_stems(tokens: list[str]) -> list[str]:
    return [result for token in tokens if (result := _module_stem(token)) not in _MODULE_FILLER_STEMS]


def _matches_component(words: list[str], tokens: list[str], token_stems: list[str]) -> bool:
    word_stems = [_module_stem(word) for word in words]
    if word_stems == token_stems:
        return True
    return bool(words) and "".join(words) == "".join(tokens)


def _uses_module_docstring(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "__doc__" and isinstance(node.ctx, ast.Load):
            return True
        if isinstance(node, ast.Attribute) and node.attr == "__doc__":
            return True
        if isinstance(node, ast.Constant) and node.value == "__doc__":
            return True
    return False


def _is_executable_module(tree: ast.Module) -> bool:
    return any(isinstance(statement, ast.If) and _is_main_guard(statement.test) for statement in tree.body)


def _is_main_guard(node: ast.expr) -> bool:
    if isinstance(node, ast.BoolOp):
        return any(_is_main_guard(value) for value in node.values)
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
        return False
    operands = (node.left, node.comparators[0])
    return any(isinstance(operand, ast.Name) and operand.id == "__name__" for operand in operands) and any(
        isinstance(operand, ast.Constant) and operand.value == "__main__" for operand in operands
    )


def _module_stem(word: str) -> str:
    result = stem(word)
    if (
        result != word
        and len(result) >= _MIN_DOUBLED_STEM_LENGTH
        and result[-1] == result[-2]
        and result[-1] not in "aeiou"
    ):
        return result[:-1]
    return result

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
    parse_or_none,
)
from sarj_python_lint.rules._comments import is_protected, split_identifier, stem
from sarj_python_lint.rules._docstrings import STOPWORDS, VALUE_MARKER_RE, restates, sections
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_SPECIAL_MODULES = frozenset({"__init__.py", "__main__.py"})
_SUMMARY_ONLY = frozenset({"summary"})
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9']*")
_WORKING_WITH_RE = re.compile(r"\bworking\s+with\b", re.IGNORECASE)
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
        "level",
        "module",
        "operation",
        "utility",
    )
)


@final
class RedundantModuleDocstring(Rule):
    id: str = "redundant-module-docstring"
    code: str = "SARJ099"
    documentation = RuleDocumentation(
        summary="Module docstrings must add information beyond the file path.",
        rationale="A one-line restatement of a module path duplicates information already visible to readers and search tools.",
        remediation="Delete the redundant docstring or document an invariant, boundary, consumer, or compatibility constraint.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only single-line summary docstrings in non-test implementation modules are checked.",
            "Special modules, stubs, generated files, multiline documentation, and prose with protected technical facts are excluded.",
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
        if self._excluded_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None or len(tree.body) <= 1:
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
        return [
            Diagnostic(
                path=path,
                line=expression.lineno,
                col=expression.col_offset + 1,
                code=self.code,
                message=self.description,
                severity=Severity.ERROR,
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
    comparison = _WORKING_WITH_RE.sub("", docstring)
    path_stems = _path_stems(path)
    known_stems = path_stems | _MODULE_FILLER_STEMS
    if restates(comparison, known_stems):
        return True

    # Common doubled-consonant inflections lose a suffix but keep the doubled
    # consonant in the shared conservative stemmer (``logging`` -> ``logg``).
    content_stems = tuple(
        _module_stem(word)
        for match in _WORD_RE.finditer(comparison)
        if (word := match.group(0).lower()) not in STOPWORDS
    )
    if content_stems and all(content in known_stems for content in content_stems):
        return True

    # Lowercase compound filenames do not expose word boundaries to
    # ``split_identifier``; require the entire non-filler phrase to
    # reconstruct one path token so an extra purpose or constraint keeps the
    # docstring.
    content_words = tuple(
        word
        for match in _WORD_RE.finditer(comparison)
        if (word := match.group(0).lower()) not in STOPWORDS and stem(word) not in _MODULE_FILLER_STEMS
    )
    path_tokens = {*split_identifier(path.stem), *split_identifier(path.parent.name)}
    return bool(content_words) and "".join(content_words) in path_tokens


def _path_stems(path: Path) -> set[str]:
    tokens = [*split_identifier(path.stem), *split_identifier(path.parent.name)]
    return {_module_stem(token) for token in tokens}


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

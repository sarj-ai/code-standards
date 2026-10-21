from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    ColumnEncoding,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
)
from sarj_python_lint.rules._suppression_comments import scan_comments_or_none


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_SARJ = re.compile(r"(?:^|#\s*)sarj-noqa\b(?P<tail>[^#]*)", re.IGNORECASE)
_SARJ_CODES = re.compile(r"^:\s*SARJ\d+\b", re.IGNORECASE)
_PYRIGHT = re.compile(r"(?:^|#\s*)pyright:\s*(?P<tail>[^#]*)")
_SCOPED_IGNORE = re.compile(r"^ignore\s*\[\s*report[A-Za-z]+(?:\s*,\s*report[A-Za-z]+)*\s*,?\s*\]")
_DIAGNOSTIC = re.compile(r"^report[A-Z][A-Za-z]+$")
_WEAKENED = frozenset({"false", "none", "warning", "information", "hint"})
_WEAKER_MODES = frozenset({"basic", "standard"})
_DISABLED_CHECKS = frozenset({"analyzeUnannotatedFunctions", "disableBytesTypePromotions", "strictParameterNoneValue"})
_RUFF_BROAD = re.compile(
    r"^ruff:\s*(?:file-ignore\s*\[(?P<file>[^\]]+)\]|noqa\s*:\s*(?P<codes>[A-Za-z0-9_, ]+)|disable\s*\[[^\]]+\])",
    re.IGNORECASE,
)
_FLAKE8_BROAD = re.compile(r"^flake8:\s*noqa\s*:\s*[A-Za-z][A-Za-z0-9]*", re.IGNORECASE)
_BAD = "def value() -> str:\n    return 1 # pyright: ignore\n"
_GOOD = "value = vendor.value # pyright: ignore[reportPrivateUsage] -- the dependency exposes this API only privately\n"


@final
class NoBlanketSuppression(Rule):
    id = "no-blanket-suppression"
    code = "SARJ523"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Use named, line-local suppressions instead of blanket, file or range disables.",
        rationale=(
            "A blanket suppression hides unrelated errors on its line. A file-level diagnostic downgrade also "
            "authorizes future defects outside the reviewed exception. Suppression checks cannot waive themselves."
        ),
        remediation="Fix the diagnostic or use an exact, line-local rule code with a concrete boundary reason.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks actual Python comment tokens for bare or empty sarj-noqa, unscoped pyright: ignore, basic/standard Pyright modes, report* downgrades below error, analyzeUnannotatedFunctions/disableBytesTypePromotions/strictParameterNoneValue=false and scoped Ruff/Flake8 file or Ruff range disables. SARJ054 retains precedence for Ruff banned-api file directives.",
            "Ruff owns blanket noqa and type: ignore through PGH004 and PGH003. Exact local exceptions remain available; this rule does not judge whether their explanations justify the exception.",
            "Directive examples inside strings and unrelated Pyright feature flags are excluded. Source-generated markers cannot waive accountability; use explicit whole-path exclusions for generated/vendor code. Consumer type-checker configuration remains outside this source rule.",
            "The full Standards gate protects this rule and the existing suppression-accountability checks from inline waivers, rule exclusions and diagnostic baselines. Explicitly selected partial checks remain scoped.",
        ),
        examples=(
            RuleExample(
                example_id="blanket-type-ignore",
                title="An unscoped ignore hides every diagnostic on the line",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/adapter.py", _BAD),),
                focus_path=PurePosixPath("app/adapter.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="exact-local-exception",
                title="A named diagnostic retains the dependency boundary explanation",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/adapter.py", _GOOD),),
                focus_path=PurePosixPath("app/adapter.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        findings: list[Diagnostic] = []
        for comment in scan_comments_or_none(context.source) or ():
            bare_sarj = any(_SARJ_CODES.match(match["tail"]) is None for match in _SARJ.finditer(comment.body))
            broad_pyright = any(
                _broad_pyright(match["tail"].strip(), configuration=match.start() == 0)
                for match in _PYRIGHT.finditer(comment.body)
            )
            broad_ruff = _broad_ruff(comment.body) if comment.standalone else False
            if bare_sarj or broad_pyright or broad_ruff:
                findings.append(
                    Diagnostic(
                        context.path,
                        comment.line,
                        comment.col,
                        self.code,
                        "Use a named, line-local suppression with a concrete reason; blanket ignores and "
                        "file/range disables hide unrelated diagnostics.",
                        column_encoding=ColumnEncoding.CODEPOINTS,
                    )
                )
        return findings


def _broad_ruff(body: str) -> bool:
    if _FLAKE8_BROAD.match(body) is not None:
        return True
    match = _RUFF_BROAD.match(body)
    if match is None:
        return False
    selectors = (match["file"] or match["codes"] or "").upper()
    return not {"TID251", "BANNED-API"}.intersection(part.strip() for part in selectors.split(","))


def _broad_pyright(tail: str, *, configuration: bool) -> bool:
    if re.match(r"ignore(?=$|\s|\[)", tail) is not None:
        return _SCOPED_IGNORE.match(tail) is None
    if not configuration:
        return False
    options = tail.split("--", 1)[0].split("—", 1)[0].split(",")
    for raw in options:
        option = raw.strip()
        if option in _WEAKER_MODES:
            return True
        name, separator, value = option.partition("=")
        if separator and name.strip() in _DISABLED_CHECKS and value.strip() == "false":
            return True
        if separator and _DIAGNOSTIC.fullmatch(name.strip()) and value.strip() in _WEAKENED:
            return True
    return False

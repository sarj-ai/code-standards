from __future__ import annotations

from abc import ABC, abstractmethod
import ast
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import re
from typing import TYPE_CHECKING, ClassVar, Final

from sarj_rule_contracts import (
    AutofixPolicy as AutofixPolicy,
    ExampleFile as ExampleFile,
    ExampleOutcome as ExampleOutcome,
    NativeRuleSpec as NativeRuleSpec,
    RuleCategory as RuleCategory,
    RuleDocumentation as RuleDocumentation,
    RuleExample as RuleExample,
    Severity as Severity,
)

from sarj_python_lint._python_target import PythonTargetFacts


if TYPE_CHECKING:
    from collections.abc import Sequence

    from sarj_python_lint._analysis_session import AnalysisSession
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._project_index import ProjectIndexSet


# Each rule points directly to its executable examples.
REPO_BLOB: Final = "https://github.com/sarj-ai/code-standards/blob/main"
TESTS_DIR: Final = "packages/python/tests/rules"


# Keep SARJ suppressions separate because Ruff removes unknown `noqa` codes.
_SARJ_NOQA_RE = re.compile(
    r"#\s*sarj-noqa(?::\s*([A-Za-z0-9_, ]+))?",
    re.IGNORECASE,
)


def is_suppressed(source_lines: Sequence[str], line: int, code: str) -> bool:
    if line < 1 or line > len(source_lines):
        return False
    text = source_lines[line - 1]
    m = _SARJ_NOQA_RE.search(text)
    if not m:
        return False
    codes_str = m.group(1)
    if not codes_str:
        # A bare sarj-noqa intentionally suppresses every SARJ code on its line.
        return True
    codes = {val.upper() for c in codes_str.split(",") if (val := c.strip())}
    return code.upper() in codes


class ColumnEncoding(StrEnum):
    UTF8_BYTES = "utf8-bytes"
    CODEPOINTS = "codepoints"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    path: Path
    line: int
    col: int
    code: str
    message: str
    severity: Severity = Severity.ERROR
    column_encoding: ColumnEncoding = ColumnEncoding.UTF8_BYTES

    def format(self) -> str:
        label = "warning: " if self.severity is Severity.WARNING else ""
        return f"{self.path}:{self.line}:{self.col}: {self.code} {label}{self.message}"


class Rule(ABC):
    id: str
    code: str
    description: str
    documentation: ClassVar[RuleDocumentation | None] = None
    _analysis_session: AnalysisSession | None = None

    def prepare_session(self, session: AnalysisSession) -> None:
        self._analysis_session = session

    def has_declared_python_support_before(self, path: Path, minimum: tuple[int, int]) -> bool:
        facts = self._analysis_session.python_target if self._analysis_session is not None else PythonTargetFacts()
        return facts.has_declared_support_before(path, minimum)

    def check(self, path: Path, source: str) -> list[Diagnostic]:
        from sarj_python_lint._file_context import PythonFileContext  # ruff: ignore[import-outside-top-level] — avoids registry import cycle

        context = PythonFileContext(path, source, self._analysis_session)
        if isinstance(self, ProjectRule):
            context.session.project = self.project_indexes
        return self.check_context(context)

    @abstractmethod
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        raise NotImplementedError

    @classmethod
    def examples_path(cls) -> str:
        return f"{TESTS_DIR}/test_{cls.__module__.rpartition('.')[2]}.py"

    @classmethod
    def examples_url(cls) -> str:
        return f"{REPO_BLOB}/{cls.examples_path()}"

    @classmethod
    def native_spec(cls) -> NativeRuleSpec | None:
        authored = cls.documentation
        if authored is None:
            return None
        if cls.id in authored.aliases:
            msg = f"{cls.id}: a live rule ID cannot also be a historical alias"
            raise ValueError(msg)
        if authored.summary != cls.description:
            msg = f"{cls.id}: description must be the authored documentation summary"
            raise ValueError(msg)
        return NativeRuleSpec(
            engine="python",
            rule_id=cls.id,
            code=cls.code,
            summary=authored.summary,
            rationale=authored.rationale,
            remediation=authored.remediation,
            category=authored.category,
            default_level=authored.default_level,
            autofix=authored.autofix,
            aliases=authored.aliases,
            limitations=authored.limitations,
            examples=authored.examples,
        )

    @classmethod
    def public_examples(cls) -> tuple[RuleExample, ...]:
        spec = cls.native_spec()
        return () if spec is None else spec.public_examples


class ProjectRule(Rule, ABC):
    project_indexes: ProjectIndexSet | None = None

    def prepare(self, indexes: ProjectIndexSet) -> None:
        self.project_indexes = indexes


def parse_or_none(path: Path, source: str) -> ast.Module | None:
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        tree = None
    return tree

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import re
from typing import TYPE_CHECKING, ClassVar

from sarj_rule_contracts import (
    AutofixPolicy as AutofixPolicy,
    DefaultLevel as DefaultLevel,
    ExampleFile as ExampleFile,
    ExampleOutcome as ExampleOutcome,
    NativeRuleSpec as NativeRuleSpec,
    RuleCategory as RuleCategory,
    RuleDocumentation as RuleDocumentation,
    RuleExample as RuleExample,
)


if TYPE_CHECKING:
    from collections.abc import Sequence


_SARJ_NOQA_RE = re.compile(
    r"#\s*sarj-noqa(?::\s*([A-Za-z0-9_, ]+))?",
    re.IGNORECASE,
)


def is_suppressed(source_lines: Sequence[str], line: int, code: str) -> bool:
    """Report whether the diagnostic's line carries a `# sarj-noqa[: CODE]` comment."""
    if line < 1 or line > len(source_lines):
        return False
    m = _SARJ_NOQA_RE.search(source_lines[line - 1])
    if not m:
        return False
    codes_str = m.group(1)
    if not codes_str:
        return True
    codes = {val.upper() for c in codes_str.split(",") if (val := c.strip())}
    return code.upper() in codes


@dataclass(frozen=True, slots=True)
class Diagnostic:
    path: Path
    line: int
    col: int
    code: str
    message: str
    suppressible: bool = True
    baselineable: bool = True

    def format(self) -> str:
        return f"{self.path}:{self.line}:{self.col}: {self.code} {self.message}"


class Rule(ABC):
    id: str
    code: str
    description: str
    documentation: ClassVar[RuleDocumentation | None] = None

    @abstractmethod
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        raise NotImplementedError

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
            engine="iac",
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

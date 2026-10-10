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

from sarj_iac_lint._hcl import suppression_comment_lines


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


_SARJ_NOQA_RE = re.compile(
    r"#\s*sarj-noqa(?![\w-])\s*(?:(?P<colon>:)\s*(?P<codes>[A-Za-z0-9_, \t]*))?",
    re.IGNORECASE,
)
_NOQA_CODE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*", re.IGNORECASE)


def is_suppressed(
    source_lines: Sequence[str], line: int, code: str, *, comments: Mapping[int, str] | None = None
) -> bool:
    if line < 1 or line > len(source_lines):
        return False
    m = _SARJ_NOQA_RE.search(source_lines[line - 1])
    if not m:
        return False
    comment_source = suppression_comment_lines("\n".join(source_lines)) if comments is None else comments
    comment = comment_source.get(line, "")
    m = _SARJ_NOQA_RE.search(comment)
    if m is None:
        return False
    if m.group("colon") is None:
        return True
    codes_str = m.group("codes")
    if not codes_str:
        return False
    suffix = comment[m.end() :]
    separated_dash = codes_str[-1].isspace() and suffix.startswith("-")
    if suffix and not (suffix.startswith(("--", "—", "–", "*/", '"', "'", "#")) or separated_dash):
        return False
    codes = {item.strip().upper() for item in codes_str.split(",")}
    if any(_NOQA_CODE_RE.fullmatch(item) is None for item in codes):
        return False
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

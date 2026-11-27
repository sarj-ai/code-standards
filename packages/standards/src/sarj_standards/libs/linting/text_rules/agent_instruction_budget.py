from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import final, override

from sarj_standards.libs.linting.text_rule_base import Finding, Rule, RuleMeta
from sarj_standards.libs.rules import DefaultLevel, ExampleFile, ExpectedOutcome, Language, RuleCategory, RuleExample


_WORDS = 1_000
_NAMES = frozenset({"AGENTS.md", "CLAUDE.md", "SKILL.md"})


def _example(source: str) -> tuple[ExampleFile, ...]:
    return (ExampleFile(path=PurePosixPath("AGENTS.md"), source=source),)


@final
class AgentInstructionBudget(Rule):
    id = "agent-instruction-budget"
    documentation = RuleMeta(
        code="SARJ318",
        default_level=DefaultLevel.ERROR,
        summary="Keep AGENTS.md, CLAUDE.md and SKILL.md within 1,000 words.",
        rationale="Agents load these files into every relevant context. Oversized instructions dilute the constraints that matter and accumulate stale or redundant guidance.",
        remediation="Delete stale, redundant or default-behavior guidance, link one canonical document, or move machine-checkable prose into a lint rule.",
        category=RuleCategory.MAINTAINABILITY,
        languages=frozenset({Language.MARKDOWN}),
        file_patterns=("**/AGENTS.md", "**/CLAUDE.md", "**/SKILL.md"),
        examples=(
            RuleExample(
                example_id="oversized-instructions",
                title="Instructions over the word budget are rejected",
                outcome=ExpectedOutcome.MATCH,
                files=_example("word " * (_WORDS + 1)),
                focus_path=PurePosixPath("AGENTS.md"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="concise-instructions",
                title="Concise instructions remain within budget",
                outcome=ExpectedOutcome.NO_MATCH,
                files=_example("# Rules\n\nRun `make verify` before review.\n"),
                focus_path=PurePosixPath("AGENTS.md"),
                expected_count=0,
                public=True,
            ),
        ),
        limitations=(
            "Counts whitespace-separated words in the whole file, like `wc -w`, including front matter and code fences; other Markdown is out of scope. Under `.agents/skills` and `.claude/skills` only `<skill>/SKILL.md` is checked, and not when the skill directory has a `LICENSE` or `source.json` vendoring marker; exclude other installed skills with `[exclude] paths`.",
        ),
    )

    @override
    def check(self, path: Path, source: str) -> list[Finding]:
        words = len(source.split())
        if path.name not in _NAMES or words <= _WORDS:
            return []
        return [
            Finding(
                path, 1, "SARJ318", f"{path.name} has {words:,} words; keep agent instructions within {_WORDS:,} words."
            )
        ]

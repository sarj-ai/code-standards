from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_examples

from sarj_standards import api
from sarj_standards.libs.linting.text_rules.agent_instruction_budget import AgentInstructionBudget
from sarj_standards.libs.repository.rule_examples import selected
from sarj_standards.libs.rules import RuleSelector


def test_documented_examples() -> None:
    rule = selected(RuleSelector.parse("text:agent-instruction-budget"))
    verify_examples(rule.spec.examples, rule.analyze)


@pytest.mark.parametrize(
    ("path", "words", "expected"),
    [
        ("pkg/CLAUDE.md", 1_001, 1),
        (".agents/skills/x/SKILL.md", 1_001, 1),
        ("AGENTS.md", 1_000, 0),
        ("README.md", 5_000, 0),
    ],
)
def test_budget_applies_to_agent_instruction_files(path: str, words: int, expected: int) -> None:
    assert len(AgentInstructionBudget().check(Path(path), "word\n" * words)) == expected


def test_fingerprint_ignores_the_word_count(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"

    def fingerprint(words: int) -> str | None:
        path.write_text("word\n" * words, encoding="utf-8")
        report = api.Standards(tmp_path).analyze(
            [str(path)], mode=api.AnalysisMode.RAW, rules=["text:agent-instruction-budget"]
        )
        return report.diagnostics[0].fingerprint

    assert fingerprint(1_002) == fingerprint(1_001)

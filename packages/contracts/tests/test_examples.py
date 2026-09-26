from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from sarj_rule_contracts import ExampleFile, ExpectedOutcome, RuleExample
from sarj_rule_contracts.examples import ExampleFinding, verify_examples


def _examples() -> tuple[RuleExample, ...]:
    return tuple(
        RuleExample(
            example_id=label,
            title=label,
            outcome=outcome,
            files=(
                ExampleFile(PurePosixPath("case.py"), source),
                ExampleFile(PurePosixPath("support.py"), "value = 1\n"),
            ),
            focus_path=PurePosixPath("case.py"),
            expected_count=count,
            public=True,
        )
        for label, source, outcome, count in (
            ("rejects", "bad = True\n", ExpectedOutcome.MATCH, 1),
            ("accepts", "good = True\n", ExpectedOutcome.NO_MATCH, 0),
        )
    )


@pytest.mark.parametrize("behavior", ["unimplemented", "always-clean", "always-report", "correct"])
def test_examples_reject_broken_detectors(behavior: str) -> None:
    roots: list[Path] = []

    def analyze(root: Path, focus: Path) -> list[ExampleFinding]:
        roots.append(root)
        assert (root / "support.py").read_text(encoding="utf-8") == "value = 1\n"
        if behavior == "unimplemented":
            raise NotImplementedError
        report = behavior == "always-report" or (behavior == "correct" and "bad" in focus.read_text(encoding="utf-8"))
        return [ExampleFinding(focus, 1, 1, "SARJ999")] if report else []

    if behavior == "correct":
        assert verify_examples(_examples(), analyze) == 2
        assert len(set(roots)) == 2
    else:
        with pytest.raises((ValueError, NotImplementedError)):
            verify_examples(_examples(), analyze)
    assert all(not root.exists() for root in roots)


def test_duplicate_diagnostics_cannot_satisfy_expected_count() -> None:
    def analyze(_root: Path, focus: Path) -> list[ExampleFinding]:
        return [ExampleFinding(focus, 1, 1, "SARJ999")] * 2

    with pytest.raises(ValueError, match="duplicate diagnostic"):
        verify_examples(_examples(), analyze)

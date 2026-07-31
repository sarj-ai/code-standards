"""The examples/evidence links are derived, so a rename breaks a test, not a reader.

`test_rule_meta.py` asserts the derived paths resolve for every registered rule. This
file pins the derivation itself, because that is the part a future edit could quietly
weaken — swapping the classmethod for a hand-written string would still pass
`test_rule_meta` on the day it landed and rot on the first rename.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import main
from sarj_python_lint.rule_base import EVIDENCE_DIR, REPO_BLOB, TESTS_DIR, Diagnostic, Rule
from sarj_python_lint.rules import REGISTRY
from sarj_python_lint.rules.no_fstring_in_log import NoFstringInLog
from sarj_python_lint.rules.stepdown import Stepdown


if TYPE_CHECKING:
    from pathlib import Path


class _Fake(Rule):
    id: str = "fake-rule"
    code: str = "SARJ999"

    def check(self, path: Path, source: str) -> list[Diagnostic]:
        del path, source
        return []


def test_examples_path_is_derived_from_the_module_name() -> None:
    assert NoFstringInLog.examples_path() == f"{TESTS_DIR}/test_no_fstring_in_log.py"


def test_evidence_path_is_derived_from_the_code() -> None:
    assert NoFstringInLog.evidence_path() == f"{EVIDENCE_DIR}/SARJ017.md"


def test_urls_are_the_paths_under_the_repo_blob() -> None:
    assert NoFstringInLog.examples_url() == f"{REPO_BLOB}/{NoFstringInLog.examples_path()}"
    assert NoFstringInLog.evidence_url() == f"{REPO_BLOB}/{NoFstringInLog.evidence_path()}"


def test_derivation_follows_a_class_defined_anywhere() -> None:
    """The link tracks `__module__`, not a string on the class — which is the whole point."""
    assert _Fake.examples_path() == f"{TESTS_DIR}/test_test_rule_links.py"
    assert _Fake.evidence_path() == f"{EVIDENCE_DIR}/SARJ999.md"


def test_has_evidence_defaults_to_false() -> None:
    assert _Fake.has_evidence is False


def test_every_rule_link_is_unique() -> None:
    """Two rules sharing an examples path would let one rule's tests vouch for another."""
    paths = [cls.examples_path() for cls in REGISTRY.values()]
    assert len(paths) == len(set(paths))


@pytest.mark.parametrize("spelling", ["SARJ017", "sarj017", "no-fstring-in-log"])
def test_explain_accepts_a_code_or_an_id(spelling: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", spelling]) == 0
    out = capsys.readouterr().out
    assert "SARJ017  no-fstring-in-log" in out
    assert f"examples: {NoFstringInLog.examples_url()}" in out


def test_explain_prints_the_evidence_link_only_when_there_is_evidence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert NoFstringInLog.has_evidence
    assert main(["explain", "no-fstring-in-log"]) == 0
    assert f"evidence: {NoFstringInLog.evidence_url()}" in capsys.readouterr().out

    assert not Stepdown.has_evidence
    assert main(["explain", "stepdown"]) == 0
    assert "evidence:" not in capsys.readouterr().out


def test_explain_reports_an_unknown_rule_without_raising(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", "no-such-rule"]) == 2
    assert "unknown rule" in capsys.readouterr().err

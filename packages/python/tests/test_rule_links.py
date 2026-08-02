"""Rule documentation resolves to its executable examples."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import main
from sarj_python_lint.rule_base import REPO_BLOB, TESTS_DIR, Diagnostic, Rule
from sarj_python_lint.rules import REGISTRY
from sarj_python_lint.rules.no_fstring_in_log import NoFstringInLog


if TYPE_CHECKING:
    from pathlib import Path


class _Fake(Rule):
    id: str = "fake-rule"
    code: str = "SARJ999"
    description: str = "Fake rule used to test derived example links."

    def check(self, path: Path, source: str) -> list[Diagnostic]:
        del path, source
        return []


def test_examples_path_is_derived_from_the_module_name() -> None:
    assert NoFstringInLog.examples_path() == f"{TESTS_DIR}/test_no_fstring_in_log.py"


def test_examples_url_is_the_path_under_the_repo_blob() -> None:
    assert NoFstringInLog.examples_url() == f"{REPO_BLOB}/{NoFstringInLog.examples_path()}"


def test_derivation_follows_a_class_defined_anywhere() -> None:
    assert _Fake.examples_path() == f"{TESTS_DIR}/test_test_rule_links.py"


def test_every_rule_link_is_unique() -> None:
    paths = [cls.examples_path() for cls in REGISTRY.values()]
    assert len(paths) == len(set(paths))


@pytest.mark.parametrize("spelling", ["SARJ017", "sarj017", "no-fstring-in-log"])
def test_explain_accepts_a_code_or_an_id(spelling: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", spelling]) == 0
    out = capsys.readouterr().out
    assert "SARJ017  no-fstring-in-log" in out
    assert f"examples: {NoFstringInLog.examples_url()}" in out


def test_explain_reports_an_unknown_rule_without_raising(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", "no-such-rule"]) == 2
    assert "unknown rule" in capsys.readouterr().err

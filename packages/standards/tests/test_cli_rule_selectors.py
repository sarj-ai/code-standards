from __future__ import annotations

from typing import TYPE_CHECKING, TypeGuard

import pytest

from sarj_standards.cli.main import build_parser, main
from sarj_standards.libs.repository import rule_lifecycle
from sarj_standards.libs.rules import RuleEngine, RuleId, RuleSelector


if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence
    from pathlib import Path


def _parse(argv: Sequence[str]) -> dict[str, object]:
    parsed: argparse.Namespace = build_parser().parse_args(list(argv))
    values: object = vars(parsed)
    if not _is_object(values):
        msg = "argparse namespace has invalid values"
        raise TypeError(msg)
    return values


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


@pytest.mark.parametrize(
    "argv",
    [
        ("observe", "--rule", "python:no-print", "app.py"),
        ("maintain", "rules", "evaluate", "--rule", "python:no-print"),
    ],
    ids=("observe", "evaluate"),
)
def test_selected_rule_arguments_are_typed_at_the_parser_boundary(argv: tuple[str, ...]) -> None:
    args = _parse(argv)

    assert args["selected_rules"] == [RuleSelector(RuleEngine.PYTHON, RuleId("no-print"))]


def test_stage_warning_selector_is_typed_at_the_parser_boundary() -> None:
    args = _parse(("maintain", "rules", "stage-warning", "python:no-print"))

    assert args["selector"] == RuleSelector(RuleEngine.PYTHON, RuleId("no-print"))


def test_stage_warning_prints_copy_pasteable_author_validation_steps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    selector = RuleSelector(RuleEngine.PYTHON, RuleId("no-print"))

    def stage_warning(_root: Path, selected: RuleSelector, *, check: bool) -> rule_lifecycle.StageResult:
        return rule_lifecycle.StageResult(0, not check, f"staged: {selected}")

    monkeypatch.setattr(
        rule_lifecycle,
        "stage_warning",
        stage_warning,
    )

    status = main(["--root", str(tmp_path), "maintain", "rules", "stage-warning", str(selector)])

    output = capsys.readouterr().out
    assert status == 0
    assert f"maintain rules evaluate --rule {selector} --scope corpus" in output
    assert "make verify" in output
    assert "maintain rules changes --before origin/main --after HEAD" in output


def test_evaluation_scope_is_typed_at_the_parser_boundary() -> None:
    args = _parse(("maintain", "rules", "evaluate", "--rule", "python:no-print", "--scope", "effective"))

    scope = args["evaluation_scope"]
    assert isinstance(scope, str)
    assert scope == "effective"
    assert type(scope) is not str


@pytest.mark.parametrize(
    "selector",
    ["python", "unknown:no-print", "python:no_print", "python:no-print:extra"],
)
def test_rule_selector_arguments_reject_noncanonical_values(selector: str) -> None:
    with pytest.raises(SystemExit, match="2"):
        _parse(("maintain", "rules", "evaluate", "--rule", selector))

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, TypeGuard

import pytest
from typer.testing import CliRunner

from sarj_standards.cli.main import build_app, main
from sarj_standards.libs.adoption.manifest import as_table, list_field
from sarj_standards.libs.repository import rule_lifecycle
from sarj_standards.libs.rules import RuleEngine, RuleId, RuleSelector


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def _parse(argv: Sequence[str]) -> dict[str, object]:
    values: dict[str, object] = {}

    def capture(args: object) -> int:
        parsed: object = vars(args)
        if not _is_object(parsed):
            msg = "command arguments have invalid values"
            raise TypeError(msg)
        values.update(parsed)
        return 0

    result = CliRunner().invoke(build_app(capture), list(argv))
    if result.exception is not None:
        raise result.exception
    return values


def _report(output: str) -> dict[str, object]:
    value: object = json.loads(output)  # pyright: ignore[reportAny] -- narrow untyped JSON at the boundary.
    return as_table(value)


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


@pytest.mark.parametrize(
    "argv",
    [
        ("check", "--rule", "python:no-print", "app.py"),
        ("observe", "--rule", "python:no-print", "app.py"),
        ("maintain", "rules", "evaluate", "--rule", "python:no-print"),
    ],
    ids=("check", "observe", "evaluate"),
)
def test_selected_rule_arguments_are_typed_at_the_parser_boundary(argv: tuple[str, ...]) -> None:
    args = _parse(argv)

    assert args["selected_rules"] == [RuleSelector(RuleEngine.PYTHON, RuleId("no-print"))]


def test_stage_warning_selector_is_typed_at_the_parser_boundary() -> None:
    args = _parse(("maintain", "rules", "stage-warning", "python:no-print"))

    assert args["selector"] == RuleSelector(RuleEngine.PYTHON, RuleId("no-print"))


@pytest.mark.parametrize("profile", ["standard", "application"])
def test_legacy_profile_is_accepted_but_not_advertised(profile: str) -> None:
    args = _parse(("setup", "--profile", profile))
    assert args["profile"] == profile
    result = CliRunner().invoke(build_app(), ["setup", "--help"])
    assert result.exit_code == 0
    assert "--profile" not in result.output


def test_stage_warning_prints_copy_pasteable_author_validation_steps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    selector = RuleSelector(RuleEngine.PYTHON, RuleId("no-print"))

    def stage_warning(_root: Path, selected: RuleSelector, *, check: bool) -> rule_lifecycle.StageResult:
        return rule_lifecycle.StageResult(0, not check, f"staged: {selected}")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercepts lifecycle CLI dispatch
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


@pytest.mark.parametrize("paths", [[], ["sample.py"]], ids=["repository", "file"])
@pytest.mark.parametrize("extra_rules", [[], ["--rule", "python:no-dunder-all"]], ids=["single", "multiple"])
def test_check_rule_reports_only_selected_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], paths: list[str], extra_rules: list[str]
) -> None:
    (tmp_path / "sample.py").write_text(
        '__all__ = ["sample"]\n\ndef sample():\n' + "    if ready: work()\n" * 21, encoding="utf-8"
    )

    status = main(
        [
            "--root",
            str(tmp_path),
            "check",
            "--rule",
            "python:no-excessive-cognitive-complexity",
            "--format",
            "json",
            *extra_rules,
            *paths,
        ]
    )

    report = _report(capsys.readouterr().out)
    assert status == 1
    expected = (
        ["no-dunder-all", "no-excessive-cognitive-complexity"] if extra_rules else ["no-excessive-cognitive-complexity"]
    )
    assert [as_table(item)["ruleId"] for item in list_field(report, "diagnostics")] == expected


def test_check_rule_passes_despite_unselected_violations(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "sample.py").write_text("def sample():\n    if ready: work()\n", encoding="utf-8")
    status = main(
        ["--root", str(tmp_path), "check", "--rule", "python:no-excessive-cognitive-complexity", "--format", "json"]
    )
    report = _report(capsys.readouterr().out)
    assert status == 0
    assert report["diagnostics"] == []


def test_check_unknown_rule_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    status = main(["--root", str(tmp_path), "check", "--rule", "python:nonexistent-rule", "--format", "json"])
    assert status == 2
    assert "unknown" in capsys.readouterr().out.lower()


@pytest.mark.parametrize(("stage", "partial", "expected"), [(False, False, 0), (True, False, 1), (True, True, 2)])
def test_check_rule_respects_staged_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], *, stage: bool, partial: bool, expected: int
) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "sample.py").write_text("def sample():\n" + "    if ready: work()\n" * 21, encoding="utf-8")
    if stage:
        subprocess.run(["git", "-C", str(tmp_path), "add", "sample.py"], check=True, capture_output=True)
    if partial:
        (tmp_path / "sample.py").write_text("pass\n", encoding="utf-8")
    status = main(
        [
            "--root",
            str(tmp_path),
            "check",
            "--staged",
            "--rule",
            "python:no-excessive-cognitive-complexity",
            "--format",
            "json",
        ]
    )
    report = _report(capsys.readouterr().out)
    assert status == expected
    match expected:
        case 0:
            assert report["diagnostics"] == []
        case 1:
            assert [as_table(item)["ruleId"] for item in list_field(report, "diagnostics")] == [
                "no-excessive-cognitive-complexity"
            ]
        case _:
            assert "unstaged content" in str(report)

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from pathlib import Path


def test_warning_is_excluded_when_baseline_records_a_blocking_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "example.py"
    target.write_text("VALUES = [1]\n\n# ----------------\nerror_value = 2\n")
    baseline = tmp_path / "baseline.json"
    rules = ["check", "--rule", "prefer-immutable-module-constant", "--rule", "no-comment-cruft"]

    assert main([*rules, str(target)]) == 1
    control = capsys.readouterr().out
    assert "SARJ096 " in control
    assert "SARJ016 " in control

    assert main([*rules, "--update-baseline", str(baseline), str(target)]) == 0
    assert json.loads(baseline.read_text()) == {str(target): {"SARJ016": 1}}
    baseline_output = capsys.readouterr().out
    assert "1 blocking diagnostics over 1 files; 1 warnings excluded" in baseline_output

    assert main([*rules, "--baseline", str(baseline), str(target)]) == 0
    assert "SARJ096 warning:" in capsys.readouterr().out


def test_warning_only_baseline_excludes_the_finding(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "example.py"
    target.write_text("VALUES = [1]\n")
    baseline = tmp_path / "baseline.json"

    assert (
        main(
            [
                "check",
                "--rule",
                "prefer-immutable-module-constant",
                "--update-baseline",
                str(baseline),
                str(target),
            ]
        )
        == 0
    )

    assert json.loads(baseline.read_text()) == {}
    assert "0 blocking diagnostics over 0 files; 1 warnings excluded" in capsys.readouterr().out


def test_promoted_repeated_test_body_blocks_and_enters_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "test_examples.py"
    target.write_text(
        "def test_first():\n"
        "    value = build('first')\n"
        "    result = run(value)\n"
        "    assert result is True\n\n"
        "def test_second():\n"
        "    value = build('second')\n"
        "    result = run(value)\n"
        "    assert result is True\n"
    )
    command = ["check", "--rule", "no-repeated-test-body"]

    assert main([*command, str(target)]) == 1
    assert "SARJ066 " in capsys.readouterr().out

    baseline = tmp_path / "baseline.json"
    assert main([*command, "--update-baseline", str(baseline), str(target)]) == 0
    assert json.loads(baseline.read_text()) == {str(target): {"SARJ066": 1}}


@pytest.mark.parametrize(
    ("rule", "code", "source"),
    [
        ("no-any-mapping-types", "SARJ447", "from typing import Any\ndef details() -> dict[str, Any]: ...\n"),
        (
            "async-cleanup-registered-synchronously",
            "SARJ463",
            "from contextlib import AsyncExitStack\nasync def close():\n    await release()\nasync def run():\n    async with AsyncExitStack() as stack:\n        stack.callback(close)\n",
        ),
        (
            "subprocess-kill-without-reap",
            "SARJ464",
            "import subprocess\ndef run(args):\n    process = subprocess.Popen(args)\n    try:\n        process.communicate(timeout=1)\n    except subprocess.TimeoutExpired:\n        process.kill()\n",
        ),
        (
            "no-impossible-pydantic-field-bounds",
            "SARJ491",
            "from pydantic import BaseModel, Field\nclass Model(BaseModel):\n    value: int = Field(gt=0, lt=1)\n",
        ),
        (
            "no-unknown-pydantic-validator-field",
            "SARJ492",
            "from pydantic import BaseModel, field_validator\nclass Model(BaseModel):\n    value: int\n    @field_validator('missing')\n    @classmethod\n    def check(cls, value: int) -> int: return value\n",
        ),
        (
            "no-conflicting-pydantic-alias-validation",
            "SARJ493",
            "from pydantic import BaseModel, ConfigDict\nclass Model(BaseModel):\n    model_config = ConfigDict(validate_by_alias=False, validate_by_name=False)\n",
        ),
    ],
    ids=(
        "mapping-erasure",
        "dropped-async-cleanup",
        "unreaped-child",
        "empty-field-domain",
        "missing-validator-field",
        "disabled-alias-paths",
    ),
)
def test_typing_campaign_promotions_block_baseline_and_allow_exact_suppression(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], rule: str, code: str, source: str
) -> None:
    target = tmp_path / "example.py"
    target.write_text(source, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nversion = "1.0"\ndependencies = ["pydantic>=2.11"]\n', encoding="utf-8"
    )
    documentation = REGISTRY[rule].documentation
    assert documentation is not None
    assert documentation.default_level is Severity.ERROR
    findings = analyze([rule], [target])
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    command = ["check", "--rule", rule]
    assert main([*command, str(target)]) == 1
    assert code in capsys.readouterr().out
    baseline = tmp_path / "baseline.json"
    assert main([*command, "--update-baseline", str(baseline), str(target)]) == 0
    assert json.loads(baseline.read_text()) == {str(target): {code: 1}}
    capsys.readouterr()
    assert main([*command, "--baseline", str(baseline), str(target)]) == 0
    capsys.readouterr()
    lines = source.splitlines()
    lines[findings[0].line - 1] += f"  # sarj-noqa: {code} -- preserve the reviewed compatibility contract"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert main([*command, str(target)]) == 0
    assert code not in capsys.readouterr().out


def test_baseline_written_from_absolute_repo_path_is_portable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "src" / "example.py"
    target.parent.mkdir()
    target.write_text("# ----------------\nvalue = 2\n")
    baseline = tmp_path / "baseline.json"
    monkeypatch.chdir(tmp_path)
    command = ["check", "--rule", "no-comment-cruft"]

    assert main([*command, "--update-baseline", str(baseline), str(target.resolve())]) == 0
    assert json.loads(baseline.read_text()) == {"src/example.py": {"SARJ016": 1}}
    assert main([*command, "--baseline", str(baseline), "src/example.py"]) == 0


def test_explicit_missing_input_is_an_operator_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.py"

    assert main(["check", "--rule", "no-comment-cruft", str(missing)]) == 2
    assert f"input does not exist: {missing}" in capsys.readouterr().err


def test_invalid_baseline_is_a_concise_operator_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text("not json", encoding="utf-8")

    status = main(["check", "--rule", "no-comment-cruft", "--baseline", str(baseline), str(source)])

    output = capsys.readouterr()
    assert status == 2
    assert "invalid baseline" in output.err
    assert "Traceback" not in output.err


def test_baseline_update_requires_an_existing_parent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "example.py"
    source.write_text("value = 1\n", encoding="utf-8")
    baseline = tmp_path / "missing" / "baseline.json"

    status = main(["check", "--rule", "no-comment-cruft", "--update-baseline", str(baseline), str(source)])

    output = capsys.readouterr()
    assert status == 2
    assert "baseline parent does not exist" in output.err
    assert "Traceback" not in output.err


@pytest.mark.parametrize(
    "argv",
    [[], ["check"], ["check", "missing.py"], ["unknown"]],
    ids=("missing-command", "missing-files-and-rule", "missing-rule", "unknown-command"),
)
def test_cli_usage_errors_exit_two(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as failure:
        main(argv)
    assert failure.value.code == 2


@pytest.mark.parametrize(
    "argv",
    [["--help"], ["-h"], ["--version"], ["check", "--help"]],
    ids=("help", "short-help", "version", "check-help"),
)
def test_cli_help_and_version_exit_zero(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv) == 0
    assert "sarj-python-lint" in capsys.readouterr().out


def test_cli_repeated_rules_and_option_like_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "--source.py").write_text("", encoding="utf-8")
    assert main(["check", "--rule", "no-comment-cruft", "--rule", "no-comment-cruft", "--", "--source.py"]) == 0

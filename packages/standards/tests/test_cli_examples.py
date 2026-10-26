from __future__ import annotations

from io import StringIO
import sys

import pytest

from sarj_standards.libs.repository import cli_examples


def test_every_example_keeps_its_arguments_and_help_output_out_of_the_protocol(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[list[str]] = []
    output = StringIO()

    def help_command(arguments: list[str]) -> int:
        calls.append(arguments)
        sys.stdout.write("help output\n")
        sys.stderr.write("help diagnostics\n")
        raise SystemExit(0)

    assert (
        cli_examples.validate(
            ['code-standards --root "space dir" doctor', "code-standards maintain docs check"],
            invoke=help_command,
            output=output,
        )
        == 0
    )
    assert calls == [["--root", "space dir", "doctor", "--help"], ["maintain", "docs", "check", "--help"]]
    captured = capsys.readouterr()
    assert output.getvalue() == "0\n1\n"
    assert not captured.out
    assert not captured.err


@pytest.mark.parametrize("raises", [False, True])
def test_first_failure_reports_its_index_and_stops_the_batch(*, raises: bool) -> None:
    calls: list[list[str]] = []
    output = StringIO()

    def command(arguments: list[str]) -> int:
        calls.append(arguments)
        if len(calls) == 1:
            return 0
        if raises:
            raise SystemExit(2)
        return 2

    assert (
        cli_examples.validate(
            ["code-standards doctor", "code-standards init", "code-standards check"], invoke=command, output=output
        )
        == 1
    )
    assert len(calls) == 2
    assert output.getvalue() == "0\n1\n"


def test_malformed_shell_quoting_fails_without_running_a_command() -> None:
    output = StringIO()

    def unexpected_command(_arguments: list[str]) -> int:
        pytest.fail("malformed source reached the CLI")

    assert cli_examples.validate(['code-standards --root "unfinished'], invoke=unexpected_command, output=output) == 1
    assert output.getvalue() == "0\n"


def test_unexpected_cli_failure_retains_the_current_index() -> None:
    output = StringIO()

    def broken_command(_arguments: list[str]) -> int:
        msg = "CLI failed unexpectedly"
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="CLI failed unexpectedly"):
        cli_examples.validate(["code-standards doctor"], invoke=broken_command, output=output)

    assert output.getvalue() == "0\n"

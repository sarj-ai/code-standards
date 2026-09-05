from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import main


if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture


@pytest.mark.parametrize(("minimum", "expected_count"), [("3.9", 0), ("3.10", 1)])
def test_cli_respects_project_python_support(
    tmp_path: Path, capsys: CaptureFixture[str], minimum: str, expected_count: int
) -> None:
    (tmp_path / "pyproject.toml").write_text(f'[project]\nrequires-python = ">={minimum}"\n')
    path = tmp_path / "dispatch.py"
    path.write_text(_CHAIN.format(suppression=""))
    assert main(["check", "--rule", "prefer-match-value-dispatch", str(path)]) == 0
    assert capsys.readouterr().out.count("SARJ439 warning:") == expected_count


_CHAIN = (
    "if value == 'a':{suppression}\n"
    "    first()\n"
    "elif value == 'b':\n"
    "    second()\n"
    "elif value == 'c':\n"
    "    third()\n"
    "else:\n"
    "    fallback()\n"
)


@pytest.mark.parametrize(
    ("source", "expected_count"),
    [
        (_CHAIN.format(suppression=""), 1),
        (_CHAIN.format(suppression="  # sarj-noqa: SARJ439 — preserve repeated evaluation"), 0),
        (_CHAIN.format(suppression="  # sarj-noqa: SARJ080 — unrelated suppression"), 1),
        ("# @generated\n" + _CHAIN.format(suppression=""), 0),
        ("if value ==\n", 0),
    ],
    ids=("one-warning-per-chain", "exact-suppression", "other-suppression", "generated", "malformed"),
)
def test_match_value_dispatch_cli_is_advisory(
    tmp_path: Path, capsys: CaptureFixture[str], source: str, expected_count: int
) -> None:
    path = tmp_path / "dispatch.py"
    _ = path.write_text(source)

    result = main(["check", "--rule", "prefer-match-value-dispatch", str(path)])

    assert result == 0
    output = capsys.readouterr()
    assert not output.err
    assert output.out.count("SARJ439 warning:") == expected_count

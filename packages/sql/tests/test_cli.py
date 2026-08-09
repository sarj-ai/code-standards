from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_sql_lint.__main__ import main


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_explicit_missing_input_is_an_operator_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.sql"

    assert main(["check", "--rule", "prefer-jsonb", str(missing)]) == 2
    assert f"input does not exist: {missing}" in capsys.readouterr().err

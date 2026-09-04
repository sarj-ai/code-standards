from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_standards.cli.main import main


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_commit_message_wrapper_is_silent_on_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text("feat: add search\n")

    assert main(["commit-message", str(path)]) == 0
    assert not capsys.readouterr().out


def test_commit_message_wrapper_safely_fixes_mechanical_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_bytes(b"FIX : repair\r\n\r\nBody\r\n")

    assert main(["commit-message", str(path)]) == 0
    assert path.read_bytes() == b"fix: repair\r\n\r\nBody\r\n"
    assert "safely normalized" in capsys.readouterr().out


def test_commit_message_wrapper_blocks_semantic_ambiguity(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text("WIP\n")

    assert main(["commit-message", str(path)]) == 1
    assert "commit-message.invalid-header" in capsys.readouterr().err

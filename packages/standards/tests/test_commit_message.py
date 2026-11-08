from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.__main__ import main


if TYPE_CHECKING:
    from pathlib import Path


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


@pytest.mark.parametrize("rooted", [False, True])
@pytest.mark.parametrize(
    ("header", "warning"),
    [
        pytest.param("fix: " + "x" * 73, True, id="over-target"),
        pytest.param("[SARJ-1] fix(api): " + "x" * 72 + " (#123)", False, id="metadata-excluded"),
        pytest.param("FIX : " + "x" * 73, True, id="safe-normalization"),
    ],
)
def test_commit_message_advice_is_automatic_nonblocking_and_preserves_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], header: str, *, warning: bool, rooted: bool
) -> None:
    path = tmp_path / "COMMIT_EDITMSG"
    tail = "\r\n\r\nReason and caveat.\r\n\r\nCo-authored-by: Contributor <test@example.invalid>\r\n"
    path.write_bytes(f"{header}{tail}".encode())

    arguments = ["commit-message", str(path)]
    if rooted:
        arguments = ["--root", str(tmp_path), *arguments]
    assert main(arguments) == 0
    output = capsys.readouterr()
    assert ("subject.too-long" in output.out) is warning
    assert not output.err
    expected_header = header.replace("FIX : ", "fix: ")
    assert path.read_bytes() == f"{expected_header}{tail}".encode()
    assert main(arguments) == 0
    repeated = capsys.readouterr()
    assert ("subject.too-long" in repeated.out) is warning
    assert "safely normalized" not in repeated.out
    assert path.read_bytes() == f"{expected_header}{tail}".encode()

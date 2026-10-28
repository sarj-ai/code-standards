from __future__ import annotations

import errno
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_iac_lint.__main__ import analyze, main


if TYPE_CHECKING:
    import os


_RULE = "no-environment-conditional"
_SOURCE = b'resource "google_storage_bucket" "archive" {\n  count = var.environment == "prod" ? 1 : 0\n}\n'


def test_explicit_input_at_size_limit_is_analyzed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "main.tf"
    source.write_bytes(_SOURCE + b" " * (500_000 - len(_SOURCE)))

    assert [finding.code for finding in analyze([_RULE], [source])] == ["SARJ204"]
    assert main(["check", "--rule", _RULE, str(source)]) == 1
    assert "SARJ204" in capsys.readouterr().out


@pytest.mark.parametrize("size", [500_001, 2 * 1024 * 1024], ids=("over-native-limit", "outer-runner-limit"))
@pytest.mark.parametrize("options", [(), ("--fix",), ("--exit-zero",)], ids=("check", "fix", "exit-zero"))
def test_oversized_explicit_input_is_an_operator_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], size: int, options: tuple[str, ...]
) -> None:
    source = tmp_path / "main.tf"
    contents = b" " * size
    source.write_bytes(contents)

    assert main(["check", "--rule", _RULE, *options, str(source)]) == 2
    captured = capsys.readouterr()
    assert "500,000-byte analysis limit" in captured.err
    assert str(source) in captured.err
    assert not captured.out
    assert source.read_bytes() == contents


def test_rejected_input_does_not_replace_a_baseline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "main.tf"
    source.write_bytes(b" " * 500_001)
    baseline = tmp_path / "baseline.json"
    contents = '{"main.tf": {"SARJ204": 1}}\n'
    baseline.write_text(contents, encoding="utf-8")

    assert main(["check", "--rule", _RULE, "--update-baseline", str(baseline), str(source)]) == 2
    assert "500,000-byte analysis limit" in capsys.readouterr().err
    assert baseline.read_text(encoding="utf-8") == contents


def test_explicit_input_stat_failure_is_an_operator_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "main.tf"
    source.write_bytes(_SOURCE)
    original_stat = Path.stat

    def unreadable_stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if path == source:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the real filesystem boundary; an engine fake would bypass native input admission.
        Path, "stat", unreadable_stat
    )

    with pytest.raises(PermissionError, match=r"main\.tf"):
        analyze([_RULE], [source])
    assert main(["check", "--rule", _RULE, str(source)]) == 2
    assert str(source) in capsys.readouterr().err


@pytest.mark.parametrize("requested", ["file", "directory"])
def test_accepted_input_read_failure_is_an_operator_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], requested: str
) -> None:
    source = tmp_path / "main.tf"
    source.write_bytes(_SOURCE)
    original_read_text = Path.read_text

    def unreadable_text(
        path: Path, encoding: str | None = None, errors: str | None = None, newline: str | None = None
    ) -> str:
        if path == source:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original_read_text(path, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- inject an accepted-file read error through the actual native reader, not a replacement analyzer.
        Path, "read_text", unreadable_text
    )
    selected = source if requested == "file" else tmp_path

    with pytest.raises(PermissionError, match=r"main\.tf"):
        analyze([_RULE], [selected])
    assert main(["check", "--rule", _RULE, str(selected)]) == 2
    assert str(source) in capsys.readouterr().err


def test_directory_discovery_preserves_size_and_path_exclusions(tmp_path: Path) -> None:
    included = tmp_path / "main.tf"
    included.write_bytes(_SOURCE)
    (tmp_path / "oversized.tf").write_bytes(_SOURCE + b" " * 500_000)
    excluded = tmp_path / ".terraform" / "main.tf"
    excluded.parent.mkdir()
    excluded.write_bytes(_SOURCE)

    assert [(finding.path, finding.code) for finding in analyze([_RULE], [tmp_path])] == [(included, "SARJ204")]

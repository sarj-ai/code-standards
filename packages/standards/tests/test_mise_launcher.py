from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import launcher


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("filename", ["mise.toml", ".mise.toml"])
@pytest.mark.parametrize(
    "contents",
    [
        '[tools]\npython = "3.14"\n',
        '[tools]\n"pipx:sarj-standards-bootstrap" = {version = "2.0.3", uvx_args = "--python 3.14 --no-config"}\n',
        '[tools]\n"pipx:sarj-standards-bootstrap" = "latest"\n',
        "[tools\n",
    ],
)
def test_repository_launcher_ignores_mise_configuration(
    tmp_path: Path, filename: str, contents: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / filename).write_text(contents, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    arguments = ("commit-message", "message with spaces.txt")
    expected = (
        "uvx",
        "--no-config",
        "--isolated",
        "--python",
        "3.14",
        "--from",
        "sarj-standards-bootstrap",
        "code-standards",
        *arguments,
    )

    assert launcher.repository_argv(*arguments) == expected
    assert shlex.split(launcher.repository_command(*arguments)) == list(expected)


def test_conflicting_root_mise_files_do_not_affect_launcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = launcher.repository_argv("doctor")
    for filename in ("mise.toml", ".mise.toml"):
        (tmp_path / filename).write_text("[tools\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert launcher.repository_argv("doctor") == expected

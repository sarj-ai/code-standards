from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import launcher


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("filename", ["mise.toml", ".mise.toml"])
def test_mise_bootstrap_is_explicit_and_preserves_arguments(tmp_path: Path, filename: str) -> None:
    (tmp_path / filename).write_text(
        '[tools]\n"pipx:sarj-standards-bootstrap" = {version = "2.0.3", uvx_args = "--python 3.14 --no-config"}\n',
        encoding="utf-8",
    )
    arguments = ("commit-message", "message with spaces.txt")
    expected = ("mise", "exec", "pipx:sarj-standards-bootstrap", "--", "code-standards", *arguments)

    assert launcher.mise_bootstrap_version(tmp_path) == "2.0.3"
    assert launcher.repository_argv(*arguments, root=tmp_path) == expected
    assert shlex.split(launcher.repository_command(*arguments, root=tmp_path)) == list(expected)


@pytest.mark.parametrize("contents", [None, '[tools]\npython = "3.14"\n'])
def test_repository_without_opt_in_keeps_existing_launcher(tmp_path: Path, contents: str | None) -> None:
    if contents is not None:
        (tmp_path / "mise.toml").write_text(contents, encoding="utf-8")

    assert launcher.mise_bootstrap_version(tmp_path) is None
    assert launcher.repository_argv("doctor", root=tmp_path) == launcher.repository_argv("doctor")


@pytest.mark.parametrize(
    "value",
    [
        '"2.0.3"',
        '{version = "2.0.3"}',
        '{version = "latest", uvx_args = "--python 3.14 --no-config"}',
        '{version = "02.0.3", uvx_args = "--python 3.14 --no-config"}',
        '{version = "2.0.3", uvx_args = "--python 3.13 --no-config"}',
        '{version = "2.0.3", uvx_args = "--python 3.14 --no-config", uvx = "false"}',
    ],
)
def test_invalid_mise_opt_in_fails_closed(tmp_path: Path, value: str) -> None:
    (tmp_path / "mise.toml").write_text(f'[tools]\n"pipx:sarj-standards-bootstrap" = {value}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="pipx:sarj-standards-bootstrap"):
        launcher.repository_argv("doctor", root=tmp_path)


def test_malformed_mise_configuration_is_not_silently_ignored(tmp_path: Path) -> None:
    (tmp_path / "mise.toml").write_text("[tools\n", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot read Standards launcher configuration"):
        launcher.mise_bootstrap_version(tmp_path)


def test_conflicting_root_mise_files_are_rejected(tmp_path: Path) -> None:
    for filename in ("mise.toml", ".mise.toml"):
        (tmp_path / filename).write_text(
            '[tools]\n"pipx:sarj-standards-bootstrap" = {version = "2.0.3", uvx_args = "--python 3.14 --no-config"}\n',
            encoding="utf-8",
        )

    with pytest.raises(ValueError, match="not both"):
        launcher.mise_bootstrap_version(tmp_path)


def test_unrelated_mise_layers_do_not_opt_in(tmp_path: Path) -> None:
    for filename in ("mise.toml", ".mise.toml"):
        (tmp_path / filename).write_text('[tools]\npython = "3.14"\n', encoding="utf-8")
    assert launcher.repository_argv(root=tmp_path) == launcher.repository_argv()


def test_mise_pin_is_returned_for_doctor_to_check_against_installed_bundle(tmp_path: Path) -> None:
    (tmp_path / "mise.toml").write_text(
        '[tools]\n"pipx:sarj-standards-bootstrap" = {version = "2.0.2", uvx_args = "--python 3.14 --no-config"}\n',
        encoding="utf-8",
    )

    assert launcher.mise_bootstrap_version(tmp_path) == "2.0.2"

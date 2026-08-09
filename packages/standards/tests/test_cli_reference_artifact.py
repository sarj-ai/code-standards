"""Tests for the source-derived CLI-reference artifact."""

from __future__ import annotations

from pathlib import Path
from typing import TypeGuard

from sarj_standards.cli.main import build_parser
from sarj_standards.libs.repository import cli_reference_artifact


ROOT = Path(__file__).resolve().parents[3]


def _is_object_list(value: object) -> TypeGuard[list[dict[str, object]]]:
    return isinstance(value, list)


def test_shipped_reference_matches_parser_graph() -> None:
    result = cli_reference_artifact.sync(ROOT, build_parser(), check=True)

    assert result.status == 0, result.message


def test_reference_contains_nested_commands_and_arguments() -> None:
    reference = cli_reference_artifact.load()
    assert reference["version"]
    commands = reference["commands"]
    assert _is_object_list(commands)
    show = next(command for command in commands if command["name"] == "show")
    show_commands = show["commands"]
    assert _is_object_list(show_commands)
    assert any(command["name"] == "rules" for command in show_commands)
    options = reference["globalOptions"]
    assert _is_object_list(options)
    assert any(argument["names"] == ["--root"] for argument in options)
    assert reference["launcher"] == {
        "install": "uv tool install --python 3.14 sarj-standards",
        "runLatest": "uvx --isolated --python 3.14 --from sarj-standards sarj-standards",
    }

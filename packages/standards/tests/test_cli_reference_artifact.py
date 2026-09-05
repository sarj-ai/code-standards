from __future__ import annotations

from pathlib import Path
from typing import TypeGuard

from sarj_standards.cli.main import build_app
from sarj_standards.libs.repository import cli_reference_artifact


ROOT = Path(__file__).resolve().parents[3]


def _is_object_list(value: object) -> TypeGuard[list[dict[str, object]]]:
    return isinstance(value, list)


def test_shipped_reference_matches_parser_graph() -> None:
    result = cli_reference_artifact.sync(ROOT, build_app(), check=True)

    assert result.status == 0, result.message


def test_reference_omits_legacy_profile_options() -> None:
    reference = cli_reference_artifact.build(build_app())
    setup = next(command for command in reference["commands"] if command["name"] == "setup")
    show = next(command for command in reference["commands"] if command["name"] == "show")
    config = next(command for command in show["commands"] if command["name"] == "config")
    for command in (setup, config):
        assert all("--profile" not in option["names"] for option in command["options"])


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
        "install": "uv tool install --python 3.14 code-standards",
        "runLatest": "uvx --no-config --isolated --python 3.14 --from code-standards code-standards",
    }


def test_reference_preserves_the_rule_authoring_flow_and_exit_contract() -> None:
    reference = cli_reference_artifact.load()
    commands = reference["commands"]
    observe = next(command for command in commands if command["name"] == "observe")
    assert "findings with exit 0" in observe["summary"]

    maintain = next(command for command in commands if command["name"] == "maintain")
    rules = next(command for command in maintain["commands"] if command["name"] == "rules")
    evaluate = next(command for command in rules["commands"] if command["name"] == "evaluate")
    stage = next(command for command in rules["commands"] if command["name"] == "stage-warning")

    assert "findings exit 1" in evaluate["summary"]
    scope = next(option for option in evaluate["options"] if option["names"] == ["--scope"])
    assert scope["choices"] == ["corpus", "effective"]
    selector = next(option for option in stage["options"] if option["names"] == ["selector"])
    assert selector["required"]
    assert selector["summary"] == "canonical ENGINE:ID selector"

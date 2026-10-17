from __future__ import annotations

import json
from pathlib import Path

import pytest

from sarj_standards.cli.main import build_app
from sarj_standards.libs.repository import cli_reference_artifact


ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("schema", [True, 1.0, "1", None], ids=("boolean", "float", "string", "null"))
def test_reference_requires_an_integer_schema_version(schema: object) -> None:
    payload: dict[str, object] = dict(cli_reference_artifact.load())
    payload["schemaVersion"] = schema

    with pytest.raises(ValueError, match="unsupported CLI reference schemaVersion"):
        cli_reference_artifact.validate(payload)


def test_reference_load_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "reference.json"
    valid = json.dumps(cli_reference_artifact.load())
    path.write_text('{"schemaVersion":1,' + valid[1:], encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON key"):
        cli_reference_artifact.load(path)


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
    show = next(command for command in commands if command["name"] == "show")
    show_commands = show["commands"]
    assert any(command["name"] == "rules" for command in show_commands)
    options = reference["globalOptions"]
    assert any(argument["names"] == ["--root"] for argument in options)
    assert reference["launcher"] == {
        "install": "uv tool install --python 3.15.0 code-standards",
        "runLatest": "uvx --no-config --isolated --python 3.15.0 --from code-standards code-standards",
    }


def test_reference_preserves_the_rule_authoring_flow_and_exit_contract() -> None:
    reference = cli_reference_artifact.load()
    commands = reference["commands"]
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


def test_reference_documents_observe_exit_contract() -> None:
    commands = cli_reference_artifact.load()["commands"]
    observe = next(command for command in commands if command["name"] == "observe")
    assert "findings with exit 0" in observe["summary"]

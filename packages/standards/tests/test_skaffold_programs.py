import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.linting import textlint
from sarj_standards.libs.linting.devops_programs import ProgramProjectionError, block_embeds_program, execution_blocks
from sarj_standards.libs.linting.shell_ast import ShellSyntaxError, parse_shell


if TYPE_CHECKING:
    from pathlib import Path


_HEADER = "apiVersion: skaffold/v4beta7\nkind: Config\n"


def _custom_build(command: str, dependencies: str = "") -> str:
    return (
        "build:\n  artifacts:\n    - image: example\n      custom:\n"
        f"        buildCommand: {json.dumps(command)}\n{dependencies}"
    )


_CASES = (
    ("inline-python", _custom_build("python3 -c 'print(1)'"), 1, 1),
    ("shell-command-chain", _custom_build("make lint && make test"), 1, 1),
    ("external-script", _custom_build("python3 scripts/build.py -c strict"), 1, 0),
    ("external-module", _custom_build("python3 -m tools.build -c strict"), 1, 0),
    ("quoted-data", _custom_build("printf %s 'python3 -c 1'"), 1, 0),
    (
        "dependency-argv-shell-data",
        _custom_build("./build.sh", "        dependencies:\n          command: printf %s $(python3 -c 1)\n"),
        2,
        0,
    ),
    (
        "dependency-inline-interpreter",
        _custom_build("./build.sh", "        dependencies:\n          command: python3 -c print(1)\n"),
        2,
        1,
    ),
    (
        "dockerfile-shadows-dependency-command",
        _custom_build(
            "./build.sh",
            "        dependencies:\n          command: python3 -c print(1)\n          dockerfile:\n            path: Dockerfile\n",
        ),
        1,
        0,
    ),
    (
        "profile-builder",
        "profiles:\n  - name: example\n    build:\n      artifacts:\n        - image: example\n          custom:\n            buildCommand: python3 -c 'print(1)'\n",
        1,
        1,
    ),
    ("activation-is-data", "profiles:\n  - name: example\n    activation:\n      - command: python3 -c 1\n", 0, 0),
    (
        "unknown-builder",
        "build:\n  artifacts:\n    - image: example\n      unsupported:\n        command: python3 -c 1\n        buildCommand: python3 -c 1\n",
        0,
        0,
    ),
    ("unknown-nesting", "metadata:\n  custom:\n    buildCommand: python3 -c 1\n    command: python3 -c 1\n", 0, 0),
    (
        "unsupported-deploy-hook-location",
        "deploy:\n  hooks:\n    before:\n      - host:\n          command: [python3, -c, 'print(1)']\n",
        0,
        0,
    ),
    (
        "host-build-hook-direct-data",
        "build:\n  hooks:\n    before:\n      - command: [printf, '%s', '$(python3 -c 1)']\n",
        1,
        0,
    ),
    (
        "deployer-host-hook",
        "deploy:\n  kubectl:\n    hooks:\n      before:\n        - host:\n            command: [sh, -c, \"python3 -c 'print(1)'\"]\n",
        1,
        1,
    ),
    (
        "verify-direct-argv",
        "verify:\n  - name: example\n    container:\n      command: [python3]\n      args: [-c, 'print(1)']\n",
        1,
        1,
    ),
    (
        "custom-action-direct-data",
        "customActions:\n  - name: example\n    containers:\n      - name: example\n        image: example\n        command: [printf]\n        args: ['%s', '$(python3 -c 1)']\n",
        1,
        0,
    ),
    (
        "custom-test-shell",
        "test:\n  - image: example\n    custom:\n      - command: python3 -c 'print(1)'\n        dependencies:\n          command: printf %s $(python3 -c 1)\n",
        2,
        2,
    ),
)


@pytest.mark.parametrize(("case_id", "body", "count", "matches"), _CASES, ids=[case[0] for case in _CASES])
def test_skaffold_execution_paths(case_id: str, body: str, count: int, matches: int, tmp_path: Path) -> None:
    source = _HEADER + body
    blocks = execution_blocks("skaffold.yaml", source)
    assert len(blocks) == count, case_id
    assert sum(block_embeds_program(block, parse_shell=parse_shell) for block in blocks) == matches
    path = tmp_path / "skaffold.yaml"
    path.write_text(source, encoding="utf-8")
    findings = textlint.check_paths([str(path)], root=tmp_path, rule_ids=frozenset({"workflow-embedded-program"}))
    assert len(findings) == matches
    assert len({(finding.line, finding.end_line, finding.end_column) for finding in findings}) == matches


def test_skaffold_dependency_command_preserves_literal_spaces_and_quotes() -> None:
    source = _HEADER + _custom_build(
        "./build.sh", "        dependencies:\n          command: printf  '%s' 'two words'\n"
    )
    _, block = execution_blocks("skaffold.yaml", source)
    assert block.argv == ("printf", "", "'%s'", "'two", "words'")


@pytest.mark.parametrize(
    "body",
    [
        "manifests:\n  hooks:\n    after:\n      - host:\n          command: [python3, -c, 'print(1)']\n",
        "deploy:\n  helm:\n    hooks:\n      after:\n        - container:\n            command: [python3, -c, 'print(1)']\n",
        "deploy:\n  cloudrun:\n    hooks:\n      before:\n        - command: [python3, -c, 'print(1)']\n",
        "build:\n  artifacts:\n    - image: example\n      sync:\n        hooks:\n          after:\n            - container:\n                command: [python3, -c, 'print(1)']\n",
    ],
    ids=("render-host", "helm-container", "cloudrun-host", "artifact-sync-container"),
)
def test_skaffold_supported_nested_hook_locations(body: str) -> None:
    [block] = execution_blocks("skaffold.yaml", _HEADER + body)
    assert block_embeds_program(block, parse_shell=parse_shell)


def test_skaffold_alias_merge_override_and_document_locations() -> None:
    source = (
        _HEADER + "defaults: &builder\n  buildCommand: python3 -c 'print(1)'\nbuild:\n  artifacts:\n"
        "    - image: example\n      custom: *builder\n"
        "    - image: other\n      custom:\n        <<: *builder\n        buildCommand: ./build.sh\n"
        "---\n" + _HEADER + _custom_build("node -e 'console.log(1)'")
    )
    blocks = execution_blocks("skaffold.yaml", source)
    assert [(block.line, block_embeds_program(block, parse_shell=parse_shell)) for block in blocks] == [
        (8, True),
        (12, False),
        (20, True),
    ]
    assert all(block.end_line is not None and block.end_column is not None for block in blocks)


@pytest.mark.parametrize(
    "value",
    ["[python3, -c, 'print(1)']", "null", "true", "42"],
    ids=("argv-in-shell-field", "null", "boolean", "number"),
)
def test_skaffold_malformed_build_command_fails_projection(value: str) -> None:
    source = (
        _HEADER + "build:\n  artifacts:\n    - image: example\n      custom:\n        buildCommand: " + value + "\n"
    )
    with pytest.raises(ProgramProjectionError, match="execution source must be a string"):
        execution_blocks("skaffold.yaml", source)


def test_skaffold_unresolved_template_is_coverage_failure() -> None:
    with pytest.raises(ProgramProjectionError, match="executable template cannot be proven"):
        execution_blocks("skaffold.yaml", _HEADER + _custom_build("{{ .COMMAND }} -c 'print(1)'"))


def test_skaffold_windows_custom_execution_is_unproven() -> None:
    with pytest.raises(ProgramProjectionError, match=r"cmd\.exe execution cannot be projected"):
        execution_blocks("skaffold.yaml", _HEADER + _custom_build("python3 -c 'print(1)'"), platform="win32")


def test_skaffold_invalid_shell_uses_native_syntax_error() -> None:
    [block] = execution_blocks("skaffold.yaml", _HEADER + _custom_build("if true; then"))
    with pytest.raises(ShellSyntaxError):
        block_embeds_program(block, parse_shell=parse_shell)

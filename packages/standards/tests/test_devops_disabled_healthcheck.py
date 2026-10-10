from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.linting import textlint
from sarj_standards.libs.linting.devops_programs import ProgramProjectionError, block_embeds_program, execution_blocks
from sarj_standards.libs.linting.shell_ast import parse_shell


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", 0),
        ("True", 0),
        ("TRUE", 0),
        ("!!bool true", 0),
        ("false", 1),
        (None, 1),
        ('"true"', 0),
        ("yes", 0),
        ("on", 0),
        ('"y"', 0),
        ('"YES"', 0),
        ('"ON"', 0),
        ('"FALSE"', 1),
        ("no", 1),
        ("off", 1),
        ('"n"', 1),
    ],
)
def test_compose_healthcheck_runtime_boolean_owns_execution(value: str | None, expected: int) -> None:
    disable = f"      disable: {value}\n" if value is not None else ""
    source = (
        "services:\n  app:\n    image: fixture\n    healthcheck:\n"
        + disable
        + '      test: [CMD-SHELL, "printf first; printf second"]\n'
    )
    blocks = execution_blocks("compose.yaml", source)
    assert sum(block_embeds_program(block, parse_shell=parse_shell) for block in blocks) == expected


@pytest.mark.parametrize("merged", [False, True], ids=("scalar-alias", "mapping-merge"))
def test_compose_disabled_healthcheck_preserves_service_program_and_source(tmp_path: Path, *, merged: bool) -> None:
    defaults = "x-health: &health\n  disable: true\n" if merged else "x-disable: &off true\n"
    disable = "      <<: *health\n" if merged else "      disable: *off\n"
    source = (
        defaults
        + "services:\n  app:\n    image: fixture\n"
        + "    command: [python3, -c, 'print(1)']\n    healthcheck:\n"
        + disable
        + '      test: [CMD-SHELL, "printf first; printf second"]\n'
    )
    path = tmp_path / "compose.yaml"
    path.write_text(source, encoding="utf-8")
    findings = textlint.check_paths([str(path)], root=tmp_path, rule_ids=frozenset({"workflow-embedded-program"}))
    assert len(findings) == 1
    assert findings[0].code == "SARJ310"
    assert source.splitlines()[findings[0].line - 1].strip().startswith("command:")


@pytest.mark.parametrize("value", ['"t"', '"T"', '"1"', '"0"', '"  true  "', '"maybe"', "1", "null", '"${FLAG}"'])
def test_compose_unknown_or_invalid_healthcheck_disable_does_not_invent_execution(value: str) -> None:
    source = (
        "services:\n  app:\n    image: fixture\n    healthcheck:\n"
        f"      disable: {value}\n"
        '      test: [CMD-SHELL, "printf first; printf second"]\n'
    )
    with pytest.raises(ProgramProjectionError, match="cannot be proven statically"):
        execution_blocks("compose.yaml", source)

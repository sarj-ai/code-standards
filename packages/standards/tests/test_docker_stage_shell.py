from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.linting import textlint
from sarj_standards.libs.linting.devops_programs import block_embeds_program, execution_blocks
from sarj_standards.libs.linting.shell_ast import parse_shell


if TYPE_CHECKING:
    from pathlib import Path


_CASES = (
    ("python-inherited-run", 'FROM scratch AS base\nSHELL ["python3", "-c"]\nFROM base\nRUN pass\n', (True,)),
    ("python-inherited-cmd", 'FROM scratch AS base\nSHELL ["python3", "-c"]\nFROM base\nCMD pass\n', (True,)),
    (
        "python-inherited-entrypoint",
        'FROM scratch AS base\nSHELL ["python3", "-c"]\nFROM base\nENTRYPOINT pass\n',
        (True,),
    ),
    ("node-inherited-run", 'FROM scratch AS base\nSHELL ["node", "-e"]\nFROM base\nRUN void 0\n', (True,)),
    ("ruby-inherited-run", 'FROM scratch AS base\nSHELL ["ruby", "-e"]\nFROM base\nRUN nil\n', (True,)),
    ("alias-declaration-case", 'FROM scratch AS Base\nSHELL ["python3", "-c"]\nFROM base\nRUN pass\n', (True,)),
    (
        "transitive-stage",
        'FROM scratch AS base\nSHELL ["python3", "-c"]\nFROM base AS child\nFROM child\nRUN pass\n',
        (True,),
    ),
    (
        "platform-option-stage",
        'FROM scratch AS base\nSHELL ["python3", "-c"]\nFROM --platform=linux/amd64 base\nRUN pass\n',
        (True,),
    ),
    (
        "continued-from-stage",
        'FROM scratch AS base\nSHELL ["python3", "-c"]\nFROM base \\\n AS child\nRUN pass\n',
        (True,),
    ),
    ("external-image-reset", 'FROM scratch AS base\nSHELL ["python3", "-c"]\nFROM scratch\nRUN make lint\n', (False,)),
    (
        "explicit-shell-reset",
        'FROM scratch AS base\nSHELL ["python3", "-c"]\nFROM base\nSHELL ["sh", "-c"]\nRUN make lint\n',
        (False,),
    ),
    (
        "exec-form-ignores-shell",
        'FROM scratch AS base\nSHELL ["python3", "-c"]\nFROM base\nRUN ["python3", "scripts/check.py"]\n',
        (False,),
    ),
    (
        "inherited-external-interpreter",
        'FROM scratch AS base\nSHELL ["python3", "scripts/check.py"]\nFROM base\nRUN -c strict\n',
        (False,),
    ),
    ("ordinary-shell-stage", 'FROM scratch AS base\nSHELL ["bash", "-c"]\nFROM base\nRUN make lint\n', (False,)),
    (
        "stage-base-independent-branches",
        'FROM scratch AS base\nSHELL ["python3", "-c"]\nFROM base AS child\nSHELL ["sh", "-c"]\nRUN make lint\nFROM base\nRUN pass\n',
        (False, True),
    ),
    (
        "child-change-not-base",
        'FROM scratch AS base\nSHELL ["sh", "-c"]\nFROM base AS child\nSHELL ["python3", "-c"]\nFROM base\nRUN make lint\n',
        (False,),
    ),
    (
        "base-final-shell",
        'FROM scratch AS base\nSHELL ["python3", "-c"]\nSHELL ["sh", "-c"]\nFROM base\nRUN make lint\n',
        (False,),
    ),
    ("existing-inline-argv", 'FROM scratch AS base\nFROM base\nRUN ["python3", "-c", "pass"]\n', (True,)),
)


@pytest.mark.parametrize(("case_id", "source", "embedded"), _CASES, ids=[case[0] for case in _CASES])
def test_docker_named_stage_inherits_shell_config(
    tmp_path: Path, case_id: str, source: str, embedded: tuple[bool, ...]
) -> None:
    blocks = execution_blocks("Dockerfile", source)
    assert execution_blocks("Dockerfile", source) == blocks
    assert tuple(block_embeds_program(block, parse_shell=parse_shell) for block in blocks) == embedded, case_id
    path = tmp_path / "Dockerfile"
    path.write_text(source, encoding="utf-8")
    findings = textlint.check_paths([str(path)], root=tmp_path, rule_ids=frozenset({"workflow-embedded-program"}))
    assert len(findings) == sum(embedded)
    assert tuple(finding.line for finding in findings) == tuple(
        block.line for block, expected in zip(blocks, embedded, strict=True) if expected
    )


@pytest.mark.parametrize("base", ["other", "base:latest", "registry.example/base", "$BASE", "${BASE}"])
def test_docker_unknown_image_does_not_inherit_unrelated_stage(base: str) -> None:
    source = f'FROM scratch AS base\nSHELL ["python3", "-c"]\nFROM {base}\nRUN make lint\n'
    [block] = execution_blocks("Dockerfile", source)
    assert not block_embeds_program(block, parse_shell=parse_shell)

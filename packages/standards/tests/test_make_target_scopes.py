from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.linting import textlint
from sarj_standards.libs.linting.devops_programs import ProgramProjectionError, block_embeds_program, execution_blocks
from sarj_standards.libs.linting.shell_ast import parse_shell


if TYPE_CHECKING:
    from pathlib import Path

_CASES = [
    pytest.param("CMD = python3 -c 'print(\"NATIVE_INLINE\")'\nall:\n\t@$(CMD)\n", True, id="global-inline"),
    pytest.param('CMD = printf "%s\\n" DATA_ONLY\nall:\n\t@$(CMD)\n', False, id="global-data"),
    pytest.param(
        'CMD = python3 -c \'print("NATIVE_INLINE")\'\nall: CMD = printf "%s\\n" DATA_ONLY\nall:\n\t@$(CMD)\n',
        False,
        id="target-inline-to-data",
    ),
    pytest.param(
        'CMD = printf "%s\\n" DATA_ONLY\nall: CMD = python3 -c \'print("NATIVE_INLINE")\'\nall:\n\t@$(CMD)\n',
        True,
        id="target-data-to-inline",
    ),
    pytest.param(
        'CMD = printf "%s\\n" DATA_ONLY\nall: CMD = python3 -c \'print("NATIVE_INLINE")\'\nall: child\nchild:\n\t@$(CMD)\n',
        True,
        id="inherited-prerequisite",
    ),
    pytest.param(
        'CMD = printf "%s\\n" DATA_ONLY\nall: CMD = python3 -c \'print("NATIVE_INLINE")\'\nall: child\nchild: CMD = printf "%s\\n" DATA_ONLY\nchild:\n\t@$(CMD)\n',
        False,
        id="child-overrides-inherited",
    ),
    pytest.param(
        'CMD = printf "%s\\n" DATA_ONLY\n%.out: CMD = python3 -c \'print("NATIVE_INLINE")\'\n%.out:\n\t@$(CMD)\n',
        True,
        id="pattern-inline",
    ),
    pytest.param(
        'CMD = python3 -c \'print("NATIVE_INLINE")\'\n%.out: CMD = printf "%s\\n" DATA_ONLY\n%.out:\n\t@$(CMD)\n',
        False,
        id="pattern-data",
    ),
    pytest.param(
        'CMD = printf "%s\\n" DATA_ONLY\nall: OTHER = python3 -c \'print("NATIVE_INLINE")\'\nall:\n\t@$(CMD)\n',
        False,
        id="unrelated-binding",
    ),
    pytest.param(
        'CMD = printf "%s\\n" DATA_ONLY\na b: CMD = python3 -c \'print("NATIVE_INLINE")\'\na b:\n\t@$(CMD)\n',
        True,
        id="multiple-target-binding",
    ),
    pytest.param(
        'BASE = printf "%s\\n" DATA_ONLY\nall: CMD = $(BASE)\nBASE = python3 -c \'print("NATIVE_INLINE")\'\nall:\n\t@$(CMD)\n',
        True,
        id="recursive-late-global",
    ),
    pytest.param(
        'BASE = printf "%s\\n" DATA_ONLY\nall: CMD := $(BASE)\nBASE = python3 -c \'print("NATIVE_INLINE")\'\nall:\n\t@$(CMD)\n',
        False,
        id="simple-frozen-global",
    ),
    pytest.param(
        'BASE = python3 -c \'print("NATIVE_INLINE")\'\nall: CMD := $(BASE)\nBASE = printf "%s\\n" DATA_ONLY\nall:\n\t@$(CMD)\n',
        True,
        id="simple-frozen-inline",
    ),
    pytest.param(
        "all: CMD ?= python3 -c 'print(\"NATIVE_INLINE\")'\nall:\n\t@$(CMD)\n", True, id="conditional-unbound"
    ),
    pytest.param(
        'CMD = printf "%s\\n" DATA_ONLY\nall: CMD ?= python3 -c \'print("NATIVE_INLINE")\'\nall:\n\t@$(CMD)\n',
        False,
        id="conditional-bound-global",
    ),
    pytest.param(
        'CMD = printf "%s\\n" DATA_ONLY\nall: CMD ?= python3 -c \'print("NATIVE_INLINE")\'\nCMD = python3 -c \'print("NATIVE_INLINE")\'\nall:\n\t@$(CMD)\n',
        True,
        id="conditional-bound-then-global-change",
    ),
    pytest.param(
        'BASE = printf "%s\\n" DATA_ONLY\nall: CMD := $(BASE)\nall: CMD += DATA_SUFFIX\nBASE = python3 -c \'print("NATIVE_INLINE")\'\nall:\n\t@$(CMD)\n',
        False,
        id="append-frozen",
    ),
    pytest.param(
        'BASE = printf "%s\\n" DATA_ONLY\nall: CMD = $(BASE)\nall: CMD += DATA_SUFFIX\nBASE = python3 -c \'print("NATIVE_INLINE")\'\nall:\n\t@$(CMD)\n',
        True,
        id="append-recursive",
    ),
    pytest.param(
        'CMD = printf "%s\\n" DATA_ONLY\nall: override CMD = python3 -c \'print("NATIVE_INLINE")\'\nall:\n\t@$(CMD)\n',
        True,
        id="target-override-modifier",
    ),
    pytest.param(
        'CMD = printf "%s\\n" DATA_ONLY\nall: export CMD = python3 -c \'print("NATIVE_INLINE")\'\nall:\n\t@$(CMD)\n',
        True,
        id="target-export-modifier",
    ),
    pytest.param(
        'CMD = printf "%s\\n" DATA_ONLY\nsafe: CMD = printf "%s\\n" DATA_ONLY\nunsafe: CMD = python3 -c \'print("NATIVE_INLINE")\'\nsafe unsafe: child\nchild:\n\t@$(CMD)\n',
        True,
        id="two-parent-contexts",
    ),
    pytest.param('all: SHELL := python3\nall:\n\t@print("NATIVE_INLINE")\n', True, id="local-shell-interpreter"),
]


@pytest.mark.parametrize(("source", "expected"), _CASES)
def test_make_target_variable_execution(source: str, *, expected: bool, tmp_path: Path) -> None:
    blocks = execution_blocks("Makefile", source)
    assert blocks == execution_blocks("Makefile", source)
    assert any(block_embeds_program(block, parse_shell=parse_shell) for block in blocks) is expected
    path = tmp_path / "Makefile"
    path.write_text(source, encoding="utf-8")
    findings = textlint.check_paths([str(path)], root=tmp_path, rule_ids=frozenset({"workflow-embedded-program"}))
    assert bool(findings) is expected
    assert len({(finding.line, finding.code) for finding in findings}) == len(findings)


@pytest.mark.parametrize(
    "assignments",
    [
        "%.out: CMD = python3 -c 'print(1)'\nt%.out: CMD = printf data",
        "t%.out: CMD = printf data\n%.out: CMD = python3 -c 'print(1)'",
    ],
)
def test_conflicting_pattern_precedence_remains_unproven(assignments: str) -> None:
    source = f"{assignments}\ntool.out:\n\t@$(CMD)\n"
    with pytest.raises(ProgramProjectionError, match="pattern variable precedence"):
        execution_blocks("Makefile", source)


@pytest.mark.parametrize(
    "scope", ["tool.out: CMD = python3 -c 'print(1)'", "%.out: CMD = python3 -c 'print(1)'\ntool.out: child"]
)
def test_pattern_recipe_instances_and_inherited_contexts(scope: str) -> None:
    source = f"CMD = printf data\n{scope}\n%.out:\n\t@$(CMD)\nchild:\n\t@$(CMD)\n"
    blocks = execution_blocks("Makefile", source)
    assert any(block_embeds_program(block, parse_shell=parse_shell) for block in blocks)


@pytest.mark.parametrize("second", ["CMD = python3 -c 'print(1)'", "OTHER = documented-data"])
def test_compatible_overlapping_pattern_bindings(second: str) -> None:
    source = f"%.out: CMD = python3 -c 'print(1)'\nt%.out: {second}\ntool.out:\n\t@$(CMD)\n"
    blocks = execution_blocks("Makefile", source)
    assert any(block_embeds_program(block, parse_shell=parse_shell) for block in blocks)

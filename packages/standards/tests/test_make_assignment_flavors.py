import shutil
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.linting import textlint
from sarj_standards.libs.linting.devops_programs import ProgramProjectionError, block_embeds_program, execution_blocks
from sarj_standards.libs.linting.external import run_process
from sarj_standards.libs.linting.shell_ast import parse_shell


if TYPE_CHECKING:
    from pathlib import Path


_CASES = (
    (
        "simple-frozen-inline",
        "CMD = python3 -c 1\nRUN := $(CMD)\nCMD = python3 scripts/check.py\ncheck:\n\t$(RUN)\n",
        True,
        True,
    ),
    (
        "simple-frozen-file",
        "CMD = python3 scripts/check.py\nRUN := $(CMD)\nCMD = python3 -c 1\ncheck:\n\t$(RUN)\n",
        False,
        True,
    ),
    (
        "recursive-late-inline",
        "CMD = python3 scripts/check.py\nRUN = $(CMD)\nCMD = python3 -c 1\ncheck:\n\t$(RUN)\n",
        True,
        True,
    ),
    (
        "recursive-late-file",
        "CMD = python3 -c 1\nRUN = $(CMD)\nCMD = python3 scripts/check.py\ncheck:\n\t$(RUN)\n",
        False,
        True,
    ),
    (
        "simple-append-inline",
        "FLAG = -c\nRUN := python3\nRUN += $(FLAG) 1\nFLAG = scripts/check.py\ncheck:\n\t$(RUN)\n",
        True,
        True,
    ),
    (
        "simple-append-file",
        "FLAG = scripts/check.py\nRUN := python3\nRUN += $(FLAG)\nFLAG = -c 1\ncheck:\n\t$(RUN)\n",
        False,
        True,
    ),
    (
        "recursive-append-inline",
        "FLAG = scripts/check.py\nRUN = python3\nRUN += $(FLAG)\nFLAG = -c 1\ncheck:\n\t$(RUN)\n",
        True,
        True,
    ),
    (
        "recursive-append-file",
        "FLAG = -c 1\nRUN = python3\nRUN += $(FLAG)\nFLAG = scripts/check.py\ncheck:\n\t$(RUN)\n",
        False,
        True,
    ),
    ("undefined-append-recursive", "RUN += python3 $(FLAG)\nFLAG = -c 1\ncheck:\n\t$(RUN)\n", True, True),
    ("conditional-recursive-inline", "RUN ?= python3 $(FLAG)\nFLAG = -c 1\ncheck:\n\t$(RUN)\n", True, True),
    (
        "conditional-retains-simple-file",
        "CMD = python3 scripts/check.py\nRUN := $(CMD)\nRUN ?= python3 -c 1\nCMD = python3 -c 1\ncheck:\n\t$(RUN)\n",
        False,
        True,
    ),
    (
        "conditional-retains-recursive-file",
        "RUN = python3 scripts/check.py\nRUN ?= python3 -c 1\ncheck:\n\t$(RUN)\n",
        False,
        True,
    ),
    ("simple-self-reference", "RUN = python3\nRUN := $(RUN) -c 1\ncheck:\n\t$(RUN)\n", True, True),
    (
        "simple-frozen-alias-inline",
        "CMD = python3 -c 1\nALIAS = $(CMD)\nRUN := $(ALIAS)\nCMD = python3 scripts/check.py\ncheck:\n\t$(RUN)\n",
        True,
        True,
    ),
    (
        "simple-frozen-alias-file",
        "CMD = python3 scripts/check.py\nALIAS = $(CMD)\nRUN := $(ALIAS)\nCMD = python3 -c 1\ncheck:\n\t$(RUN)\n",
        False,
        True,
    ),
    (
        "quoted-inline-looking-data",
        "CMD = python3 -c 1\nRUN := $(CMD)\nCMD = python3 scripts/check.py\ncheck:\n\tprintf '%s' '$(RUN)'\n",
        False,
        True,
    ),
    ("escaped-shell-substitution-inline", 'RUN := printf %s "$$(python3 -c 1)"\ncheck:\n\t$(RUN)\n', True, True),
    ("escaped-shell-data", "RUN := printf %s '$$(python3 -c 1)'\ncheck:\n\t$(RUN)\n", False, True),
    (
        "double-colon-frozen-inline",
        "CMD = python3 -c 1\nRUN ::= $(CMD)\nCMD = python3 scripts/check.py\ncheck:\n\t$(RUN)\n",
        True,
        False,
    ),
    (
        "double-colon-frozen-file",
        "CMD = python3 scripts/check.py\nRUN ::= $(CMD)\nCMD = python3 -c 1\ncheck:\n\t$(RUN)\n",
        False,
        False,
    ),
    (
        "immediate-recursive-frozen-inline",
        "CMD = python3 -c 1\nRUN :::= $(CMD)\nCMD = python3 scripts/check.py\ncheck:\n\t$(RUN)\n",
        True,
        False,
    ),
    (
        "immediate-recursive-append-late",
        "FLAG = scripts/check.py\nRUN :::= python3\nRUN += $(FLAG)\nFLAG = -c 1\ncheck:\n\t$(RUN)\n",
        True,
        False,
    ),
)


@pytest.mark.parametrize(
    ("case_id", "source", "embedded"),
    [(case[0], case[1], case[2]) for case in _CASES],
    ids=[case[0] for case in _CASES],
)
def test_make_assignment_flavor_preserves_execution(
    tmp_path: Path, case_id: str, source: str, *, embedded: bool
) -> None:
    [block] = execution_blocks("Makefile", source)
    assert execution_blocks("Makefile", source) == [block]
    assert block_embeds_program(block, parse_shell=parse_shell) is embedded, case_id
    assert block.line == len(source.splitlines())
    path = tmp_path / "Makefile"
    path.write_text(source, encoding="utf-8")
    findings = textlint.check_paths([str(path)], root=tmp_path, rule_ids=frozenset({"workflow-embedded-program"}))
    assert len(findings) == int(embedded)
    assert all(finding.line == block.line for finding in findings)


@pytest.mark.parametrize(
    ("case_id", "source"),
    [(case[0], case[1]) for case in _CASES if case[3]],
    ids=[case[0] for case in _CASES if case[3]],
)
def test_make_assignment_projection_matches_native_dry_run(tmp_path: Path, case_id: str, source: str) -> None:
    executable = shutil.which("make")
    if executable is None:
        pytest.skip("GNU Make is unavailable")
    version = run_process((executable, "--version"), cwd=tmp_path)
    if "GNU Make" not in version.stdout:
        pytest.skip("dry-run parity requires GNU Make")
    (tmp_path / "Makefile").write_text(source, encoding="utf-8")
    result = run_process((executable, "-n", "-r", "-f", "Makefile", "check"), cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    [block] = execution_blocks("Makefile", source)
    assert block.source == result.stdout.rstrip("\n"), case_id


@pytest.mark.parametrize("definitions", ["FIRST = $(SECOND)\nSECOND = $(FIRST)\n", "FIRST = $(BROKEN\n"])
def test_make_assignment_malformed_or_recursive_source_fails_coverage(definitions: str) -> None:
    with pytest.raises(ProgramProjectionError):
        execution_blocks("Makefile", definitions + "check:\n\t$(FIRST)\n")


@pytest.mark.parametrize("source", ["RUN := $(UNKNOWN)\ncheck:\n\t$(RUN)\n", "RUN = $(UNKNOWN)\ncheck:\n\t$(RUN)\n"])
def test_make_unknown_variable_does_not_invent_inline_source(source: str) -> None:
    [block] = execution_blocks("Makefile", source)
    assert not block_embeds_program(block, parse_shell=parse_shell)

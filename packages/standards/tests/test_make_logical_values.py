from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting import shell_ast
from sarj_standards.libs.linting.devops_programs import ProgramProjectionError, block_embeds_program, execution_blocks
from sarj_standards.libs.linting.embedded_shell import analyze_sources
from sarj_standards.libs.linting.external import run_process
from sarj_standards.libs.linting.shell_ast import parse_shell


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("prefix", ["FILES :=", "FILES =", "check: FILES :="])
@pytest.mark.parametrize("indent", ["  ", "\t"])
def test_assignment_continuations_match_make_without_phantom_recipes(tmp_path: Path, prefix: str, indent: str) -> None:
    source = f"{prefix} first \\\n{indent}second \\\n{indent}third\ncheck:\n\t@printf '%s\\n' \"$(FILES)\"\n"
    path = tmp_path / "Makefile"
    path.write_text(source)
    executable = shutil.which("make")
    assert executable is not None
    native = run_process((executable, "-n", "-r", "-f", str(path), "check"), cwd=tmp_path)
    assert native.returncode == 0, native.stderr
    [block] = execution_blocks("Makefile", source)
    assert block.line == 5
    assert block.source == native.stdout.rstrip("\n")
    [report] = analyze_sources(root=tmp_path, paths=[str(path)], selected=frozenset({"shellcheck"}))
    assert not report.issues
    assert not report.diagnostics


@pytest.mark.parametrize("quote", ['"', "'"])
@pytest.mark.parametrize("definition", ["", "VALUE = $(CHOICE)\n", "VALUE := $(CHOICE)\n"])
def test_unknown_make_value_remains_dynamic(tmp_path: Path, quote: str, definition: str) -> None:
    variable = "VALUE" if definition else "CHOICE"
    source = definition + f"check:\n\t@if [ -n {quote}$({variable}){quote} ]; then printf set; else printf unset; fi\n"
    path = tmp_path / "Makefile"
    path.write_text(source)
    executable = shutil.which("make")
    assert executable is not None
    for assignment, expected in [("CHOICE=", "unset"), ("CHOICE=yes", "set")]:
        native = run_process((executable, "-s", "-r", "-f", str(path), "check", assignment), cwd=tmp_path)
        assert native.returncode == 0, native.stderr
        assert native.stdout == expected
    [report] = analyze_sources(root=tmp_path, paths=[str(path)], selected=frozenset({"shellcheck"}))
    assert not report.issues
    assert not report.diagnostics


def test_unknown_argument_preserves_real_literal_shell_warning(tmp_path: Path) -> None:
    path = tmp_path / "Makefile"
    path.write_text('check:\n\t@if [ -n "literal" ]; then printf \'%s\' "$(CHOICE)"; fi\n')
    [report] = analyze_sources(root=tmp_path, paths=[str(path)], selected=frozenset({"shellcheck"}))
    assert not report.issues
    assert [item.code for item in report.diagnostics] == ["SC2157"]


@pytest.mark.parametrize(
    ("command", "embedded"), [('python3 -c "print(1)" "$(CHOICE)"', True), ('python3 check.py "$(CHOICE)"', False)]
)
def test_unknown_argument_preserves_program_ownership(command: str, *, embedded: bool) -> None:
    [block] = execution_blocks("Makefile", f"check:\n\t{command}\n")
    assert block_embeds_program(block, parse_shell=parse_shell) is embedded


def test_unknown_selected_shell_payload_fails_closed() -> None:
    [block] = execution_blocks("Makefile", 'check:\n\tbash -c "$(CHOICE)"\n')
    with pytest.raises(ProgramProjectionError, match="cannot be proven statically"):
        block_embeds_program(block, parse_shell=parse_shell)


def test_authored_make_marker_is_still_literal(tmp_path: Path) -> None:
    path = tmp_path / "Makefile"
    path.write_text('check:\n\t@if [ -n "make_expansion" ]; then printf yes; fi\n')
    [report] = analyze_sources(root=tmp_path, paths=[str(path)], selected=frozenset({"shellcheck"}))
    assert [item.code for item in report.diagnostics] == ["SC2157"]


def test_posix_assignment_continuation_fails_closed() -> None:
    with pytest.raises(ProgramProjectionError, match="POSIX"):
        execution_blocks("Makefile", ".POSIX:\nFILES = first \\\n  second\ncheck:\n\tprintf '%s' \"$(FILES)\"\n")


def test_make_automatic_target_does_not_become_shell_array(tmp_path: Path) -> None:
    path = tmp_path / "Makefile"
    path.write_text("check:\n\t@printf '%s' $@\n")
    executable = shutil.which("make")
    assert executable is not None
    native = run_process((executable, "-n", "-r", "-f", str(path), "check"), cwd=tmp_path)
    assert native.stdout == "printf '%s' check\n"
    [report] = analyze_sources(root=tmp_path, paths=[str(path)], selected=frozenset({"shellcheck"}))
    assert not report.issues
    assert not report.diagnostics


def test_make_single_character_variable_preserves_known_value() -> None:
    [block] = execution_blocks("Makefile", "x = python3 -c 1\ncheck:\n\t$x\n")
    assert block_embeds_program(block, parse_shell=parse_shell)


def test_unknown_make_value_in_shell_comment_remains_inert(tmp_path: Path) -> None:
    path = tmp_path / "Makefile"
    path.write_text("check:\n\tprintf ok # $(COMMENT)\n")
    [report] = analyze_sources(root=tmp_path, paths=[str(path)], selected=frozenset({"shellcheck"}))
    assert not report.issues
    assert not report.diagnostics


@pytest.mark.parametrize("operator", ["#", "##", "%", "%%"])
def test_unknown_make_value_in_shell_pattern_fails_closed(operator: str) -> None:
    with pytest.raises(ProgramProjectionError, match="shell context cannot be proven"):
        execution_blocks("Makefile", f"check:\n\tTEXT=abc; printf '%s' \"$${{TEXT{operator}$(PATTERN)}}\"\n")


def test_unknown_make_value_in_parameter_default_remains_dynamic(tmp_path: Path) -> None:
    path = tmp_path / "Makefile"
    path.write_text("check:\n\tprintf '%s' \"$${VALUE:-$(DEFAULT)}\"\n")
    [report] = analyze_sources(root=tmp_path, paths=[str(path)], selected=frozenset({"shellcheck"}))
    assert not report.issues
    assert not report.diagnostics


def test_unknown_make_value_beside_plain_shell_parameter_remains_dynamic(tmp_path: Path) -> None:
    path = tmp_path / "Makefile"
    path.write_text("check:\n\tprintf '%s' \"$${HOME}/$(VALUE)\"\n")
    [report] = analyze_sources(root=tmp_path, paths=[str(path)], selected=frozenset({"shellcheck"}))
    assert not report.issues
    assert not report.diagnostics


@pytest.mark.parametrize("failure", ["missing native parser", "invalid native parser protocol"])
def test_unknown_make_parser_failure_is_a_structured_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    path = tmp_path / "Makefile"
    path.write_text("check:\n\tprintf '%s' \"$(CHOICE)\"\n")

    def unavailable() -> Path:
        raise shell_ast.ShellParseError(failure)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- native parser lookup failure is the adapter contract under test; injecting another analyzer would bypass it.
        shell_ast, "_checked_executable", unavailable
    )
    [report] = analyze_sources(root=tmp_path, paths=[str(path)], selected=frozenset({"shellcheck"}))
    assert report.completion is Completion.FAILED
    assert not report.diagnostics
    [issue] = report.issues
    assert issue.kind == "embedded-shell-failure"
    assert failure in issue.message

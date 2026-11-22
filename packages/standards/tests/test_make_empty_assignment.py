from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion, Severity
from sarj_standards.libs.linting import shell_ast
from sarj_standards.libs.linting.analysis import report_from_tools
from sarj_standards.libs.linting.devops_programs import execution_blocks
from sarj_standards.libs.linting.embedded_shell import analyze_sources
from sarj_standards.libs.linting.external import run_process


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "definition",
    [
        "EMPTY ?=\n",
        "EMPTY =\n",
        "EMPTY :=\n",
        "OTHER =\nEMPTY = $(OTHER)\n",
        "OTHER =\nEMPTY := $(OTHER)\n",
        "check: EMPTY ?=\n",
    ],
)
def test_explicit_empty_make_assignment_value_preserves_default_execution(tmp_path: Path, definition: str) -> None:
    source = definition + "check:\n\tVALUE=$(EMPTY) sh ./reader.sh\n"
    path = tmp_path / "Makefile"
    path.write_text(source)
    (tmp_path / "reader.sh").write_text('#!/bin/sh\nprintf "<%s>" "$VALUE"\n')
    make = shutil.which("make")
    assert make is not None
    native = run_process((make, "-s", "-r", "-f", str(path), "check"), cwd=tmp_path)
    assert native.returncode == 0, native.stderr
    assert native.stdout == "<>"
    [block] = execution_blocks("Makefile", source)
    projected = run_process(("sh", "-c", block.source), cwd=tmp_path)
    assert projected.returncode == 0, projected.stderr
    assert projected.stdout == native.stdout
    [report] = analyze_sources(root=tmp_path, paths=(str(path),), selected=frozenset({"shellcheck"}))
    assert report.completion is Completion.COMPLETE
    assert not report.diagnostics


@pytest.mark.parametrize(
    ("recipe", "errors"),
    [
        pytest.param("VALUE= sh ./reader.sh", 1, id="authored-empty-assignment"),
        pytest.param("VALUE= $(EMPTY)sh ./reader.sh", 1, id="empty-macro-in-command"),
        pytest.param("VALUE=$(EMPTY) OTHER= sh ./reader.sh", 1, id="adjacent-real-empty-assignment"),
        pytest.param("$(EMPTY) printf ready", 0, id="empty-macro-does-not-create-a-command-word"),
        pytest.param("printf '<%s>' $(EMPTY)", 0, id="empty-macro-does-not-create-an-argument"),
        pytest.param("VALUE=pre$(EMPTY) sh ./reader.sh", 0, id="nonempty-value-suffix"),
        pytest.param("VALUE=$(EMPTY)$(EMPTY) sh ./reader.sh", 0, id="multiple-empty-value-expansions"),
        pytest.param('VALUE="$(EMPTY)" sh ./reader.sh', 0, id="already-quoted-empty-value"),
        pytest.param("VALUE=$(EMPTY) sh ./reader.sh $(UNKNOWN)", 0, id="mixed-provenance"),
    ],
)
def test_empty_make_projection_keeps_authored_findings_and_other_word_boundaries(
    tmp_path: Path, recipe: str, errors: int
) -> None:
    path = tmp_path / "Makefile"
    path.write_text(f"EMPTY =\ncheck:\n\t{recipe}\n")
    (tmp_path / "reader.sh").write_text('#!/bin/sh\nprintf "<%s>" "$VALUE"\n')
    [report] = analyze_sources(root=tmp_path, paths=(str(path),), selected=frozenset({"shellcheck"}))
    assert report.completion is Completion.COMPLETE
    findings = [item for item in report.diagnostics if item.rule_id == "SC1007"]
    assert len(findings) == errors
    assert all(item.severity is Severity.ERROR for item in findings)


def test_empty_make_assignment_after_unicode_has_no_synthetic_finding(tmp_path: Path) -> None:
    path = tmp_path / "Makefile"
    path.write_text("EMPTY =\ncheck:\n\tprintf 'é'; VALUE=$(EMPTY) printf ready\n")
    [report] = analyze_sources(root=tmp_path, paths=(str(path),), selected=frozenset({"shellcheck"}))
    assert report.completion is Completion.COMPLETE
    assert not report.diagnostics


def test_empty_make_assignment_cannot_hide_malformed_shell(tmp_path: Path) -> None:
    path = tmp_path / "Makefile"
    path.write_text("EMPTY =\ncheck:\n\tVALUE=$(EMPTY) if true; then\n")
    reports = analyze_sources(root=tmp_path, paths=(str(path),), selected=frozenset({"shellcheck"}))
    assert report_from_tools(tmp_path, reports).exit_code in {1, 2}


def test_empty_make_assignment_parser_failure_cannot_qualify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "Makefile"
    path.write_text("EMPTY =\ncheck:\n\tVALUE=$(EMPTY) printf ready\n")

    def unavailable() -> Path:
        msg = "native parser unavailable"
        raise shell_ast.ShellParseError(msg)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- Exercise actual native lookup failure; replacing the analyzer would bypass the empty-expansion path.
        shell_ast, "_checked_executable", unavailable
    )
    [report] = analyze_sources(root=tmp_path, paths=(str(path),), selected=frozenset({"shellcheck"}))
    assert report.completion is Completion.FAILED
    assert not report.diagnostics
    assert "native parser unavailable" in report.issues[0].message

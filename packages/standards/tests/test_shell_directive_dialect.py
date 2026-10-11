from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion, TrustMode
from sarj_standards.libs.linting import shell_format, textlint
from sarj_standards.libs.linting.external import analyze_external
from sarj_standards.libs.rules import EvaluationCase, Language, RuleProblem


if TYPE_CHECKING:
    from pathlib import Path


PROBLEM = RuleProblem(
    key="shell-source-directive-dialect",
    summary="Header ShellCheck directives describe the dialect of sourced shell libraries.",
    harm="The formatter rejects valid Bash libraries while native ShellCheck accepts their explicit source contract.",
    languages=frozenset({Language.SHELL}),
    bad_examples=("# shellcheck shell=bash\nvalues=(one two)\n",),
    good_examples=("#!/bin/bash\nvalues=(one two)\n",),
    exclusions=("An executable shebang remains authoritative", "Data and directives after code are not headers"),
)


@pytest.mark.parametrize("relative", ["library.sh", "library"])
def test_header_directive_allows_native_bash_source_libraries(tmp_path: Path, relative: str) -> None:
    case = EvaluationCase(
        "bash-source-library",
        Language.SHELL,
        '# shellcheck shell=bash\nvalues=(one two)\nprintf "%s\\n" "${values[@]}"\n',
    )
    assert case.language in PROBLEM.languages
    path = tmp_path / relative
    path.write_text(case.source)
    reports = analyze_external(
        [str(path)], root=tmp_path, trust=TrustMode.SAFE, capabilities=frozenset({"shellcheck", "shfmt"})
    )
    assert {report.name for report in reports} == {"shellcheck", "shfmt"}
    assert all(report.completion is Completion.COMPLETE and not report.diagnostics for report in reports)
    assert textlint.shell_dialect(path) == "bash"
    assert shell_format.fix_sources(tmp_path, [str(path)]) == 0
    assert path.read_text() == case.source


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("#!/bin/sh\n# shellcheck shell=bash\n", "sh", id="runtime-shebang-wins"),
        pytest.param("#!/usr/bin/env python3\n# shellcheck shell=bash\n", None, id="foreign-shebang-wins"),
        pytest.param("# license\n\n# shellcheck shell=bash\n", "bash", id="header-comments-and-blanks"),
        pytest.param("printf done\n# shellcheck shell=bash\n", "sh", id="directive-after-code"),
        pytest.param("printf '%s' '# shellcheck shell=bash'\n", "sh", id="quoted-data"),
        pytest.param("# documentation: shellcheck shell=bash\n", "sh", id="comment-prose"),
        pytest.param("# shellcheck shell=unknown\n", "sh", id="unknown-dialect"),
    ],
)
def test_shell_directive_classification_preserves_runtime_and_data_boundaries(
    tmp_path: Path, source: str, expected: str | None
) -> None:
    path = tmp_path / "library.sh"
    path.write_text(source)
    assert textlint.shell_dialect(path) == expected


@pytest.mark.parametrize("suffix", [".py", ".yaml", ".md"])
def test_shell_analysis_directive_does_not_reclassify_foreign_file_types(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / ("document" + suffix)
    path.write_text("# shellcheck shell=bash\n")
    assert textlint.shell_dialect(path) is None

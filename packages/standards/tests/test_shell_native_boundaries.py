from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion, TrustMode
from sarj_standards.libs.linting import shell_format, textlint
from sarj_standards.libs.linting.devops_tools import checked_tool
from sarj_standards.libs.linting.external import analyze_external
from sarj_standards.libs.rules import EvaluationCase, ExpectedOutcome, Language, RuleProblem


if TYPE_CHECKING:
    from pathlib import Path


PROBLEM = RuleProblem(
    key="shell-native-dialect-boundaries",
    summary="Supported shell source contracts must reach the correct native parser.",
    harm="Bats and Bash sources are skipped or rejected while upstream analyzers accept them.",
    languages=frozenset({Language.SHELL}),
    bad_examples=("#!/opt/tools/bin/bash\nprintf '%s' $1\n", "@test 'example' {\necho ok\n}\n"),
    good_examples=("#!/bin/bash\nprintf '%s' \"$1\"\n",),
    exclusions=("Foreign and unproven shebangs", "Directives after code or inside other directive values"),
)


@pytest.mark.parametrize(
    ("name", "source", "dialect", "fix_status"),
    [
        pytest.param("entry", "#!/opt/tools/bin/bash\nprintf '%s' $1\n", "bash", 0, id="custom-bash-location"),
        pytest.param("entry.sh", "#!\v/bin/bash\nprintf '%s' $1\n", "bash", 2, id="legacy-shebang-whitespace"),
        pytest.param("entry.sh", "#!/usr/bin/env\vbash\nprintf '%s' $1\n", "bash", 2, id="legacy-env-whitespace"),
        pytest.param("entry.sh", "#!/opt/tools/bin/dash\nprintf '%s' $1\n", "dash", 0, id="custom-posix-location"),
        pytest.param("entry", "#!/opt/tools/bin/env bash\nprintf '%s' $1\n", "bash", 0, id="custom-env-location"),
        pytest.param("suite.bats", "@test 'example' {\nprintf '%s' $1\n}\n", "bats", 0, id="bats-source"),
        pytest.param(
            "suite.bats",
            "# shellcheck shell=bash\n@test 'example' {\nprintf '%s' $1\n}\n",
            "bats",
            0,
            id="bats-bash-analysis-directive",
        ),
        pytest.param(
            "suite.bats", "#!/usr/bin/env bats\n@test 'example' {\nprintf '%s' $1\n}\n", "bats", 0, id="bats-executable"
        ),
    ],
)
def test_native_dialects_receive_existing_correctness_checks_and_safe_formatting(
    tmp_path: Path, name: str, source: str, dialect: str, fix_status: int
) -> None:
    case = EvaluationCase(name, Language.SHELL, source, ExpectedOutcome.MATCH)
    assert case.language in PROBLEM.languages
    path = tmp_path / name
    path.write_text(case.source)
    reports = analyze_external(
        [str(path)], root=tmp_path, trust=TrustMode.SAFE, capabilities=frozenset({"shellcheck", "shfmt"})
    )
    assert {item.name for item in reports} == {"shellcheck", "shfmt"}
    assert all(item.completion is Completion.COMPLETE for item in reports)
    assert textlint.shell_dialect(path) == dialect
    assert sum(finding.rule_id == "SC2086" for item in reports for finding in item.diagnostics) == 1
    if fix_status:
        assert shell_format.fix_sources(tmp_path, [str(path)]) == fix_status
        assert path.read_bytes() == case.source.encode()
        return
    formatter = checked_tool("shfmt", root=tmp_path).executable
    assert formatter is not None
    expected = subprocess.run(
        [str(formatter), "-i", "2", "-ci", "-ln=" + ("posix" if dialect == "dash" else dialect)],
        input=source,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    assert shell_format.fix_sources(tmp_path, [str(path)]) == 0
    assert path.read_text() == expected
    assert shell_format.fix_sources(tmp_path, [str(path)]) == 0
    assert path.read_text() == expected


@pytest.mark.parametrize(
    "directive",
    [
        "# shellcheck disable=SC2034 shell=bash",
        "# shellcheck shell='bash'",
        '# shellcheck disable="SC2034" shell="bash"',
        '# shellcheck source="library with spaces" shell=bash # sourced contract',
    ],
)
def test_native_directive_grammar_selects_valid_bash_libraries(tmp_path: Path, directive: str) -> None:
    case = EvaluationCase(
        directive,
        Language.SHELL,
        directive + '\nvalues=(one two)\nprintf "%s\\n" "${values[@]}"\n',
    )
    path = tmp_path / "library.sh"
    path.write_text(case.source)
    reports = analyze_external(
        [str(path)], root=tmp_path, trust=TrustMode.SAFE, capabilities=frozenset({"shellcheck", "shfmt"})
    )
    assert {item.name for item in reports} == {"shellcheck", "shfmt"}
    assert all(item.completion is Completion.COMPLETE and not item.diagnostics for item in reports)
    assert textlint.shell_dialect(path) == "bash"
    assert shell_format.fix_sources(tmp_path, [str(path)]) == 0
    assert path.read_text() == case.source


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("#!/opt/tools/bin/python3\n", None, id="foreign-custom-location"),
        pytest.param("#!/opt/tools/bin/bash-helper\n", None, id="basename-near-miss"),
        pytest.param("#!bash\n", None, id="relative-interpreter"),
        pytest.param("#!/usr/bin/env --unknown bash\n", None, id="unproven-env-options"),
        pytest.param('# shellcheck source="path shell=bash"\n', "sh", id="quoted-source-value"),
        pytest.param("# shellcheck disable=SC2034 # shell=bash\n", "sh", id="trailing-comment"),
        pytest.param("# shellcheck not-a-pair shell=bash\n", "sh", id="malformed-prefix"),
        pytest.param("# shellcheck shell='ba\\sh'\n", "sh", id="directive-quotes-are-literal"),
        pytest.param("# shellcheck shell='bash\n", "sh", id="unclosed-directive-value"),
    ],
)
def test_native_dialect_near_misses_remain_excluded(tmp_path: Path, source: str, expected: str | None) -> None:
    path = tmp_path / "library.sh"
    path.write_text(source)
    assert textlint.shell_dialect(path) == expected


def test_bats_suffix_retains_executable_shebang_priority(tmp_path: Path) -> None:
    path = tmp_path / "suite.bats"
    path.write_text("#!/bin/bash\n@test 'example' {\nprintf '%s' $1\n}\n")
    assert textlint.shell_dialect(path) == "bash"
    [report] = shell_format.analyze_sources(root=tmp_path, paths=[str(path)])
    assert report.completion is Completion.FAILED

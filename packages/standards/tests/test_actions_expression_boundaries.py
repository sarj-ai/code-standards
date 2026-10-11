from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting import embedded_shell, shell_format
from sarj_standards.libs.linting.devops_programs import block_embeds_program, execution_blocks
from sarj_standards.libs.linting.devops_tools import checked_tool
from sarj_standards.libs.linting.shell_ast import parse_shell
from sarj_standards.libs.rules import EvaluationCase, Language, RuleProblem


if TYPE_CHECKING:
    from pathlib import Path


PROBLEM = RuleProblem(
    key="actions-expression-shell-boundaries",
    summary="Actions interpolation ends outside its single-quoted string literals.",
    harm="Truncated interpolation masks report false shell syntax errors and false embedded programs.",
    languages=frozenset({Language.SHELL}),
    bad_examples=("printf '%s\\n' '${{ format('{0}', '}}') }}'\n",),
    good_examples=("printf '%s\\n' '${{ format('{0}', 'value') }}'\n",),
    exclusions=("Expression semantics remain owned by actionlint", "Templated blocks remain check only"),
)


def _workflow(source: str) -> str:
    body = "".join("          " + line + "\n" for line in source.splitlines())
    return (
        "name: check\n'on': push\njobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n      - shell: bash\n        run: |\n"
        + body
    )


@pytest.mark.parametrize(
    "expression",
    [
        "${{ format('{0}', '}}') }}",
        "${{ format('{0}', 'it''s }}') }}",
        "${{ format('{0}{1}', '}}', '}}') }}",
        "${{ format('{0}', '}}; python -c code #') }}",
        "${{ format('{0}', '${{ nested }}') }}",
        "${{ format('{0}', '}}') }}${{ format('{0}', '}}') }}",
    ],
)
def test_valid_actions_expressions_stay_opaque_to_both_shell_adapters(tmp_path: Path, expression: str) -> None:
    quote = '"' if "it''s" in expression else "'"
    case = EvaluationCase(expression, Language.SHELL, f"printf '%s\\n' {quote}{expression}{quote}\n")
    assert case.language in PROBLEM.languages
    relative = ".github/workflows/check.yml"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    source = _workflow(case.source)
    path.write_text(source)
    executable = checked_tool("actionlint", root=tmp_path).executable
    assert executable is not None
    native = subprocess.run(
        [str(executable), "-shellcheck=", "-pyflakes=", str(path)], text=True, capture_output=True, check=False
    )
    assert native.returncode == 0, native.stdout + native.stderr
    reports = embedded_shell.analyze_sources(
        root=tmp_path, paths=[str(path)], selected=frozenset({"shellcheck", "shfmt"})
    )
    assert {item.name for item in reports} == {"shellcheck", "shfmt"}
    assert all(item.completion is Completion.COMPLETE and not item.diagnostics for item in reports)
    [block] = execution_blocks(relative, source)
    assert not block_embeds_program(block, parse_shell=parse_shell)
    assert shell_format.fix_sources(tmp_path, [str(path)]) == 0
    assert path.read_text() == source


@pytest.mark.parametrize("value", ["}}", "😀 }}"])
def test_masked_expression_keeps_neighboring_shell_finding_and_exact_source_position(
    tmp_path: Path, value: str
) -> None:
    relative = ".github/workflows/check.yml"
    expression = "${{ format('{0}', '" + value + "') }}"
    source = _workflow("printf '%s\\n' '" + expression + "' $value\n")
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(source)
    [report] = embedded_shell.analyze_sources(root=tmp_path, paths=[str(path)], selected=frozenset({"shellcheck"}))
    assert report.completion is Completion.COMPLETE
    [finding] = report.diagnostics
    assert finding.rule_id == "SC2086"
    assert finding.location.region is not None
    assert finding.location.region.start.byte_offset == path.read_bytes().index(b"$value")


def test_expression_boundary_fix_preserves_exact_code_suppression(tmp_path: Path) -> None:
    source = _workflow("# shellcheck disable=SC2086\nprintf '%s\\n' '${{ format('{0}', '}}') }}' $value\n")
    path = tmp_path / ".github/workflows/check.yml"
    path.parent.mkdir(parents=True)
    path.write_text(source)
    [report] = embedded_shell.analyze_sources(root=tmp_path, paths=[str(path)], selected=frozenset({"shellcheck"}))
    assert report.completion is Completion.COMPLETE
    assert not report.diagnostics

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.linting.devops_programs import execution_blocks
from sarj_standards.libs.linting.embedded_shell import analyze_sources, shell_block
from sarj_standards.libs.rules import EvaluationCase, ExpectedOutcome, Language, RuleProblem


if TYPE_CHECKING:
    from pathlib import Path


PROBLEM = RuleProblem(
    key="make-physical-recipe-lines",
    summary="Literal separator data must not truncate Make recipes or introduce interpreter assignments.",
    harm="Truncated recipes miss executable source; fake assignments inside comments can bypass shell analysis.",
    languages=frozenset({Language.CONFIG}),
    bad_examples=("# comment\u2028SHELL=python3\ncheck:\n\tprintf '%s' $$value\n",),
    good_examples=("SHELL=python3\ncheck:\n\tprint(1)\n",),
    exclusions=("Actual LF and CRLF lines retain native Make recipe and variable semantics",),
)


@pytest.mark.parametrize("separator", ["\v", "\f", "\r", "\x85", "\u2028", "\u2029"])
@pytest.mark.parametrize("context", ["recipe", "inline", "oneshell"])
def test_recipe_separator_data_preserves_source_and_physical_lines(separator: str, context: str) -> None:
    command = f"printf '%s' 'before{separator}after'; printf '%s' end"
    if context == "inline":
        source = f"check: ; @{command}\nnext:\n\tprintf next\n"
        expected = [(1, command), (4 if separator == "\r" else 3, "printf next")]
    elif context == "oneshell":
        source = f".ONESHELL:\ncheck:\n\t@{command}\n\tprintf next\n"
        expected = [(3, command + "\nprintf next")]
    else:
        source = f"check:\n\t@{command}\n\tprintf next\n"
        expected = [(2, command), (4 if separator == "\r" else 3, "printf next")]
    case = EvaluationCase("recipe-separator-data", Language.CONFIG, source, path=PurePosixPath("Makefile"))
    assert case.language in PROBLEM.languages
    assert [(block.line, block.source) for block in execution_blocks("Makefile", case.source)] == expected


@pytest.mark.parametrize("separator", ["\v", "\f", "\r", "\x85", "\u2028", "\u2029"])
def test_comment_data_cannot_change_recipe_interpreter(separator: str) -> None:
    case = EvaluationCase(
        "comment-interpreter-assignment",
        Language.CONFIG,
        f"# comment{separator}SHELL=python3\ncheck:\n\tprintf '%s' $$value\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("Makefile"),
    )
    [block] = execution_blocks("Makefile", case.source)
    candidate = shell_block(block)
    assert candidate is not None
    assert candidate.dialect == "posix"
    assert candidate.source == "printf '%s' $value"
    assert block.line == (4 if separator == "\r" else 3)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_real_make_lines_keep_interpreter_assignments(newline: str) -> None:
    source = newline.join(["SHELL=python3", "check:", "\tprint(1)", ""])
    [block] = execution_blocks("Makefile", source)
    assert block.source == "print(1)"
    assert block.line == 3
    assert shell_block(block) is None


@pytest.mark.parametrize("separator", ["\v", "\f", "\r", "\x85", "\u2028", "\u2029"])
def test_embedded_findings_anchor_to_recipe_bytes(tmp_path: Path, separator: str) -> None:
    source = f"# comment{separator}SHELL=python3\ncheck:\n\tprintf '%s' $$value\n"
    path = tmp_path / "Makefile"
    path.write_bytes(source.encode())
    [report] = analyze_sources(root=tmp_path, paths=[str(path)], selected=frozenset({"shellcheck"}))
    [finding] = [item for item in report.diagnostics if item.code == "SC2086"]
    assert finding.location.region is not None
    assert finding.location.region.start.byte_offset == source.encode().index(b"\tprintf")

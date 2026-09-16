import ast
from pathlib import Path
import runpy
import textwrap
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from sarj_python_lint.__main__ import analyze, app, main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_excessive_cognitive_complexity import (
    NoExcessiveCognitiveComplexity,
    function_complexity,
)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("return value", 0),
        ("for slots[a if flag else b] in items:\n    pass", 2),
        ("if a:\n    if b:\n        return value", 3),
        ("if not a:\n    return\nif not b:\n    return\nreturn value", 2),
        ("if a:\n    pass\nelif b:\n    if c:\n        pass\nelse:\n    if d:\n        pass", 7),
        ("if a:\n    pass\nelse:\n    if b:\n        pass", 4),
        ("return a and b and c", 1),
        ("return a and (b or c) and d", 3),
        ("return (a and b) or (c and d)", 3),
        ("return a if b else (c if d else e)", 3),
        ("try:\n    work()\nexcept Error:\n    if retry:\n        work()\nfinally:\n    cleanup()", 3),
        ("for item in items:\n    if item:\n        continue\nelse:\n    finish()", 4),
        ("async for item in items:\n    if item:\n        await work()", 3),
        ("return [x for x in xs if x]", 3),
        ("return [y for x in xs for y in x if y]", 6),
        ("return [x if ok else y for x in xs]", 3),
        ("match value:\n    case 1:\n        pass\n    case _ if ready:\n        if valid:\n            work()", 5),
        ("with manager():\n    if ready:\n        work()", 1),
        ("def inner():\n    if ready:\n        work()\nreturn inner", 0),
        ("class Inner:\n    def method(self):\n        if ready:\n            work()\nreturn Inner", 0),
        ("return lambda: value if ready else other", 0),
        ("return recurse(value)", 0),
    ],
)
def test_scores_control_flow_without_counting_other_function_bodies(body: str, expected: int) -> None:
    source = "async def sample():\n" + textwrap.indent(body, "    ")
    function = ast.parse(source).body[0]
    assert isinstance(function, ast.AsyncFunctionDef)
    assert sum(point.amount for point in function_complexity(function)) == expected


def _guards(count: int) -> str:
    return "def sample():\n" + "    if ready:\n        work()\n" * count


def test_reports_only_above_threshold_with_score_and_contributors() -> None:
    rule = NoExcessiveCognitiveComplexity()
    assert rule.check(Path("src/sample.py"), _guards(20)) == []
    diagnostics = rule.check(Path("src/sample.py"), _guards(21))
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert (diagnostic.line, diagnostic.col, diagnostic.severity) == (1, 1, Severity.ERROR)
    assert "21" in diagnostic.message
    assert "20" in diagnostic.message
    assert "L2 +1" in diagnostic.message


def test_nested_functions_and_methods_are_reported_once_each() -> None:
    source = "def outer():\n" + textwrap.indent(_guards(21), "    ")
    source += "class Example:\n" + textwrap.indent(_guards(21), "    ")
    diagnostics = NoExcessiveCognitiveComplexity().check(Path("src/sample.py"), source)
    assert [diagnostic.line for diagnostic in diagnostics] == [2, 46]


@pytest.mark.parametrize("path", ["src/generated/sample.py", "vendor/sample.py"])
def test_generated_code_is_excluded(path: str) -> None:
    assert NoExcessiveCognitiveComplexity().check(Path(path), _guards(21)) == []


def test_authored_tests_are_checked_and_parse_failures_do_not_crash() -> None:
    rule = NoExcessiveCognitiveComplexity()
    assert len(rule.check(Path("tests/test_sample.py"), _guards(21))) == 1
    assert rule.check(Path("src/sample.py"), "def broken(") == []
    assert rule.check(Path("src/sample.py"), "# @generated\n" + _guards(21)) == []


def test_runner_honors_exact_suppression_without_suppressing_other_functions(tmp_path: Path) -> None:
    path = tmp_path / "sample.py"
    source = _guards(21).replace("def sample():", "def sample():  # sarj-noqa: SARJ444 -- dispatch reviewed")
    path.write_text(source + _guards(21))
    diagnostics = analyze([NoExcessiveCognitiveComplexity.id], [path])
    assert len(diagnostics) == 1
    assert diagnostics[0].severity is Severity.ERROR


def test_long_valid_expression_does_not_exhaust_the_python_call_stack() -> None:
    source = "def sample():\n    return " + "+".join(["value"] * 600)
    assert NoExcessiveCognitiveComplexity().check(Path("src/sample.py"), source) == []


def test_cli_emits_actionable_error(tmp_path: Path) -> None:
    path = tmp_path / "sample.py"
    path.write_text(_guards(21))
    result = CliRunner().invoke(app, ["check", "--rule", NoExcessiveCognitiveComplexity.id, str(path)])
    assert result.exit_code == 0
    assert "SARJ444 Cognitive complexity 21 exceeds 20" in result.stdout
    assert "run relevant tests before and after, then remeasure" in result.stdout


@pytest.mark.parametrize(
    ("score", "severity", "exit_code"),
    [(20, None, 0), (21, Severity.ERROR, 1), (25, Severity.ERROR, 1), (26, Severity.ERROR, 1)],
)
def test_severity_boundaries_and_cli_exit_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], score: int, severity: Severity | None, exit_code: int
) -> None:
    path = tmp_path / "sample.py"
    source = _guards(score)
    path.write_text(source)
    diagnostics = NoExcessiveCognitiveComplexity().check(path, source)
    assert [d.severity for d in diagnostics] == ([] if severity is None else [severity])
    result = CliRunner().invoke(app, ["check", "--rule", NoExcessiveCognitiveComplexity.id, str(path)])
    assert result.exception is None
    assert main(["check", "--rule", NoExcessiveCognitiveComplexity.id, str(path)]) == exit_code
    if severity is not None:
        assert f"Cognitive complexity {score} exceeds" in capsys.readouterr().out


def test_synthetic_library_documentation_scores() -> None:
    documentation = NoExcessiveCognitiveComplexity.documentation
    assert documentation is not None
    examples = [example for example in documentation.examples if example.scenario == "library-check"]
    expected_scores = [[28], [7]]
    for example, expected in zip(examples, expected_scores, strict=True):
        source = example.files[0].source
        functions = [
            node for node in ast.walk(ast.parse(source)) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert [sum(point.amount for point in function_complexity(node)) for node in functions] == expected
        assert len(NoExcessiveCognitiveComplexity().check(Path("src/library.py"), source)) == example.expected_count


@pytest.mark.parametrize("example_id", ["library-check-before", "library-check-after"])
@pytest.mark.parametrize(
    ("borrowed_count", "reference_only", "expected"),
    [(0, False, True), (4, False, True), (5, False, False), (float("nan"), False, False), (0, True, False)],
)
def test_library_examples_preserve_eligibility(
    tmp_path: Path, example_id: str, borrowed_count: float, reference_only: bool, expected: bool
) -> None:
    documentation = NoExcessiveCognitiveComplexity.documentation
    assert documentation is not None
    example = next(item for item in documentation.examples if item.example_id == example_id)
    path = tmp_path / "library_example.py"
    path.write_text(example.focus_file.source + "\nresult = can_borrow(member, book)\n", encoding="utf-8")
    namespace = runpy.run_path(
        str(path),
        init_globals={
            "member": SimpleNamespace(
                active=True, email_verified=True, suspended=False, balance=0, borrowed_count=borrowed_count
            ),
            "book": SimpleNamespace(available=True, reference_only=reference_only),
        },
    )
    assert namespace["result"] is expected

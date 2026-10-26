from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys

import pytest

from sarj_python_lint.__main__ import check_source
from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules import REGISTRY


_RULE_ID = "no-excessive-cognitive-complexity"
_PATH = Path("app/decisions.py")


def _source(depth: int = 6, literal: str = "1", predicate: str = "True", *, unit: str = "    ") -> str:
    lines = ["def ready():", unit + "def _ready():"]
    lines.extend(unit * (index + 2) + f"if {predicate}:" for index in range(depth))
    lines.extend([unit * (depth + 2) + f"return {literal}", unit + "return _ready()"])
    return "\n".join(lines) + "\n"


def _expected(depth: int, literal: str, *, unit: str = "    ") -> str:
    return (
        "def ready():\n"
        + unit
        + "def _ready():\n"
        + "\n" * depth
        + unit * 2
        + f"return {literal}\n"
        + unit
        + "return _ready()\n"
    )


@pytest.mark.parametrize("depth", [pytest.param(6, id="native-score21"), pytest.param(12, id="native-score78")])
@pytest.mark.parametrize("ending", [pytest.param("\n", id="lf"), pytest.param("\r\n", id="crlf")])
@pytest.mark.parametrize(
    "literal",
    [
        pytest.param("True", id="boolean"),
        pytest.param("0x2A", id="authored-hexadecimal"),
        pytest.param("(0x2A)", id="parenthesized-literal"),
        pytest.param("'préservé 日本語'", id="unicode-string"),
        pytest.param("b'\\x41'", id="authored-bytes-escape"),
    ],
)
def test_redundant_constant_guards_preserve_exact_authored_return_lines_and_runtime(
    depth: int, ending: str, literal: str, tmp_path: Path
) -> None:
    source = _source(depth, literal).replace("\n", ending)
    rule = REGISTRY[_RULE_ID]()
    before = check_source([rule], _PATH, source)
    assert len(before) == 1
    assert before[0].code == "SARJ444"
    fixed = fix_source(_PATH, source, rule_ids=[_RULE_ID])
    assert fixed == _expected(depth, literal).replace("\n", ending)
    assert check_source([rule], _PATH, fixed) == []
    assert fix_source(_PATH, fixed, rule_ids=[_RULE_ID]) == fixed
    original_leaf = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant)
    )
    fixed_leaf = next(
        node
        for node in ast.walk(ast.parse(fixed))
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant)
    )
    assert original_leaf.lineno == fixed_leaf.lineno
    outputs: list[str] = []
    for filename, candidate in (("before.py", source), ("after.py", fixed)):
        path = tmp_path / filename
        path.write_bytes((candidate + "\nvalue = ready()\nprint(type(value).__name__, repr(value))\n").encode("utf-8"))
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize("unit", [pytest.param("    ", id="spaces"), pytest.param("\t", id="tabs")])
def test_depth_bound_and_authored_indentation_are_preserved(unit: str) -> None:
    source = _source(32, "1", unit=unit)
    assert fix_source(_PATH, source, rule_ids=[_RULE_ID]) == _expected(32, "1", unit=unit)
    too_deep = _source(33, "1", unit=unit)
    assert check_source([REGISTRY[_RULE_ID]()], _PATH, too_deep)
    assert fix_source(_PATH, too_deep, rule_ids=[_RULE_ID]) == too_deep


_REFUSALS = (
    pytest.param(_source(predicate="False"), id="false-guard"),
    pytest.param(_source(predicate="1"), id="truthy-integer-is-not-true-singleton"),
    pytest.param(_source(predicate="True is True"), id="nonliteral-predicate"),
    pytest.param(
        _source().replace("        if True:\n", "        if True:  # preserve reason\n", 1), id="guard-comment"
    ),
    pytest.param(_source().replace("return 1\n", "return 1  # preserve reason\n"), id="return-comment"),
    pytest.param(
        _source().replace("    def _ready():\n", "    def _ready():  # preserve reason\n"), id="function-comment"
    ),
    pytest.param(_source().replace("return 1\n", "return value\n"), id="nonliteral-result"),
    pytest.param(_source().replace("return 1\n", "return '''first\nsecond'''\n"), id="multiline-literal-return"),
    pytest.param(
        _source().replace("if True:\n                                return 1", "if True: return 1"),
        id="inline-return-physical-prefix",
    ),
    pytest.param(
        _source()
        .replace("    def _ready():\n", "    def ready_inner():\n")
        .replace("return _ready()", "return ready_inner()"),
        id="public-nested-helper",
    ),
    pytest.param(
        "def _ready():\n" + "\n".join(line[4:] for line in _source().splitlines()[2:-1]) + "\n", id="module-helper-api"
    ),
    pytest.param(_source().replace("    return _ready()\n", "    return _ready\n"), id="escaped-helper"),
    pytest.param(_source().replace("def ready():", "async def ready():"), id="async-ancestor"),
    pytest.param(_source().replace("    return _ready()", "    yield _ready()"), id="generator-ancestor"),
    pytest.param(
        _source()
        .replace("def ready():", "def ready(callback):")
        .replace("    return _ready()", "    callback()\n    return _ready()"),
        id="external-callback-observer",
    ),
    pytest.param(
        _source()
        .replace("def ready():", "def ready(value):")
        .replace("    return _ready()", "    value = None\n    return _ready()"),
        id="unknown-finalizer-observer",
    ),
    pytest.param(
        _source()
        .replace("def ready():", "def ready():\n    if False:\n        global watched")
        .replace("    return _ready()", "    watched = None\n    return _ready()"),
        id="dead-global-finalizer-boundary",
    ),
    pytest.param(_source().replace("    def _ready():", "    def _ready(value=None):"), id="parameterized-helper"),
    pytest.param(_source().replace("    def _ready():", "    def _ready[T]():"), id="helper-type-parameters"),
    pytest.param(
        _source()
        .replace("def ready():", "def ready(decorator):")
        .replace("    def _ready():", "    @decorator\n    def _ready():"),
        id="decorated-helper",
    ),
    pytest.param(
        "import sys\n" + _source().replace("    return _ready()", "    sys._getframe()\n    return _ready()"),
        id="frame-capability",
    ),
    pytest.param(
        _source().replace("    return _ready()", "    failure = 1 / 0\n    return _ready()"), id="reachable-error-frame"
    ),
    pytest.param(
        _source().replace("        if True:\n", "        pass\n        if True:\n", 1), id="additional-helper-statement"
    ),
    pytest.param(
        _source().replace(
            "                            if True:\n",
            "                            if True:\n                                pass\n",
            1,
        ),
        id="additional-nested-statement",
    ),
    pytest.param(_source().replace("\n", "\r"), id="unsupported-bare-cr"),
    pytest.param("DATA = 'before\u2028after'\n" + _source(), id="unsupported-nonphysical-separator"),
)


@pytest.mark.parametrize("source", _REFUSALS)
def test_other_complexity_and_observer_contracts_remain_unchanged(source: str) -> None:
    assert check_source([REGISTRY[_RULE_ID]()], _PATH, source)
    assert fix_source(_PATH, source, rule_ids=[_RULE_ID]) == source


def test_else_branch_and_trailing_source_are_retained_for_review() -> None:
    source = _source().replace("    return _ready()\n", "        else:\n            return 2\n    return _ready()\n")
    assert check_source([REGISTRY[_RULE_ID]()], _PATH, source)
    assert fix_source(_PATH, source, rule_ids=[_RULE_ID]) == source


def test_multiline_true_header_preserves_all_physical_lines_and_trailing_suffix() -> None:
    source = (
        _source()
        .replace("        if True:\n", "        if (\n            True\n        ):\n", 1)
        .replace("return 1\n", "return 1   \n")
    )
    fixed = fix_source(_PATH, source, rule_ids=[_RULE_ID])
    assert fixed != source
    assert fixed.count("\n") == source.count("\n")
    assert "        return 1   \n" in fixed
    assert fix_source(_PATH, fixed, rule_ids=[_RULE_ID]) == fixed


def test_outside_comment_and_missing_final_newline_are_preserved() -> None:
    source = _source().replace("    return _ready()\n", "    # preserve parent rationale\n    return _ready()")
    fixed = fix_source(_PATH, source, rule_ids=[_RULE_ID])
    assert fixed == _expected(6, "1").replace(
        "    return _ready()\n", "    # preserve parent rationale\n    return _ready()"
    )


@pytest.mark.parametrize(
    "rule_ids",
    [
        pytest.param([], id="excluded-selection"),
        pytest.param(["no-delete-statement"], id="other-selected-fixer"),
        pytest.param(["no-secret-in-log"], id="selected-rule-with-no-builder"),
    ],
)
def test_unselected_complexity_fix_never_runs(rule_ids: list[str]) -> None:
    source = _source()
    assert fix_source(_PATH, source, rule_ids=rule_ids) == source


def test_generated_and_suppressed_complexity_remain_unchanged() -> None:
    source = _source()
    assert fix_source(Path("generated/decisions.py"), source, rule_ids=[_RULE_ID]) == source
    suppressed = source.replace(
        "    def _ready():", "    def _ready():  # sarj-noqa: SARJ444 — deliberately visible decision tree"
    )
    assert fix_source(_PATH, suppressed, rule_ids=[_RULE_ID]) == suppressed
    assert fix_source(_PATH, source) == _expected(6, "1")


def test_external_callback_observes_guard_bytecode_and_requires_manual_review(tmp_path: Path) -> None:
    source = (
        _source()
        .replace("def ready():", "def ready(observer):")
        .replace("    return _ready()", "    observer()\n    return _ready()")
    )
    assert fix_source(_PATH, source, rule_ids=[_RULE_ID]) == source
    unsafe = (
        _expected(6, "1")
        .replace("def ready():", "def ready(observer):")
        .replace("    return _ready()", "    observer()\n    return _ready()")
    )
    oracle = (
        "\nimport dis\nimport sys\n"
        "def observer():\n"
        "    helper = sys._getframe(1).f_locals['_ready']\n"
        "    print(sum(instruction.opname == 'NOP' for instruction in dis.get_instructions(helper)))\n"
        "assert ready(observer) == 1\n"
    )
    values: list[str] = []
    for filename, candidate in (("before.py", source), ("unsafe.py", unsafe)):
        path = tmp_path / filename
        path.write_text(candidate + oracle)
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        values.append(result.stdout)
    assert values == ["6\n", "0\n"]


def test_native_complexity_threshold_retains_unreported_five_guard_helpers() -> None:
    source = _source(5, "1")
    assert check_source([REGISTRY[_RULE_ID]()], _PATH, source) == []
    assert fix_source(_PATH, source, rule_ids=[_RULE_ID]) == source


def test_deletion_and_complexity_fixes_share_a_convergent_combined_plan(tmp_path: Path) -> None:
    deleted = "    def _deleted():\n        unused = None\n        del unused\n        return 1\n"
    complex_body = "\n".join(_source(6, "2").splitlines()[1:-1]).replace("_ready", "_complex") + "\n"
    source = "def ready():\n" + deleted + complex_body + "    return _deleted(), _complex()\n"
    rule_ids = ["no-delete-statement", _RULE_ID]
    fixed = fix_source(_PATH, source, rule_ids=rule_ids)
    assert fixed != source
    assert check_source([REGISTRY[name]() for name in rule_ids], _PATH, fixed) == []
    assert fix_source(_PATH, fixed, rule_ids=rule_ids) == fixed
    assert fix_source(_PATH, source) == fixed
    for filename, candidate in (("before.py", source), ("after.py", fixed)):
        path = tmp_path / filename
        path.write_text(candidate + "\nprint(ready())\n")
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        assert result.stdout == "(1, 2)\n"

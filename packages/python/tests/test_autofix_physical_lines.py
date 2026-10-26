from __future__ import annotations

import ast
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from sarj_rule_contracts import RuleId

    from sarj_python_lint.rule_base import RuleExample


_SAFE_RULES = {
    rule_id
    for rule_id, rule in REGISTRY.items()
    if rule.documentation is not None and rule.documentation.autofix.value == "safe"
}
_FIXED_EXAMPLES = tuple(
    (rule_id, example)
    for rule_id, rule in sorted(REGISTRY.items())
    if rule.documentation is not None and rule.documentation.autofix.value == "safe"
    for example in rule.documentation.examples
    if example.fixed_files and example.focus_path.suffix == ".py"
)
_SEPARATORS = (
    pytest.param("\v", id="vertical-tab"),
    pytest.param("\f", id="form-feed"),
    pytest.param("\x1c", id="file-separator"),
    pytest.param("\x1d", id="group-separator"),
    pytest.param("\x1e", id="record-separator"),
    pytest.param("\x85", id="next-line"),
    pytest.param("\u2028", id="line-separator"),
    pytest.param("\u2029", id="paragraph-separator"),
)


@dataclass(frozen=True, slots=True)
class _ShadowSource:
    source: str
    prefix: str
    name: str


def test_every_safe_python_rule_has_a_fixed_example_in_the_separator_matrix() -> None:
    assert len(_SAFE_RULES) == 50
    assert {rule_id for rule_id, _ in _FIXED_EXAMPLES} == _SAFE_RULES


@pytest.mark.parametrize(
    ("rule_id", "example"),
    _FIXED_EXAMPLES,
    ids=[f"{rule_id}:{example.example_id}" for rule_id, example in _FIXED_EXAMPLES],
)
@pytest.mark.parametrize("separator", _SEPARATORS)
def test_every_safe_fixer_preserves_unrelated_quoted_shadow_source(
    rule_id: RuleId, example: RuleExample, separator: str
) -> None:
    path = Path(example.focus_path)
    case = _with_shadow_source(example.focus_file.source, separator)
    source = case.source
    compile(source, str(path), "exec", dont_inherit=True)
    before = REGISTRY[rule_id]().check(path, source)
    fixed = fix_source(path, source, rule_ids=[rule_id])
    assert case.prefix in fixed
    assert _data_value(fixed, case.name) == _data_value(source, case.name)
    compile(fixed, str(path), "exec", dont_inherit=True)
    assert len(REGISTRY[rule_id]().check(path, fixed)) <= len(before)
    assert fix_source(path, fixed, rule_ids=[rule_id]) == fixed
    assert fix_source(path, source, rule_ids=[]) == source


def _with_shadow_source(source: str, separator: str) -> _ShadowSource:
    tree = ast.parse(source)
    end_line = 0
    for index, statement in enumerate(tree.body):
        docstring = (
            index == 0
            and isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
        future = isinstance(statement, ast.ImportFrom) and statement.module == "__future__"
        if not docstring and not future:
            break
        end_line = statement.end_lineno or statement.lineno
    lines = StringIO(source, newline="").readlines()
    position = sum(map(len, lines[:end_line]))
    header, tail = source[:position], source[position:]
    if header and not header.endswith(("\r", "\n")):
        header += "\n"
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    name = "_SARJ_PHYSICAL_LINE_DATA"
    while name in names:
        name += "_"
    shadow = tail.replace("\r\n", "\n").replace("\r", "\n").replace("\n", separator)
    data = "sentinel" + separator + shadow + separator + "end"
    quoted = "'" + data.replace("\\", "\\\\").replace("'", "\\'") + "'"
    prefix = name + " = " + quoted + "\n"
    return _ShadowSource(header + prefix + tail, prefix, name)


def _data_value(source: str, name: str) -> str:
    for statement in ast.parse(source).body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == name
        ):
            assert isinstance(statement.value, ast.Constant)
            assert isinstance(statement.value.value, str)
            return statement.value.value
    raise AssertionError

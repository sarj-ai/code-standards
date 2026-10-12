from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sarj_rule_contracts import RuleId

from sarj_python_lint.__main__ import check_source
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rules import REGISTRY


_RULES = (
    "complex-postgres-query-requires-architecture-review",
    "no-analytical-aggregation-in-postgres-store",
    "no-offset-pagination",
)


def test_docstring_ids_are_lazy_immutable_and_file_local() -> None:
    source = (
        '"module documentation"\n'
        'later = "ordinary string"\n'
        'class Record:\n    "class documentation"\n    "later expression"\n'
        '    def get(self):\n        "method documentation"\n        return "result"\n'
        'async def load():\n    "async documentation"\n    return None\n'
        'def not_documented():\n    42\n    "later function expression"\n'
    )
    context = PythonFileContext(Path("app.py"), source)
    assert "tree" not in vars(context)
    assert "docstring_node_ids" not in vars(context)
    result = context.docstring_node_ids
    constants = {node.value: id(node) for node in context.nodes(ast.Constant) if isinstance(node.value, str)}
    assert result == frozenset(
        constants[value]
        for value in ("module documentation", "class documentation", "method documentation", "async documentation")
    )
    assert isinstance(result, frozenset)
    assert context.docstring_node_ids is result
    assert result.isdisjoint(PythonFileContext(Path("app.py"), source).docstring_node_ids)


def test_docstring_ids_require_a_valid_tree_without_poisoning_later_files() -> None:
    with pytest.raises(ValueError, match="successfully parsed"):
        _ = PythonFileContext(Path("app.py"), "def broken(:").docstring_node_ids
    assert PythonFileContext(Path("app.py"), "value = 1\n").docstring_node_ids == frozenset()


@pytest.mark.parametrize("rule_id", _RULES)
def test_shared_docstring_exclusions_preserve_standalone_and_rule_order(rule_id: str) -> None:
    rules = [REGISTRY[RuleId(key)]() for key in _RULES]
    hits = 0
    for example in REGISTRY[RuleId(rule_id)].public_examples():
        path = Path(example.focus_path)
        source = example.focus_file.source
        separate = sorted(finding.format() for rule in rules for finding in rule.check(path, source))
        forward = sorted(finding.format() for finding in check_source(rules, path, source))
        reverse = sorted(finding.format() for finding in check_source(list(reversed(rules)), path, source))
        assert forward == reverse == separate
        hits += len(forward)
    assert hits > 0

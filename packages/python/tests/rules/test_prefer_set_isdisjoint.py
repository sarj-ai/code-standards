from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_set_isdisjoint import PreferSetIsdisjoint


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/policy.py") -> list[Diagnostic]:
    return PreferSetIsdisjoint().check(Path(path), textwrap.dedent(source))


@pytest.mark.parametrize(
    "example",
    PreferSetIsdisjoint.public_examples(),
    ids=tuple(example.example_id for example in PreferSetIsdisjoint.public_examples()),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


@pytest.mark.parametrize(
    "source",
    [
        "if not ({1, 2} & {3}):\n    pass",
        "if {1, 2} & {3}:\n    pass",
        "if not {1, 2}.intersection({3}):\n    pass",
        "left = set(values)\nright = frozenset(other)\nassert left & right",
        "left = {value for value in values}\nright = set(other)\nif left.intersection(right):\n    pass",
        "left = set(values)\nitems = [x for x in rows if left & {x}]",
    ],
)
def test_flags_boolean_only_builtin_intersections(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "def overlap(left: set[int], right: set[int]):\n    return bool(left & right)",
        "left: set[int] = load()\nif left & {1}:\n    pass",
        "result = {1} & {2}",
        "if custom.intersection(values):\n    pass",
        "if {1}.intersection(values):\n    pass",
        "if {1}.intersection(a, b):\n    pass",
        "set = custom_factory\nleft = set(values)\nif left & {1}:\n    pass",
        "left = set(values)\nleft = load()\nif left & {1}:\n    pass",
    ],
)
def test_rejects_unproven_or_value_producing_intersections(source: str) -> None:
    assert _check(source) == []


def test_branch_assignment_does_not_escape_as_exact_type_proof() -> None:
    source = "if condition:\n    left = set(values)\nif left & {1}:\n    pass"
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "left = set(values)\n(left := custom)\nif left & {1}:\n    pass",
        "left = set(values)\nimport custom as left\nif left & {1}:\n    pass",
        "left = set(values)\nwith manager() as left:\n    if left & {1}:\n        pass",
        "left = set(values)\ntry:\n    pass\nexcept Error as left:\n    if left & {1}:\n        pass",
        "left = set(values)\nitems = [x for left in rows if left & {1}]",
        "left = set(values)\npredicate = lambda left: 1 if left & {1} else 0",
        "left = set(values)\nif (left := custom) and left & {1}:\n    pass",
        "left = set(values)\nwhile left & {1}:\n    left = custom",
    ],
)
def test_rejects_scope_and_rebinding_false_positives(source: str) -> None:
    assert _check(source) == []


def test_honors_exact_suppression() -> None:
    source = "left = set(values)\nif left & {1}:  # sarj-noqa: SARJ431\n    pass"
    assert _check(source) == []


def test_skips_generated_and_malformed_files() -> None:
    assert _check("if {1} & {2}:\n    pass", "generated/client.py") == []
    assert _check("if {1} &") == []

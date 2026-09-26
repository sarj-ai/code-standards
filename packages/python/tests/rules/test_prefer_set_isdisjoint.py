from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules._project_index import ProjectIndexSet
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
        'if ready and bool({"retry_settings", "calling_window"} & updates.keys()):\n    refresh()',
        "if not bool({1, 2} & tuple(values)):\n    pass",
        "if {1, 2} & {key: value for key, value in rows}:\n    pass",
        "if {1, 2} & (value for value in values):\n    pass",
        "if {1}.intersection(values):\n    pass",
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
        "if {1}.intersection(a, b):\n    pass",
        "set = custom_factory\nleft = set(values)\nif left & {1}:\n    pass",
        "left = set(values)\nleft = load()\nif left & {1}:\n    pass",
        "if not bool({1, 2} & values):\n    pass",
        "tuple = custom_factory\nif {1} & tuple(values):\n    pass",
    ],
)
def test_rejects_unproven_or_value_producing_intersections(source: str) -> None:
    assert _check(source) == []


def test_branch_assignment_does_not_escape_as_exact_type_proof() -> None:
    source = "if condition:\n    left = set(values)\nif left & {1}:\n    pass"
    assert _check(source) == []


def test_reflected_and_without_iteration_is_not_reported() -> None:
    source = "class Right:\n    def __rand__(self, left):\n        return {1}\n\nif {1} & Right():\n    pass"
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


@pytest.mark.parametrize(
    "source",
    [
        "bool = custom_predicate\nif bool({1} & values):\n    pass",
        "def check(bool, values):\n    if bool({1} & values):\n        pass",
        "from policy import predicate as bool\nif bool({1} & values):\n    pass",
    ],
)
def test_shadowed_bool_wrapper_is_clean(source: str) -> None:
    assert _check(source) == []


def test_honors_exact_suppression() -> None:
    source = "left = set(values)\nif left & {1}:  # sarj-noqa: SARJ431\n    pass"
    assert _check(source) == []


def test_skips_generated_and_malformed_files() -> None:
    assert _check("if {1} & {2}:\n    pass", "generated/client.py") == []
    assert _check("if {1} &") == []


@pytest.mark.parametrize("annotation", ["set[str]", "frozenset[str]"])
def test_declared_set_field_overlap(annotation: str) -> None:
    source = f"class Case:\n    tags: {annotation}\ndef accepts(case: Case):\n    if ready:\n        pass\n    elif case.tags & {{'inbound', 'audio'}}:\n        return True\n"
    findings = _check(source)
    assert len(findings) == 1
    assert "not left.isdisjoint(right)" in findings[0].message
    assert (
        _check(source.replace("case.tags & {'inbound', 'audio'}", "not case.tags.isdisjoint({'inbound', 'audio'})"))
        == []
    )


@pytest.mark.parametrize(
    "change",
    [
        "unknown-type",
        "integer-field",
        "union-field",
        "rebound-owner",
        "overwritten-field",
        "shadowed-set",
        "property-field",
    ],
)
def test_set_field_near_misses(change: str) -> None:
    source = "class Case:\n    tags: set[str]\ndef accepts(case: Case):\n    if case.tags & {'inbound'}:\n        return True\n"
    match change:
        case "unknown-type":
            source = source.replace("case: Case", "case")
        case "integer-field":
            source = source.replace("set[str]", "int")
        case "union-field":
            source = source.replace("set[str]", "set[str] | Custom")
        case "rebound-owner":
            source = source.replace("    if case.tags", "    case = custom\n    if case.tags")
        case "overwritten-field":
            source = source.replace("    if case.tags", "    case.tags = custom\n    if case.tags")
        case "shadowed-set":
            source = "set = Custom\n" + source
        case _:
            source = source.replace(
                "    tags: set[str]", "    tags: set[str]\n    @property\n    def tags(self): return custom"
            )
    assert _check(source) == []


def test_imported_set_field_type(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='sample'\nversion='0.1.0'\n")
    (tmp_path / "models.py").write_text("class Case:\n    tags: frozenset[str]\n")
    path = tmp_path / "policy.py"
    source = "from models import Case as Scenario\ndef accepts(case: Scenario):\n    return 1 if case.tags & {'inbound'} else 0\n"
    path.write_text(source)
    rule = PreferSetIsdisjoint()
    rule.prepare(ProjectIndexSet.build([path], {path: source}))
    assert len(rule.check(path, source)) == 1


@pytest.mark.parametrize(
    "insertion",
    [
        "    predicate = lambda case: bool(case.tags & {'inbound'})\n",
        "    def case(): pass\n",
        "    match value:\n        case {**case}: pass\n",
    ],
)
def test_nested_field_owner_shadowing(insertion: str) -> None:
    source = (
        "class Case:\n    tags: set[str]\ndef accepts(case: Case):\n"
        + insertion
        + "    if case.tags & {'inbound'}:\n        pass\n"
    )
    assert _check(source) == []


def test_class_local_collection_type_is_not_builtin() -> None:
    assert (
        _check(
            "class Case:\n    set = Custom\n    tags: set[str]\ndef accepts(case: Case):\n    if case.tags & {'inbound'}:\n        pass\n"
        )
        == []
    )


def test_rebound_owner_type_is_not_inferred() -> None:
    assert (
        _check(
            "class Case:\n    tags: set[str]\nCase = Custom\ndef accepts(case: Case):\n    if case.tags & {'inbound'}:\n        pass\n"
        )
        == []
    )

from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.prefer_set_isdisjoint import PreferSetIsdisjoint


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/policy.py") -> list[Diagnostic]:
    return PreferSetIsdisjoint().check(Path(path), textwrap.dedent(source))


def test_boolean_set_intersection_is_blocking() -> None:
    assert PreferSetIsdisjoint.documentation is not None
    assert PreferSetIsdisjoint.documentation.default_level is Severity.ERROR


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
        "def overlap(left: frozenset[int]):\n    return bool(left & {1})",
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


@pytest.mark.parametrize(
    "source",
    [
        "if {'a': 1}.keys() & {'a'}:\n    pass",
        "if not dict(a=1).keys() & {'a'}:\n    pass",
        "payload = {'a': 1}\nif payload.keys() & {'a'}:\n    pass",
        "def check():\n    payload: dict[str, int] = dict(a=1)\n    if payload.keys() & {'a'}:\n        pass",
        "payload = {key: value for key, value in rows}\nassert payload.keys() & {'a'}",
    ],
)
def test_dict_key_view_boolean_intersection(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "def check(payload: dict):\n    if payload.keys() & {'a'}:\n        pass",
        "payload = custom()\nif payload.keys() & {'a'}:\n    pass",
        "payload = {}\npayload = custom()\nif payload.keys() & {'a'}:\n    pass",
        "if ready:\n    payload = {}\nif payload.keys() & {'a'}:\n    pass",
        "payload = {}\nresult = payload.keys() & {'a'}",
        "payload = {}\nif payload.items() & {('a', 1)}:\n    pass",
        "payload = {}\nif payload.values() & {1}:\n    pass",
        "dict = custom\nif dict().keys() & {'a'}:\n    pass",
        "def dict():\n    return custom\nif dict().keys() & {'a'}:\n    pass",
        "from custom import *\nif dict().keys() & {'a'}:\n    pass",
        "try:\n    work()\nexcept Error as dict:\n    if dict().keys() & {'a'}:\n        pass",
        "match custom:\n    case dict:\n        if dict().keys() & {'a'}:\n            pass",
        "payload = {}\nmatch other:\n    case {**payload}:\n        if payload.keys() & {'a'}:\n            pass",
        "payload = {}\nresults = [x for payload in rows if payload.keys() & {'a'}]",
        "payload = {}\ncheck = lambda payload: 1 if payload.keys() & {'a'} else 0",
        "payload = {}\ntry:\n    pass\nexcept Error as payload:\n    if payload.keys() & {'a'}:\n        pass",
        "payload = {}\ndef check():\n    if payload.keys() & {'a'}:\n        pass",
        "payload = {}\nif (payload := custom()).keys() & {'a'}:\n    pass",
        "payload = {}\nif payload.keys() & {'a'}:  # sarj-noqa: SARJ431\n    pass",
    ],
)
def test_dict_key_view_exclusions(source: str) -> None:
    assert _check(source) == []


_BOOLEAN_CONTEXT_CASES = (
    EvaluationCase("assignment", Language.PYTHON, "overlap = bool({1} & {2})", ExpectedOutcome.MATCH),
    EvaluationCase("annotated-assignment", Language.PYTHON, "overlap: bool = bool({1} & {2})", ExpectedOutcome.MATCH),
    EvaluationCase("return", Language.PYTHON, "def overlap():\n    return bool({1} & {2})", ExpectedOutcome.MATCH),
    EvaluationCase(
        "boolean-value", Language.PYTHON, "overlap = bool({1}.intersection({2})) or ready", ExpectedOutcome.MATCH
    ),
    EvaluationCase("lambda", Language.PYTHON, "predicate = lambda: bool({1} & {2})", ExpectedOutcome.MATCH),
    EvaluationCase(
        "generator-literal", Language.PYTHON, "checks = (bool({1} & {2}) for row in rows)", ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "generator-eager-iterable",
        Language.PYTHON,
        "tags = {'read'}\nchecks = (row for row in choose(bool(tags & {'read'})))",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("existing-condition-once", Language.PYTHON, "if bool({1} & {2}):\n    pass", ExpectedOutcome.MATCH),
)


@pytest.mark.parametrize("case", _BOOLEAN_CONTEXT_CASES, ids=tuple(case.case_id for case in _BOOLEAN_CONTEXT_CASES))
def test_explicit_bool_consumes_intersection_in_value_context(case: EvaluationCase) -> None:
    assert len(_check(case.source)) == 1


def test_negated_bool_value_suggests_disjoint_predicate() -> None:
    findings = _check("disjoint = not bool({1} & {2})")
    assert len(findings) == 1
    assert "use `left.isdisjoint(right)`" in findings[0].message


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("value = {1} & {2}", id="stored-set"),
        pytest.param("def values():\n    return {1} & {2}", id="returned-set"),
        pytest.param("def check(bool):\n    return bool({1} & {2})", id="shadowed-bool"),
        pytest.param("def check(tags):\n    return bool(tags & {'read'})", id="unknown-parameter"),
        pytest.param("def check(tags: int):\n    return bool(tags & 1)", id="integer-mask"),
        pytest.param("def check(tags: CustomSet):\n    return bool(tags & {'read'})", id="custom-set"),
        pytest.param("def check(tags: set[str] | Custom):\n    return bool(tags & {'read'})", id="union"),
        pytest.param("tags = {'read'}\ntags = custom\nresult = bool(tags & {'read'})", id="rebound"),
        pytest.param("set = Custom\ntags = set()\nresult = bool(tags & {'read'})", id="shadowed-set"),
        pytest.param(
            "class Owner:\n    bool = predicate\n    overlap = bool({'read'} & {'write'})",
            id="class-shadow",
        ),
        pytest.param("tags = {'read'}\nresult = [bool(tags & {'read'}) for tags in rows]", id="comprehension-shadow"),
        pytest.param("tags = {'read'}\npredicate = lambda tags: bool(tags & {'read'})", id="lambda-shadow"),
        pytest.param("tags = {'read'}\nresult = bool((tags := custom) & {'read'})", id="walrus-rebound"),
        pytest.param(
            "tags = {'read'}\nresult = ((tags := custom), bool(tags & {'read'}))", id="walrus-before-tuple-item"
        ),
        pytest.param(
            "tags = {'read'}\nconsume((tags := custom), bool(tags & {'read'}))", id="walrus-before-call-argument"
        ),
        pytest.param("tags = {'read'}\nresult = (tags := custom) or bool(tags & {'read'})", id="walrus-before-bool-op"),
        pytest.param(
            "tags = {'read'}\nif (tags := custom) or bool(tags & {'read'}):\n    pass", id="walrus-before-condition"
        ),
        pytest.param(
            "tags = {'read'}\npredicate = lambda: bool(tags & {'read'})\ntags = custom\nresult = predicate()",
            id="deferred-lambda-binding",
        ),
        pytest.param(
            "tags = {'read'}\nchecks = (bool(tags & {'read'}) for row in rows)\ntags = custom\nresult = list(checks)",
            id="deferred-generator-binding",
        ),
        pytest.param(
            "tags = {'read'}\nchecks = (row for row in rows if bool(tags & {'read'}))\ntags = custom\nresult = list(checks)",
            id="deferred-generator-filter",
        ),
        pytest.param(
            "tags = {'read'}\nif (tags := custom):\n    result = bool(tags & {'read'})", id="walrus-if-header"
        ),
        pytest.param(
            "tags = {'read'}\nfor row in (tags := custom):\n    result = bool(tags & {'read'})", id="walrus-for-header"
        ),
        pytest.param(
            "tags = {'read'}\nwith manager(tags := custom):\n    result = bool(tags & {'read'})",
            id="walrus-with-header",
        ),
        pytest.param("result = bool({1}.intersection(*operands))", id="starred-intersection-value"),
        pytest.param("if {1}.intersection(*operands):\n    pass", id="starred-intersection-condition"),
        pytest.param(
            "tags = {'read'}\nwith make_custom() as tags, choose(bool(tags & {'read'})):\n    pass",
            id="with-earlier-binding",
        ),
        pytest.param(
            "tags = {'read'}\nfor row in rows:\n    result = bool(tags & {'read'})\n    tags = custom",
            id="for-later-iteration",
        ),
        pytest.param(
            "tags = {'read'}\nwhile ready:\n    result = bool(tags & {'read'})\n    tags = custom",
            id="while-later-iteration",
        ),
        pytest.param(
            "tags = {'read'}\ntry:\n    tags = custom\n    fail()\nexcept Error:\n    result = bool(tags & {'read'})",
            id="except-after-rebinding",
        ),
        pytest.param(
            "tags = {'read'}\ntry:\n    tags = custom\nfinally:\n    result = bool(tags & {'read'})",
            id="finally-after-rebinding",
        ),
        pytest.param(
            "tags = {'read'}\ntry:\n    tags = custom\nexcept Error:\n    pass\nelse:\n    result = bool(tags & {'read'})",
            id="else-after-rebinding",
        ),
    ],
)
def test_explicit_bool_contract_near_misses(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "binding",
    [
        pytest.param("import module as tags", id="import"),
        pytest.param("from module import custom as tags", id="from-import"),
        pytest.param("from module import *", id="star-import"),
        pytest.param("class tags:\n    pass", id="class"),
        pytest.param("def tags():\n    pass", id="function"),
        pytest.param("try:\n    fail()\nexcept Error as tags:\n    pass", id="exception"),
        pytest.param("match value:\n    case tags:\n        pass", id="match-capture"),
        pytest.param("match value:\n    case [*tags]:\n        pass", id="match-star"),
        pytest.param("match value:\n    case {'key': item, **tags}:\n        pass", id="match-mapping"),
        pytest.param("del tags", id="delete"),
    ],
)
def test_compound_binding_forms_discard_set_proof(binding: str) -> None:
    source = "tags = {'read'}\ntry:\n" + textwrap.indent(binding, "    ")
    source += "\nfinally:\n    result = bool(tags & {'read'})"
    assert _check(source) == []


def test_imported_declared_field_inside_bool_assignment(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='sample'\nversion='0.1.0'\n")
    (tmp_path / "models.py").write_text("class Case:\n    tags: frozenset[str]\n")
    path = tmp_path / "policy.py"
    source = (
        "from models import Case\n"
        "def accepts(case: Case):\n"
        "    checks_access = bool(case.tags & {'read', 'write'}) or ready\n"
        "    return checks_access\n"
    )
    path.write_text(source)
    rule = PreferSetIsdisjoint()
    rule.prepare(ProjectIndexSet.build([path], {path: source}))
    assert len(rule.check(path, source)) == 1

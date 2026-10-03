from pathlib import Path
from textwrap import dedent

import pytest

from sarj_python_lint.rule_base import AutofixPolicy, RuleExample, Severity
from sarj_python_lint.rules.prefer_immutable_module_constant import PreferImmutableModuleConstant
from tests.illustrative_examples import illustrative_examples


@pytest.mark.parametrize(
    ("source", "replacement"),
    [
        pytest.param("VALUES = [1, 2, 3]", "tuple", id="list"),
        pytest.param("KINDS = {'a', 'b'}", "frozenset", id="set"),
        pytest.param("VALUES = list(runtime_values)", "tuple", id="populated-list-constructor"),
        pytest.param("KINDS = set(runtime_values)", "frozenset", id="populated-set-constructor"),
        pytest.param("LABELS = dict(runtime_items)", "Final", id="populated-dict-constructor"),
        pytest.param("_VALUES = [1, 2, 3]", "tuple", id="private-constant"),
        pytest.param("X = [1, 2, 3]", "tuple", id="single-letter-constant"),
        pytest.param("VALUES = [runtime_value]", "tuple", id="dynamic-list-element"),
        pytest.param("LABELS = {'value': runtime_value}", "Final", id="dynamic-dict-value"),
        pytest.param("VALUES = [value for value in runtime_values]", "tuple", id="list-comprehension"),
        pytest.param("KINDS = {value for value in runtime_values}", "frozenset", id="set-comprehension"),
        pytest.param(
            "LABELS = {value.code: value for value in runtime_values}",
            "Final",
            id="dict-comprehension",
        ),
        pytest.param("VALUES = [*runtime_values]", "tuple", id="dynamic-list-spread"),
        pytest.param("VALUES = [1]\ndef mutate(VALUES):\n    VALUES.append(1)", "tuple", id="parameter-shadow"),
        pytest.param("VALUES = [1]\ndef mutate():\n    VALUES = []\n    VALUES.append(1)", "tuple", id="local-shadow"),
        pytest.param("VALUES = [1]\ntuple({'values': VALUES})", "tuple", id="nested-inside-safe-call"),
        pytest.param(
            "VALUES = [1]\nconsume([value for value in VALUES])",
            "tuple",
            id="comprehension-copies-elements",
        ),
        pytest.param("VALUES = [1]\nconsume({'first': VALUES[0]})", "tuple", id="element-only-escapes"),
        pytest.param("KINDS = {'a'}\nconsume(*KINDS)", "frozenset", id="star-expands-elements"),
    ],
)
def test_warns_for_literal_mutable_module_constants(source: str, replacement: str) -> None:
    findings = PreferImmutableModuleConstant().check(Path("service.py"), source)

    assert len(findings) == 1
    assert findings[0].code == "SARJ096"
    assert findings[0].severity is Severity.WARNING
    assert replacement in findings[0].message


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("from typing import Final\nLABELS: Final = {'a': 'A'}", id="bare"),
        pytest.param("from typing import Final\nLABELS: Final[dict[str, str]] = {'a': 'A'}", id="typed"),
        pytest.param("from typing import Final as F\nLABELS: F[dict[str, str]] = {'a': 'A'}", id="alias"),
        pytest.param("import typing\nLABELS: typing.Final = {'a': 'A'}", id="qualified"),
        pytest.param("import typing as t\nLABELS: t.Final[dict[str, str]] = {'a': 'A'}", id="module-alias"),
        pytest.param("from typing_extensions import Final\nLABELS: Final = {'a': 'A'}", id="extensions"),
        pytest.param("import typing_extensions as t\nLABELS: t.Final = {'a': 'A'}", id="extensions-module-alias"),
        pytest.param("from typing import Final\nLABELS: 'Final[dict[str, str]]' = {'a': 'A'}", id="quoted"),
        pytest.param("import typing as t\nLABELS: 't.Final' = {'a': 'A'}", id="quoted-module-alias"),
        pytest.param("from typing import Final, Mapping\nLABELS: Final[Mapping[str, str]] = {'a': 'A'}", id="mapping"),
        pytest.param(
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from typing import Final\n"
            "LABELS: Final = {'a': 'A'}",
            id="type-only-import",
        ),
        pytest.param(
            "from typing import Final\ndef unrelated(Final):\n    return Final\nLABELS: Final = {'a': 'A'}",
            id="parameter-shadow",
        ),
        pytest.param(
            "from typing import Final\ndef unrelated():\n    Final = object()\nLABELS: Final = {'a': 'A'}",
            id="local-shadow",
        ),
    ],
)
def test_accepts_final_dictionary_bindings(source: str) -> None:
    assert PreferImmutableModuleConstant().check(Path("service.py"), source) == []


@pytest.mark.parametrize("value", ["{'a': 'A'}", "dict(runtime_items)", "{key: value for key, value in runtime_items}"])
def test_final_dictionary_expressions_are_accepted(value: str) -> None:
    source = f"from typing import Final\nLABELS: Final[dict[str, str]] = {value}"
    assert PreferImmutableModuleConstant().check(Path("service.py"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("LABELS: Final = {'a': 'A'}", id="unimported"),
        pytest.param("from custom import Final\nLABELS: Final = {'a': 'A'}", id="unrelated-import"),
        pytest.param("from typing import Final\nFinal = Custom\nLABELS: Final = {'a': 'A'}", id="rebound"),
        pytest.param("import typing as t\nt = Custom\nLABELS: t.Final = {'a': 'A'}", id="rebound-module"),
        pytest.param("def unrelated():\n    from typing import Final\nLABELS: Final = {'a': 'A'}", id="nested-import"),
        pytest.param("from typing import final\nLABELS: final = {'a': 'A'}", id="decorator"),
        pytest.param("from typing import Final\nLABELS: dict[str, Final[str]] = {'a': 'A'}", id="nested-final"),
        pytest.param("from typing import Final\nLABELS: Final[str, str] = {'a': 'A'}", id="multiple-arguments"),
        pytest.param("from typing import Final\nLABELS: 'Final[' = {'a': 'A'}", id="malformed-string"),
        pytest.param("from typing import Final\nLABELS: Final[dict] | None = {'a': 'A'}", id="union"),
        pytest.param(
            "from typing import Annotated, Final\nLABELS: Annotated[dict, Final] = {'a': 'A'}",
            id="metadata",
        ),
        pytest.param(
            "from typing import Final\nOTHER = (Final := Custom)\nLABELS: Final = {'a': 'A'}",
            id="walrus-shadow",
        ),
        pytest.param(
            "from typing import Final\ntry:\n    run()\nexcept Exception as Final:\n    pass\n"
            "LABELS: Final = {'a': 'A'}",
            id="exception-shadow",
        ),
        pytest.param(
            "from typing import Final\nmatch value:\n    case {'value': Final}:\n        pass\n"
            "LABELS: Final = {'a': 'A'}",
            id="pattern-shadow",
        ),
        pytest.param("LABELS: dict[str, str] = {'a': 'A'}", id="plain-dict-annotation"),
        pytest.param("from typing import Mapping\nLABELS: Mapping[str, str] = {'a': 'A'}", id="plain-mapping"),
    ],
)
def test_final_lookalikes_do_not_hide_dictionary_findings(source: str) -> None:
    findings = PreferImmutableModuleConstant().check(Path("service.py"), source)
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert "Final[dict" in findings[0].message
    assert "does not freeze" in findings[0].message


@pytest.mark.parametrize(("value", "replacement"), [("[1, 2]", "tuple"), ("{1, 2}", "frozenset")])
def test_final_does_not_replace_native_immutable_collections(value: str, replacement: str) -> None:
    source = f"from typing import Final\nVALUES: Final = {value}"
    findings = PreferImmutableModuleConstant().check(Path("service.py"), source)
    assert len(findings) == 1
    assert replacement in findings[0].message


def test_runtime_immutable_mapping_remains_accepted() -> None:
    source = "from types import MappingProxyType\nLABELS = MappingProxyType({'a': 'A'})"
    assert PreferImmutableModuleConstant().check(Path("service.py"), source) == []


def test_rule_retains_warning_and_no_autofix_policy() -> None:
    documentation = PreferImmutableModuleConstant.documentation
    assert documentation is not None
    assert documentation.default_level is Severity.WARNING
    assert documentation.autofix is AutofixPolicy.NONE


@illustrative_examples(PreferImmutableModuleConstant)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file

    findings = PreferImmutableModuleConstant().check(Path(focus.path), focus.source)

    assert len(findings) == example.expected_count


@pytest.mark.parametrize(
    "source",
    [
        "VALUES = (1, 2, 3)",
        "KINDS = frozenset({'a', 'b'})",
        "VALUES = []",
        "LABELS: dict = {}",
        "VALUES = list()",
        "LABELS = dict()",
        "KINDS = set()",
        "labels = {'a': 'A'}",
        "__all__ = ['public']",
        "VALUES = {'a'}\nVALUES.add('b')",
        "VALUES = {'a'}\nVALUES.difference_update({'b'})",
        "VALUES = [1]\nVALUES += [2]",
        "VALUES = [1]\nVALUES = [2]",
        "LABELS = {}\nLABELS['a'] = 'A'",
        "VALUES = [1]\ndef reset():\n    global VALUES\n    VALUES = []",
        "LABELS = {'a': []}\nLABELS['a'].append('A')",
        "LABELS = {'a': {'b': 'B'}}\nLABELS['a']['b'] = 'C'",
        "BG_TASKS = set()\nservice = Service(bg_tasks=BG_TASKS)",
        "BG_TASKS = {'task'}\ndef install(task):\n    task.add_done_callback(BG_TASKS.discard)",
        "VALUES = (value for value in runtime_values)",
        "VALUES = [value for value in runtime_values]\nVALUES.append(extra)",
        "KINDS = {value for value in runtime_values}\nKINDS.update(extra)",
        "LABELS = {value.code: value for value in runtime_values}\nconsume(LABELS)",
    ],
)
def test_ignores_immutable_dynamic_nonconstant_and_intentionally_mutated_values(source: str) -> None:
    assert PreferImmutableModuleConstant().check(Path("service.py"), source) == []


def test_ignores_test_and_generated_files() -> None:
    source = dedent("""\
        # generated by schema compiler
        VALUES = [1, 2, 3]
        """)

    rule = PreferImmutableModuleConstant()
    assert rule.check(Path("tests/test_service.py"), "VALUES = [1, 2, 3]") == []
    assert rule.check(Path("generated.py"), source) == []
    assert rule.check(Path("common/testing/builders.py"), "VALUES = [1, 2, 3]") == []


def test_generated_module_docstring_is_clean() -> None:
    source = '"""This file is generated. Do not edit it by hand."""\nMODULES = {"x": 1}\n'
    assert PreferImmutableModuleConstant().check(Path("builtins.py"), source) == []


def test_incidental_generate_and_do_not_edit_prose_is_not_treated_as_generated() -> None:
    source = '"""Generate reports; do not edit runtime state."""\nVALUES = [1]\n'
    assert len(PreferImmutableModuleConstant().check(Path("reports.py"), source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "VALUES = [1]\ndef mutate():\n    alias = VALUES\n    alias.append(2)",
        "VALUES = [1]\ndef mutate():\n    append = VALUES.append\n    append(2)",
        "VALUES = [1]\ndef mutate():\n    first, alias = (object(), VALUES)\n    alias.append(2)",
        "VALUES = [1]\ndef mutate():\n    VALUES.__setitem__(0, 2)",
        "VALUES = [1]\ndef snapshot():\n    return VALUES.copy()",
    ],
    ids=["direct-alias", "bound-mutator", "unpacked-alias", "dunder-mutation", "copy-api"],
)
def test_alias_mutation_and_concrete_collection_apis_are_clean(source: str) -> None:
    assert PreferImmutableModuleConstant().check(Path("service.py"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        "VALUES = [1]\nAPPEND = VALUES.append",
        "VALUES = [1]\ndef callback():\n    return VALUES.append",
        "VALUES = [1]\ndef callback(append=VALUES.append):\n    return append",
    ],
    ids=["module-alias", "return", "default"],
)
def test_exported_bound_mutator_preserves_concrete_collection_contract(source: str) -> None:
    assert PreferImmutableModuleConstant().check(Path("service.py"), source) == []


def test_unrelated_bound_mutator_does_not_hide_module_finding() -> None:
    source = "VALUES = [1]\nAPPEND = unrelated.append"
    assert len(PreferImmutableModuleConstant().check(Path("service.py"), source)) == 1


def test_mutating_independent_local_copy_does_not_hide_module_finding() -> None:
    source = "VALUES = [1]\ndef mutate():\n    local = list(VALUES)\n    local.append(2)"
    assert len(PreferImmutableModuleConstant().check(Path("service.py"), source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "VALUES = [[1], [2]]\ndef mutate():\n    first, second = VALUES\n    first.append(3)",
        "LABELS = {'a': 'A'}\ndef render():\n    label = LABELS['a']\n    consume(label)",
        "VALUES = [1]\ndef use():\n    unrelated, alias = (lambda: None, VALUES)\n    unrelated()",
    ],
    ids=["nested-element-mutation", "mapping-scalar-consumer", "unrelated-positional-element"],
)
def test_extracted_elements_do_not_hide_module_finding(source: str) -> None:
    assert len(PreferImmutableModuleConstant().check(Path("service.py"), source)) == 1


def test_positional_destructuring_tracks_whole_collection_alias() -> None:
    source = "VALUES = [1]\ndef mutate():\n    unrelated, alias = (lambda: None, VALUES)\n    alias.append(2)"
    assert PreferImmutableModuleConstant().check(Path("service.py"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        "VALUES = [1]\ndef mutate():\n    alias, *rest = (VALUES, object())\n    alias.append(2)",
        "VALUES = [1]\ndef mutate():\n    *rest, alias = (object(), VALUES)\n    alias.append(2)",
    ],
    ids=["fixed-prefix", "fixed-suffix"],
)
def test_starred_destructuring_tracks_fixed_whole_collection_alias(source: str) -> None:
    assert PreferImmutableModuleConstant().check(Path("service.py"), source) == []


def test_starred_capture_conservatively_exempts_nested_whole_collection() -> None:
    source = "VALUES = [1]\ndef mutate():\n    first, *rest = (object(), VALUES)\n    rest[0].append(2)"
    assert PreferImmutableModuleConstant().check(Path("service.py"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        "def tuple(value):\n    value.append(2)\nVALUES = [1]\ntuple(VALUES)",
        "VALUES = [1]\ndef mutate(tuple):\n    tuple(VALUES)",
    ],
    ids=["module-function", "function-parameter"],
)
def test_shadowed_non_escaping_builtin_can_receive_mutable_constant(source: str) -> None:
    assert PreferImmutableModuleConstant().check(Path("service.py"), source) == []


@pytest.mark.parametrize(
    "source",
    ["VALUES = [1]\nconsume(VALUES[0])", "VALUES = [1]\nconsume(VALUES[:])"],
    ids=["element", "slice"],
)
def test_passing_subscript_does_not_hide_module_finding(source: str) -> None:
    assert len(PreferImmutableModuleConstant().check(Path("service.py"), source)) == 1


@pytest.mark.parametrize("source", ["A = B = []\nA.append(1)", "A = B = {}\nconsume(B)", "A = B = set()"])
def test_chained_mutable_assignments_are_conservatively_exempt(source: str) -> None:
    assert PreferImmutableModuleConstant().check(Path("service.py"), source) == []


@pytest.mark.parametrize(
    "source",
    [
        "OPTIONS = {'enabled': True}\nService(config={'options': OPTIONS})",
        "OPTIONS = {'enabled': True}\n@route(config={'options': OPTIONS})\ndef handler(): pass",
        "OPTIONS = {'enabled': True}\n@register(config={'options': OPTIONS})\nclass Handler: pass",
        "OPTIONS = {'enabled': True}\ndef handler(config=Factory({'options': OPTIONS})): pass",
        "OPTIONS = {'enabled': True}\nhandler = lambda config=Factory({'options': OPTIONS}): config",
        "VALUES = [1]\nconsume({'outer': [{'values': VALUES}]})",
        "KINDS = {'a'}\nconsume(*(KINDS,))",
        (
            "OPTIONS = {'enabled': True}\n"
            "def build():\n"
            "    turn_handling = {'preemptive': OPTIONS}\n"
            "    kwargs = {'turn_handling': turn_handling}\n"
            "    return Service(**kwargs)"
        ),
    ],
)
def test_ignores_constants_nested_in_literal_containers_passed_to_unknown_calls(source: str) -> None:
    assert PreferImmutableModuleConstant().check(Path("service.py"), source) == []


def test_ignores_mapping_embedded_in_a_module_document_passed_to_an_unknown_call() -> None:
    source = "TOOL_SCHEMA = {'type': 'object'}\nSCENARIO = {'tools': [TOOL_SCHEMA]}\njson.dump(SCENARIO, stream)\n"

    assert PreferImmutableModuleConstant().check(Path("service.py"), source) == []


def test_local_shadow_inside_escaping_container_does_not_hide_module_finding() -> None:
    source = "OPTIONS = {'module': True}\ndef build():\n    OPTIONS = {'local': True}\n    consume({'x': OPTIONS})"

    findings = PreferImmutableModuleConstant().check(Path("service.py"), source)

    assert len(findings) == 1
    assert findings[0].line == 1


@pytest.mark.parametrize(
    "compound",
    [
        "if enabled:\n        VALUES = []",
        "for _ in items:\n        VALUES = []",
        "try:\n        VALUES = []\n    except RuntimeError:\n        pass",
        "match value:\n        case 1:\n            VALUES = []",
        "with manager():\n        VALUES = []",
    ],
)
def test_nested_local_shadow_does_not_hide_module_finding(compound: str) -> None:
    source = f"VALUES = [1]\ndef mutate(enabled, items, value):\n    {compound}\n    VALUES.append(2)"

    findings = PreferImmutableModuleConstant().check(Path("service.py"), source)

    assert len(findings) == 1
    assert findings[0].line == 1


@pytest.mark.parametrize(
    "source",
    [
        "list = factory\nVALUES = list(runtime_values)",
        "from custom import dict\nVALUES = dict(runtime_values)",
        "def set(*values): return values\nVALUES = set(runtime_values)",
    ],
)
def test_ignores_constructor_calls_when_builtin_name_is_shadowed(source: str) -> None:
    assert PreferImmutableModuleConstant().check(Path("service.py"), source) == []


@pytest.mark.parametrize(
    ("source", "line"),
    [
        pytest.param("if enabled:\n    LABELS = {'a': 'A'}", 2, id="if"),
        pytest.param("if enabled:\n    pass\nelse:\n    LABELS = {'a': 'A'}", 4, id="else"),
        pytest.param("try:\n    LABELS = {'a': 'A'}\nexcept RuntimeError:\n    pass", 2, id="try"),
        pytest.param("try:\n    run()\nexcept RuntimeError:\n    LABELS = {'a': 'A'}", 4, id="except"),
        pytest.param("try:\n    run()\nexcept* RuntimeError:\n    LABELS = {'a': 'A'}", 4, id="except-star"),
        pytest.param(
            "try:\n    run()\nexcept RuntimeError:\n    pass\nelse:\n    LABELS = {'a': 'A'}", 6, id="try-else"
        ),
        pytest.param("try:\n    run()\nfinally:\n    LABELS = {'a': 'A'}", 4, id="finally"),
        pytest.param("if enabled:\n    try:\n        LABELS = {'a': 'A'}\n    finally:\n        pass", 3, id="nested"),
        pytest.param("if enabled:\n    VALUES = [1, 2]", 2, id="list"),
        pytest.param("if enabled:\n    KINDS = {'a', 'b'}", 2, id="set"),
    ],
)
def test_reports_collection_constants_in_module_conditionals(source: str, line: int) -> None:
    findings = PreferImmutableModuleConstant().check(Path("service.py"), source)
    assert len(findings) == 1
    assert findings[0].line == line


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("if enabled:\n    LABELS: Final[dict[str, str]] = {'a': 'A'}", id="annotated-branch"),
        pytest.param("LABELS: Final[dict[str, str]]\nif enabled:\n    LABELS = {'a': 'A'}", id="prior-annotation"),
        pytest.param("if enabled:\n    LABELS: Final[dict[str, str]]\n    LABELS = {'a': 'A'}", id="branch-annotation"),
        pytest.param(
            "try:\n    LABELS: Final = dict.fromkeys(keys)\nexcept RuntimeError:\n    pass", id="factory-final"
        ),
        pytest.param("if enabled:\n    VALUES = [1]\n    VALUES.append(2)", id="mutation"),
        pytest.param("if enabled:\n    LABELS = {'a': 'A'}\n    consume(LABELS)", id="escape"),
        pytest.param("if enabled:\n    VALUES = [1]\nelse:\n    VALUES = [2]", id="alternative-bindings"),
        pytest.param("VALUES = [1]\nif enabled:\n    VALUES = [2]", id="reassignment"),
        pytest.param("if enabled:\n    A = B = [1]\nB.append(2)", id="chained-alias"),
        pytest.param("if enabled:\n    def build():\n        VALUES = [1]", id="function-scope"),
        pytest.param("if enabled:\n    class Config:\n        VALUES = [1]", id="class-scope"),
        pytest.param("if enabled:\n    for item in items:\n        VALUES = [1]", id="loop-out-of-scope"),
    ],
)
def test_module_conditionals_preserve_final_and_mutation_exclusions(source: str) -> None:
    assert PreferImmutableModuleConstant().check(Path("service.py"), "from typing import Final\n" + source) == []


@pytest.mark.parametrize("value", ["dict.fromkeys(keys)", "dict.fromkeys(('a', 'b'), 'A')"])
def test_reports_nonempty_fromkeys_dictionary_constants(value: str) -> None:
    findings = PreferImmutableModuleConstant().check(Path("service.py"), f"LABELS = {value}")
    assert len(findings) == 1
    assert "Final[dict" in findings[0].message


@pytest.mark.parametrize(
    "source",
    [
        "LABELS = dict.fromkeys(())",
        "LABELS = dict.fromkeys([], 'A')",
        "LABELS = dict.fromkeys({})",
        "LABELS = dict.fromkeys('')",
        "LABELS = dict.fromkeys(b'')",
        "LABELS = dict.fromkeys()",
        "LABELS = dict.fromkeys(*keys)",
        "LABELS = dict.fromkeys(keys=keys)",
        "from custom import dict\nLABELS = dict.fromkeys(keys)",
        "from custom import *\nLABELS = dict.fromkeys(keys)",
        "if enabled:\n    dict = custom\nLABELS = dict.fromkeys(keys)",
        "LABELS = dict.fromkeys(keys)\nLABELS.update(extra)",
        "LABELS = dict.fromkeys(keys)\nconsume(LABELS)",
        "from typing import Final\nLABELS: Final = dict.fromkeys(keys)",
    ],
)
def test_fromkeys_preserves_empty_shadowed_mutated_and_final_exclusions(source: str) -> None:
    assert PreferImmutableModuleConstant().check(Path("service.py"), source) == []


def test_conditional_final_lookalike_still_warns() -> None:
    source = "from custom import Final\nif enabled:\n    LABELS: Final = {'a': 'A'}"
    assert len(PreferImmutableModuleConstant().check(Path("service.py"), source)) == 1

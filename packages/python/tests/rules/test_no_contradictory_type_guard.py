from __future__ import annotations

from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING, TypeGuard, TypeIs

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.__main__ import check_source
from sarj_python_lint.rule_base import AutofixPolicy, Severity
from sarj_python_lint.rules.no_contradictory_type_guard import NoContradictoryTypeGuard
from sarj_python_lint.rules.no_partial_type_is import NoPartialTypeIs
from sarj_python_lint.rules.no_shallow_container_type_guard import NoShallowContainerTypeGuard


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, Rule, RuleExample


def _source(target: str = "str", checked: str = "int", *, guard: str = "TypeGuard", input_type: str = "object") -> str:
    return (
        f"from typing import {guard}\n"
        f"def identifies(value: {input_type}) -> {guard}[{target}]:\n"
        f"    return isinstance(value, {checked})\n"
    )


_BASE = _source()
_CASES = (
    EvaluationCase("wrong-primitive", Language.PYTHON, _BASE, ExpectedOutcome.MATCH),
    EvaluationCase("type-is-wrong-primitive", Language.PYTHON, _source(guard="TypeIs"), ExpectedOutcome.MATCH),
    EvaluationCase("consistent-string", Language.PYTHON, _source(checked="str")),
    EvaluationCase("consistent-int", Language.PYTHON, _source("int", "int")),
    EvaluationCase("consistent-bool", Language.PYTHON, _source("bool", "bool")),
    EvaluationCase("consistent-bytes", Language.PYTHON, _source("bytes", "bytes")),
    EvaluationCase("partial-bool-is-int", Language.PYTHON, _source("int", "bool")),
    EvaluationCase("int-is-not-bool", Language.PYTHON, _source("bool", "int"), ExpectedOutcome.MATCH),
    EvaluationCase(
        "type-is-int-bool-false-branch", Language.PYTHON, _source("int", "bool", guard="TypeIs"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "type-is-bool-int-true-branch", Language.PYTHON, _source("bool", "int", guard="TypeIs"), ExpectedOutcome.MATCH
    ),
    EvaluationCase("bool-input-constrains-int-test", Language.PYTHON, _source("bool", "int", input_type="bool")),
    EvaluationCase("bool-union-constrains-int-test", Language.PYTHON, _source("bool", "int", input_type="bool | str")),
    EvaluationCase(
        "type-is-bool-input-int-test", Language.PYTHON, _source("bool", "int", guard="TypeIs", input_type="bool | str")
    ),
    EvaluationCase(
        "int-input-includes-nonbool", Language.PYTHON, _source("bool", "int", input_type="int"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "int-input-admits-bool-witness",
        Language.PYTHON,
        _source("str", "bool", input_type="int"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "type-guard-unrelated-target-allowed-by-checker",
        Language.PYTHON,
        _source(input_type="int"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("type-is-compiler-invalid-target-input", Language.PYTHON, _source(guard="TypeIs", input_type="int")),
    EvaluationCase(
        "type-is-too-broad-int-target-for-bool-input",
        Language.PYTHON,
        _source("int", "bool", guard="TypeIs", input_type="bool"),
    ),
    EvaluationCase("impossible-isinstance", Language.PYTHON, _source(input_type="str")),
    EvaluationCase("nullable-input", Language.PYTHON, _source(input_type="int | str | None"), ExpectedOutcome.MATCH),
    EvaluationCase("input-object-union", Language.PYTHON, _source(input_type="object | int"), ExpectedOutcome.MATCH),
    EvaluationCase("unknown-input", Language.PYTHON, _source(input_type="Any")),
    EvaluationCase("constrained-input", Language.PYTHON, _source(input_type="PositiveInt")),
    EvaluationCase("constrained-union-input", Language.PYTHON, _source(input_type="PositiveInt | str")),
    EvaluationCase("literal-input", Language.PYTHON, _source(input_type="Literal[1]")),
    EvaluationCase("literal-target", Language.PYTHON, _source("Literal['a']")),
    EvaluationCase("opaque-target", Language.PYTHON, _source("Text")),
    EvaluationCase("target-union", Language.PYTHON, _source("str | bytes")),
    EvaluationCase("float-target", Language.PYTHON, _source("float")),
    EvaluationCase("float-checked", Language.PYTHON, _source(checked="float")),
    EvaluationCase("float-input", Language.PYTHON, _source(input_type="float | str")),
    EvaluationCase("custom-checked", Language.PYTHON, _source(checked="CustomInt")),
    EvaluationCase("tuple-checked", Language.PYTHON, _source(checked="(int, bool)")),
    EvaluationCase("second-parameter", Language.PYTHON, _BASE.replace("value: object", "value: object, info: object")),
    EvaluationCase("variadic", Language.PYTHON, _BASE.replace("value: object", "value: object, **kwargs")),
    EvaluationCase("different-parameter-test", Language.PYTHON, _BASE.replace("isinstance(value", "isinstance(other")),
    EvaluationCase(
        "partial-predicate",
        Language.PYTHON,
        _BASE.replace("isinstance(value, int)", "isinstance(value, str) and len(value) > 0"),
    ),
    EvaluationCase("helper-predicate", Language.PYTHON, _BASE.replace("isinstance(value, int)", "recognizes(value)")),
    EvaluationCase(
        "negative-check",
        Language.PYTHON,
        _BASE.replace("return isinstance", "return not isinstance"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("multistatement", Language.PYTHON, _BASE.replace("    return", "    normalize(value)\n    return")),
    EvaluationCase("decorated", Language.PYTHON, _BASE.replace("def identifies", "@adapt\ndef identifies")),
    EvaluationCase("generic", Language.PYTHON, _BASE.replace("identifies(", "identifies[T](")),
    EvaluationCase("async", Language.PYTHON, _BASE.replace("def identifies", "async def identifies")),
    EvaluationCase(
        "nested",
        Language.PYTHON,
        "from typing import TypeGuard\ndef outer():\n" + "\n".join("    " + line for line in _BASE.splitlines()[1:]),
    ),
    EvaluationCase("custom-guard", Language.PYTHON, _BASE.replace("from typing", "from framework")),
    EvaluationCase("guard-shadow", Language.PYTHON, _BASE + "TypeGuard = custom\n"),
    EvaluationCase("builtin-shadow", Language.PYTHON, "int = Custom\n" + _BASE),
    EvaluationCase("isinstance-shadow", Language.PYTHON, "isinstance = custom\n" + _BASE),
    EvaluationCase("builtin-module-mutation", Language.PYTHON, "import builtins\nbuiltins.int = Custom\n" + _BASE),
    EvaluationCase("guard-module-mutation", Language.PYTHON, "import typing\ntyping.TypeGuard = custom\n" + _BASE),
    EvaluationCase("guard-module-escape", Language.PYTHON, "import typing\nconfigure(typing)\n" + _BASE),
    EvaluationCase(
        "guard-module-setattr", Language.PYTHON, "import typing\nsetattr(typing, 'TypeGuard', custom)\n" + _BASE
    ),
    EvaluationCase("guard-module-alias", Language.PYTHON, "import typing\nother = typing\n" + _BASE),
    EvaluationCase("wildcard", Language.PYTHON, "from unknown import *\n" + _BASE),
    EvaluationCase("dynamic-namespace", Language.PYTHON, "globals()['int'] = Custom\n" + _BASE),
    EvaluationCase("malformed", Language.PYTHON, "def broken("),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _BASE),
    EvaluationCase(
        "extensions", Language.PYTHON, _BASE.replace("from typing", "from typing_extensions"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "guard-alias",
        Language.PYTHON,
        _BASE.replace("import TypeGuard", "import TypeGuard as Guard").replace("-> TypeGuard", "-> Guard"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        _BASE.replace("from typing import TypeGuard", "import typing as t").replace("-> TypeGuard", "-> t.TypeGuard"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "builtin-alias",
        Language.PYTHON,
        "from builtins import int as Integer\n" + _BASE.replace("value, int", "value, Integer"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "normalized-symbol", Language.PYTHON, _BASE.replace("TypeGuard", "ＴｙｐｅＧｕａｒｄ"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "docstring",
        Language.PYTHON,
        _BASE.replace("    return", '    "Recognize text."\n    return'),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "positional-only", Language.PYTHON, _BASE.replace("value: object)", "value: object, /)"), ExpectedOutcome.MATCH
    ),
)


def _check(source: str, path: str = "app/guards.py") -> list[Diagnostic]:
    return NoContradictoryTypeGuard().check(Path(path), source)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = _check(case.source)
    assert len(findings) == int(case.expected is ExpectedOutcome.MATCH)
    assert all(finding.severity is Severity.WARNING for finding in findings)


@pytest.mark.parametrize("example", NoContradictoryTypeGuard.public_examples())
def test_public_examples(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source)) == example.expected_count


def test_metadata_suppression_and_test_paths() -> None:
    docs = NoContradictoryTypeGuard.documentation
    assert docs is not None
    assert docs.autofix is AutofixPolicy.NONE
    assert docs.default_level is Severity.WARNING
    finding = _check(_BASE)[0]
    assert (finding.code, finding.line, finding.col) == ("SARJ513", 3, 5)
    assert (
        _check(_BASE.replace("value, int)", "value, int)  # sarj-noqa: SARJ513 -- deliberate contradictory test")) == []
    )
    assert len(_check(_BASE.replace("value, int)", "value, int)  # sarj-noqa: SARJ512 -- unrelated"))) == 1
    assert len(_check(_BASE, "tests/test_guards.py")) == 1


def test_nearby_guard_rules_keep_distinct_owners() -> None:
    rules: list[Rule] = [NoContradictoryTypeGuard(), NoPartialTypeIs(), NoShallowContainerTypeGuard()]
    assert [finding.code for finding in check_source(rules, Path("app/guards.py"), _BASE)] == ["SARJ513"]
    partial = _source("int", "int", guard="TypeIs").replace(
        "isinstance(value, int)", "isinstance(value, int) and value > 0"
    )
    assert [finding.code for finding in check_source(rules, Path("app/guards.py"), partial)] == ["SARJ512"]
    shallow = "from typing import TypeGuard\ndef check(value: object) -> TypeGuard[list[str]]:\n    return isinstance(value, list)\n"
    assert [finding.code for finding in check_source(rules, Path("app/guards.py"), shallow)] == ["SARJ472"]


def _claims_text(value: object) -> TypeGuard[str]:
    return isinstance(value, int)  # sarj-noqa: SARJ513 -- reproduce the trusted but contradictory promise


def _claims_all_ints(value: object) -> TypeIs[int]:
    return isinstance(value, bool)  # sarj-noqa: SARJ513 -- reproduce unsound negative narrowing


def test_contradictory_true_and_false_branches_fail_at_runtime() -> None:
    def render(value: object) -> str:
        return value.upper() if _claims_text(value) else "other"

    def describe(value: int | str) -> str:
        return "bool" if _claims_all_ints(value) else value.upper()

    with pytest.raises(AttributeError, match="upper"):
        render(1)
    with pytest.raises(AttributeError, match="upper"):
        describe(0)


_RUNTIME_TYPES: dict[str, type[object]] = {"int": int, "bool": bool, "str": str, "bytes": bytes}
_RUNTIME_INPUTS: dict[str, tuple[type[object], ...]] = {
    "object": (object,),
    "int": (int,),
    "bool": (bool,),
    "str": (str,),
    "bytes": (bytes,),
    "int | bool": (int, bool),
    "int | str": (int, str),
    "int | bytes": (int, bytes),
    "bool | str": (bool, str),
    "bool | bytes": (bool, bytes),
    "str | bytes": (str, bytes),
    "int | str | None": (int, str, type(None)),
}


@pytest.mark.parametrize(
    ("guard", "target_name", "checked_name", "input_name"),
    tuple(product(("TypeGuard", "TypeIs"), _RUNTIME_TYPES, _RUNTIME_TYPES, _RUNTIME_INPUTS)),
)
def test_primitive_relations_agree_with_python_runtime_subtyping(
    guard: str, target_name: str, checked_name: str, input_name: str
) -> None:
    target = _RUNTIME_TYPES[target_name]
    checked = _RUNTIME_TYPES[checked_name]
    input_types = _RUNTIME_INPUTS[input_name]
    values = [value for value in (0, False, "", b"", None, object()) if isinstance(value, input_types)]
    accepted = [value for value in values if isinstance(value, checked)]
    compiler_owns = guard == "TypeIs" and not issubclass(target, input_types)
    wrong_true_branch = any(not isinstance(value, target) for value in accepted)
    wrong_false_branch = guard == "TypeIs" and any(
        isinstance(value, target) and not isinstance(value, checked) for value in values
    )
    matches = not compiler_owns and bool(accepted) and (wrong_true_branch or wrong_false_branch)
    assert len(_check(_source(target_name, checked_name, guard=guard, input_type=input_name))) == int(matches)


def test_large_flat_union_input_preserves_its_primitive_witnesses_without_recursion() -> None:
    many = " | ".join(["str"] * 1500 + ["int"])
    assert len(_check(_source(input_type=many))) == 1


def test_deep_right_grouped_union_input_preserves_its_witnesses_without_recursion() -> None:
    annotation = "".join(["str | ("] * 100 + ["int"] + [")"] * 100)
    assert len(_check(_source(input_type=annotation))) == 1


@pytest.mark.parametrize("wrapper", ["Optional[{}]", "Union[{}, None]"])
def test_large_unsupported_input_wrappers_abstain_without_recursion(wrapper: str) -> None:
    many = " | ".join(["str"] * 1500 + ["int"])
    source = "from typing import Optional, Union\n" + _source(input_type=wrapper.format(many))
    assert _check(source) == []


def test_over_budget_input_union_abstains_without_recursion() -> None:
    many = " | ".join(["str"] * 2300 + ["int"])
    assert _check(_source(input_type=many)) == []


@pytest.mark.parametrize(
    ("guard", "target_name", "checked_name", "input_name"),
    tuple(product(("TypeGuard", "TypeIs"), _RUNTIME_TYPES, _RUNTIME_TYPES, _RUNTIME_INPUTS)),
)
def test_negated_checks_agree_with_runtime_witnesses(
    guard: str, target_name: str, checked_name: str, input_name: str
) -> None:
    target = _RUNTIME_TYPES[target_name]
    checked = _RUNTIME_TYPES[checked_name]
    input_types = _RUNTIME_INPUTS[input_name]
    values = [value for value in (0, False, "", b"", None) if isinstance(value, input_types)]
    compiler_owns = guard == "TypeIs" and not issubclass(target, input_types)
    wrong_true = any(not isinstance(value, checked) and not isinstance(value, target) for value in values)
    wrong_false = guard == "TypeIs" and any(
        isinstance(value, target) and isinstance(value, checked) for value in values
    )
    source = _source(target_name, checked_name, guard=guard, input_type=input_name).replace(
        "return isinstance", "return not isinstance"
    )
    assert len(_check(source)) == int(not compiler_owns and (wrong_true or wrong_false))


@pytest.mark.parametrize(
    ("guard", "target_name", "input_name", "result"),
    tuple(product(("TypeGuard", "TypeIs"), _RUNTIME_TYPES, _RUNTIME_INPUTS, (True, False))),
)
def test_constant_results_agree_with_runtime_witnesses(
    guard: str, target_name: str, input_name: str, result: bool
) -> None:
    target = _RUNTIME_TYPES[target_name]
    input_types = _RUNTIME_INPUTS[input_name]
    values = [value for value in (0, False, "", b"", None) if isinstance(value, input_types)]
    compiler_owns = guard == "TypeIs" and not issubclass(target, input_types)
    wrong_true = result and any(not isinstance(value, target) for value in values)
    wrong_false = guard == "TypeIs" and not result and any(isinstance(value, target) for value in values)
    source = _source(target_name, guard=guard, input_type=input_name).replace("isinstance(value, int)", str(result))
    assert len(_check(source)) == int(not compiler_owns and (wrong_true or wrong_false))


@pytest.mark.parametrize("annotation", ["Never", "NoReturn", "Literal[1]", "PositiveInt", "Any", "int | Never"])
@pytest.mark.parametrize("predicate", ["True", "False", "not isinstance(value, str)"])
def test_constants_and_negation_preserve_uninhabited_or_opaque_inputs(annotation: str, predicate: str) -> None:
    source = "from typing import Any, Literal, Never, NoReturn\n" + _source(input_type=annotation)
    assert _check(source.replace("isinstance(value, int)", predicate)) == []


def _claims_everything_is_text(_value: object) -> TypeGuard[str]:
    return True  # sarj-noqa: SARJ513 -- demonstrate a constant predicate's invalid true branch


def _claims_nonints_are_text(value: object) -> TypeGuard[str]:
    return not isinstance(value, int)  # sarj-noqa: SARJ513 -- demonstrate an invalid complement predicate


def test_constant_and_complement_guards_fail_for_proven_none_witness() -> None:
    def render(value: object) -> str:
        return value.upper() if _claims_everything_is_text(value) else "other"

    def describe(value: object) -> str:
        return value.upper() if _claims_nonints_are_text(value) else "integer"

    with pytest.raises(AttributeError, match="upper"):
        render(None)
    with pytest.raises(AttributeError, match="upper"):
        describe(None)


def test_public_overload_inputs_override_broad_implementation_input() -> None:
    source = (
        "from typing import Literal, TypeGuard, overload\n"
        "@overload\ndef recognizes(value: Literal[1]) -> TypeGuard[int]: ...\n"
        "@overload\ndef recognizes(value: Literal[2]) -> TypeGuard[int]: ...\n"
        "def recognizes(value: object) -> TypeGuard[int]:\n    return True\n"
    )
    assert _check(source) == []
    implementation = source.split("def recognizes(value: object)", maxsplit=1)[1]
    assert len(_check("from typing import TypeGuard\ndef recognizes(value: object)" + implementation)) == 1

from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.no_input_model_mutation import NoInputModelMutation
from sarj_python_lint.rules.no_mutating_container_transform import NoMutatingContainerTransform


_CASES = (
    EvaluationCase(
        "borrowed-list-sort",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    values.sort()\n    return values\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "borrowed-dict-item-write",
        Language.PYTHON,
        "def normalize(values: dict[str, int]) -> dict[str, int]:\n    values['count'] = 1\n    return values\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "borrowed-set-update",
        Language.PYTHON,
        "def normalize(values: set[str]) -> set[str]:\n    values.add('new')\n    return values\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "method-value-contract",
        Language.PYTHON,
        "class Mapper:\n    def ordered(self, values: list[int]) -> list[int]:\n        values.reverse()\n        return values\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "borrowed-alias",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    result = values\n    result.sort()\n    return result\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "copying-after-write-is-too-late",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    values.sort()\n    return list(values)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "return-expression-mutation",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    return values.reverse() or values\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "in-place-list-addition",
        Language.PYTHON,
        "def extend(values: list[int]) -> list[int]:\n    values += [1]\n    return values\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "item-deletion",
        Language.PYTHON,
        "def trim(values: list[int]) -> list[int]:\n    del values[0]\n    return values\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "fresh-list-builder",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    result = list(values)\n    result.sort()\n    return result\n",
    ),
    EvaluationCase(
        "fresh-dict-builder",
        Language.PYTHON,
        "def normalize(values: dict[str, int]) -> dict[str, int]:\n    result = dict(values)\n    result['count'] = 1\n    return result\n",
    ),
    EvaluationCase(
        "rebound-input-is-a-local-builder",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    values = values.copy()\n    values.sort()\n    return values\n",
    ),
    EvaluationCase(
        "fresh-alias-does-not-change-input-ownership",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    result = list(values)\n    alias = result\n    alias.sort()\n    return result\n",
    ),
    EvaluationCase("void-command", Language.PYTHON, "def order(values: list[int]) -> None:\n    values.sort()\n"),
    EvaluationCase(
        "scalar-command-result",
        Language.PYTHON,
        "def append(values: list[int]) -> int:\n    values.append(1)\n    return len(values)\n",
    ),
    EvaluationCase(
        "unknown-input-contract",
        Language.PYTHON,
        "def ordered(values) -> list[int]:\n    values.sort()\n    return values\n",
    ),
    EvaluationCase(
        "unknown-receiver-method",
        Language.PYTHON,
        "def ordered(values: list[int], client) -> list[int]:\n    client.sort()\n    return values\n",
    ),
    EvaluationCase(
        "decorated-framework-contract",
        Language.PYTHON,
        "@framework_contract\ndef ordered(values: list[int]) -> list[int]:\n    values.sort()\n    return values\n",
    ),
    EvaluationCase(
        "conditional-ownership-is-unresolved",
        Language.PYTHON,
        "def ordered(values: list[int], flag: bool) -> list[int]:\n    if flag:\n        values = list(values)\n    values.sort()\n    return values\n",
    ),
    EvaluationCase(
        "deferred-callback-is-not-executed",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    callback = lambda: values.sort()\n    return values\n",
    ),
    EvaluationCase(
        "shadowed-container-type",
        Language.PYTHON,
        "class list: pass\ndef ordered(values: list[int]) -> list[int]:\n    values.sort()\n    return values\n",
    ),
    EvaluationCase(
        "model-input-retains-existing-owner",
        Language.PYTHON,
        "from pydantic import BaseModel\nclass Record(BaseModel):\n    value: int\ndef add(values: list[Record]) -> list[Record]:\n    values.append(Record(value=1))\n    return values\n",
    ),
    EvaluationCase(
        "dynamic-namespace",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    exec(code)\n    values.sort()\n    return values\n",
    ),
    EvaluationCase(
        "modified-method-identity-is-uncertain",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    alias = values\n    values.sort = command\n    alias.sort()\n    return values\n",
    ),
    EvaluationCase(
        "builtin-provider-is-uncertain",
        Language.PYTHON,
        "import builtins\nbuiltins.list = Other\ndef ordered(values: list[int]) -> list[int]:\n    values.sort()\n    return values\n",
    ),
    EvaluationCase(
        "void-return-mismatch-belongs-to-type-checking",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    values.sort()\n    return None\n",
    ),
    EvaluationCase(
        "async-container-value-contract",
        Language.PYTHON,
        "async def ordered(values: list[int]) -> list[int]:\n    values.sort()\n    return values\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "model-output-does-not-hide-primitive-list-write",
        Language.PYTHON,
        "def build(values: list[int]) -> list[Record]:\n    values.sort()\n    return build_records(values)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "model-output-does-not-hide-primitive-dict-write",
        Language.PYTHON,
        "def build(values: dict[str, int]) -> dict[str, Record]:\n    values['count'] = 1\n    return build_records(values)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "model-output-after-local-copy",
        Language.PYTHON,
        "def build(values: list[int]) -> list[Record]:\n    result = list(values)\n    result.sort()\n    return build_records(result)\n",
    ),
    EvaluationCase(
        "opaque-input-does-not-become-a-primitive-owner",
        Language.PYTHON,
        "def build(values: list[Record]) -> list[str]:\n    values.clear()\n    return build_names(values)\n",
    ),
    EvaluationCase(
        "input-write-before-eager-comprehension",
        Language.PYTHON,
        "def build(values: list[int]) -> list[str]:\n    values.sort()\n    return [str(value) for value in values]\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "comprehension-captures-borrowed-input",
        Language.PYTHON,
        "def build(values: list[int], repetitions) -> list[int]:\n    return [values.pop() for item in repetitions]\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "comprehension-target-shadows-input",
        Language.PYTHON,
        "def build(values: list[int], buckets) -> list[int]:\n    return [values.pop() for values in buckets]\n",
    ),
    EvaluationCase(
        "outermost-iterable-uses-enclosing-binding",
        Language.PYTHON,
        "def build(values: list[int]) -> list[int]:\n    return [values for values in range(values.pop())]\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "pure-eager-comprehension",
        Language.PYTHON,
        "def build(values: list[int]) -> list[str]:\n    return [str(value) for value in values]\n",
    ),
    EvaluationCase(
        "conditional-input-write",
        Language.PYTHON,
        "def ordered(values: list[int], reverse: bool) -> list[int]:\n    if reverse:\n        values.reverse()\n    return values\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "returning-branch-input-write",
        Language.PYTHON,
        "def ordered(values: list[int], reverse: bool) -> list[int]:\n    if reverse:\n        values.reverse()\n        return values\n    return values\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "joined-alias-retains-borrowed-origin",
        Language.PYTHON,
        "def ordered(values: list[int], flag: bool) -> list[int]:\n    if flag:\n        result = values\n    else:\n        result = values\n    result.sort()\n    return result\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nested-conditional-input-write",
        Language.PYTHON,
        "def ordered(values: list[int], first: bool, second: bool) -> list[int]:\n    if first:\n        if second:\n            values.sort()\n    return values\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "uncertain-join-does-not-prove-borrowed-receiver",
        Language.PYTHON,
        "def ordered(values: list[int], flag: bool) -> list[int]:\n    if flag:\n        result = list(values)\n    else:\n        result = values\n    result.sort()\n    return result\n",
    ),
    EvaluationCase(
        "both-branches-create-local-values",
        Language.PYTHON,
        "def ordered(values: list[int], flag: bool) -> list[int]:\n    if flag:\n        values = list(values)\n    else:\n        values = sorted(values)\n    values.sort()\n    return values\n",
    ),
    EvaluationCase(
        "conditional-method-replacement-invalidates-join",
        Language.PYTHON,
        "def ordered(values: list[int], flag: bool) -> list[int]:\n    if flag:\n        values.sort = command\n    values.sort()\n    return values\n",
    ),
    EvaluationCase(
        "unreachable-constant-branch-write",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    if False:\n        values.sort()\n    return values\n",
    ),
    EvaluationCase(
        "constant-branch-copies-before-write",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    if True:\n        values = list(values)\n    values.sort()\n    return values\n",
    ),
    EvaluationCase(
        "short-circuit-false-and-skips-write",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    ignored = False and values.pop()\n    return values\n",
    ),
    EvaluationCase(
        "short-circuit-true-or-skips-write",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    ignored = True or values.pop()\n    return values\n",
    ),
    EvaluationCase(
        "conditional-expression-skips-write",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    ignored = values.pop() if False else 0\n    return values\n",
    ),
    EvaluationCase(
        "conditional-expression-evaluates-write",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    ignored = values.pop() if True else 0\n    return values\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unknown-short-circuit-can-evaluate-write",
        Language.PYTHON,
        "def ordered(values: list[int], flag: bool) -> list[int]:\n    ignored = flag and values.pop()\n    return values\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nested-literal-short-circuit-skips-write",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    ignored = (False and True) and values.pop()\n    return values\n",
    ),
    EvaluationCase(
        "literal-negation-skips-branch-write",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    if not True:\n        values.sort()\n    return values\n",
    ),
    EvaluationCase(
        "conditional-alias-retains-one-borrowed-owner",
        Language.PYTHON,
        "def ordered(values: list[int], flag: bool) -> list[int]:\n    result = values if flag else values\n    result.sort()\n    return result\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "literal-selected-alias-retains-borrowed-owner",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    result = values if True else []\n    result.sort()\n    return result\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "annotated-conditional-alias",
        Language.PYTHON,
        "def ordered(values: list[int], flag: bool) -> list[int]:\n    result: list[int] = values if flag else values\n    result.reverse()\n    return result\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "literal-selected-copy-is-local",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    result = values if False else list(values)\n    result.sort()\n    return result\n",
    ),
    EvaluationCase(
        "conditional-value-ownership-remains-uncertain",
        Language.PYTHON,
        "def ordered(values: list[int], flag: bool) -> list[int]:\n    result = values if flag else list(values)\n    result.sort()\n    return result\n",
    ),
    EvaluationCase(
        "empty-comprehension-does-not-evaluate-body",
        Language.PYTHON,
        "def trim(values: list[int]) -> list[int]:\n    return [values.pop() for item in ()]\n",
    ),
    EvaluationCase(
        "false-filter-does-not-evaluate-body",
        Language.PYTHON,
        "def trim(values: list[int]) -> list[int]:\n    return [values.pop() for item in (0,) if False]\n",
    ),
    EvaluationCase(
        "false-filter-stops-subsequent-filter",
        Language.PYTHON,
        "def trim(values: list[int]) -> list[int]:\n    return [0 for item in (0,) if False if values.pop()]\n",
    ),
    EvaluationCase(
        "false-filter-stops-inner-iterable",
        Language.PYTHON,
        "def trim(values: list[int]) -> list[int]:\n    return [0 for item in (0,) if False for other in (values.pop(),)]\n",
    ),
    EvaluationCase(
        "empty-inner-iterable-does-not-evaluate-body",
        Language.PYTHON,
        "def trim(values: list[int]) -> list[int]:\n    return [values.pop() for item in (0,) for other in ()]\n",
    ),
    EvaluationCase(
        "empty-comprehension-does-not-assign-borrowed-item",
        Language.PYTHON,
        "def trim(values: list[int]) -> list[int]:\n    return [0 for values[0] in ()]\n",
    ),
    EvaluationCase(
        "nonempty-comprehension-assigns-borrowed-item",
        Language.PYTHON,
        "def trim(values: list[int]) -> list[int]:\n    return [0 for values[0] in (7,)]\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "outer-iterable-effect-precedes-false-filter",
        Language.PYTHON,
        "def trim(values: list[int]) -> list[int]:\n    return [item for item in (values.pop(),) if False]\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "earlier-filter-effect-precedes-false-filter",
        Language.PYTHON,
        "def trim(values: list[int]) -> list[int]:\n    return [0 for item in (0,) if values.pop() if False]\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "inner-iterable-effect-precedes-false-filter",
        Language.PYTHON,
        "def trim(values: list[int]) -> list[int]:\n    return [0 for item in (0,) for other in (values.pop(),) if False]\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "empty-set-comprehension-does-not-evaluate-body",
        Language.PYTHON,
        "def trim(values: list[int]) -> set[int]:\n    return {values.pop() for item in ()}\n",
    ),
    EvaluationCase(
        "false-dict-comprehension-does-not-evaluate-value",
        Language.PYTHON,
        "def trim(values: list[int]) -> dict[int, int]:\n    return {item: values.pop() for item in (0,) if False}\n",
    ),
    EvaluationCase(
        "live-dict-comprehension-evaluates-value",
        Language.PYTHON,
        "def trim(values: list[int]) -> dict[int, int]:\n    return {item: values.pop() for item in (0,)}\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("malformed-source", Language.PYTHON, "def ordered(:\n"),
    EvaluationCase(
        "early-return-does-not-hide-later-input-write",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    if not values:\n        return []\n    values.sort()\n    return values\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "precondition-raise-does-not-hide-later-input-write",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    if not values:\n        raise ValueError('empty')\n    values.reverse()\n    return values\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "guard-condition-can-mutate-the-input",
        Language.PYTHON,
        "def trim(values: list[int]) -> list[int]:\n    if values.pop():\n        return []\n    return values\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "guarded-fresh-builder",
        Language.PYTHON,
        "def ordered(values: list[int]) -> list[int]:\n    if not values:\n        return []\n    result = list(values)\n    result.sort()\n    return result\n",
    ),
)


@pytest.mark.parametrize("case", _CASES, ids=[case.case_id for case in _CASES])
def test_labeled_container_effect_cases(case: EvaluationCase) -> None:
    findings = NoMutatingContainerTransform().check(Path("app/counts.py"), case.source)
    assert len(findings) == int(case.expected is ExpectedOutcome.MATCH)


def test_documented_examples() -> None:
    verify_native_rule(NoMutatingContainerTransform, analyze)


def test_deep_elif_chain_preserves_neighboring_function_analysis() -> None:
    source = (
        "def deep(values: list[int], flag: bool) -> list[int]:\n    if flag:\n        pass\n"
        + "    elif flag:\n        pass\n" * 500
        + "    return values\n"
        + "def ordered(values: list[int]) -> list[int]:\n    values.sort()\n    return values\n"
    )
    [finding] = NoMutatingContainerTransform().check(Path("app/counts.py"), source)
    assert finding.line == len(source.splitlines()) - 1


def test_warning_location_suppression_and_generated_sources() -> None:
    rule = NoMutatingContainerTransform()
    source = _CASES[0].source
    [finding] = rule.check(Path("app/counts.py"), source)
    assert (finding.code, finding.line, finding.col, finding.severity.value) == ("SARJ520", 2, 5, "warning")
    suppressed = source.replace("values.sort()", "values.sort()  # sarj-noqa: SARJ520 — documented legacy in-place API")
    assert rule.check(Path("app/counts.py"), suppressed) == []
    assert rule.check(Path("generated/counts.py"), source) == []


def test_existing_model_mutation_owner_has_precedence() -> None:
    source = next(case.source for case in _CASES if case.case_id == "model-input-retains-existing-owner")
    path = Path("app/records.py")
    owner = NoInputModelMutation()
    owner.prepare(ProjectIndexSet.single(path, source))
    assert [finding.code for finding in owner.check(path, source)] == ["SARJ481"]
    assert NoMutatingContainerTransform().check(path, source) == []


def test_warning_does_not_block_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "counts.py"
    target.write_text(_CASES[0].source)
    assert main(["check", "--rule", NoMutatingContainerTransform.id, str(target)]) == 0
    assert "SARJ520 warning:" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("declarations", "annotation", "operation", "expected_count"),
    [
        ("import operator\n", "list[int]", "operator.setitem(values, 0, 2)", 1),
        ("import operator\n", "list[int]", "operator.delitem(values, 0)", 1),
        ("import operator\n", "list[int]", "operator.iadd(values, [2])", 1),
        ("from operator import iconcat as extend\n", "list[int]", "extend(values, [2])", 1),
        ("import operator as op\n", "list[int]", "op.imul(values, 2)", 1),
        ("import operator\n", "dict[str, int]", "operator.ior(values, {'other': 2})", 1),
        ("import operator\n", "set[int]", "operator.isub(values, {1})", 1),
        ("import operator\n", "list[int]", "operator.add(values, [2])", 0),
        ("import operator\n", "list[int]", "values = list(values)\n    operator.setitem(values, 0, 2)", 0),
        (
            "import operator\noperator.setitem = command\n",
            "list[int]",
            "operator.setitem(values, 0, 2)",
            0,
        ),
        (
            "import operator as changed\nfrom operator import setitem\nchanged.setitem = command\n",
            "list[int]",
            "setitem(values, 0, 2)",
            0,
        ),
        (
            "def setitem(values, index, value):\n    pass\n",
            "list[int]",
            "setitem(values, 0, 2)",
            0,
        ),
    ],
    ids=[
        "setitem",
        "delitem",
        "inplace-add",
        "import-alias",
        "module-alias",
        "dict-inplace-union",
        "set-inplace-subtraction",
        "fresh-functional-add",
        "copy-before-functional-write",
        "patched-provider",
        "provider-alias-write",
        "unrelated-local-name",
    ],
)
def test_source_proven_operator_mutation(
    declarations: str, annotation: str, operation: str, expected_count: int
) -> None:
    source = f"{declarations}def transform(values: {annotation}) -> {annotation}:\n    {operation}\n    return values\n"
    diagnostics = NoMutatingContainerTransform().check(Path("app/counts.py"), source)
    assert len(diagnostics) == expected_count


@pytest.mark.parametrize(
    ("statement", "expected_count"),
    [
        ("values = values[:] = []", 0),
        ("values, values[:] = [], [2]", 0),
        ("values[0]: int", 0),
        ("local: tuple[values.sort()] = None", 0),
        ("values[0]: int = 2", 1),
        ("values[values.pop()]: int", 1),
        ("local: list[int] = [values.pop()]", 1),
        ("alias: list[int] = values\n    alias.sort()", 1),
    ],
    ids=[
        "chain-target-rebinds-before-write",
        "unpack-target-rebinds-before-write",
        "item-annotation-is-not-write",
        "local-annotation-is-not-evaluated",
        "annotated-item-value-is-write",
        "annotation-target-index-is-evaluated",
        "annotated-value-is-evaluated",
        "annotated-alias-retains-owner",
    ],
)
def test_assignment_execution_contract(statement: str, expected_count: int) -> None:
    source = f"def transform(values: list[int]) -> list[int]:\n    {statement}\n    return values\n"
    assert len(NoMutatingContainerTransform().check(Path("app/counts.py"), source)) == expected_count


@pytest.mark.parametrize(
    ("source", "expected_count"),
    [
        (
            f"def ordered(values: list[int]) -> list[int]:\n    return list({consumer}(values.pop() for _ in [0]))\n",
            1,
        )
        for consumer in ("list", "tuple", "set", "frozenset")
    ]
    + [
        (
            "def ordered(values: list[int]) -> list[int]:\n    pending = (values.pop() for _ in [0])\n    return values\n",
            0,
        ),
        (
            "def ordered(values: list[int], consume) -> list[int]:\n    return consume(values.pop() for _ in [0])\n",
            0,
        ),
        (
            "def tuple(iterable):\n    return []\ndef ordered(values: list[int]) -> list[int]:\n    return list(tuple(values.pop() for _ in [0]))\n",
            0,
        ),
        (
            "from unittest.mock import patch\ndef defer(iterable):\n    return []\npatch('builtins.tuple', new=defer).start()\ndef ordered(values: list[int]) -> list[int]:\n    return list(tuple(values.pop() for _ in [0]))\n",
            0,
        ),
        (
            "async def ordered(values: list[int], source) -> list[int]:\n    return list(values.pop() async for _ in source)\n",
            0,
        ),
        ("def ordered(values: list[int]) -> list[int]:\n    return list(values.pop() for _ in [])\n", 0),
        (
            "def ordered(values: list[int]) -> list[int]:\n    return list(values.pop() for _ in [0] if False)\n",
            0,
        ),
        (
            "def ordered(values: list[int]) -> list[int]:\n    return list(values.pop() for values in [[1, 2]])\n",
            0,
        ),
        (
            "def ordered(values: list[int]) -> list[int]:\n    return list(1 for _ in range(values.pop()) if False)\n",
            1,
        ),
    ],
    ids=[
        "native-list",
        "native-tuple",
        "native-set",
        "native-frozenset",
        "deferred-generator",
        "unknown-consumer",
        "shadowed-consumer",
        "patched-consumer",
        "async-generator",
        "empty-generator",
        "false-filter",
        "target-shadows-borrowed-root",
        "outer-iterable-evaluates-before-filter",
    ],
)
def test_eager_generator_consumption(source: str, expected_count: int) -> None:
    assert len(NoMutatingContainerTransform().check(Path("app/counts.py"), source)) == expected_count


_COMMAND_MARKER = "def command(function):\n    return lambda *args: None\n"
_PREPARED_CLASS_NAMESPACE = (
    _COMMAND_MARKER
    + "class Meta(type):\n    @classmethod\n    def __prepare__(cls, name, bases):\n        return {'staticmethod': command}\n"
)


@pytest.mark.parametrize(
    ("declarations", "class_header", "markers", "parameters", "expected_count"),
    [
        ("", "class Mapper:", "@staticmethod", "", 1),
        ("", "class Mapper:", "@classmethod", "cls, ", 1),
        ("from typing import final\n", "class Mapper:", "@final", "self, ", 1),
        ("from typing import final\n", "class Mapper:", "@staticmethod\n@final", "", 1),
        ("import typing as t\n", "class Mapper:", "@t.final", "self, ", 1),
        (_COMMAND_MARKER, "class Mapper:", "@command", "self, ", 0),
        (_COMMAND_MARKER + "staticmethod = command\n", "class Mapper:", "@staticmethod", "", 0),
        (_PREPARED_CLASS_NAMESPACE, "class Mapper(metaclass=Meta):", "@staticmethod", "", 0),
        (
            _PREPARED_CLASS_NAMESPACE + "class Base(metaclass=Meta):\n    pass\n",
            "class Mapper(Base):",
            "@staticmethod",
            "",
            0,
        ),
        (
            _COMMAND_MARKER + "from unittest.mock import patch\npatch('builtins.staticmethod', new=command).start()\n",
            "class Mapper:",
            "@staticmethod",
            "",
            0,
        ),
        ("", "class Mapper:", "@staticmethod\n@classmethod", "cls, ", 0),
        (
            _COMMAND_MARKER + "def final(function):\n    return command(function)\n",
            "class Mapper:",
            "@final",
            "self, ",
            0,
        ),
    ],
    ids=[
        "native-staticmethod",
        "native-classmethod",
        "native-final-method",
        "static-final-composition",
        "module-alias-final",
        "custom-command-marker",
        "shadowed-staticmethod",
        "metaclass-prepared-marker",
        "inherited-prepared-marker",
        "patched-staticmethod",
        "ambiguous-binder-composition",
        "unrelated-final-name",
    ],
)
def test_body_preserving_method_markers(
    declarations: str, class_header: str, markers: str, parameters: str, expected_count: int
) -> None:
    decorators = "\n".join("    " + marker for marker in markers.splitlines())
    source = (
        f"{declarations}{class_header}\n{decorators}\n"
        f"    def ordered({parameters}values: list[int]) -> list[int]:\n"
        "        values.sort()\n        return values\n"
    )
    assert len(NoMutatingContainerTransform().check(Path("app/counts.py"), source)) == expected_count


@pytest.mark.parametrize(
    ("declarations", "annotation", "assignment", "operation", "expected_count"),
    [
        ("from typing import assert_type\n", "list[int]", "assert_type(values, list[int])", "result.reverse()", 1),
        ("from typing import cast\n", "list[int]", "cast(list[int], values)", "result.reverse()", 1),
        (
            "from typing import assert_type as checked\n",
            "list[int]",
            "checked(values, list[int])",
            "result.reverse()",
            1,
        ),
        ("import typing as t\n", "list[int]", "t.assert_type(values, list[int])", "result.reverse()", 1),
        (
            "from typing import assert_type, cast\n",
            "list[int]",
            "assert_type(cast(list[int], values), list[int])",
            "result.reverse()",
            1,
        ),
        (
            "from typing import assert_type\n",
            "list[int]",
            "assert_type(values, list[int])",
            "values = []\n    result.reverse()",
            1,
        ),
        (
            "from typing import assert_type\n",
            "dict[str, int]",
            "assert_type(values, dict[str, int])",
            "result.update({'count': 2})",
            1,
        ),
        ("from typing import assert_type\n", "set[int]", "assert_type(values, set[int])", "result.add(2)", 1),
        (
            "from typing import assert_type\n",
            "list[int]",
            "assert_type(list(values), list[int])",
            "result.reverse()",
            0,
        ),
        (
            "def assert_type(values, typ):\n    return list(values)\n",
            "list[int]",
            "assert_type(values, list[int])",
            "result.reverse()",
            0,
        ),
        (
            "import typing as t\nt.assert_type = clone\n",
            "list[int]",
            "t.assert_type(values, list[int])",
            "result.reverse()",
            0,
        ),
        (
            "import typing as t\nt.assert_type = clone\nfrom typing import assert_type\n",
            "list[int]",
            "assert_type(values, list[int])",
            "result.reverse()",
            0,
        ),
        (
            "import typing as t\nfrom plugin import external\nexternal(t.assert_type)\n",
            "list[int]",
            "t.assert_type(values, list[int])",
            "result.reverse()",
            0,
        ),
        (
            "from unittest.mock import patch\npatch('typing.assert_type', new=clone).start()\nfrom typing import assert_type\n",
            "list[int]",
            "assert_type(values, list[int])",
            "result.reverse()",
            0,
        ),
        (
            "from typing import assert_type\n",
            "list[int]",
            "assert_type(values, list[int], unexpected)",
            "result.reverse()",
            0,
        ),
    ],
    ids=[
        "assert-type",
        "cast",
        "import-alias",
        "module-alias",
        "nested-identities",
        "root-rebind-retains-alias",
        "dict-identity",
        "set-identity",
        "identity-of-fresh-copy",
        "unrelated-local-helper",
        "provider-write",
        "provider-alias-write",
        "opaque-qualified-function-escape",
        "mock-patched-provider",
        "invalid-arity-does-not-call-helper",
    ],
)
def test_typing_helper_identity(
    declarations: str, annotation: str, assignment: str, operation: str, expected_count: int
) -> None:
    source = (
        f"{declarations}def transform(values: {annotation}) -> {annotation}:\n"
        f"    result = {assignment}\n    {operation}\n    return result\n"
    )
    assert len(NoMutatingContainerTransform().check(Path("app/counts.py"), source)) == expected_count


@pytest.mark.parametrize(
    ("statement", "expected_count"),
    [(f"if {literal}:\n        values.sort()", 0) for literal in ("[]", "()", "{}", "[*()]", "{**{}}", "{*()}")]
    + [
        (
            f"if {literal}:\n        values = list(values)\n    else:\n        values.reverse()",
            0,
        )
        for literal in ("[0]", "(0,)", "{'count': 0}", "{0}")
    ]
    + [
        ("[] and values.pop()", 0),
        ("if [values.pop()]:\n        pass", 1),
        ("if {'count': values.pop()}:\n        pass", 1),
        ("if [*values]:\n        values.sort()", 1),
    ],
    ids=[
        "empty-list",
        "empty-tuple",
        "empty-dict",
        "empty-sequence-expansion",
        "empty-dict-expansion",
        "empty-set-expansion",
        "nonempty-list",
        "nonempty-tuple",
        "nonempty-dict",
        "nonempty-set",
        "empty-literal-short-circuits",
        "list-content-is-evaluated",
        "dict-content-is-evaluated",
        "unknown-spread-remains-uncertain",
    ],
)
def test_literal_collection_reachability(statement: str, expected_count: int) -> None:
    source = f"def ordered(values: list[int]) -> list[int]:\n    {statement}\n    return values\n"
    assert len(NoMutatingContainerTransform().check(Path("app/counts.py"), source)) == expected_count


@pytest.mark.parametrize(
    ("statement", "expected_count"),
    [
        ("if 0 > 1:\n        values.sort()", 0),
        ("0 > 1 < values.pop()", 0),
        ("values.pop() if 0 > 1 else None", 0),
        ("if 1 <= 2:\n        values = list(values)\n    else:\n        values.reverse()", 0),
        ("'a' > 'b' < str(values.pop())", 0),
        ("if b'a' != b'a':\n        values.reverse()", 0),
        ("values.pop() < 0 > 1 < values.pop()", 1),
        ("0 < 1 < values.pop()", 1),
        ("values.pop() < 4", 1),
        ("0 > values[0] < values.pop()", 1),
        ("if None is False:\n        values.sort()", 0),
    ],
    ids=[
        "false-comparison-branch",
        "false-comparison-chain",
        "false-comparison-expression",
        "true-comparison-branch",
        "string-order-chain",
        "bytes-equality",
        "earlier-effect-before-false-link",
        "true-link-continues",
        "left-operand-effect",
        "unknown-comparison-remains-uncertain",
        "known-singleton-identity",
    ],
)
def test_literal_comparison_reachability(statement: str, expected_count: int) -> None:
    source = f"def ordered(values: list[int]) -> list[int]:\n    {statement}\n    return values\n"
    assert len(NoMutatingContainerTransform().check(Path("app/counts.py"), source)) == expected_count


@pytest.mark.parametrize(
    ("declarations", "annotation", "statements", "expected_count"),
    [
        ("", "tuple[int, ...]", "values.reverse()\n    return tuple(values)", 1),
        ("", "frozenset[int]", "values.reverse()\n    return frozenset(values)", 1),
        ("", "frozenset[int,]", "values.reverse()\n    return frozenset(values)", 1),
        ("", "tuple[()]", "values.reverse()\n    return ()", 1),
        ("", "'tuple[int, ...]'", "values.reverse()\n    return tuple(values)", 1),
        ("", "tuple[int, ...]", "result = list(values)\n    result.reverse()\n    return tuple(result)", 0),
        ("", "frozenset[int]", "result = list(values)\n    result.reverse()\n    return frozenset(result)", 0),
        ("class tuple:\n    pass\n", "tuple[int, ...]", "values.reverse()\n    return tuple(values)", 0),
        ("class frozenset:\n    pass\n", "frozenset[int]", "values.reverse()\n    return frozenset(values)", 0),
    ],
    ids=[
        "tuple-replacement",
        "frozenset-replacement",
        "frozenset-trailing-comma",
        "empty-tuple-result",
        "quoted-immutable-output",
        "copy-before-tuple",
        "copy-before-frozenset",
        "shadowed-tuple",
        "shadowed-frozenset",
    ],
)
def test_immutable_container_output(declarations: str, annotation: str, statements: str, expected_count: int) -> None:
    source = f"{declarations}def replaced(values: list[int]) -> {annotation}:\n    {statements}\n"
    assert len(NoMutatingContainerTransform().check(Path("app/counts.py"), source)) == expected_count


@pytest.mark.parametrize(
    ("declarations", "annotation", "statement", "expected_count"),
    [
        ("", "list[int]", "list.sort(values)", 1),
        ("", "list[int]", "list.reverse(values)", 1),
        ("", "dict[str, int]", "dict.update(values, count=2)", 1),
        ("", "set[int]", "set.add(values, 2)", 1),
        ("", "list[int]", "values.__setitem__(0, 2)", 1),
        ("", "dict[str, int]", "values.__delitem__('count')", 1),
        ("", "list[int]", "values.__iadd__([2])", 1),
        ("", "dict[str, int]", "values.__ior__({'count': 2})", 1),
        ("", "set[int]", "values.__iand__({2})", 1),
        ("", "set[int]", "values.__init__({2})", 1),
        ("", "list[int]", "list.__setitem__(values, 0, 2)", 1),
        ("", "list[int]", "result = list(values)\n    list.sort(result)", 0),
        ("", "list[int]", "result = list(values)\n    result.__setitem__(0, 2)", 0),
        ("", "dict[str, int]", "dict.get(values, 'count')", 0),
        (
            "class Handler:\n    @staticmethod\n    def sort(values):\n        return list(values)\n",
            "list[int]",
            "Handler.sort(values)",
            0,
        ),
    ],
    ids=[
        "list-sort-descriptor",
        "list-reverse-descriptor",
        "dict-update-descriptor",
        "set-add-descriptor",
        "list-item-special-method",
        "dict-delete-special-method",
        "list-inplace-special-method",
        "dict-inplace-special-method",
        "set-inplace-special-method",
        "set-reinitialize",
        "unbound-item-special-method",
        "unbound-fresh-copy",
        "bound-fresh-copy",
        "unbound-query",
        "custom-descriptor",
    ],
)
def test_native_mutation_dispatch(declarations: str, annotation: str, statement: str, expected_count: int) -> None:
    source = f"{declarations}def changed(values: {annotation}) -> {annotation}:\n    {statement}\n    return values\n"
    assert len(NoMutatingContainerTransform().check(Path("app/counts.py"), source)) == expected_count


@pytest.mark.parametrize(
    ("expression", "expected_count"),
    [
        ("True and values", 1),
        ("False or values", 1),
        ("[] or values", 1),
        ("values or values", 1),
        ("values and values", 1),
        ("True and (False or values)", 1),
        ("False and values", 0),
        ("True or values", 0),
        ("values or list(values)", 0),
        ("flag and values", 0),
        ("values and list(values)", 0),
        ("list(values) or list(values)", 0),
    ],
    ids=[
        "true-and",
        "false-or",
        "empty-or",
        "same-owner-or",
        "same-owner-and",
        "nested-selection",
        "false-and",
        "true-or",
        "ambiguous-copy-or",
        "ambiguous-condition-and",
        "ambiguous-copy-and",
        "all-fresh",
    ],
)
def test_boolean_value_identity(expression: str, expected_count: int) -> None:
    source = (
        "def changed(values: list[int], flag: bool) -> list[int]:\n"
        f"    result = {expression}\n    result.reverse()\n    return values\n"
    )
    assert len(NoMutatingContainerTransform().check(Path("app/counts.py"), source)) == expected_count

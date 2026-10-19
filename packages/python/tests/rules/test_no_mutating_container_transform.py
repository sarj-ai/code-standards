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

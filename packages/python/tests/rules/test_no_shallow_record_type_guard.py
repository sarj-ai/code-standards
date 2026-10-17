from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, TypedDict, TypeGuard

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language, RuleProblem

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_contradictory_type_guard import NoContradictoryTypeGuard
from sarj_python_lint.rules.no_partial_type_is import NoPartialTypeIs
from sarj_python_lint.rules.no_shallow_container_type_guard import NoShallowContainerTypeGuard
from sarj_python_lint.rules.no_shallow_record_type_guard import NoShallowRecordTypeGuard


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _source(record: str = "TypedDict", *, field: str = "text: str", check: str | None = None) -> str:
    container = check or ("dict" if record == "TypedDict" else "tuple")
    return (
        f"from typing import {record}, TypeGuard\n"
        f"class Payload({record}):\n    {field}\n"
        f"def claims_payload(value: object) -> TypeGuard[Payload]:\n    return isinstance(value, {container})\n"
    )


_TYPED = _source()
_NAMED = _source("NamedTuple")
_PROBLEM = RuleProblem(
    key="shallow-record-guard",
    summary="A container-only predicate promises a local record's required shape without checking it.",
    harm="An empty dict or tuple passes the guard and then fails a required-key or named-attribute consumer.",
    languages=frozenset({Language.PYTHON}),
    bad_examples=(_TYPED, _NAMED),
    good_examples=(_TYPED.replace("TypeGuard[Payload]", "TypeGuard[dict[object, object]]"),),
    exclusions=("Optional-only, inherited, decorated, opaque, escaped, overloaded and constrained-input contracts.",),
)
_CASES = (
    EvaluationCase("required-typed-dict", Language.PYTHON, _TYPED, ExpectedOutcome.MATCH),
    EvaluationCase("required-named-tuple", Language.PYTHON, _NAMED, ExpectedOutcome.MATCH),
    EvaluationCase("type-is-record", Language.PYTHON, _TYPED.replace("TypeGuard", "TypeIs"), ExpectedOutcome.MATCH),
    EvaluationCase("honest-container", Language.PYTHON, _PROBLEM.good_examples[0]),
    EvaluationCase("checked-nominal-class", Language.PYTHON, _NAMED.replace("value, tuple", "value, Payload")),
    EvaluationCase("different-parameter", Language.PYTHON, _TYPED.replace("value, dict", "other, dict")),
    EvaluationCase("different-container", Language.PYTHON, _source(check="list")),
    EvaluationCase("constrained-input", Language.PYTHON, _TYPED.replace("value: object", "value: Payload | None")),
    EvaluationCase("generic", Language.PYTHON, _TYPED.replace("claims_payload(", "claims_payload[T](")),
    EvaluationCase("decorated", Language.PYTHON, _TYPED.replace("def claims", "@decorate\ndef claims")),
    EvaluationCase(
        "nested", Language.PYTHON, "def outer():\n" + "\n".join("    " + line for line in _TYPED.splitlines())
    ),
    EvaluationCase("async", Language.PYTHON, _TYPED.replace("def claims", "async def claims")),
    EvaluationCase(
        "content-check", Language.PYTHON, _TYPED.replace("value, dict)", "value, dict) and 'text' in value")
    ),
    EvaluationCase("helper-check", Language.PYTHON, _TYPED.replace("isinstance(value, dict)", "validates(value)")),
    EvaluationCase(
        "multiple-returns",
        Language.PYTHON,
        _TYPED.replace("return isinstance", "if flag: return False\n    return isinstance"),
    ),
    EvaluationCase(
        "aliased-target",
        Language.PYTHON,
        _TYPED.replace("def claims", "Alias = Payload\ndef claims").replace("TypeGuard[Payload]", "TypeGuard[Alias]"),
    ),
    EvaluationCase(
        "imported-target", Language.PYTHON, "from app import Payload\n" + _TYPED[_TYPED.index("def claims") :]
    ),
    EvaluationCase("decorated-record", Language.PYTHON, _TYPED.replace("class Payload", "@decorate\nclass Payload")),
    EvaluationCase(
        "inherited-record",
        Language.PYTHON,
        _TYPED.replace("class Payload(TypedDict)", "class Parent(TypedDict):\n    text: str\nclass Payload(Parent)"),
    ),
    EvaluationCase(
        "optional-record", Language.PYTHON, _TYPED.replace("Payload(TypedDict)", "Payload(TypedDict, total=False)")
    ),
    EvaluationCase("empty-record", Language.PYTHON, _source(field="pass")),
    EvaluationCase(
        "named-default", Language.PYTHON, _source("NamedTuple", field="text: str = 'ready'"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "named-default-nominal-check",
        Language.PYTHON,
        _source("NamedTuple", field="text: str = 'ready'", check="Payload"),
    ),
    EvaluationCase(
        "named-default-order-invalid",
        Language.PYTHON,
        _source("NamedTuple", field="text: str = 'ready'\n    count: int"),
    ),
    EvaluationCase("named-empty", Language.PYTHON, _source("NamedTuple", field="pass"), ExpectedOutcome.MATCH),
    EvaluationCase("named-empty-nominal-check", Language.PYTHON, _source("NamedTuple", field="pass", check="Payload")),
    EvaluationCase(
        "custom-base", Language.PYTHON, _TYPED.replace("from typing import TypedDict", "from app import TypedDict")
    ),
    EvaluationCase("opaque-field", Language.PYTHON, _source(field="text: DomainText")),
    EvaluationCase("computed-field", Language.PYTHON, _source(field="text: make_type()")),
    EvaluationCase("string-field", Language.PYTHON, _source(field="text: 'str'")),
    EvaluationCase("class-method", Language.PYTHON, _source(field="text: str\n    def method(self): pass")),
    EvaluationCase("rebound-record", Language.PYTHON, _TYPED.replace("def claims", "Payload = alternate\ndef claims")),
    EvaluationCase("escaped-record", Language.PYTHON, _TYPED.replace("def claims", "configure(Payload)\ndef claims")),
    EvaluationCase(
        "record-mutation",
        Language.PYTHON,
        _TYPED.replace("def claims", "Payload.__required_keys__ = frozenset()\ndef claims"),
    ),
    EvaluationCase(
        "class-scope-shadow", Language.PYTHON, _source("NamedTuple", field="str: int = 1\n    text: str = 'x'")
    ),
    EvaluationCase("duplicate-field", Language.PYTHON, _source(field="text: str\n    text: int")),
    EvaluationCase("malformed", Language.PYTHON, "class Payload("),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_record_guard_cases(case: EvaluationCase) -> None:
    findings = NoShallowRecordTypeGuard().check(Path("app/guards.py"), case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)
    assert len(findings) <= 1


@pytest.mark.parametrize("module", ["typing", "typing_extensions"])
@pytest.mark.parametrize("record", ["TypedDict", "NamedTuple"])
def test_import_aliases_and_module_aliases(module: str, record: str) -> None:
    source = _source(record).replace("from typing import", f"from {module} import")
    assert len(NoShallowRecordTypeGuard().check(Path("app/guards.py"), source)) == 1
    aliased = (
        source.replace(f"{record}, TypeGuard", f"{record} as Record, TypeGuard as Guard")
        .replace(f"Payload({record})", "Payload(Record)")
        .replace("-> TypeGuard[", "-> Guard[")
    )
    assert len(NoShallowRecordTypeGuard().check(Path("app/guards.py"), aliased)) == 1
    qualified = (
        source.replace(f"from {module} import {record}, TypeGuard", f"import {module} as t")
        .replace(f"Payload({record})", f"Payload(t.{record})")
        .replace("-> TypeGuard[", "-> t.TypeGuard[")
    )
    assert len(NoShallowRecordTypeGuard().check(Path("app/guards.py"), qualified)) == 1


@pytest.mark.parametrize(
    ("wrapper", "total", "expected"), [("Required", False, 1), ("NotRequired", True, 0), ("ReadOnly", True, 1)]
)
def test_requiredness_wrappers(wrapper: str, *, total: bool, expected: int) -> None:
    source = f"from typing import {wrapper}\n" + _source(field=f"text: {wrapper}[str]")
    if not total:
        source = source.replace("Payload(TypedDict)", "Payload(TypedDict, total=False)")
    assert len(NoShallowRecordTypeGuard().check(Path("app/guards.py"), source)) == expected


@pytest.mark.parametrize(
    ("annotation", "total", "expected"),
    [
        ("ReadOnly[Required[str]]", False, 1),
        ("ReadOnly[NotRequired[str]]", True, 0),
        ("Annotated[Required[str], 'wire']", False, 1),
        ("Annotated[NotRequired[str], 'wire']", True, 0),
        ("ReadOnly[str]", False, 0),
        ("list[str | None]", True, 1),
    ],
)
def test_nested_requiredness_and_builtin_annotations(annotation: str, *, total: bool, expected: int) -> None:
    source = "from typing import Annotated, Required, NotRequired, ReadOnly\n" + _source(field=f"text: {annotation}")
    if not total:
        source = source.replace("Payload(TypedDict)", "Payload(TypedDict, total=False)")
    assert len(NoShallowRecordTypeGuard().check(Path("app/guards.py"), source)) == expected


@pytest.mark.parametrize("record", ["TypedDict", "NamedTuple"])
def test_public_overloads_constrain_implementation_inputs(record: str) -> None:
    source = "from typing import overload\n" + _source(record)
    declarations = (
        "@overload\ndef claims_payload(value: Payload) -> TypeGuard[Payload]: ...\n"
        "@overload\ndef claims_payload(value: None) -> TypeGuard[Payload]: ...\n"
    )
    source = source.replace("def claims_payload(value: object)", f"{declarations}def claims_payload(value: object)")
    assert NoShallowRecordTypeGuard().check(Path("app/guards.py"), source) == []


@pytest.mark.parametrize(
    "prefix",
    [
        "from typing import *\n",
        "dict = alternate\n",
        "def unrelated(isinstance): pass\n",
        "import builtins\nbuiltins.dict = alternate\n",
        "import builtins as native\nconfigure(native)\n",
        "namespace = repr.__self__\n",
        "namespace = __lazy_import__('builtins')\n",
    ],
)
def test_builtin_or_namespace_ambiguity_abstains(prefix: str) -> None:
    assert NoShallowRecordTypeGuard().check(Path("app/guards.py"), prefix + _TYPED) == []


def test_unicode_normalized_import_aliases_remain_supported() -> None:
    source = _TYPED.replace("TypedDict", "ＴｙｐｅｄＤｉｃｔ").replace("TypeGuard", "ＴｙｐｅＧｕａｒｄ")
    assert len(NoShallowRecordTypeGuard().check(Path("app/guards.py"), source)) == 1


def test_deep_or_wide_annotations_abstain_without_recursive_analysis() -> None:
    long_union = " | ".join("str" for _ in range(1500))
    many_literals = ",".join(repr(str(index)) for index in range(1500))
    sources = [
        _source(field=f"text: {long_union}"),
        "from typing import Literal\n" + _source(field=f"text: Literal[{many_literals}]"),
    ]
    for source in sources:
        assert NoShallowRecordTypeGuard().check(Path("app/guards.py"), source) == []


@pytest.mark.parametrize("example", NoShallowRecordTypeGuard.public_examples())
def test_published_examples(example: RuleExample) -> None:
    source = example.files[0].source
    assert len(NoShallowRecordTypeGuard().check(Path(str(example.focus_path)), source)) == example.expected_count


@pytest.mark.parametrize("symbol", ["TypedDict", "NamedTuple", "Required", "NotRequired", "ReadOnly", "TypeGuard"])
def test_typing_namespace_mutation_abstains(symbol: str) -> None:
    source = f"import typing\ntyping.{symbol} = alternate\n" + _TYPED
    assert NoShallowRecordTypeGuard().check(Path("app/guards.py"), source) == []


@pytest.mark.parametrize("path", ["src/generated/guards.py", "vendor/guards.py"])
def test_generated_paths(path: str) -> None:
    assert NoShallowRecordTypeGuard().check(Path(path), _TYPED) == []


def test_exact_suppression_and_warning() -> None:
    rule = NoShallowRecordTypeGuard()
    findings = rule.check(Path("tests/test_guards.py"), _TYPED)
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert rule.check(Path("app/guards.py"), _TYPED.rstrip() + "  # sarj-noqa: SARJ514 -- trusted boundary\n") == []
    assert rule.check(Path("app/guards.py"), _TYPED.rstrip() + "  # sarj-noqa: SARJ513 -- different owner\n")


def test_registered_warning_and_neighboring_owners(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "guards.py"
    path.write_text(_TYPED)
    assert main(["check", "--rule", NoShallowRecordTypeGuard.id, str(path)]) == 0
    assert "SARJ514" in capsys.readouterr().out
    rules = [
        NoShallowRecordTypeGuard.id,
        NoShallowContainerTypeGuard.id,
        NoPartialTypeIs.id,
        NoContradictoryTypeGuard.id,
    ]
    assert [finding.code for finding in analyze(rules, [path])] == ["SARJ514"]


class _Payload(TypedDict):
    text: str


class _Row(NamedTuple):
    text: str = "ready"


class _EmptyRow(NamedTuple):
    pass


def _claims_payload(value: object) -> TypeGuard[_Payload]:
    return isinstance(value, dict)  # sarj-noqa: SARJ514 -- prove the unchecked required-key counterexample


def _claims_row(value: object) -> TypeGuard[_Row]:
    return isinstance(value, tuple)  # sarj-noqa: SARJ514 -- prove the unchecked named-attribute counterexample


def _claims_empty_row(value: object) -> TypeGuard[_EmptyRow]:
    return isinstance(value, tuple)  # sarj-noqa: SARJ514 -- prove the unchecked nominal-record API counterexample


def test_checker_accepted_contracts_fail_concrete_consumers() -> None:
    payload: object = {}
    row: object = ()
    if _claims_payload(payload):
        with pytest.raises(KeyError, match="text"):
            payload["text"].upper()
    if _claims_row(row):
        with pytest.raises(AttributeError, match="text"):
            row.text.upper()
    defaulted = _Row()
    assert defaulted.text.upper() == "READY"
    assert isinstance(defaulted, _Row)
    assert not isinstance(row, _Row)
    if _claims_empty_row(row):
        with pytest.raises(AttributeError, match="_asdict"):
            row._asdict()
    assert _EmptyRow()._asdict() == {}
    assert not isinstance(row, _EmptyRow)

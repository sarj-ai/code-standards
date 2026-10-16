from pathlib import Path
from typing import TYPE_CHECKING, TypeIs

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import AutofixPolicy, Severity
from sarj_python_lint.rules.no_partial_type_is import NoPartialTypeIs
from sarj_python_lint.rules.no_shallow_container_type_guard import NoShallowContainerTypeGuard


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _source(check: str = "value > 0", target: str = "int", input_type: str = "object") -> str:
    container = target.partition("[")[0]
    return (
        "from typing import TypeIs\n"
        f"def identifies(value: {input_type}) -> TypeIs[{target}]:\n"
        f"    return isinstance(value, {container}) and {check}\n"
    )


_BASE = _source()
_CASES = (
    EvaluationCase("positive-int", Language.PYTHON, _BASE, ExpectedOutcome.MATCH),
    EvaluationCase("nonnegative-int", Language.PYTHON, _source("value >= 0"), ExpectedOutcome.MATCH),
    EvaluationCase("negative-int", Language.PYTHON, _source("value < -1"), ExpectedOutcome.MATCH),
    EvaluationCase("bounded-int", Language.PYTHON, _source("value <= +100"), ExpectedOutcome.MATCH),
    EvaluationCase("selected-int", Language.PYTHON, _source("value == 3"), ExpectedOutcome.MATCH),
    EvaluationCase("excluded-int", Language.PYTHON, _source("value != 3"), ExpectedOutcome.MATCH),
    EvaluationCase("selected-string", Language.PYTHON, _source('value == "open"', "str"), ExpectedOutcome.MATCH),
    EvaluationCase("nonempty-string", Language.PYTHON, _source('value != ""', "str"), ExpectedOutcome.MATCH),
    EvaluationCase("ordered-string", Language.PYTHON, _source('value > "a"', "str"), ExpectedOutcome.MATCH),
    EvaluationCase("selected-bytes", Language.PYTHON, _source('value == b"open"', "bytes"), ExpectedOutcome.MATCH),
    EvaluationCase("selected-boolean", Language.PYTHON, _source("value == True", "bool"), ExpectedOutcome.MATCH),
    EvaluationCase("union-input", Language.PYTHON, _source(input_type="int | str"), ExpectedOutcome.MATCH),
    EvaluationCase("same-kind-input", Language.PYTHON, _source(input_type="int"), ExpectedOutcome.MATCH),
    EvaluationCase("nonempty-list", Language.PYTHON, _source("len(value) > 0", "list[str]"), ExpectedOutcome.MATCH),
    EvaluationCase(
        "nonempty-dict", Language.PYTHON, _source("len(value) != 0", "dict[str, int]"), ExpectedOutcome.MATCH
    ),
    EvaluationCase("nonempty-set", Language.PYTHON, _source("len(value) >= 1", "set[object]"), ExpectedOutcome.MATCH),
    EvaluationCase("length-string", Language.PYTHON, _source("len(value) > 0", "str"), ExpectedOutcome.MATCH),
    EvaluationCase("length-bytes", Language.PYTHON, _source("len(value) == 1", "bytes"), ExpectedOutcome.MATCH),
    EvaluationCase("type-guard", Language.PYTHON, _BASE.replace("TypeIs", "TypeGuard")),
    EvaluationCase("total-string", Language.PYTHON, _source("len(value) >= 0", "str")),
    EvaluationCase("total-list-length", Language.PYTHON, _source("len(value) >= 0", "list[str]")),
    EvaluationCase("identity-comparison", Language.PYTHON, _source("value is not None")),
    EvaluationCase("membership-not-inferred", Language.PYTHON, _source("value in (1, 2)")),
    EvaluationCase("dynamic-bound", Language.PYTHON, _source("value > threshold")),
    EvaluationCase("helper-predicate", Language.PYTHON, _source("allowed(value)")),
    EvaluationCase("cross-kind-comparison", Language.PYTHON, _source('value != ""')),
    EvaluationCase("bool-not-int-literal", Language.PYTHON, _source("value != True")),
    EvaluationCase("float-not-inferred", Language.PYTHON, _source("value > 0", "float")),
    EvaluationCase("input-does-not-admit-target", Language.PYTHON, _source(input_type="str")),
    EvaluationCase("refined-input", Language.PYTHON, _source(input_type="PositiveInt")),
    EvaluationCase("refined-target", Language.PYTHON, _source("value > 0", "PositiveInt")),
    EvaluationCase("literal-target", Language.PYTHON, _source('value == "a"', 'Literal["a"]')),
    EvaluationCase("target-union", Language.PYTHON, _source("value > 0", "int | str")),
    EvaluationCase("decorated", Language.PYTHON, _BASE.replace("def identifies", "@adapt\ndef identifies")),
    EvaluationCase("generic", Language.PYTHON, _BASE.replace("identifies(", "identifies[T](")),
    EvaluationCase("async", Language.PYTHON, _BASE.replace("def identifies", "async def identifies")),
    EvaluationCase("different-parameter", Language.PYTHON, _source("other > 0")),
    EvaluationCase("multi-statement", Language.PYTHON, _BASE.replace("    return", "    validate(value)\n    return")),
    EvaluationCase("or-predicate", Language.PYTHON, _BASE.replace(" and ", " or ")),
    EvaluationCase("unfiltered", Language.PYTHON, _BASE.replace(" and value > 0", "")),
    EvaluationCase("three-conditions", Language.PYTHON, _BASE.replace("value > 0", "value > 0 and value < 10")),
    EvaluationCase("string-annotation", Language.PYTHON, _BASE.replace("TypeIs[int]", '"TypeIs[int]"')),
    EvaluationCase("custom-type-is", Language.PYTHON, _BASE.replace("from typing import", "from custom import")),
    EvaluationCase("malformed", Language.PYTHON, "def broken("),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _BASE),
    EvaluationCase(
        "unrelated-relative-import", Language.PYTHON, "from .domain import User\n" + _BASE, ExpectedOutcome.MATCH
    ),
    EvaluationCase("wildcard", Language.PYTHON, "from custom import *\n" + _BASE),
    EvaluationCase("builtin-shadow", Language.PYTHON, "int = Custom\n" + _BASE),
    EvaluationCase("guard-shadow", Language.PYTHON, _BASE + "TypeIs = Custom\n"),
    EvaluationCase("builtin-mutation", Language.PYTHON, "import builtins\nbuiltins.int = Custom\n" + _BASE),
    EvaluationCase("guard-mutation", Language.PYTHON, "import typing\ntyping.TypeIs = Custom\n" + _BASE),
    EvaluationCase("len-shadow", Language.PYTHON, "len = custom\n" + _source("len(value) > 0", "str")),
    EvaluationCase("builtin-namespace", Language.PYTHON, "namespace = __builtins__\n" + _BASE),
    EvaluationCase("guard-capture", Language.PYTHON, "match item:\n    case TypeIs:\n        pass\n" + _BASE),
    EvaluationCase("guard-walrus", Language.PYTHON, "def configure(x=(TypeIs := Custom)): pass\n" + _BASE),
    EvaluationCase(
        "type-checking-import",
        Language.PYTHON,
        _BASE.replace(
            "from typing import TypeIs",
            "from __future__ import annotations\nfrom typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from typing import TypeIs",
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "extensions",
        Language.PYTHON,
        _BASE.replace("from typing import", "from typing_extensions import"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "alias",
        Language.PYTHON,
        _BASE.replace("import TypeIs", "import TypeIs as Guard").replace("-> TypeIs", "-> Guard"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        _BASE.replace("from typing import TypeIs", "import typing as types").replace("-> TypeIs", "-> types.TypeIs"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "builtin-alias",
        Language.PYTHON,
        "from builtins import int as Integer\n"
        + _BASE.replace("TypeIs[int]", "TypeIs[Integer]").replace("value, int", "value, Integer"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "normalized-symbol", Language.PYTHON, _BASE.replace("TypeIs", "ＴｙｐｅＩｓ"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "docstring",
        Language.PYTHON,
        _BASE.replace("    return", '    """Recognize positive numbers."""\n    return'),
        ExpectedOutcome.MATCH,
    ),
)


def _check(source: str, path: Path = Path("app/guards.py")) -> list[Diagnostic]:
    return NoPartialTypeIs().check(path, source)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = _check(case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)
    assert all(finding.severity is Severity.WARNING for finding in findings)


@pytest.mark.parametrize("example", NoPartialTypeIs.public_examples())
def test_public_examples(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source)) == example.expected_count


def test_metadata_and_exact_suppression() -> None:
    docs = NoPartialTypeIs.documentation
    assert docs is not None
    assert docs.default_level is Severity.WARNING
    assert docs.autofix is AutofixPolicy.NONE
    finding = _check(_BASE)[0]
    assert (finding.code, finding.line, finding.col) == ("SARJ512", 3, 5)
    assert "false-branch" in finding.message
    assert _check(_BASE.replace("value > 0", "value > 0  # sarj-noqa: SARJ512 -- reviewed contract")) == []
    assert len(_check(_BASE.replace("value > 0", "value > 0  # sarj-noqa: SARJ511 -- unrelated"))) == 1


def test_distinct_from_shallow_container_guard() -> None:
    source = _source("len(value) > 0", "list[object]")
    assert len(_check(source)) == 1
    assert NoShallowContainerTypeGuard().check(Path("app/guards.py"), source) == []
    assert _check(source) == _check(source)


def _is_positive(value: object) -> TypeIs[int]:
    return isinstance(value, int) and value > 0  # sarj-noqa: SARJ512 -- exercise unsound negative narrowing


def test_false_branch_runtime_failure_is_reproducible() -> None:
    def describe(value: int | str) -> str:
        if _is_positive(value):
            return str(value + 1)
        return value.upper()

    assert describe(1) == "2"
    assert describe("word") == "WORD"
    with pytest.raises(AttributeError, match="upper"):
        describe(0)


@pytest.mark.parametrize("path", ["src/generated/guards.py", "vendor/guards.py"])
def test_generated_and_vendor_paths(path: str) -> None:
    assert _check(_BASE, Path(path)) == []


def test_registered_warning_is_nonblocking_and_suppression_is_exact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "guards.py"
    path.write_text(_BASE)
    assert main(["check", "--rule", NoPartialTypeIs.id, str(path)]) == 0
    output = capsys.readouterr().out
    assert "SARJ512" in output
    assert "TypeIs rejects" in output
    findings = analyze([NoPartialTypeIs.id, NoShallowContainerTypeGuard.id], [path])
    assert [finding.code for finding in findings] == ["SARJ512"]
    path.write_text(_BASE.replace("value > 0", "value > 0  # sarj-noqa: SARJ512 -- deliberate partial compatibility"))
    assert analyze([NoPartialTypeIs.id], [path]) == []


@pytest.mark.parametrize(
    "mutation",
    [
        "setattr(types, 'TypeIs', Custom)",
        "configure(types)",
        "configure(namespace=types)",
        "configure({'namespace': types})",
        "alias = types\nalias.TypeIs = Custom",
        "types.__dict__['TypeIs'] = Custom",
    ],
    ids=["setattr", "positional-escape", "keyword-escape", "nested-escape", "alias-mutation", "namespace-dict"],
)
def test_typing_namespace_mutation_abstains(mutation: str) -> None:
    source = _BASE.replace("from typing import TypeIs", "import typing as types").replace(
        "-> TypeIs", "-> types.TypeIs"
    )
    source = source.replace("def ", f"{mutation}\ndef ", 1)
    assert _check(source) == []


def test_deep_flat_input_union_abstains_without_recursion_failure() -> None:
    input_type = " | ".join(["str"] * 1500 + ["int"])
    assert _check(_source(input_type=input_type)) == []

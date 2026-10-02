from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import AutofixPolicy, Severity
from sarj_python_lint.rules.no_shallow_container_type_guard import NoShallowContainerTypeGuard


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


_BASE = "from typing import TypeGuard\ndef is_mapping(value: object) -> TypeGuard[dict[str, object]]:\n    return isinstance(value, dict)\n"
_CASES = (
    EvaluationCase("dictionary-keys", Language.PYTHON, _BASE, ExpectedOutcome.MATCH),
    EvaluationCase(
        "dictionary-values",
        Language.PYTHON,
        _BASE.replace("dict[str, object]", "dict[object, int]"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "both-dictionary-slots",
        Language.PYTHON,
        _BASE.replace("dict[str, object]", "dict[str, bytes]"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "list-elements",
        Language.PYTHON,
        _BASE.replace("dict[str, object]", "list[float]").replace("value, dict", "value, list"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "set-elements",
        Language.PYTHON,
        _BASE.replace("dict[str, object]", "set[bool]").replace("value, dict", "value, set"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("type-is", Language.PYTHON, _BASE.replace("TypeGuard", "TypeIs"), ExpectedOutcome.MATCH),
    EvaluationCase(
        "typing-extensions",
        Language.PYTHON,
        _BASE.replace("from typing import", "from typing_extensions import"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "typing-symbol-alias",
        Language.PYTHON,
        _BASE.replace("import TypeGuard", "import TypeGuard as Guard").replace("-> TypeGuard", "-> Guard"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "typing-module-alias",
        Language.PYTHON,
        _BASE.replace("from typing import TypeGuard", "import typing as types").replace(
            "-> TypeGuard", "-> types.TypeGuard"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "builtin-module-alias",
        Language.PYTHON,
        "import builtins as primitives\n"
        + _BASE.replace("value: object", "value: primitives.object")
        .replace("dict[str, object]", "primitives.dict[primitives.str, primitives.object]")
        .replace("isinstance(value, dict)", "primitives.isinstance(value, primitives.dict)"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "builtin-symbol-alias",
        Language.PYTHON,
        "from builtins import dict as Mapping, str as Text, object as Value\n"
        + _BASE.replace("value: object", "value: Value")
        .replace("dict[str, object]", "Mapping[Text, Value]")
        .replace("value, dict", "value, Mapping"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "type-checking-annotation-import",
        Language.PYTHON,
        _BASE.replace(
            "from typing import TypeGuard",
            "from __future__ import annotations\nfrom typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from typing import TypeGuard",
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "positional-only", Language.PYTHON, _BASE.replace("value: object)", "value: object, /)"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "leading-docstring",
        Language.PYTHON,
        _BASE.replace("    return", '    """Identify a mapping."""\n    return'),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("honest-dictionary", Language.PYTHON, _BASE.replace("dict[str, object]", "dict[object, object]")),
    EvaluationCase(
        "honest-list",
        Language.PYTHON,
        _BASE.replace("dict[str, object]", "list[object]").replace("value, dict", "value, list"),
    ),
    EvaluationCase(
        "honest-set",
        Language.PYTHON,
        _BASE.replace("dict[str, object]", "set[object]").replace("value, dict", "value, set"),
    ),
    EvaluationCase("any-slot", Language.PYTHON, _BASE.replace("dict[str, object]", "dict[str, Any]")),
    EvaluationCase("union-slot", Language.PYTHON, _BASE.replace("dict[str, object]", "dict[str | int, object]")),
    EvaluationCase("type-variable-slot", Language.PYTHON, _BASE.replace("dict[str, object]", "dict[str, T]")),
    EvaluationCase(
        "protocol-slot",
        Language.PYTHON,
        "from typing import Protocol\nclass Value(Protocol):\n    pass\n"
        + _BASE.replace("dict[str, object]", "dict[str, Value]"),
    ),
    EvaluationCase(
        "unproven-alias-slot",
        Language.PYTHON,
        "Text = str\n" + _BASE.replace("dict[str, object]", "dict[Text, object]"),
    ),
    EvaluationCase("json-input", Language.PYTHON, _BASE.replace("value: object", "value: JsonValue")),
    EvaluationCase("dictionary-input", Language.PYTHON, _BASE.replace("value: object", "value: dict[str, object]")),
    EvaluationCase("unknown-input", Language.PYTHON, _BASE.replace("value: object", "value: Any")),
    EvaluationCase("missing-input-annotation", Language.PYTHON, _BASE.replace("value: object", "value")),
    EvaluationCase(
        "scalar-guard", Language.PYTHON, _BASE.replace("dict[str, object]", "str").replace("value, dict", "value, str")
    ),
    EvaluationCase("bare-container", Language.PYTHON, _BASE.replace("dict[str, object]", "dict")),
    EvaluationCase("different-container-check", Language.PYTHON, _BASE.replace("value, dict", "value, list")),
    EvaluationCase(
        "extra-dictionary-slot", Language.PYTHON, _BASE.replace("dict[str, object]", "dict[str, object, int]")
    ),
    EvaluationCase("container-tuple-check", Language.PYTHON, _BASE.replace("value, dict", "value, (dict, list)")),
    EvaluationCase(
        "validated-keys",
        Language.PYTHON,
        _BASE.replace(
            "isinstance(value, dict)", "isinstance(value, dict) and all(isinstance(key, str) for key in value)"
        ),
    ),
    EvaluationCase(
        "content-loop",
        Language.PYTHON,
        _BASE.replace(
            "    return isinstance(value, dict)",
            "    if not isinstance(value, dict):\n        return False\n    for key in value:\n        if not isinstance(key, str):\n            return False\n    return True",
        ),
    ),
    EvaluationCase(
        "other-input-checked", Language.PYTHON, _BASE.replace("isinstance(value, dict)", "isinstance(other, dict)")
    ),
    EvaluationCase(
        "keyword-call",
        Language.PYTHON,
        _BASE.replace("isinstance(value, dict)", "isinstance(value=value, class_or_tuple=dict)"),
    ),
    EvaluationCase(
        "multiple-parameters", Language.PYTHON, _BASE.replace("value: object)", "value: object, other: object)")
    ),
    EvaluationCase("keyword-only-parameter", Language.PYTHON, _BASE.replace("(value: object)", "(*, value: object)")),
    EvaluationCase(
        "decorated-function", Language.PYTHON, _BASE.replace("def is_mapping", "@validator\ndef is_mapping")
    ),
    EvaluationCase("async-function", Language.PYTHON, _BASE.replace("def is_mapping", "async def is_mapping")),
    EvaluationCase("generic-function", Language.PYTHON, _BASE.replace("def is_mapping", "def is_mapping[object]")),
    EvaluationCase(
        "nested-function",
        Language.PYTHON,
        "from typing import TypeGuard\ndef outer():\n    def is_mapping(value: object) -> TypeGuard[dict[str, object]]:\n        return isinstance(value, dict)\n",
    ),
    EvaluationCase(
        "method",
        Language.PYTHON,
        "from typing import TypeGuard\nclass Checker:\n    def is_mapping(value: object) -> TypeGuard[dict[str, object]]:\n        return isinstance(value, dict)\n",
    ),
    EvaluationCase(
        "local-shadow",
        Language.PYTHON,
        _BASE.replace("value: object)", "dict: object)").replace("isinstance(value, dict)", "isinstance(dict, dict)"),
    ),
    EvaluationCase("shadowed-instance-check", Language.PYTHON, "isinstance = custom_check\n" + _BASE),
    EvaluationCase("shadowed-container", Language.PYTHON, "dict = custom_container\n" + _BASE),
    EvaluationCase("shadowed-object", Language.PYTHON, "object = custom_type\n" + _BASE),
    EvaluationCase("shadowed-slot", Language.PYTHON, "str = custom_type\n" + _BASE),
    EvaluationCase(
        "rebound-guard", Language.PYTHON, _BASE.replace("def is_mapping", "TypeGuard = custom_guard\ndef is_mapping")
    ),
    EvaluationCase("foreign-guard", Language.PYTHON, _BASE.replace("from typing import", "from custom import")),
    EvaluationCase("relative-input-alias", Language.PYTHON, "from .contracts import object\n" + _BASE),
    EvaluationCase("relative-container-alias", Language.PYTHON, "from .contracts import dict\n" + _BASE),
    EvaluationCase("relative-instance-check", Language.PYTHON, "from .checks import isinstance\n" + _BASE),
    EvaluationCase(
        "type-checking-relative-input",
        Language.PYTHON,
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from .contracts import object\n" + _BASE,
    ),
    EvaluationCase(
        "conditional-foreign-input",
        Language.PYTHON,
        "if use_contracts:\n    from domain import object\n" + _BASE,
    ),
    EvaluationCase(
        "relative-guard-replacement",
        Language.PYTHON,
        _BASE.replace("def is_mapping", "from .contracts import TypeGuard\ndef is_mapping"),
    ),
    EvaluationCase(
        "relative-container-symbol-alias-replacement",
        Language.PYTHON,
        "from builtins import dict as Mapping\nfrom .contracts import Mapping\n"
        + _BASE.replace("dict[str, object]", "Mapping[str, object]").replace("value, dict", "value, Mapping"),
    ),
    EvaluationCase(
        "unrelated-relative-import", Language.PYTHON, "from .contracts import Payload\n" + _BASE, ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "explicit-builtin-import", Language.PYTHON, "from builtins import object, dict\n" + _BASE, ExpectedOutcome.MATCH
    ),
    EvaluationCase("wildcard-import", Language.PYTHON, "from custom import *\n" + _BASE),
    EvaluationCase("builtins-mutated", Language.PYTHON, "import builtins\nbuiltins.dict = custom_container\n" + _BASE),
    EvaluationCase("typing-mutated", Language.PYTHON, "import typing\ntyping.TypeGuard = custom_guard\n" + _BASE),
    EvaluationCase(
        "guard-walrus-in-function-default",
        Language.PYTHON,
        _BASE.replace(
            "def is_mapping",
            "class Marker:\n    @classmethod\n    def __class_getitem__(cls, item):\n        return bool\ndef configure(unused=(TypeGuard := Marker)):\n    pass\ndef is_mapping",
        ),
    ),
    EvaluationCase(
        "input-walrus-in-function-default",
        Language.PYTHON,
        _BASE.replace(
            "def is_mapping", "def configure(unused=(object := dict[str, object])):\n    pass\ndef is_mapping"
        ),
    ),
    EvaluationCase(
        "typing-root-walrus-in-function-default",
        Language.PYTHON,
        _BASE.replace("from typing import TypeGuard", "import typing as guard_types")
        .replace("-> TypeGuard", "-> guard_types.TypeGuard")
        .replace(
            "def is_mapping",
            "class Marker:\n    TypeGuard = list\ndef configure(unused=(guard_types := Marker)):\n    pass\ndef is_mapping",
        ),
    ),
    EvaluationCase(
        "unrelated-default-walrus",
        Language.PYTHON,
        _BASE.replace("def is_mapping", "def configure(unused=(record := None)):\n    pass\ndef is_mapping"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "captured-guard",
        Language.PYTHON,
        _BASE.replace("def is_mapping", "match source:\n    case TypeGuard:\n        pass\ndef is_mapping"),
    ),
    EvaluationCase(
        "captured-guard-alias",
        Language.PYTHON,
        _BASE.replace("import TypeGuard", "import TypeGuard as Guard")
        .replace("-> TypeGuard", "-> Guard")
        .replace("def is_mapping", "match source:\n    case Guard:\n        pass\ndef is_mapping"),
    ),
    EvaluationCase(
        "captured-typing-root",
        Language.PYTHON,
        _BASE.replace("from typing import TypeGuard", "import typing as guard_types")
        .replace("-> TypeGuard", "-> guard_types.TypeGuard")
        .replace("def is_mapping", "match source:\n    case guard_types:\n        pass\ndef is_mapping"),
    ),
    EvaluationCase(
        "captured-builtins-root",
        Language.PYTHON,
        "import builtins as primitives\nmatch source:\n    case primitives:\n        pass\n"
        + _BASE.replace("value: object", "value: primitives.object")
        .replace("dict[str, object]", "primitives.dict[primitives.str, primitives.object]")
        .replace("isinstance(value, dict)", "primitives.isinstance(value, primitives.dict)"),
    ),
    EvaluationCase(
        "captured-container-alias",
        Language.PYTHON,
        "from builtins import dict as Mapping\nmatch source:\n    case Mapping:\n        pass\n"
        + _BASE.replace("dict[str, object]", "Mapping[str, object]").replace("value, dict", "value, Mapping"),
    ),
    EvaluationCase(
        "captured-list",
        Language.PYTHON,
        "match source:\n    case list:\n        pass\n"
        + _BASE.replace("dict[str, object]", "list[str]").replace("value, dict", "value, list"),
    ),
    EvaluationCase("captured-dict", Language.PYTHON, "match source:\n    case dict:\n        pass\n" + _BASE),
    EvaluationCase(
        "captured-instance-check", Language.PYTHON, "match source:\n    case isinstance:\n        pass\n" + _BASE
    ),
    EvaluationCase("captured-slot", Language.PYTHON, "match source:\n    case str:\n        pass\n" + _BASE),
    EvaluationCase(
        "mapping-rest-container", Language.PYTHON, "match source:\n    case {**dict}:\n        pass\n" + _BASE
    ),
    EvaluationCase(
        "sequence-star-instance-check",
        Language.PYTHON,
        "match source:\n    case [*isinstance]:\n        pass\n" + _BASE,
    ),
    EvaluationCase(
        "exception-bound-guard",
        Language.PYTHON,
        _BASE.replace("def is_mapping", "try:\n    pass\nexcept Exception as TypeGuard:\n    pass\ndef is_mapping"),
    ),
    EvaluationCase(
        "exception-bound-typing-root",
        Language.PYTHON,
        _BASE.replace("from typing import TypeGuard", "import typing as guard_types")
        .replace("-> TypeGuard", "-> guard_types.TypeGuard")
        .replace("def is_mapping", "try:\n    pass\nexcept Exception as guard_types:\n    pass\ndef is_mapping"),
    ),
    EvaluationCase(
        "exception-bound-container", Language.PYTHON, "try:\n    pass\nexcept Exception as dict:\n    pass\n" + _BASE
    ),
    EvaluationCase(
        "exception-bound-instance-check",
        Language.PYTHON,
        "try:\n    pass\nexcept Exception as isinstance:\n    pass\n" + _BASE,
    ),
    EvaluationCase(
        "unrelated-capture",
        Language.PYTHON,
        "match source:\n    case record:\n        pass\n" + _BASE,
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unrelated-exception",
        Language.PYTHON,
        "try:\n    pass\nexcept Exception as error:\n    pass\n" + _BASE,
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "wildcard-pattern", Language.PYTHON, "match source:\n    case _:\n        pass\n" + _BASE, ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "global-rebinding", Language.PYTHON, _BASE + "def change():\n    global dict\n    dict = custom_container\n"
    ),
    EvaluationCase(
        "strings-and-comments",
        Language.PYTHON,
        '# TypeGuard[dict[str, object]]\nexample = "return isinstance(value, dict)"\n',
    ),
    EvaluationCase("generated-banner", Language.PYTHON, "# @generated\n" + _BASE),
    EvaluationCase("malformed", Language.PYTHON, "def broken("),
)


def _check(source: str, path: Path = Path("app/values.py")) -> list[Diagnostic]:
    return NoShallowContainerTypeGuard().check(path, source)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = _check(case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)
    assert all(finding.severity is Severity.WARNING for finding in findings)


@pytest.mark.parametrize("path", ["src/generated/values.py", "vendor/values.py"])
def test_generated_and_vendor_exclusions(path: str) -> None:
    assert _check(_BASE, Path(path)) == []


@pytest.mark.parametrize("example", NoShallowContainerTypeGuard.public_examples())
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, Path(str(focus.path)))) == example.expected_count


def test_metadata_and_diagnostic_are_actionable() -> None:
    documentation = NoShallowContainerTypeGuard.documentation
    assert documentation is not None
    assert documentation.default_level is Severity.WARNING
    assert documentation.autofix is AutofixPolicy.NONE
    finding = _check(_BASE)[0]
    assert (finding.code, finding.line, finding.col) == ("SARJ472", 3, 5)
    assert "container contents" in finding.message
    assert "object" in finding.message


def test_exact_suppression_and_warning_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "values.py"
    path.write_text(_BASE)
    assert main(["check", "--rule", NoShallowContainerTypeGuard.id, str(path)]) == 0
    assert "SARJ472 warning:" in capsys.readouterr().out
    marked = _BASE.replace(
        "return isinstance(value, dict)",
        "return isinstance(value, dict)  # sarj-noqa: SARJ472 -- compatibility contract",
    )
    path.write_text(marked)
    assert analyze([NoShallowContainerTypeGuard.id], [path]) == []
    path.write_text(marked.replace("SARJ472", "SARJ469"))
    assert len(analyze([NoShallowContainerTypeGuard.id], [path])) == 1


def test_nearby_rules_do_not_duplicate_guard_warning(tmp_path: Path) -> None:
    path = tmp_path / "values.py"
    path.write_text(_BASE)
    rules = [NoShallowContainerTypeGuard.id, "no-nullable-dependency-fallback", "no-hidden-constructor-fallback"]
    assert [finding.code for finding in analyze(rules, [path])] == ["SARJ472"]
    assert analyze(rules, [path]) == analyze(rules, [path])

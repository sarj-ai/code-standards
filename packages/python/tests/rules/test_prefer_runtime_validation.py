from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_shallow_container_type_guard import NoShallowContainerTypeGuard
from sarj_python_lint.rules.prefer_runtime_validation import PreferRuntimeValidation


def test_documented_examples() -> None:
    verify_native_rule(PreferRuntimeValidation, analyze)


CASES = (
    (
        "direct",
        "from typing import TypeGuard\ndef f(value: object) -> TypeGuard[str]: return isinstance(value, str)",
        1,
    ),
    ("module-alias", "import typing as t\ndef f(value: object) -> t.TypeGuard[str]: return isinstance(value, str)", 1),
    (
        "symbol-alias",
        "from typing_extensions import TypeGuard as Guard\ndef f(value: object) -> Guard[str]: return isinstance(value, str)",
        1,
    ),
    (
        "quoted",
        "from typing import TypeGuard\ndef f(value: object) -> 'TypeGuard[str]': return isinstance(value, str)",
        1,
    ),
    (
        "type-alias",
        "from typing import TypeGuard\ntype Guard = TypeGuard[str]\ndef f(value: object) -> Guard: return isinstance(value, str)",
        1,
    ),
    (
        "old-alias",
        "from typing import TypeGuard, TypeAlias\nGuard: TypeAlias = TypeGuard[str]\ndef f(value: object) -> Guard: return isinstance(value, str)",
        1,
    ),
    ("generic", "from typing import TypeGuard\ndef f[T](value: object) -> TypeGuard[T]: return check(value)", 1),
    (
        "nested",
        "from typing import TypeGuard\ndef outer():\n    def f(value: object) -> TypeGuard[str]: return isinstance(value, str)",
        1,
    ),
    ("bool", "def f(value: object) -> bool: return isinstance(value, str)", 0),
    ("type-is", "from typing import TypeIs\ndef f(value: object) -> TypeIs[str]: return isinstance(value, str)", 0),
    ("unrelated", "from app import TypeGuard\ndef f(value) -> TypeGuard[str]: return True", 0),
    ("shadowed", "from typing import TypeGuard\nTypeGuard = Custom\ndef f(value) -> TypeGuard[str]: return True", 0),
    ("generic-shadow", "from typing import TypeGuard\ndef f[TypeGuard](value) -> TypeGuard[str]: return True", 0),
    (
        "module-mutated",
        "import typing\ntyping.TypeGuard = Custom\ndef f(value) -> typing.TypeGuard[str]: return True",
        0,
    ),
    ("recursive-alias", "type Guard = Guard\ndef f(value) -> Guard: return True", 0),
    ("wildcard", "from app import *\nfrom typing import TypeGuard\ndef f(value) -> TypeGuard[str]: return True", 0),
    ("malformed", "from typing import TypeGuard\ndef", 0),
    (
        "local-value-shadows-alias",
        "from typing import TypeGuard\ntype Refine = TypeGuard[str]\ndef outer():\n    Refine: type[str] = str\n    def f(value: object) -> Refine: return True",
        0,
    ),
    (
        "shadowed-type-alias",
        "from typing import TypeGuard\ntype Refine = TypeGuard[str]\ndef f[Refine](value: object) -> Refine: return True",
        0,
    ),
)


@pytest.mark.parametrize(("label", "source", "count"), CASES, ids=[case[0] for case in CASES])
def test_guard_policy(label: str, source: str, count: int) -> None:
    findings = PreferRuntimeValidation().check(Path("app/records.py"), source)
    assert len(findings) == count, label
    assert all(finding.severity is Severity.WARNING for finding in findings)


def test_exact_suppression_and_generated_source() -> None:
    source = CASES[0][1] + "  # sarj-noqa: SARJ534 -- low-level native value refinement has no model representation\n"
    assert check_source([PreferRuntimeValidation()], Path("app/records.py"), source) == []
    assert PreferRuntimeValidation().check(Path("vendor/records.py"), CASES[0][1]) == []


def test_policy_warning_preserves_the_existing_correctness_error() -> None:
    source = "from typing import TypeGuard\ndef f(value: object) -> TypeGuard[dict[str, object]]:\n    return isinstance(value, dict)\n"
    findings = check_source([PreferRuntimeValidation(), NoShallowContainerTypeGuard()], Path("app/records.py"), source)
    assert [(finding.code, finding.severity) for finding in findings] == [
        ("SARJ534", Severity.WARNING),
        ("SARJ472", Severity.ERROR),
    ]
